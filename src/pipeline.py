import asyncio

from src.agent.discovery import DiscoveryAgent
from src.agent.qualification import LeadQualifier
from src.collector.scrapy_runner import ScrapyCollector
from src.dedupe.leads import dedupe
from src.extract.adaptive import AdaptiveLeadExtractor
from src.extract.evidence import EvidenceBuilder
from src.extract.documents import is_document_url, extract_document_text
from html import escape
from urllib.parse import urlparse
import time
from src.exports.csv_export import export_csv
from src.exports.google_sheets import export_google_sheets
from src.exports.xlsx_export import export_xlsx
from src.models.criteria import CrawlerConfig, SearchCriteria
from src.models.lead import Lead
from src.policy import domain_matches
from src.observability.job_events import JobEvent, emit_event, NullJobEventSink


def _persist_evidence(scrap_id, evidence):
    if not scrap_id: return None
    import uuid as _uuid
    from src.db import db as _db
    from psycopg.types.json import Jsonb as _Jsonb
    evidence_id=_uuid.uuid4()
    with _db() as conn:
        conn.execute("INSERT INTO evidence(id,scrap_id,source_type,source_id,data) VALUES(%s,%s,%s,%s,%s)",(evidence_id,_uuid.UUID(str(scrap_id)),evidence.source,None,_Jsonb(evidence.model_dump(mode="json"))))
        conn.commit()
    return evidence_id


def _domain_allowed(url: str, rules: list[tuple[str, str]]) -> bool:
    host = urlparse(url).hostname or ""
    if any(rule_type == "blacklist" and domain_matches(host, domain) for domain, rule_type in rules):
        return False
    whitelists = [domain for domain, rule_type in rules if rule_type == "whitelist"]
    return not whitelists or any(domain_matches(host, domain) for domain in whitelists)


def _persist_lead(scrap_id, lead: Lead, evidence_id=None) -> bool:
    if not scrap_id:
        return True
    import uuid as _uuid
    import re as _re
    from src.db import db as _db
    from psycopg.types.json import Jsonb as _Jsonb
    data = lead.model_dump(mode="json")
    sid = _uuid.UUID(str(scrap_id))
    email = str(lead.email or "").strip().casefold()
    first = _re.sub(r"[^a-z0-9]", "", (lead.first_name or "").casefold())
    last = _re.sub(r"[^a-z0-9]", "", (lead.last_name or "").casefold())
    company = _re.sub(r"[^a-z0-9]", "", (lead.company_name or "").casefold())
    with _db() as conn:
        existing = None
        if email:
            existing = conn.execute("SELECT id,data FROM leads WHERE scrap_id=%s AND lower(data->>'email')=lower(%s) LIMIT 1", (sid, email)).fetchone()
        if not existing and first and last and company:
            existing = conn.execute("SELECT id,data FROM leads WHERE scrap_id=%s AND regexp_replace(lower(data->>'first_name'),'[^a-z0-9]','','g')=%s AND regexp_replace(lower(data->>'last_name'),'[^a-z0-9]','','g')=%s AND regexp_replace(lower(data->>'company_name'),'[^a-z0-9]','','g')=%s LIMIT 1", (sid, first, last, company)).fetchone()
        if not existing and first and last:
            existing = conn.execute("SELECT id,data FROM leads WHERE scrap_id=%s AND data->>'source_url'=%s AND regexp_replace(lower(data->>'first_name'),'[^a-z0-9]','','g')=%s AND regexp_replace(lower(data->>'last_name'),'[^a-z0-9]','','g')=%s LIMIT 1", (sid, str(lead.source_url), first, last)).fetchone()
        if existing:
            existing_data = existing[1] or {}
            merged = dict(existing_data)
            for key, value in data.items():
                if value not in (None, ""):
                    merged[key] = value
            old_stage = existing_data.get("capture_stage", "scrapy")
            new_stage = data.get("capture_stage", "scrapy")
            if old_stage != new_stage:
                merged["capture_stage"] = "serp+scrapy"
            conn.execute("UPDATE leads SET data=%s WHERE id=%s", (_Jsonb(merged), existing[0]))
            if evidence_id:
                conn.execute("INSERT INTO lead_sources(lead_id,evidence_id) VALUES(%s,%s) ON CONFLICT DO NOTHING", (existing[0], evidence_id))
            conn.commit()
            return False
        lead_id = _uuid.uuid4()
        conn.execute("INSERT INTO leads(id,scrap_id,data) VALUES(%s,%s,%s)", (lead_id, sid, _Jsonb(data)))
        if evidence_id:
            conn.execute("INSERT INTO lead_sources(lead_id,evidence_id) VALUES(%s,%s) ON CONFLICT DO NOTHING", (lead_id, evidence_id))
        conn.commit()
    return True


class LeadDiscoveryPipeline:
    def __init__(
        self,
        model: str = "openai/gpt-oss-20b",
        max_pages: int = 25,
        crawler_config: CrawlerConfig | None = None,
        generic_prefixes: set[str] | None = None,
        domain_rules: list[tuple[str, str]] | None = None,
    ):
        self.crawler_config = crawler_config or CrawlerConfig(max_crawl_pages=max_pages)
        self.generic_prefixes = generic_prefixes
        self.domain_rules = domain_rules or []
        self.discovery = DiscoveryAgent(config=self.crawler_config)
        self.collector = ScrapyCollector(
            max_pages=self.crawler_config.max_crawl_pages,
            max_urls=self.crawler_config.max_crawl_urls,
            max_depth=self.crawler_config.max_crawl_depth,
        )
        self.extractor = AdaptiveLeadExtractor(model=model, generic_prefixes=generic_prefixes)
        self.serp_extractor = AdaptiveLeadExtractor(model=model, generic_prefixes=generic_prefixes, allow_emailless=True)
        self.qualifier = LeadQualifier()
        self.evidence = EvidenceBuilder()

    async def run(self, criteria: SearchCriteria, event_sink=None, scrap_id=None, cancel_check=None) -> list[Lead]:
        sink = event_sink or NullJobEventSink()
        started_at = time.monotonic()
        emit_event(sink, "Discovery", "Starting discovery")
        candidates = await self.discovery.discover(criteria, event_sink=sink)
        sink.emit(JobEvent(stage="URLs", state="complete", message=f"Captured {len(candidates)} candidate URLs from search", counts={"urls_captured": len(candidates)}, items=[{"url": c.url, "query": c.query} for c in candidates[:250]]))
        emit_event(sink, "Collection", "Collecting candidate sources", urls_total=len(candidates))
        leads: list[Lead] = []
        timeout_seconds = self.crawler_config.max_duration_hours * 3600
        stop_reason = None
        persisted_total = 0
        if scrap_id:
            import uuid as _uuid
            from src.db import db as _db
            with _db() as conn:
                persisted_total = int(conn.execute("SELECT count(*) FROM leads WHERE scrap_id=%s", (_uuid.UUID(str(scrap_id)),)).fetchone()[0])

        def should_stop():
            nonlocal stop_reason
            if cancel_check and cancel_check():
                stop_reason = "canceled"
                return True
            if persisted_total >= criteria.max_leads:
                stop_reason = "lead_limit"
                return True
            if time.monotonic() - started_at >= timeout_seconds:
                stop_reason = "time_limit"
                return True
            return False

        def scrapy_progress(event):
            state = event.get("state", "running")
            message = event.get("message", "Scrapy progress")
            url = event.get("url")
            if url:
                message = f"{message}: {url}"
            emit_event(
                sink,
                "Collection",
                message,
                state=state,
                urls_submitted=int(event.get("urls_submitted", len(candidates))),
                pages_collected=int(event.get("pages_collected", 0)),
                pages_failed=int(event.get("pages_failed", 0)),
            )

        page_queue: asyncio.Queue[CollectedPage | None] = asyncio.Queue(maxsize=16)
        loop = asyncio.get_running_loop()

        def page_callback(page):
            future = asyncio.run_coroutine_threadsafe(page_queue.put(page), loop)
            future.result()

        async def collect_stream():
            try:
                return await self.collector.collect_async(
                    (candidate.url for candidate in candidates),
                    progress_callback=scrapy_progress,
                    scrap_id=scrap_id,
                    page_callback=page_callback,
                    cancel_check=should_stop,
                )
            finally:
                await page_queue.put(None)

        collector_task = asyncio.create_task(collect_stream())
        emit_event(sink, "Extraction", "Processing pages incrementally")

        page_index = 0
        extracted_total = qualified_total = persisted_total = 0
        cancelled = False
        while True:
            if should_stop():
                break
            page = await page_queue.get()
            if page is None:
                break
            page_index += 1
            if cancel_check and cancel_check():
                cancelled = True
                emit_event(sink, "Collection", "Job cancellation requested", state="canceled")
            if cancelled:
                continue
            if page.status >= 400 or not _domain_allowed(page.url, self.domain_rules):
                continue

            if is_document_url(page.url, page.content_type):
                try:
                    document_text = extract_document_text(page.body, page.url, page.content_type)
                except Exception as exc:
                    print(f"document_extraction_error={page.url}: {exc}")
                    continue
                if not document_text.strip():
                    continue
                html = f"<html><body><pre>{escape(document_text)}</pre></body></html>"
                page_text = document_text
            else:
                if not page.html.strip():
                    continue
                html = page.html
                page_text = page.text

            evidence = self.evidence.build(
                url=page.url,
                html=html,
                text=page_text,
                status=page.status,
                rendered=False,
                source=page.source,
            )
            evidence_id = _persist_evidence(scrap_id, evidence)
            emit_event(sink, "Evidence", f"Evidence persisted for page {page_index}", page=page_index, evidence=page_index)

            extracted = await self.extractor.extract(
                html,
                page.url,
                evidence=evidence,
            )
            emit_event(sink, "Validation", f"Validated page {page_index}", page=page_index, extracted=len(extracted))

            qualified = [
                lead
                for lead in extracted
                if self.qualifier.qualify(lead, criteria).relevant
            ]
            extracted_total += len(extracted)
            qualified_total += len(qualified)
            persisted = 0
            for lead in qualified:
                if _persist_lead(scrap_id, lead, evidence_id=evidence_id):
                    persisted += 1
                    persisted_total += 1
                leads.append(lead)
            persisted_total += persisted
            emit_event(sink, "Leads", "Lead candidates processed", extracted=len(extracted), qualified=len(qualified), persisted=persisted, leads=len(leads), extracted_total=extracted_total, qualified_total=qualified_total, persisted_total=persisted_total)
            if should_stop():
                break

        try:
            crawl_result = await collector_task
        except RuntimeError:
            if stop_reason != "canceled":
                crawl_result = []
            else:
                raise
        if stop_reason == "lead_limit":
            emit_event(sink, "Collection", f"Lead target reached ({criteria.max_leads}); stopping crawl", state="completed", stop_reason=stop_reason, leads=persisted_total)
        elif stop_reason == "time_limit":
            emit_event(sink, "Collection", f"Research timeout reached ({self.crawler_config.max_duration_hours} hours); stopping crawl", state="completed", stop_reason=stop_reason, leads=persisted_total)
        elif stop_reason == "canceled":
            emit_event(sink, "Collection", "Job cancellation requested", state="canceled", stop_reason=stop_reason)
        else:
            emit_event(sink, "Collection", "Collection complete", pages_collected=len(crawl_result), urls_total=len(candidates))

        final = dedupe(leads)[:criteria.max_leads]
        emit_event(sink, "Qualification/Deduplication", "Qualification and deduplication complete", input_leads=len(leads), leads=len(final))
        emit_event(sink, "Leads", "Lead set ready", state="complete", leads=len(final))
        return final

    async def _stream_pages(self, urls, *, progress_callback=None, scrap_id=None, cancel_check=None):
        page_queue: asyncio.Queue[CollectedPage | None] = asyncio.Queue(maxsize=16)
        loop = asyncio.get_running_loop()

        def page_callback(page):
            future = asyncio.run_coroutine_threadsafe(page_queue.put(page), loop)
            future.result()

        async def collect_stream():
            try:
                return await self.collector.collect_async(
                    urls,
                    progress_callback=progress_callback,
                    scrap_id=scrap_id,
                    page_callback=page_callback,
                    cancel_check=cancel_check,
                )
            finally:
                await page_queue.put(None)

        collector_task = asyncio.create_task(collect_stream())
        while True:
            page = await page_queue.get()
            if page is None:
                break
            yield page
        await collector_task

    async def process_serp_records(self, criteria: SearchCriteria, results, event_sink=None, scrap_id=None, cancel_check=None) -> list[Lead]:
        """Extract and persist leads from SERP title/snippet evidence without crawling destination URLs."""
        sink = event_sink or NullJobEventSink()
        records = [r if isinstance(r, dict) else r.model_dump() for r in results]
        leads: list[Lead] = []
        extracted_total = qualified_total = persisted_total = 0
        for index, record in enumerate(records, start=1):
            if cancel_check and cancel_check():
                break
            url = str(record.get("url") or "").strip()
            snippet = str(record.get("snippet") or "").strip()
            title = str(record.get("title") or "").strip()
            if not url or not (snippet or title):
                continue
            html = f"<html><body><h1>{escape(title)}</h1><p>{escape(snippet)}</p></body></html>"
            text = f"{title}\n{snippet}".strip()
            evidence = self.evidence.build(url=url, html=html, text=text, status=200, rendered=True, source="serp-snippet")
            evidence_id = _persist_evidence(scrap_id, evidence)
            extracted = []
            candidate_text = title.replace("\xa0", " ").strip()
            import re as _re
            email_match = _re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, _re.I)
            phone_match = _re.search(r"(?:\+\d[\d ()().-]{7,}\d|\b(?:0\d{1,3}[ ()-]?)?\d{2,4}[ ()-]\d{2,4}[ ()-]\d{2,4}\b)", text)
            parts = _re.split(r"\s+(?:-|–|—|\|)\s+", candidate_text, maxsplit=1)
            name_part = _re.sub(r"\s+(?:Email|Phone|Email & Phone Number|Contact)\b.*$", "", parts[0], flags=_re.I).strip()
            name_part = _re.sub(r",?\s*(?:MD|MBBS|PhD|MSc|DO|RN|DDS|DMD)$", "", name_part, flags=_re.I).strip()
            name_words = name_part.split()
            role_part = parts[1].split("|",1)[0].strip() if len(parts)>1 else ""
            role_signal = bool(_re.search(r"\b(doctor|physician|surgeon|medical|dentist|nurse|director|manager|chief|professor|consultant|specialist|researcher|therapist)\b", role_part, _re.I))
            company_signal = bool(_re.search(r"\b(group|technology|healthcare|association|company|hospital|clinic|university|foundation|summit)\b", role_part, _re.I))
            generic_name = bool(_re.search(r"\b(group|technology|healthcare|association|company|hospital|clinic|university|foundation|summit)\b", name_part, _re.I))
            if 2 <= len(name_words) <= 5 and not generic_name and (role_signal or company_signal):
                try:
                    payload={"first_name":name_words[0],"last_name":" ".join(name_words[1:]),"position":role_part if role_signal else None,"company_name":role_part if company_signal and not role_signal else None,"email":email_match.group(0) if email_match else None,"phone":self.serp_extractor._normalize_phone(phone_match.group(0)) if phone_match else None,"source_url":url,"capture_stage":"serp"}
                    extracted=[Lead.model_validate(payload, context={"generic_prefixes":self.generic_prefixes,"allow_serp_without_email":True})]
                except (ValidationError, TypeError, ValueError):
                    extracted=[]
            if not extracted and (email_match or phone_match):
                try:
                    extracted = await self.serp_extractor.extract(html, url, evidence=evidence)
                except Exception as exc:
                    emit_event(sink, "Extraction", f"SERP extraction failed {index}: {type(exc).__name__}", evidence=index, extracted=0, error=str(exc)[:500])
                    continue
            extracted = [lead.model_copy(update={"capture_stage":"serp"}) for lead in extracted]
            qualified = [lead for lead in extracted if self.qualifier.qualify(lead, criteria).relevant]
            extracted_total += len(extracted)
            qualified_total += len(qualified)
            persisted = 0
            for lead in qualified:
                if _persist_lead(scrap_id, lead, evidence_id=evidence_id):
                    persisted += 1
                    persisted_total += 1
                leads.append(lead)
            emit_event(sink, "Leads", "SERP leads persisted", extracted=len(extracted), qualified=len(qualified), persisted=persisted, leads=len(leads), extracted_total=extracted_total, qualified_total=qualified_total, persisted_total=persisted_total)
            if scrap_id and persisted_total >= criteria.max_leads:
                break
        return leads

    async def run_harvested(self, criteria: SearchCriteria, results, event_sink=None, scrap_id=None, cancel_check=None) -> list[Lead]:
        """Process SERP result occurrences, including snippets as first-class evidence."""
        sink = event_sink or NullJobEventSink()
        records = [r if isinstance(r, dict) else r.model_dump() for r in results]
        urls = [r.get("url", "") for r in records if r.get("url")]
        emit_event(sink, "URLs", "Imported SERP result occurrences", urls_total=len(urls), snippets=sum(bool(r.get("snippet", "").strip()) for r in records))
        leads: list[Lead] = []
        extracted_total = qualified_total = persisted_total = extraction_failures = 0
        started_at = time.monotonic()
        timeout_seconds = self.crawler_config.max_duration_hours * 3600
        stop_reason = None

        def should_stop_harvest():
            nonlocal stop_reason
            if cancel_check and cancel_check():
                stop_reason = "canceled"
                return True
            if len(dedupe(leads)) >= criteria.max_leads:
                stop_reason = "lead_limit"
                return True
            if time.monotonic() - started_at >= timeout_seconds:
                stop_reason = "time_limit"
                return True
            return False

        # Snippets are evidence, not just display metadata. Process them even when
        # the destination page later fails, so contact details visible in the SERP
        # are not discarded.
        for index, record in enumerate(records, start=1):
            if should_stop_harvest():
                break
            snippet = str(record.get("snippet", "")).strip()
            if not snippet:
                continue
            url = record.get("url")
            if not url:
                continue
            title = str(record.get("title", "")).strip()
            snippet_text = f"{title}\n{snippet}".strip()
            html = f"<html><body><h1>{escape(title)}</h1><p>{escape(snippet)}</p></body></html>"
            evidence = self.evidence.build(url=url, html=html, text=snippet_text, status=200, rendered=True, source="serp-snippet")
            _persist_evidence(scrap_id, evidence)
            emit_event(sink, "Evidence", f"SERP snippet evidence persisted {index}", evidence=index)
            try:
                extracted = await self.serp_extractor.extract(html, url, evidence=evidence)
            except Exception as exc:
                extraction_failures += 1
                emit_event(sink, "Extraction", f"Extraction failed for SERP evidence {index}: {type(exc).__name__}: {exc}", evidence=index, extracted=0, error_type=type(exc).__name__, error=str(exc)[:1000], extraction_failures=extraction_failures)
                extracted = []
            qualified = [lead for lead in extracted if self.qualifier.qualify(lead, criteria).relevant]
            extracted_total += len(extracted); qualified_total += len(qualified)
            persisted = 0
            for lead in qualified:
                if _persist_lead(scrap_id, lead, evidence_id=evidence_id):
                    persisted += 1
                    persisted_total += 1
            leads.extend(qualified)
            emit_event(sink, "Leads", "SERP lead candidates processed", extracted=len(extracted), qualified=len(qualified), persisted=persisted, leads=len(leads), extracted_total=extracted_total, qualified_total=qualified_total, persisted_total=persisted_total)
            if should_stop_harvest():
                break

        if urls:
            progress_callback = lambda event: emit_event(
                sink,
                "Collection",
                event.get("message", "Scrapy progress"),
                state=event.get("state", "running"),
                urls_submitted=int(event.get("urls_submitted", len(urls))),
                pages_collected=int(event.get("pages_collected", 0)),
                pages_failed=int(event.get("pages_failed", 0)),
            )
            snippet_queues: dict[str, list[str]] = {}
            for record in records:
                if record.get("url") and record.get("snippet"):
                    snippet_queues.setdefault(record["url"], []).append(str(record["snippet"]))
            page_index = 0
            cancelled = False
            try:
                async for page in self._stream_pages(urls, progress_callback=progress_callback, scrap_id=scrap_id, cancel_check=should_stop_harvest):
                    page_index += 1
                    if should_stop_harvest():
                        cancelled = stop_reason == "canceled"
                        if stop_reason != "canceled":
                            break
                        emit_event(sink, "Collection", "Job cancellation requested", state="canceled")
                    if cancelled or page.error or page.status >= 400 or page.status == 0:
                        continue
                    if is_document_url(page.url, page.content_type):
                        try:
                            document_text = extract_document_text(page.body, page.url, page.content_type)
                        except Exception:
                            continue
                        if not document_text.strip():
                            continue
                        html = f"<html><body><pre>{escape(document_text)}</pre></body></html>"
                        page_text = document_text
                    else:
                        if not page.html.strip():
                            continue
                        html = page.html
                        page_text = page.text
                    snippets = snippet_queues.get(page.url, [])
                    if snippets:
                        page_text = ("\n\nSERP SNIPPET EVIDENCE:\n" + "\n\n".join(snippets) + "\n\n" + page_text).strip()
                    evidence = self.evidence.build(url=page.url, html=html, text=page_text, status=page.status, rendered=False, source=page.source)
                    evidence_id = _persist_evidence(scrap_id, evidence)
                    emit_event(sink, "Evidence", f"Evidence persisted for page {page_index}", page=page_index, evidence=page_index)
                    try:
                        extracted = await self.extractor.extract(html, page.url, evidence=evidence)
                    except Exception as exc:
                        extraction_failures += 1
                        emit_event(sink, "Extraction", f"Extraction failed for page {page_index}: {type(exc).__name__}: {exc}", page=page_index, extracted=0, error_type=type(exc).__name__, error=str(exc)[:1000], extraction_failures=extraction_failures)
                        extracted = []
                    qualified = [lead for lead in extracted if self.qualifier.qualify(lead, criteria).relevant]
                    extracted_total += len(extracted); qualified_total += len(qualified)
                    persisted = 0
                    for lead in qualified:
                        if _persist_lead(scrap_id, lead, evidence_id=evidence_id):
                            persisted += 1
                    persisted_total += persisted
                    leads.extend(qualified)
                    emit_event(sink, "Validation", f"Validated page {page_index}", page=page_index, extracted=len(extracted))
                    emit_event(sink, "Leads", "Lead candidates processed", extracted=len(extracted), qualified=len(qualified), persisted=persisted, leads=len(leads), extracted_total=extracted_total, qualified_total=qualified_total, persisted_total=persisted_total)
            except Exception as exc:
                emit_event(sink, "Collection", "Collection failed", state="failed", urls_total=len(urls))
                print(f"collection_error={exc}")
                raise
            if stop_reason == "lead_limit":
                emit_event(sink, "Collection", f"Lead target reached ({criteria.max_leads}); stopping crawl", state="completed", stop_reason=stop_reason)
            elif stop_reason == "time_limit":
                emit_event(sink, "Collection", f"Research timeout reached ({self.crawler_config.max_duration_hours} hours); stopping crawl", state="completed", stop_reason=stop_reason)
            elif stop_reason == "canceled":
                emit_event(sink, "Collection", "Job cancellation requested", state="canceled", stop_reason=stop_reason)
            else:
                emit_event(sink, "Collection", "Collection complete", pages_collected=page_index, urls_total=len(urls))

        final = dedupe(leads)[:criteria.max_leads]
        emit_event(sink, "Qualification/Deduplication", "Qualification and deduplication complete", input_leads=len(leads), leads=len(final))
        emit_event(sink, "Leads", "Lead set ready", state="complete", leads=len(final))
        return final

    async def run_urls(self, criteria: SearchCriteria, urls, event_sink=None, scrap_id=None, cancel_check=None) -> list[Lead]:
        """Run the autonomous collection/extraction pipeline on human-imported URL occurrences."""
        sink = event_sink or NullJobEventSink()
        url_list = list(urls)
        emit_event(sink, "URLs", "Imported SERP URL occurrences", urls_total=len(url_list))
        page_queue: asyncio.Queue[CollectedPage | None] = asyncio.Queue(maxsize=16)
        loop = asyncio.get_running_loop()

        def page_callback(page):
            future = asyncio.run_coroutine_threadsafe(page_queue.put(page), loop)
            future.result()

        async def collect_stream():
            try:
                return await self.collector.collect_async(url_list, scrap_id=scrap_id, page_callback=page_callback, cancel_check=cancel_check)
            finally:
                await page_queue.put(None)

        collector_task = asyncio.create_task(collect_stream())
        leads: list[Lead] = []
        emit_event(sink, "Extraction", "Processing pages incrementally")

        page_index = 0
        cancelled = False
        while True:
            page = await page_queue.get()
            if page is None:
                break
            page_index += 1
            if cancel_check and cancel_check():
                cancelled = True
                emit_event(sink, "Collection", "Job cancellation requested", state="canceled")
            if cancelled:
                continue
            if page.status >= 400 or not _domain_allowed(page.url, self.domain_rules):
                continue
            if is_document_url(page.url, page.content_type):
                try:
                    document_text = extract_document_text(page.body, page.url, page.content_type)
                except Exception:
                    continue
                if not document_text.strip():
                    continue
                html = f"<html><body><pre>{escape(document_text)}</pre></body></html>"
                page_text = document_text
            else:
                if not page.html.strip():
                    continue
                html = page.html
                page_text = page.text
            evidence = self.evidence.build(url=page.url, html=html, text=page_text, status=page.status, rendered=False, source=page.source)
            _persist_evidence(scrap_id, evidence)
            emit_event(sink, "Evidence", f"Evidence persisted for page {page_index}", page=page_index, evidence=page_index)
            try:
                extracted = await self.extractor.extract(html, page.url, evidence=evidence)
            except Exception as exc:
                emit_event(
                    sink,
                    "Extraction",
                    f"Extraction failed for page {page_index}: {type(exc).__name__}: {exc}",
                    page=page_index,
                    extracted=0,
                    error_type=type(exc).__name__,
                    error=str(exc)[:1000],
                )
                extracted = []
            qualified = [lead for lead in extracted if self.qualifier.qualify(lead, criteria).relevant]
            leads.extend(qualified)
            emit_event(sink, "Validation", f"Validated page {page_index}", page=page_index, extracted=len(extracted))
            emit_event(sink, "Leads", "Lead candidates accepted", extracted=len(extracted), qualified=len(qualified), leads=len(leads))
        crawl_result = await collector_task
        emit_event(sink, "Collection", "Collection complete", pages_collected=len(crawl_result), urls_total=len(url_list))
        final = dedupe(leads)[:criteria.max_leads]
        emit_event(sink, "Qualification/Deduplication", "Qualification and deduplication complete", input_leads=len(leads), leads=len(final))
        emit_event(sink, "Leads", "Lead set ready", state="complete", leads=len(final))
        return final

    async def run_and_export(
        self,
        criteria: SearchCriteria,
        output: str = "output/leads.csv",
        *,
        google_spreadsheet_id: str | None = None,
        google_worksheet: str = "Leads",
        event_sink=None,
    ) -> str:
        leads = await self.run(criteria, event_sink=event_sink)

        if google_spreadsheet_id:
            return export_google_sheets(
                leads, google_spreadsheet_id, worksheet=google_worksheet
            )
        if output.lower().endswith(".xlsx"):
            return str(export_xlsx(leads, output))
        return str(export_csv(leads, output))

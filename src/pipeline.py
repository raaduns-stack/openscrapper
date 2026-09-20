import asyncio

from src.agent.discovery import DiscoveryAgent
from src.agent.qualification import LeadQualifier
from src.collector.scrapy_runner import ScrapyCollector
from src.dedupe.leads import dedupe, persist_lead
from src.extract.adaptive import AdaptiveLeadExtractor
from src.extract.evidence import EvidenceBuilder
from src.extract.documents import is_document_url, extract_document_text
from src.extract.phone import extract_phone
from html import escape
from urllib.parse import urlparse
import time
from src.exports.csv_export import export_csv
from src.exports.google_sheets import export_google_sheets
from src.exports.xlsx_export import export_xlsx
from src.models.criteria import CrawlerConfig, SearchCriteria
from src.models.lead import Lead
from pydantic import ValidationError
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
    return persist_lead(scrap_id, lead, evidence_id=evidence_id)


class LeadDiscoveryPipeline:
    def __init__(
        self,
        model: str = "openai/gpt-oss-20b",
        max_pages: int = 25,
        crawler_config: CrawlerConfig | None = None,
        generic_prefixes: set[str] | None = None,
        domain_rules: list[tuple[str, str]] | None = None,
        llm_call_counter=None,
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
        self.extractor = AdaptiveLeadExtractor(model=model, generic_prefixes=generic_prefixes, llm_call_counter=llm_call_counter)
        self.serp_extractor = AdaptiveLeadExtractor(model=model, generic_prefixes=generic_prefixes, llm_call_counter=llm_call_counter)
        self.qualifier = LeadQualifier()
        self.evidence = EvidenceBuilder()

    async def run(self, criteria: SearchCriteria, event_sink=None, scrap_id=None, cancel_check=None) -> list[Lead]:
        sink = event_sink or NullJobEventSink()
        started_at = time.monotonic()
        emit_event(sink, "Discovery", "Starting discovery")
        candidates = await self.discovery.discover(criteria, event_sink=sink)
        sink.emit(JobEvent(stage="URLs", state="complete", message=f"Captured {len(candidates)} candidate URLs from search", counts={"urls_captured": len(candidates)}, items=[{"url": str(c.url), "query": c.query} for c in candidates[:250]]))
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

    async def _stream_pages(self, urls, *, progress_callback=None, scrap_id=None, cancel_check=None, collector=None):
        collector = collector or self.collector
        page_queue: asyncio.Queue[CollectedPage | None] = asyncio.Queue(maxsize=16)
        loop = asyncio.get_running_loop()

        def page_callback(page):
            future = asyncio.run_coroutine_threadsafe(page_queue.put(page), loop)
            future.result()

        async def collect_stream():
            try:
                return await collector.collect_async(
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

    @staticmethod
    def _serp_payload(record: dict, source_url: str) -> dict | None:
        """Extract a person from SERP title/snippet evidence without requiring email."""
        import re as _re

        title = str(record.get("title") or "").replace("\xa0", " ").strip()
        snippet = str(record.get("snippet") or "").replace("\xa0", " ").strip()
        raw_text = str(record.get("raw_text") or "").replace("\xa0", " ").strip()
        text = " ".join(part for part in (title, snippet, raw_text) if part)
        evidence_text = " ".join(part for part in (snippet, raw_text) if part)
        if not text:
            return None

        email_match = _re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, _re.I)
        phone_value = extract_phone(text, None)
        position = None
        company_name = None
        city = state = country = None

        from urllib.parse import urlparse as _urlparse
        parsed_url = _urlparse(source_url)
        path = (parsed_url.path or "").casefold()
        host = (parsed_url.hostname or "").casefold()
        is_linkedin_person = host.endswith("linkedin.com") and "/in/" in path
        is_author_page = "/author/" in path or "/profile" in path
        is_facebook_person = host.endswith("facebook.com") and "/p/" in path

        name_part = ""
        # Strong person evidence in snippets takes precedence over page titles.
        name_match = _re.search(
            r"\b([A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+){1,3}),\s+based\s+in\b",
            evidence_text,
        )
        if name_match:
            name_part = name_match.group(1).strip()

        if not name_part:
            # Common editorial/profile wording: "endorses Jane Doe, RN".
            name_match = _re.search(
                r"\b(?:endorses|featuring|profile(?:d)? on|by)\s+([A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+){1,3})(?:,\s*(?:RN|NP|MD|DNP|BSN|MSN|PhD|DO|DDS|DMD)\b)?",
                title,
            )
            if name_match:
                name_part = name_match.group(1).strip()
                cred_match = _re.search(r"\b(RN|NP|MD|DNP|BSN|MSN|PhD|DO|DDS|DMD)\b", title, _re.I)
                if cred_match:
                    position = cred_match.group(1).upper()

        if not name_part:
            # Person-profile pages have a stronger title contract than arbitrary web pages.
            title_person = title
            if is_linkedin_person or is_author_page or is_facebook_person:
                title_person = _re.split(r"\s+(?:-|–|—|\|)\s+", title_person, maxsplit=1)[0]
                title_person = title_person.split(",", 1)[0].strip()
                # Facebook pages such as "Nurse Emily" identify the page subject as Emily.
                if is_facebook_person:
                    nurse_match = _re.match(r"(?:Nurse|Doctor|Dr\.?)\s+([A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+)*)", title_person)
                    if nurse_match:
                        name_part = nurse_match.group(1).strip()
                        position = title_person[:nurse_match.start(1)].strip() or position
                if not name_part:
                    name_part = title_person.strip()
            else:
                # Search-result titles that explicitly advertise an individual's contact record.
                contact_name = _re.match(
                    r"^([A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+){1,3})\s+(?:email|phone)\b",
                    title, _re.I,
                )
                if contact_name:
                    name_part = contact_name.group(1).strip()
                else:
                    # Generic title fallback; it is accepted only if the candidate words are not
                    # recognizable page/category terms.
                    name_part = title
                    name_part = _re.sub(
                        r"\s+(?:email\s*(?:&|and)\s*phone(?:\s+number)?|phone\s*(?:&|and)\s*email(?:\s+address)?|email\s+address)\b.*$",
                        "", name_part, flags=_re.I,
                    ).strip(" -|:")

        # Strip honorifics and professional credentials from the person-name portion.
        name_part = _re.sub(r"^(?:Dr\.?|Doctor|Prof\.?|Professor|Mr\.?|Mrs\.?|Ms\.?|Miss)\s+", "", name_part, flags=_re.I).strip()
        name_part = _re.sub(r",?\s*(?:MD|MBBS|PhD|MSc|DO|RN|DDS|DMD|BSN|MSN|NP)(?:\s*,\s*(?:RN|BSN|MSN|NP|DNP|PhD|MD))*$", "", name_part, flags=_re.I).strip()

        if not position:
            role_match = _re.search(r"\bis\s+currently\s+(?:a|an|the)\s+([^,.]+)", evidence_text, _re.I)
            if role_match:
                position = role_match.group(1).strip()

        if not position:
            role_match = _re.search(r"\bcurrently\s+(?:a|an|the)\s+([^,.]+)", evidence_text, _re.I)
            if role_match:
                position = role_match.group(1).strip()

        # LinkedIn snippets often contain a clean "Name · Role · Company" representation.
        if not position and is_linkedin_person:
            role_match = _re.search(r"\b(?:Registered|Licensed|Family|Staff|Senior|Critical Care|Clinical|Nurse|Operating Room|Intensive Care|Assistant|Customer|Practice|Medical|Healthcare)[^\n·|]{0,120}", raw_text, _re.I)
            if role_match:
                position = role_match.group(0).strip(" .")

        location_match = _re.search(
            r"\bbased\s+in\s+([^,.;]+),\s*([A-Z]{2}),\s*(US|USA|United States|UK|United Kingdom|Canada|Australia|India|South Africa)\b",
            evidence_text, _re.I,
        )
        if location_match:
            city = location_match.group(1).strip()
            state = location_match.group(2).strip().upper()
            country = location_match.group(3).strip()
            country = {"us": "United States", "usa": "United States", "uk": "United Kingdom"}.get(country.casefold(), country)

        if not name_part:
            return None
        name_words = name_part.split()
        if not 2 <= len(name_words) <= 5:
            if not (len(name_words) == 1 and (is_linkedin_person or is_author_page or is_facebook_person)):
                return None
        bad_name_tokens = {
            "email", "phone", "number", "list", "database", "contacts", "verified",
            "gmail", "yahoo", "outlook", "hotmail", "alumni", "job", "board",
            "programme", "program", "faculty", "learning", "columns", "salary",
            "registered", "new", "graduate", "programs", "leading", "homecare",
            "agency", "award-winning", "travel", "official", "site", "join",
            "explore", "benefits", "trusted", "health", "matched", "flexible",
            "jobs", "contact", "customer", "service", "find", "exam", "login",
            "directory", "search", "hiring", "alert", "hudson", "valley", "black",
            "association", "nys", "perinatal", "psychiatry", "greater", "city",
            "information", "fishin", "hole", "nursing", "nurses",
        }
        if any(token.casefold().strip(".,:;()") in bad_name_tokens for token in name_words):
            return None
        # A role word can be a legitimate surname (e.g. Sandy Nurse); allow it on
        # explicit person/profile pages but not on arbitrary category pages.
        if not (is_linkedin_person or is_author_page or is_facebook_person):
            if any(token.casefold().strip(".,:;()") in {"nurse", "doctor", "health", "company"} for token in name_words):
                return None

        # An explicit snippet identity may use a middle name; preserve it in last_name.
        return {
            "first_name": name_words[0],
            "last_name": " ".join(name_words[1:]),
            "position": position,
            "company_name": company_name,
            "email": email_match.group(0) if email_match else None,
            "phone": phone_value,
            "city": city,
            "state": state,
            "country": country,
            "source_url": source_url,
            "capture_stage": "serp",
        }

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
            raw_text = str(record.get("raw_text") or "").strip()
            title = str(record.get("title") or "").strip()
            if not url or not (snippet or title):
                continue
            html = f"<html><body><h1>{escape(title)}</h1><p>{escape(snippet)}</p></body></html>"
            text = f"{title}\n{snippet}\n{raw_text}".strip()
            evidence = self.evidence.build(url=url, html=html, text=text, status=200, rendered=True, source="serp-snippet")
            evidence_id = _persist_evidence(scrap_id, evidence)
            extracted = []
            payload = self._serp_payload(record, url)
            if payload:
                try:
                    extracted = [Lead.model_validate(payload, context={"generic_prefixes": self.generic_prefixes})]
                except (ValidationError, TypeError, ValueError):
                    extracted = []
            # SERP master records are deterministic evidence. Never invoke the LLM here.
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
        urls = [str(r.get("url", "")).strip() for r in records if r.get("url")]
        unique_urls = list(dict.fromkeys(urls))
        skipped_urls = 0
        if scrap_id and unique_urls:
            import uuid as _uuid
            from src.db import db as _db
            with _db() as conn:
                rows = conn.execute("SELECT DISTINCT url FROM crawl_pages WHERE scrap_id=%s AND url = ANY(%s)", (_uuid.UUID(str(scrap_id)), unique_urls)).fetchall()
            crawled = {str(row[0]).strip() for row in rows}
            skipped_urls = sum(1 for url in unique_urls if url in crawled)
            unique_urls = [url for url in unique_urls if url not in crawled]
        urls = unique_urls
        emit_event(sink, "URLs", "Imported SERP result occurrences", urls_total=len(urls), urls_skipped=skipped_urls, snippets=sum(bool(r.get("snippet", "").strip()) for r in records))
        leads: list[Lead] = []
        extracted_total = qualified_total = persisted_total = extraction_failures = 0
        if scrap_id:
            import uuid as _uuid
            from src.db import db as _db
            with _db() as conn:
                persisted_total = int(conn.execute("SELECT count(*) FROM leads WHERE scrap_id=%s", (_uuid.UUID(str(scrap_id)),)).fetchone()[0])
        started_at = time.monotonic()
        timeout_seconds = self.crawler_config.max_duration_hours * 3600
        stop_reason = None

        def should_stop_harvest():
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

        # Snippets are evidence, not just display metadata. Process them even when
        # the destination page later fails, so contact details visible in the SERP
        # are not discarded.
        for index, record in enumerate(records, start=1):
            if should_stop_harvest():
                break
            snippet = str(record.get("snippet", "")).strip()
            raw_text = str(record.get("raw_text", "")).strip()
            if not (snippet or raw_text):
                continue
            url = record.get("url")
            if not url:
                continue
            title = str(record.get("title", "")).strip()
            snippet_text = f"{title}\n{snippet}\n{raw_text}".strip()
            html = f"<html><body><h1>{escape(title)}</h1><p>{escape(snippet)}</p></body></html>"
            evidence = self.evidence.build(url=url, html=html, text=snippet_text, status=200, rendered=True, source="serp-snippet")
            evidence_id = _persist_evidence(scrap_id, evidence)
            emit_event(sink, "Evidence", f"SERP snippet evidence persisted {index}", evidence=index)
            try:
                # SERP title/snippet extraction must use the deterministic SERP
                # parser so email is optional under the approved qualification rule.
                # scrap_id=None prevents this helper from persisting a second copy;
                # the current loop persists the result and links the current evidence.
                extracted = await self.process_serp_records(
                    criteria,
                    [record],
                    scrap_id=None,
                    cancel_check=cancel_check,
                )
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
                record_url = str(record.get("url", "")).strip()
                if record_url in urls and record.get("snippet"):
                    snippet_queues.setdefault(record_url, []).append(str(record["snippet"]))
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

    async def enrich_lead(self, criteria: SearchCriteria, lead: Lead, event_sink=None, scrap_id=None, cancel_check=None) -> list[Lead]:
        """Enrich one persisted lead through the same controlled Scrapy engine."""
        sink = event_sink or NullJobEventSink()
        source_url = str(lead.source_url).strip()
        website = str(lead.website).strip() if lead.website else ""
        seed_urls = []
        for candidate in (source_url, website):
            if not candidate or candidate in seed_urls:
                continue
            parsed = urlparse(candidate)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                seed_urls.append(candidate)
        if not seed_urls:
            return []
        emit_event(sink, "URLs", "Enriching lead sources", urls_total=len(seed_urls), items=[{"url": url} for url in seed_urls])
        started_at = time.monotonic()
        timeout_seconds = self.crawler_config.max_duration_hours * 3600
        stop_reason = None

        def should_stop():
            nonlocal stop_reason
            if cancel_check and cancel_check():
                stop_reason = "canceled"
                return True
            if time.monotonic() - started_at >= timeout_seconds:
                stop_reason = "time_limit"
                return True
            return False

        progress_callback = lambda event: emit_event(
            sink, "Collection", event.get("message", "Scrapy progress"),
            state=event.get("state", "running"),
            urls_submitted=int(event.get("urls_submitted", len(seed_urls))),
            pages_collected=int(event.get("pages_collected", 0)),
            pages_failed=int(event.get("pages_failed", 0)),
        )
        # Enrichment must remain bounded even when legacy Scrap configs contain
        # null crawl limits. Existing explicit limits are preserved.
        enrichment_config = self.crawler_config.model_copy(update={
            "max_crawl_pages": self.crawler_config.max_crawl_pages or 100,
            "max_crawl_urls": self.crawler_config.max_crawl_urls or 250,
            "max_crawl_depth": self.crawler_config.max_crawl_depth if self.crawler_config.max_crawl_depth is not None else 5,
        })
        enrichment_collector = ScrapyCollector(
            max_pages=enrichment_config.max_crawl_pages,
            max_urls=enrichment_config.max_crawl_urls,
            max_depth=enrichment_config.max_crawl_depth,
        )
        leads = []
        async for page in self._stream_pages(
            seed_urls,
            progress_callback=progress_callback,
            scrap_id=scrap_id,
            cancel_check=should_stop,
            collector=enrichment_collector,
        ):
            if should_stop() or page.error or page.status >= 400 or not _domain_allowed(page.url, self.domain_rules):
                continue
            if is_document_url(page.url, page.content_type):
                try:
                    page_text = extract_document_text(page.body, page.url, page.content_type)
                except Exception:
                    continue
                if not page_text.strip():
                    continue
                html = f"<html><body><pre>{escape(page_text)}</pre></body></html>"
            else:
                if not page.html.strip():
                    continue
                html = page.html
                page_text = page.text
            evidence = self.evidence.build(
                url=page.url, html=html, text=page_text, status=page.status,
                rendered=False, source=page.source,
            )
            evidence_id = _persist_evidence(scrap_id, evidence)
            try:
                extracted = await self.extractor.extract(html, page.url, evidence=evidence)
            except Exception as exc:
                emit_event(sink, "Extraction", f"Enrichment extraction failed: {type(exc).__name__}: {exc}")
                continue
            qualified = [lead_item for lead_item in extracted if self.qualifier.qualify(lead_item, criteria).relevant]
            for lead_item in qualified:
                _persist_lead(scrap_id, lead_item, evidence_id=evidence_id)
            leads.extend(qualified)
            emit_event(
                sink, "Leads", "Enrichment candidates processed",
                extracted=len(extracted), qualified=len(qualified), leads=len(leads),
            )
            if should_stop():
                break
        if stop_reason == "time_limit":
            emit_event(sink, "Collection", "Enrichment timeout reached", state="completed", stop_reason=stop_reason)
        elif stop_reason == "canceled":
            emit_event(sink, "Collection", "Enrichment canceled", state="canceled", stop_reason=stop_reason)
        else:
            emit_event(sink, "Collection", "Enrichment complete", state="completed")
        return dedupe(leads)


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

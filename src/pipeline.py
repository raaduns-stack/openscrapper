from src.agent.discovery import DiscoveryAgent
from src.browser.openclaw import OpenClawBrowser
from src.browser.paginator import Paginator
from src.dedupe.leads import dedupe
from src.agent.qualification import LeadQualifier
from src.extract.adaptive import AdaptiveLeadExtractor
from src.models.criteria import SearchCriteria
from src.models.lead import Lead
from src.exports.csv_export import export_csv
from src.exports.xlsx_export import export_xlsx


class LeadDiscoveryPipeline:
    def __init__(self, model: str = "openai/gpt-oss-20b", max_pages: int = 25):
        self.discovery = DiscoveryAgent()
        self.browser = OpenClawBrowser()
        self.paginator = Paginator(self.browser, max_pages=max_pages)
        self.extractor = AdaptiveLeadExtractor(model=model)
        self.qualifier = LeadQualifier()

    async def run(self, criteria: SearchCriteria) -> list[Lead]:
        candidates = await self.discovery.discover(criteria)
        leads: list[Lead] = []

        for candidate in candidates:
            try:
                pages = self.paginator.collect(candidate.url)

                for page_url, html in pages:
                    extracted = await self.extractor.extract(
                        html,
                        page_url,
                    )
                    leads.extend(
                        lead for lead in extracted
                        if self.qualifier.qualify(lead, criteria).relevant
                    )

                    if len(leads) >= criteria.max_leads:
                        break

            except Exception as exc:
                print(f"skip={candidate.url} error={exc}")
                continue

            if len(leads) >= criteria.max_leads:
                break

        return dedupe(leads)[:criteria.max_leads]

    async def run_and_export(
        self,
        criteria: SearchCriteria,
        output: str = "output/leads.csv",
    ) -> str:
        leads = await self.run(criteria)

        if output.lower().endswith(".xlsx"):
            return export_xlsx(leads, output)

        return export_csv(leads, output)

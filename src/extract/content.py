from crawlee.crawlers import HttpCrawler, HttpCrawlingContext
import trafilatura


class CrawleeContentExtractor:
    async def extract(self, url: str) -> str:
        result = None

        async def handler(context: HttpCrawlingContext) -> None:
            nonlocal result
            html = (await context.get_snapshot()).html
            result = trafilatura.extract(
                html,
                include_links=True,
                include_tables=True,
                output_format="txt",
            ) or html
            crawler.stop()

        crawler = HttpCrawler(request_handler=handler)
        await crawler.run([url])

        if result is None:
            raise RuntimeError(f"No content extracted: {url}")

        return result

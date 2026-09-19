from urllib.parse import quote_plus
class BingQueryAdapter:
    name='bing'
    def build_url(self, query: str) -> str:
        return 'https://www.bing.com/search?q=' + quote_plus(query)

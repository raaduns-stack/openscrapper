from urllib.parse import quote_plus
class GoogleQueryAdapter:
    name='google'
    def build_url(self, query: str) -> str:
        return 'https://www.google.com/search?q=' + quote_plus(query)

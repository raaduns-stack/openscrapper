from src.search.premium import HttpPremiumSerpProvider, PremiumSerpItem


class FakeProvider:
    def __init__(self):
        self.pages = []

    def search(self, search_url, *, limit, page=1):
        self.pages.append(page)
        count = min(limit, 100 if page < 3 else 50)
        return [PremiumSerpItem(f"https://example.com/{page}/{i}") for i in range(count)]


class FakeHttpProvider(HttpPremiumSerpProvider):
    def __init__(self, provider):
        self.fake = provider

    def _provider(self):
        return "serper", self.fake


def test_premium_search_all_fetches_pages_concurrently_and_preserves_order():
    fake = FakeProvider()
    client = FakeHttpProvider(fake)
    items = client.search_all("https://www.google.com/search?q=test", limit=250)

    assert len(items) == 250
    assert sorted(fake.pages) == [1, 2, 3]
    assert items[0].url == "https://example.com/1/0"
    assert items[-1].url == "https://example.com/3/49"


def test_premium_search_all_preserves_repeated_url_occurrences():
    class DuplicateProvider:
        def search(self, search_url, *, limit, page=1):
            return [PremiumSerpItem("https://example.com/repeated") for _ in range(limit)]

    client = FakeHttpProvider(DuplicateProvider())
    items = client.search_all("https://www.google.com/search?q=test", limit=200)

    assert len(items) == 200
    assert all(item.url == "https://example.com/repeated" for item in items)


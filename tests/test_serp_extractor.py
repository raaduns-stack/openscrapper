from src.search.serp_extractor import extract_destination_urls

def test_serp_extractor_returns_destination_urls_without_search_engine_links():
    html='''<a href="https://linkedin.com/in/a">A</a><a href="https://www.google.com/search?q=x">Google</a><a href="/contact">Contact</a>'''
    urls=extract_destination_urls(html,'https://www.example.com/page')
    assert 'https://linkedin.com/in/a' in urls
    assert 'https://www.example.com/contact' in urls
    assert not any('google.com/search' in u for u in urls)

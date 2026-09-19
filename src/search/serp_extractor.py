from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
SEARCH_HOSTS={"www.google.com","google.com","www.bing.com","bing.com"}
CHALLENGE_MARKERS=("/sorry/","captcha","unusual traffic","verify you are human")

def extract_destination_urls(html: str, base_url: str) -> list[str]:
    soup=BeautifulSoup(html,'html.parser'); host=urlparse(base_url).netloc.lower()
    if any(marker in (base_url.lower()+" "+soup.get_text(" ",strip=True).lower()) for marker in CHALLENGE_MARKERS):
        return []
    selectors=['a:has(h3)','li.b_algo h2 a','li.b_algo a[href]']
    anchors=[]
    for selector in selectors:
        found=soup.select(selector)
        if found: anchors.extend(found)
    if not anchors: anchors=soup.select('a[href]')
    out=[]
    for a in anchors:
        href=(a.get('href') or '').strip(); u=urljoin(base_url,href); parsed=urlparse(u)
        if parsed.scheme not in {'http','https'} or not parsed.netloc or parsed.netloc.lower() in SEARCH_HOSTS: continue
        out.append(u)
    return out

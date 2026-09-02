import sys
from src.browser.openclaw import OpenClawBrowser
from src.extract.leads import LeadExtractor
from src.dedupe.leads import dedupe
from src.exports.csv_export import export_csv

def main(url: str):
    browser = OpenClawBrowser()
    browser.navigate(url)
    leads = LeadExtractor().extract(browser.html(), url)
    leads = dedupe(leads)
    path = export_csv(leads)
    print(f"leads={len(leads)}")
    print(f"export={path}")

if __name__ == "__main__":
    main(sys.argv[1])

# Scrappee Browser Import v0.6.9

Automatic Google/Bing SERP collection built directly on the stable v0.6.7 extraction method.

## Flow

1. Open Google or Bing and run the search manually.
2. Open the extension and log in.
3. Click **START AUTOMATIC SERP COLLECTION**.
4. The extension captures the current rendered SERP with the stable extractor.
5. Each page is immediately synced to the authenticated Current Scrap.
6. The real Google/Bing Next link is followed automatically.
7. If Google/Bing shows a CAPTCHA or challenge, collection pauses.
8. Solve the challenge in the browser and click **RESUME AFTER CAPTCHA**.
9. Collection continues until there is no usable Next link, the server SERP limit is reached, the user stops it, or the page stops changing.

The extension does not solve or bypass CAPTCHAs.

## Scrapy handoff

Collected SERP results remain in the existing Current Scrap and use the existing Scrappee research/Scrapy pipeline. No new crawler architecture is introduced.

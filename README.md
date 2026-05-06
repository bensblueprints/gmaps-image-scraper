# gmaps-image-scraper

Scrapes business photos from Google Maps place listings. No API key.

## Setup

```powershell
cd C:\Users\HP\Projects\gmaps-image-scraper
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

## Use

```powershell
# single query
python scrape.py "joe's pizza brooklyn"

# direct place URL
python scrape.py --url "https://www.google.com/maps/place/..."

# batch from a file (one query/URL per line)
python scrape.py --csv leads.txt --max 30 --out .\photos

# watch the browser run
python scrape.py "broome motor inn" --headful
```

Output: `./photos/<slug>/<hash>.jpg`. Resolution is bumped to 2048×2048 where possible.

## Web service

Hosted at **https://maps.advancedmarketing.co** (Coolify, Contabo VPS 2). Token-protected — set `ACCESS_TOKEN` in Coolify env. Submit a query, get a zip back.

Local dev:
```powershell
$env:ACCESS_TOKEN="dev"
uvicorn app:app --reload
```

## Caveats

- ToS-grey. Use for your own client research / lead enrichment, not redistribution.
- Google's DOM changes; if selectors break, run `--headful` and update `open_photos_panel`.
- Rate-sensitive. For >50 places at a time, add sleeps or split runs.

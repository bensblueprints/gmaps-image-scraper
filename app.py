"""FastAPI front-end for the Google Maps photo scraper.

One HTML form: enter a query (or place URL), submit, get a zip back.
Token auth via ACCESS_TOKEN env (set in Coolify).
"""
from __future__ import annotations

import io
import os
import secrets
import tempfile
import zipfile
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from scrape import scrape_one, slugify

ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN", "")
MAX_PHOTOS_CAP = int(os.environ.get("MAX_PHOTOS_CAP", "60"))

app = FastAPI(title="GMaps Image Scraper")

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GMaps Image Scraper</title>
<style>
:root { color-scheme: dark; }
body { font: 15px/1.5 -apple-system,Segoe UI,Inter,sans-serif; max-width: 540px;
       margin: 8vh auto; padding: 0 20px; background:#0b0d10; color:#e6e8eb; }
h1 { font-size: 22px; margin: 0 0 4px; }
p.sub { color:#8a929c; margin:0 0 28px; }
label { display:block; font-size:13px; color:#a8b0ba; margin: 14px 0 6px; }
input { width:100%; padding:10px 12px; background:#15181d; color:#e6e8eb;
        border:1px solid #262b33; border-radius:8px; font:inherit; box-sizing:border-box; }
input:focus { outline:none; border-color:#4d7cff; }
button { margin-top:22px; width:100%; padding:11px; background:#4d7cff; color:#fff;
         border:0; border-radius:8px; font:600 14px/1 inherit; cursor:pointer; }
button:hover { background:#5e8aff; }
button:disabled { background:#2a2f38; cursor:wait; }
.err { color:#ff7a7a; margin-top:14px; font-size:13px; }
.note { color:#7a818c; font-size:12px; margin-top:18px; }
</style>
</head>
<body>
<h1>GMaps Image Scraper</h1>
<p class="sub">Enter a business query or a Google Maps place URL. Returns a zip of photos.</p>
<form id="f" method="post" action="/scrape">
  <label>Query or place URL</label>
  <input name="query" required placeholder="joe's pizza brooklyn" autofocus>
  <label>Max photos (1–{cap})</label>
  <input name="max_photos" type="number" min="1" max="{cap}" value="30">
  <label>Access token</label>
  <input name="token" type="password" required>
  <button type="submit" id="btn">Scrape</button>
  <div class="err" id="err">{err}</div>
</form>
<p class="note">Photos are returned at up to 2048×2048. Job typically takes 20–60s.</p>
<script>
const f = document.getElementById('f');
f.addEventListener('submit', () => {
  const b = document.getElementById('btn');
  b.disabled = true; b.textContent = 'Scraping… (20–60s)';
});
</script>
</body></html>"""


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return PAGE.replace("{err}", "").replace("{cap}", str(MAX_PHOTOS_CAP))


@app.get("/healthz")
async def health() -> dict:
    return {"ok": True}


@app.post("/scrape")
async def scrape_endpoint(
    request: Request,
    query: str = Form(...),
    max_photos: int = Form(30),
    token: str = Form(...),
) -> StreamingResponse:
    if not ACCESS_TOKEN or not secrets.compare_digest(token, ACCESS_TOKEN):
        raise HTTPException(status_code=401, detail="invalid token")
    max_photos = max(1, min(int(max_photos), MAX_PHOTOS_CAP))

    with tempfile.TemporaryDirectory() as td:
        out_root = Path(td)
        try:
            await scrape_one(query, out_root, max_photos, headful=False)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"scrape failed: {e}")

        files = sorted(p for p in out_root.rglob("*") if p.is_file())
        if not files:
            raise HTTPException(status_code=404, detail="no photos found")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in files:
                zf.write(f, arcname=f.relative_to(out_root))
        buf.seek(0)

        slug = slugify(query)
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{slug}.zip"'},
        )

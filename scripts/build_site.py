#!/usr/bin/env python3
"""Build the public site for GitHub Pages -> docs/.

Usage: python3 scripts/build_site.py   (after scripts/build_questions.py)

app/index.html is written as a page body (that's how the claude.ai preview
expects it). This wraps it in a full HTML document with link-preview tags and
copies the questions and preview image alongside.
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP, DOCS = ROOT / "app", ROOT / "docs"
SITE_URL = "https://sreeraagmohan.github.io/tbb-quiz/"
TITLE = "TBB Current Affairs Quiz"
DESCRIPTION = "Free UPSC Prelims current affairs practice, written from every issue of The Bharat Briefing."
FAVICON = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
    "%3Crect width='32' height='32' fill='%23ad2c24'/%3E%3Ctext x='16' y='23' font-family='Georgia' "
    "font-weight='bold' font-size='20' fill='%23f7e9d4' text-anchor='middle'%3ET%3C/text%3E%3C/svg%3E"
)


def main():
    page = (APP / "index.html").read_text()
    split = page.index('<div class="wrap"')
    head, body = page[:split], page[split:]
    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="description" content="{DESCRIPTION}">
<meta property="og:type" content="website">
<meta property="og:url" content="{SITE_URL}">
<meta property="og:title" content="{TITLE}">
<meta property="og:description" content="{DESCRIPTION}">
<meta property="og:image" content="{SITE_URL}og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="627">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="{FAVICON}">
<style>
:root {{ padding-top: env(safe-area-inset-top, 0px); padding-bottom: env(safe-area-inset-bottom, 0px); color-scheme: light; }}
body {{ margin: 0; }}
img {{ max-width: 100%; }}
[hidden] {{ display: none !important; }}
</style>
{head.strip()}
</head>
<body>
{body.strip()}
</body>
</html>
"""
    DOCS.mkdir(exist_ok=True)
    (DOCS / "index.html").write_text(doc)
    shutil.copy(APP / "questions.json", DOCS / "questions.json")
    shutil.copy(ROOT / "assets" / "og.png", DOCS / "og.png")
    (DOCS / ".nojekyll").touch()
    print(f"built docs/ for {SITE_URL}")


if __name__ == "__main__":
    main()

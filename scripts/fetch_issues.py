#!/usr/bin/env python3
"""Pull every published TBB issue from the beehiiv API into data/raw/.

Usage: python3 scripts/fetch_issues.py

Reads BEEHIIV_API_KEY (and optionally BEEHIIV_PUBLICATION_ID) from .env.
Writes one JSON file per issue to data/raw/ and an index to data/issues.json.
Safe to re-run: existing files are overwritten with the latest content.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
INDEX = ROOT / "data" / "issues.json"
API = "https://api.beehiiv.com/v2"
IST = ZoneInfo("Asia/Kolkata")


def load_env():
    env = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip("'\"")
    env.update({k: v for k, v in os.environ.items() if k.startswith("BEEHIIV_")})
    return {k: v for k, v in env.items() if v}


def get(path, key, params=None):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"}
    )
    last = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500:
                body = e.read().decode(errors="replace")[:500]
                sys.exit(f"beehiiv returned {e.code} for {path}: {body}")
            last = f"HTTP {e.code}"
        except urllib.error.URLError as e:
            last = e.reason
        time.sleep(2 ** attempt * 2)
    sys.exit(f"Gave up on {path} after retries ({last})")


def pick_publication(env, key):
    if env.get("BEEHIIV_PUBLICATION_ID"):
        return env["BEEHIIV_PUBLICATION_ID"]
    pubs = get("/publications", key)["data"]
    for p in pubs:
        print(f"  found publication {p['id']}  {p.get('name')}")
    if len(pubs) != 1:
        sys.exit("This key sees several publications. Set BEEHIIV_PUBLICATION_ID in .env.")
    return pubs[0]["id"]


def save(post):
    ts = post.get("publish_date") or post.get("displayed_date") or post.get("created")
    date = datetime.fromtimestamp(ts, IST).strftime("%Y-%m-%d") if ts else "undated"
    html = (((post.get("content") or {}).get("free") or {}).get("web")) or ""
    record = {
        "id": post["id"],
        "date": date,
        "title": post.get("title"),
        "subtitle": post.get("subtitle"),
        "slug": post.get("slug"),
        "web_url": post.get("web_url"),
        "content_tags": post.get("content_tags") or [],
        "html": html,
    }
    name = f"{date}_{post.get('slug') or post['id']}.json"
    (RAW / name).write_text(json.dumps(record, ensure_ascii=False, indent=1))
    return {k: record[k] for k in ("id", "date", "title", "web_url")} | {
        "file": f"raw/{name}",
        "chars": len(html),
    }


def main():
    env = load_env()
    key = env.get("BEEHIIV_API_KEY")
    if not key:
        sys.exit("Add BEEHIIV_API_KEY to .env first.")
    pub_id = pick_publication(env, key)
    RAW.mkdir(parents=True, exist_ok=True)

    base = {
        "expand[]": ["free_web_content"],
        "status": "confirmed",
        "platform": "all",
        "limit": 50,
        "order_by": "publish_date",
        "direction": "asc",
    }
    index, page, cursor = [], 1, None
    while True:
        params = base | ({"cursor": cursor} if cursor else {"page": page})
        resp = get(f"/publications/{pub_id}/posts", key, params)
        for post in resp.get("data", []):
            index.append(save(post))
        print(f"  fetched {len(index)} issues so far")
        # beehiiv supports both cursor and page pagination; follow whichever it returns.
        if resp.get("next_cursor") and resp.get("has_more", True):
            cursor = resp["next_cursor"]
        elif cursor is None and page < resp.get("total_pages", 0):
            page += 1
        else:
            break

    index.sort(key=lambda r: r["date"])
    INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=1))
    empty = [r for r in index if r["chars"] == 0]
    print(f"\nSaved {len(index)} issues, {index[0]['date'] if index else '-'} to {index[-1]['date'] if index else '-'}")
    if empty:
        print(f"{len(empty)} issues came back with no web content, e.g. {empty[0]['title']!r}")


if __name__ == "__main__":
    main()

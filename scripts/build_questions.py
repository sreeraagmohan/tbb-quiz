#!/usr/bin/env python3
"""Validate every question file in data/questions/ and build app/questions.json.

Usage: python3 scripts/build_questions.py

Each question must point at a real story, have exactly four distinct options,
and quote a `source` sentence that appears verbatim in that story. The output
joins in the issue date, titles and a deep link that scrolls to the quote.
"""
import json
import re
import sys
import urllib.parse
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QDIR = ROOT / "data" / "questions"
OUT = ROOT / "app" / "questions.json"

TOPICS = [
    "Polity & Governance",
    "Economy",
    "International Relations",
    "Environment & Energy",
    "Science & Tech",
    "Defence & Security",
    "Agriculture",
    "Society",
    "Geography",
]
FORMATS = {"single", "statements", "pairs"}


def norm(s):
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip()


def slugify(title):
    s = re.sub(r"['’‘\"“”]", "", title.lower())
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def deep_link(url, story, quote):
    """Link that highlights the quoted sentence (text fragment). Browsers that
    can't match it fall back to the story's heading anchor, which beehiiv adds
    on some posts, and otherwise open the issue at the top."""
    words = quote.split()
    start = " ".join(words[:8]) if len(words) > 10 else quote
    frag = urllib.parse.quote(start, safe="").replace("-", "%2D")
    anchor = "also-in-the-news" if story["kind"] == "aitn" else slugify(story["title"])
    return f"{url}#{anchor}:~:text={frag}"


def check(q, stories):
    errs = []
    for key in ("id", "story_id", "topic", "difficulty", "format", "prompt", "options", "answer", "explain", "source"):
        if key not in q:
            errs.append(f"missing {key}")
    if errs:
        return errs
    story = stories.get(q["story_id"])
    if not story:
        return [f"unknown story {q['story_id']}"]
    if q["topic"] not in TOPICS:
        errs.append(f"unknown topic {q['topic']!r}")
    if q["format"] not in FORMATS:
        errs.append(f"unknown format {q['format']!r}")
    if q["format"] != "single" and not (q.get("items") and q.get("ask")):
        errs.append("statements/pairs need items and ask")
    if len(q["options"]) != 4 or len(set(q["options"])) != 4:
        errs.append("need exactly four distinct options")
    if not 0 <= q["answer"] < len(q["options"]):
        errs.append("answer out of range")
    haystack = norm(story["text"] + " " + (story["sound_smarter"] or ""))
    if norm(q["source"]) not in haystack:
        errs.append(f"source not found in story: {q['source'][:70]!r}")
    return errs


def main():
    stories = {s["id"]: s for s in json.loads((ROOT / "data" / "stories.json").read_text())}
    questions, failed = [], 0
    for f in sorted(QDIR.glob("*.json")):
        for q in json.loads(f.read_text()):
            errs = check(q, stories)
            if errs:
                failed += 1
                print(f"{f.name} {q.get('id')}: " + "; ".join(errs))
                continue
            s = stories[q["story_id"]]
            questions.append(
                q
                | {
                    "date": s["date"],
                    "issue_no": s["issue_no"],
                    "issue_title": s["issue_title"],
                    "story_title": s["title"],
                    "link": deep_link(s["url"], s, q["source"]),
                }
            )

    ids = Counter(q["id"] for q in questions)
    dupes = [i for i, n in ids.items() if n > 1]
    if dupes:
        sys.exit(f"Duplicate question ids: {dupes}")
    if failed:
        sys.exit(f"\n{failed} question(s) failed checks; nothing written.")

    questions.sort(key=lambda q: (q["date"], q["id"]))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(questions, ensure_ascii=False, indent=1))
    print(f"{len(questions)} questions OK -> {OUT.relative_to(ROOT)}")
    print("topics:", dict(Counter(q["topic"] for q in questions).most_common()))
    print("formats:", dict(Counter(q["format"] for q in questions)))
    print("answer positions (non-single):", dict(Counter(q["answer"] for q in questions if q["format"] != "single")))


if __name__ == "__main__":
    main()

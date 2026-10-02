#!/usr/bin/env python3
"""Split every daily issue in data/raw/ into individual stories.

Usage: python3 scripts/extract_stories.py

Writes data/stories.json: one record per lead story and per Also in the news
item, with the issue date, link, story text and Sound smarter (if any).
Weekly Digests are skipped because they recap stories already in the dailies.
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from htmltext import html_to_text  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "stories.json"

SECTION = re.compile(r"^## (?:(\d+) ?/ )?(.+)$", re.M)
ISSUE_META = re.compile(r"Issue #(\d+)\s+([A-Z][a-z]+ \d{1,2}, \d{4})")
SOUND_SMARTER = re.compile(r"\n?💡 ?Sound smarter\n", re.I)
FOOTER = re.compile(
    r"\n(?:#+ )?(Got questions, feedback|Say hello at hello@|Be back in your inbox|Was this email forwarded|Sign up now to get)"
)
# Unnumbered sections that are never stories in their own right.
NOT_STORIES = re.compile(r"^(today in india|chai break|thank you|we break down)", re.I)
AITN_ITEM = re.compile(r"^(?:- )?([^:\n]{4,140}):\s+(.+)$")


def first_words(text, n=8):
    words = re.sub(r"\s+", " ", text).strip().split(" ")
    return " ".join(words[:n])


def summary_titles(text):
    """Headlines of the Also in the news items, from the Today in India list."""
    m = re.search(r"^(?:- )?Also in the news: (.+)$", text, re.M)
    return [t.strip() for t in m.group(1).split(";")] if m else []


def split_aitn(body, titles):
    paras = [p.strip().removeprefix("- ") for p in re.split(r"\n+", body)]
    paras = [p for p in paras if len(p) > 40 or AITN_ITEM.match(p)]
    titled = [AITN_ITEM.match(p) for p in paras]
    # Two formats: "Headline: body" paragraphs, or untitled paragraphs whose
    # headlines only appear in the Today in India summary.
    if sum(bool(m) and ". " not in m.group(1) for m in titled) * 2 >= len(paras):
        items = []
        for p, m in zip(paras, titled):
            if m and ". " not in m.group(1):
                items.append({"title": m.group(1).strip(), "text": m.group(2).strip(), "anchor": m.group(1).strip()})
            elif items:
                items[-1]["text"] += " " + p
        return items
    use_titles = len(titles) == len(paras)
    return [
        {"title": titles[i] if use_titles else first_words(p), "text": p, "anchor": first_words(p)}
        for i, p in enumerate(paras)
    ]


def stories_for(issue):
    text = html_to_text(issue["html"])
    text = FOOTER.split(text)[0]
    meta = ISSUE_META.search(text)
    issue_no = int(meta.group(1)) if meta else None


    date = (
        datetime.strptime(meta.group(2), "%B %d, %Y").strftime("%Y-%m-%d")
        if meta
        else issue["date"]
    )
    base = {
        "issue_id": issue["id"],
        "issue_no": issue_no,
        "date": date,
        "issue_title": re.sub(r"^🛕\s*", "", issue["title"] or ""),
        "url": issue["web_url"],
    }

    # Headings before the issue number are the title and subtitle, not sections.
    heads = [h for h in SECTION.finditer(text) if not meta or h.start() > meta.start()]
    # Special issues (e.g. state-election explainers) have no numbered sections;
    # there every section except the boilerplate ones is a story.
    special = not any(h.group(1) for h in heads)
    out = []
    for i, h in enumerate(heads):
        num, title = h.group(1), h.group(2).strip()
        body = text[h.end() : heads[i + 1].start() if i + 1 < len(heads) else len(text)].strip()
        is_aitn = title.lower().startswith("also in the news")
        if special and not is_aitn and not NOT_STORIES.match(title) and body:
            num = str(i + 1)
        if not num and not is_aitn:
            continue  # Today in India, Editor's note, Chai break, etc.
        if is_aitn:
            for j, item in enumerate(split_aitn(body, summary_titles(text)), 1):
                out.append(
                    base
                    | {
                        "id": f"{date}-aitn{j}",
                        "kind": "aitn",
                        "title": item["title"],
                        "text": item["text"],
                        "sound_smarter": None,
                        "anchor": item["anchor"],
                    }
                )
        else:
            parts = SOUND_SMARTER.split(body, maxsplit=1)
            story_text = parts[0].strip()
            out.append(
                base
                | {
                    "id": f"{date}-{num}",
                    "kind": "lead",
                    "title": title,
                    "text": story_text,
                    "sound_smarter": parts[1].strip() if len(parts) > 1 else None,
                    "anchor": first_words(story_text),
                }
            )
    return out


def main():
    all_stories, skipped = [], []
    for f in sorted(RAW.glob("*.json")):
        issue = json.loads(f.read_text())
        if "weekly digest" in (issue["title"] or "").lower():
            continue
        s = stories_for(issue)
        if not s:
            skipped.append(issue["title"])
        all_stories.extend(s)

    # Ids must be unique; two posts on one date would collide.
    seen = {}
    for s in all_stories:
        n = seen.get(s["id"], 0)
        seen[s["id"]] = n + 1
        if n:
            s["id"] += f"-{n}"

    OUT.write_text(json.dumps(all_stories, ensure_ascii=False, indent=1))
    leads = sum(s["kind"] == "lead" for s in all_stories)
    print(f"{len(all_stories)} stories ({leads} leads, {len(all_stories) - leads} also-in-the-news items)")
    print(f"from {len({s['issue_id'] for s in all_stories})} issues")
    if skipped:
        print(f"No stories found in {len(skipped)} posts: {skipped}")


if __name__ == "__main__":
    main()

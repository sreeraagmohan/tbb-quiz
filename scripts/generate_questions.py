#!/usr/bin/env python3
"""Write UPSC-style questions for each story with Claude, then check them.

Usage (from the project folder, with the virtualenv):
  .venv/bin/python scripts/generate_questions.py write [--limit N] [--ids STORY_ID ...]
  .venv/bin/python scripts/generate_questions.py check
  .venv/bin/python scripts/generate_questions.py collect

write    asks Claude for 0-3 questions per story -> data/gen/write/<story>.json
check    a second pass solves each question blind from the story, and a third
         proofreads each explanation against the story -> data/gen/check/<story>.json
collect  keeps questions that pass both checks and the build checks
         -> data/questions/generated.json (dropped ones -> data/gen/dropped.json)
dedupe   finds questions across the whole bank that test the same fact and
         drops the generated repeats -> data/gen/dupes.json, then re-collects
rebalance rewrites a planned set of statements/pairs questions so correct answers
         spread evenly across (a)-(d); rewrites that pass the same checks replace
         the originals -> data/gen/rebalance/<question>.json, then re-collects

Every step skips work it has already done, so re-running is safe and cheap.
Stories that already have hand-written questions in data/questions/ are skipped.
"""
import argparse
import json
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).parent))
from build_questions import TOPICS, check as build_check  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GEN = ROOT / "data" / "gen"
WRITE_DIR, CHECK_DIR = GEN / "write", GEN / "check"
QDIR = ROOT / "data" / "questions"
OUT = QDIR / "generated.json"
DUPES = GEN / "dupes.json"
REBAL_DIR = GEN / "rebalance"
REBAL_PLAN = GEN / "rebalance_plan.json"
PROMPTS = Path(__file__).parent / "prompts"

MODEL = "claude-opus-5-5"
PRICE = {"input_tokens": 4.00, "output_tokens": 20.00, "cache_creation_input_tokens": 5.00, "cache_read_input_tokens": 0.20}
EXAMPLE_IDS = ["s03", "s09", "s11", "s19", "s35"]

TWO = ["1 only", "2 only", "Both 1 and 2", "Neither 1 nor 2"]
THREE = ["1 and 2 only", "2 and 3 only", "1 and 3 only", "1, 2 and 3"]
HOW_MANY = ["Only one", "Only two", "All three", "None"]

QUESTION = {
    "type": "object",
    "properties": {
        "topic": {"type": "string", "enum": TOPICS},
        "difficulty": {"type": "integer", "enum": [1, 2, 3]},
        "format": {"type": "string", "enum": ["single", "statements", "pairs"]},
        "prompt": {"type": "string"},
        "items": {"type": "array", "items": {"type": "string"}},
        "ask": {"type": "string"},
        "options": {"type": "array", "items": {"type": "string"}},
        "answer": {"type": "integer"},
        "explain": {"type": "string"},
        "source": {"type": "string"},
    },
    "required": ["topic", "difficulty", "format", "prompt", "items", "ask", "options", "answer", "explain", "source"],
    "additionalProperties": False,
}
WRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "upsc_relevance": {"type": "string", "enum": ["high", "medium", "low", "none"]},
        "note": {"type": "string"},
        "questions": {"type": "array", "items": QUESTION},
    },
    "required": ["upsc_relevance", "note", "questions"],
    "additionalProperties": False,
}
SOLVE_SCHEMA = {
    "type": "object",
    "properties": {"results": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "chosen": {"type": "integer"},
            "exactly_one_correct": {"type": "boolean"},
            "grounded_in_story": {"type": "boolean"},
            "problem": {"type": "string"},
            "verdict": {"type": "string", "enum": ["keep", "drop"]},
        },
        "required": ["chosen", "exactly_one_correct", "grounded_in_story", "problem", "verdict"],
        "additionalProperties": False,
    }}},
    "required": ["results"],
    "additionalProperties": False,
}
AUDIT_SCHEMA = {
    "type": "object",
    "properties": {"results": {"type": "array", "items": {
        "type": "object",
        "properties": {"accurate": {"type": "boolean"}, "problem": {"type": "string"}},
        "required": ["accurate", "problem"],
        "additionalProperties": False,
    }}},
    "required": ["results"],
    "additionalProperties": False,
}


DEDUPE_SCHEMA = {
    "type": "object",
    "properties": {"groups": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "fact": {"type": "string"},
            "ids": {"type": "array", "items": {"type": "string"}},
            "keep": {"type": "string"},
        },
        "required": ["fact", "ids", "keep"],
        "additionalProperties": False,
    }}},
    "required": ["groups"],
    "additionalProperties": False,
}


def load_env():
    # Locally keys live in .env; in GitHub Actions they arrive as environment secrets.
    env_file = ROOT / ".env"
    for line in (env_file.read_text().splitlines() if env_file.exists() else []):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if v.strip() and not os.environ.get(k.strip()):
                os.environ[k.strip()] = v.strip().strip("'\"")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Add ANTHROPIC_API_KEY to .env first.")


def read(path):
    return json.loads(path.read_text())


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1))


def writer_prompt():
    fields = list(QUESTION["properties"])
    examples = []
    for q in read(QDIR / "sample.json"):
        if q["id"] in EXAMPLE_IDS:
            q = {"items": [], "ask": ""} | q
            examples.append({k: q[k] for k in fields})
    return (PROMPTS / "writer.md").read_text().replace(
        "{EXAMPLES}", json.dumps(examples, ensure_ascii=False, indent=1)
    )


def story_block(s):
    d = datetime.strptime(s["date"], "%Y-%m-%d")
    lines = [
        f"Issue date: {d:%A} {d.day} {d:%B %Y}",
        f"Issue: {s['issue_title']}",
        f"Story type: {'Also in the news item' if s['kind'] == 'aitn' else 'lead story'}",
        f"Story title: {s['title']}",
        "",
        "Story text:",
        s["text"],
    ]
    if s["sound_smarter"]:
        lines += ["", "Sound smarter (TBB analysis):", s["sound_smarter"]]
    return "\n".join(lines)


def render(q, i, order, key=False):
    out = [f"Question {i + 1}", q["prompt"]]
    out += [f"{n}. {item}" for n, item in enumerate(q["items"], 1)]
    if q["ask"]:
        out.append(q["ask"])
    out += [f"({'abcd'[k]}) {q['options'][o]}" for k, o in enumerate(order)]
    if key:
        out.append(f"Correct answer: ({'abcd'[order.index(q['answer'])]}) {q['options'][q['answer']]}")
        out.append(f"Explanation: {q['explain']}")
    return "\n".join(out)


def call(client, system, user, schema, effort):
    """One structured-output request. Returns (parsed JSON or None, usage, error)."""
    resp = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
    )
    usage = {k: getattr(resp.usage, k, 0) or 0 for k in PRICE}
    if resp.stop_reason in ("refusal", "max_tokens"):
        return None, usage, resp.stop_reason
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text), usage, None


def cost(usage):
    return sum(usage.get(k, 0) * p for k, p in PRICE.items()) / 1e6


# ---------- steps ----------

def do_write(client, system, s):
    # The writer sees one story at a time, so left alone it piles answers onto the
    # same options. A random target per question keeps the bank balanced.
    targets = ", ".join(f"({random.choice('abcd')})" for _ in range(3))
    hint = (f"\n\nAnswer pattern: for your first, second and third statements or pairs questions, "
            f"make the correct option {targets} respectively, where the story allows it.")
    data, usage, err = call(client, system, story_block(s) + hint, WRITE_SCHEMA, "high")
    rec = {"story_id": s["id"], "error": err, "usage": usage, "result": data}
    write(WRITE_DIR / f"{s['id']}.json", rec)
    n = len((data or {}).get("questions", []))
    return f"{s['id']}: {err or f'{n} question(s)'} (${cost(usage):.3f})"


def do_check(client, prompts, s, written):
    qs = written["result"]["questions"]
    # Shuffle plain options so the solver can't lean on "correct answer first".
    perms = [random.sample(range(4), 4) if q["format"] == "single" else [0, 1, 2, 3] for q in qs]
    story = story_block(s)
    blind = "\n\n".join(render(q, i, perms[i]) for i, q in enumerate(qs))
    solved, u1, e1 = call(client, prompts["solver"], f"{story}\n\n---\n\n{blind}", SOLVE_SCHEMA, "medium")
    keyed = "\n\n".join(render(q, i, [0, 1, 2, 3], key=True) for i, q in enumerate(qs))
    audited, u2, e2 = call(client, prompts["auditor"], f"{story}\n\n---\n\n{keyed}", AUDIT_SCHEMA, "medium")
    usage = {k: u1[k] + u2[k] for k in PRICE}
    write(CHECK_DIR / f"{s['id']}.json",
          {"story_id": s["id"], "error": e1 or e2, "perms": perms, "solve": solved, "audit": audited, "usage": usage})
    return f"{s['id']}: checked {len(qs)} (${cost(usage):.3f})"


def run(jobs, fn, workers):
    """jobs: list of (story_id, args). Prints one line per finished story."""
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fn, *args): sid for sid, args in jobs}
        for f in as_completed(futures):
            done += 1
            try:
                print(f"[{done}/{len(jobs)}] {f.result()}", flush=True)
            except (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.BadRequestError) as e:
                # Billing, key or request problems won't fix themselves; stop instead of burning the queue.
                pool.shutdown(cancel_futures=True)
                sys.exit(f"Stopped: {getattr(e, 'message', e)}")
            except anthropic.APIError as e:
                # Nothing is saved for this story, so the next run retries it.
                print(f"[{done}/{len(jobs)}] {futures[f]}: API error, will retry next run ({e})", flush=True)


def format_problems(q):
    f, items, opts = q["format"], q["items"], q["options"]
    if f == "single":
        return [] if not items and not q["ask"] else ["single question has items"]
    if f == "statements":
        allowed = {2: [TWO], 3: [THREE, HOW_MANY]}.get(len(items))
        if not allowed:
            return ["statements need 2 or 3 items"]
        return [] if opts in allowed else ["non-standard statement options"]
    if len(items) != 3 or any(" — " not in i for i in items):
        return ["pairs need 3 'A — B' items"]
    return [] if opts == HOW_MANY else ["non-standard pairs options"]


def do_collect(stories):
    keep, dropped, unchecked = [], [], 0
    dupes = read(DUPES)["drop"] if DUPES.exists() else {}
    overrides = {}
    for f in REBAL_DIR.glob("*.json"):
        r = read(f)
        if r.get("passed"):
            overrides[r["id"]] = r["rewritten"]
    for wf in sorted(WRITE_DIR.glob("*.json")):
        w = read(wf)
        qs = (w.get("result") or {}).get("questions") or []
        if not qs:
            continue
        cf = CHECK_DIR / wf.name
        if not cf.exists():
            unchecked += len(qs)
            continue
        c = read(cf)
        solve = (c.get("solve") or {}).get("results", [])
        audit = (c.get("audit") or {}).get("results", [])
        for i, q in enumerate(qs):
            reasons = []
            r = solve[i] if i < len(solve) else None
            a = audit[i] if i < len(audit) else None
            if not r:
                reasons.append("not solved")
            else:
                chosen = c["perms"][i][r["chosen"]] if 0 <= r["chosen"] < 4 else -1
                if chosen != q["answer"]:
                    reasons.append("blind solver picked a different answer")
                if not r["exactly_one_correct"]:
                    reasons.append("not exactly one correct option")
                if not r["grounded_in_story"]:
                    reasons.append("needs facts outside the story")
                if r["verdict"] != "keep":
                    reasons.append(f"solver: {r['problem'] or 'drop'}")
            if not a:
                reasons.append("explanation not audited")
            elif not a["accurate"]:
                reasons.append(f"explanation: {a['problem']}")
            reasons += format_problems(q)
            out = {"id": f"g-{w['story_id']}-{i + 1}", "story_id": w["story_id"]} | q
            if q["format"] == "single":
                out.pop("items"), out.pop("ask")
            reasons += build_check(out, stories)
            if out["id"] in overrides and not reasons:
                # A rebalanced rewrite already passed the solver and auditor itself.
                out = {"id": out["id"], "story_id": out["story_id"]} | overrides[out["id"]]
                reasons = format_problems(out) + build_check(out, stories)
            if out["id"] in dupes:
                reasons.append(f"same fact as {dupes[out['id']]['kept']}")
            if reasons:
                dropped.append(out | {"reasons": reasons})
            else:
                keep.append(out)
    write(OUT, keep)
    write(GEN / "dropped.json", dropped)
    total = len(keep) + len(dropped)
    print(f"kept {len(keep)} of {total} checked questions -> {OUT.relative_to(ROOT)}")
    if dropped:
        print(f"dropped {len(dropped)} -> data/gen/dropped.json")
    if unchecked:
        print(f"{unchecked} questions written but not checked yet; run `check`.")


def do_dedupe(client, stories):
    hand = [q for f in sorted(QDIR.glob("*.json")) if f != OUT for q in read(f)]
    bank = hand + (read(OUT) if OUT.exists() else [])
    lines = []
    for q in sorted(bank, key=lambda q: (q["topic"], stories[q["story_id"]]["date"], q["id"])):
        stem = q["prompt"] + "".join(f" ({n}) {item}" for n, item in enumerate(q.get("items", []), 1))
        lines.append(f"{q['id']} | {stories[q['story_id']]['date']} | {q['topic']} | {stem} => {q['options'][q['answer']]}")
    print(f"Looking for repeated facts across {len(bank)} questions...")
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=64000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=(PROMPTS / "dedupe.md").read_text(),
        messages=[{"role": "user", "content": "id | issue date | topic | question => correct answer\n\n" + "\n".join(lines)}],
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": DEDUPE_SCHEMA}},
    ) as stream:
        resp = stream.get_final_message()
    usage = {k: getattr(resp.usage, k, 0) or 0 for k in PRICE}
    if resp.stop_reason in ("refusal", "max_tokens"):
        sys.exit(f"Dedupe stopped early ({resp.stop_reason}); nothing changed.")
    groups = json.loads(next(b.text for b in resp.content if b.type == "text"))["groups"]

    state = read(DUPES) if DUPES.exists() else {"drop": {}, "usage": {k: 0 for k in PRICE}}
    state["usage"] = {k: state["usage"].get(k, 0) + usage[k] for k in PRICE}
    known = {q["id"] for q in bank}
    for g in groups:
        ids = [i for i in g["ids"] if i in known]
        hand_ids = sorted(i for i in ids if not i.startswith("g-"))
        # Hand-written questions are never dropped; otherwise keep Claude's pick.
        keeps = hand_ids or ([g["keep"]] if g["keep"] in ids else ids[:1])
        for i in ids:
            if i.startswith("g-") and i not in keeps:
                state["drop"][i] = {"kept": keeps[0], "fact": g["fact"]}
    write(DUPES, state)
    print(f"{len(groups)} groups of repeats; {len(state['drop'])} generated questions marked as repeats (${cost(usage):.2f})")
    do_collect(stories)


def option_kind(q):
    if q["format"] == "pairs":
        return "pairs"
    return {tuple(TWO): "two", tuple(THREE): "three", tuple(HOW_MANY): "how-many"}.get(tuple(q["options"]))


# (kind, current answer, target answer, how many): aimed at the options that are
# rarely correct. About a quarter of the generated statements/pairs questions.
REBAL_MOVES = [
    ("three", 0, 3, 25), ("three", 2, 3, 25), ("three", 0, 1, 15), ("three", 2, 1, 15),
    ("how-many", 1, 3, 15), ("how-many", 1, 0, 10),
    ("pairs", 1, 3, 8), ("pairs", 1, 0, 4), ("pairs", 2, 0, 4),
    ("two", 0, 3, 10), ("two", 2, 3, 6), ("two", 0, 1, 6),
]


def make_plan():
    if REBAL_PLAN.exists():
        return read(REBAL_PLAN)
    rng = random.Random(42)
    pool = [q for q in read(OUT) if q["format"] != "single"]
    plan, used = [], set()
    for kind, cur, target, n in REBAL_MOVES:
        cands = [q for q in pool if option_kind(q) == kind and q["answer"] == cur and q["id"] not in used]
        for q in rng.sample(cands, min(n, len(cands))):
            used.add(q["id"])
            plan.append({"id": q["id"], "target": target})
    write(REBAL_PLAN, plan)
    return plan


def do_rebalance(client, prompts, s, q, target):
    fields = list(QUESTION["properties"])
    current = {k: q.get(k, [] if k == "items" else "") for k in fields}
    letter = "abcd"[target]
    user = (f"{story_block(s)}\n\n---\n\nCurrent question:\n{json.dumps(current, ensure_ascii=False, indent=1)}"
            f"\n\nTarget: make option ({letter}) \"{q['options'][target]}\" the correct answer.")
    new, u0, e0 = call(client, prompts["rebalance"], user, QUESTION, "high")
    usage, rec = dict(u0), {"id": q["id"], "story_id": q["story_id"], "target": target, "original": current}
    reasons = [e0] if e0 else []
    if new:
        rec["rewritten"] = new
        reasons += [] if new["answer"] == target else ["rewrite did not land on the target option"]
        reasons += format_problems(new) + build_check({"id": q["id"], "story_id": q["story_id"]} | new, {s["id"]: s})
        if not reasons:
            story = story_block(s)
            solved, u1, e1 = call(client, prompts["solver"], f"{story}\n\n---\n\n{render(new, 0, [0, 1, 2, 3])}", SOLVE_SCHEMA, "medium")
            audited, u2, e2 = call(client, prompts["auditor"], f"{story}\n\n---\n\n{render(new, 0, [0, 1, 2, 3], key=True)}", AUDIT_SCHEMA, "medium")
            usage = {k: usage[k] + u1[k] + u2[k] for k in PRICE}
            r = (solved or {}).get("results", [None])[0]
            a = (audited or {}).get("results", [None])[0]
            if e1 or e2 or not r or not a:
                reasons.append(e1 or e2 or "check returned nothing")
            else:
                if r["chosen"] != target:
                    reasons.append("blind solver picked a different answer")
                if not (r["exactly_one_correct"] and r["grounded_in_story"] and r["verdict"] == "keep"):
                    reasons.append(f"solver: {r['problem'] or 'drop'}")
                if not a["accurate"]:
                    reasons.append(f"explanation: {a['problem']}")
            rec |= {"solve": solved, "audit": audited}
    rec |= {"passed": not reasons, "reasons": reasons, "usage": usage}
    write(REBAL_DIR / f"{q['id']}.json", rec)
    return f"{q['id']} -> ({letter}): {'ok' if not reasons else '; '.join(reasons)[:90]} (${cost(usage):.3f})"


def spend():
    files = [f for d in (WRITE_DIR, CHECK_DIR, REBAL_DIR) for f in d.glob("*.json")] + ([DUPES] if DUPES.exists() else [])
    return sum(cost(read(f)["usage"]) for f in files)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["write", "check", "collect", "dedupe", "rebalance"])
    ap.add_argument("--limit", type=int, help="only this many stories, spread evenly across the archive")
    ap.add_argument("--ids", nargs="*", help="only these story ids")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    stories = {s["id"]: s for s in read(ROOT / "data" / "stories.json")}
    if args.step == "collect":
        do_collect(stories)
        print(f"API spend so far: ${spend():.2f}")
        return

    load_env()
    client = anthropic.Anthropic(max_retries=5)
    if args.step == "dedupe":
        do_dedupe(client, stories)
        print(f"API spend so far: ${spend():.2f}")
        return
    if args.step == "rebalance":
        current = {q["id"]: q for q in read(OUT)}
        prompts = {n: (PROMPTS / f"{n}.md").read_text() for n in ("rebalance", "solver", "auditor")}
        jobs = [(p["id"], (client, prompts, stories[current[p["id"]]["story_id"]], current[p["id"]], p["target"]))
                for p in make_plan() if p["id"] in current and not (REBAL_DIR / f"{p['id']}.json").exists()]
        print(f"Rebalancing {len(jobs)} questions...")
        run(jobs, do_rebalance, args.workers)
        do_collect(stories)
        print(f"API spend so far: ${spend():.2f}")
        return
    if args.step == "write":
        hand_written = {q["story_id"] for f in QDIR.glob("*.json") if f != OUT for q in read(f)}
        pending = [s for sid, s in sorted(stories.items(), key=lambda kv: (kv[1]["date"], kv[0]))
                   if sid not in hand_written and not (WRITE_DIR / f"{sid}.json").exists()]
        if args.ids:
            pending = [s for s in pending if s["id"] in args.ids]
        if args.limit and args.limit < len(pending):
            step = len(pending) / args.limit
            pending = [pending[int(i * step)] for i in range(args.limit)]
        system = writer_prompt()
        print(f"Writing questions for {len(pending)} stories...")
        run([(s["id"], (client, system, s)) for s in pending], do_write, args.workers)
    else:
        prompts = {"solver": (PROMPTS / "solver.md").read_text(), "auditor": (PROMPTS / "auditor.md").read_text()}
        jobs = []
        for wf in sorted(WRITE_DIR.glob("*.json")):
            w = read(wf)
            if (w.get("result") or {}).get("questions") and not (CHECK_DIR / wf.name).exists():
                jobs.append((w["story_id"], (client, prompts, stories[w["story_id"]], w)))
        print(f"Checking questions for {len(jobs)} stories...")
        run(jobs, do_check, args.workers)
    print(f"API spend so far: ${spend():.2f}")


if __name__ == "__main__":
    main()

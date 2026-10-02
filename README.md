# TBB Current Affairs Quiz

A public, gamified UPSC Prelims current-affairs quiz built from The Bharat Briefing archive. Every question links back to the TBB issue it came from. Doubles as a subscriber-growth channel (LinkedIn showcase).

## Decisions so far

- Source: all TBB issues, pulled via the beehiiv API (nothing is paywalled).
- Audience: public. Anyone can play without signing in; progress is kept in the browser.
- Sync: optional email sign-in (one-time code, no password) to sync progress across phone and laptop. Sign-in offers an explicit opt-in to subscribe to TBB, sent to beehiiv with a quiz-specific source tag.

## Layout

- `scripts/fetch_issues.py` pulls every issue into `data/raw/` (gitignored) and writes `data/issues.json`.
- `scripts/extract_stories.py` splits daily issues into stories (leads, Also in the news items, election specials) in `data/stories.json`. Weekly Digests are skipped because they repeat the dailies.
- `data/questions/*.json` holds the questions. Every question quotes a `source` sentence from its story.
- `scripts/build_questions.py` checks each question (four distinct options, a real story, the source quote found word for word) and writes `app/questions.json` with dates, titles and a deep link that highlights the quoted sentence in the issue.
- `app/index.html` is the quiz. It loads `questions.json` and keeps progress in the browser for now.
- `scripts/generate_questions.py` writes questions with Claude, checks them twice (blind solve, explanation audit), removes repeats and rebalances answer patterns. State lives in `data/gen/` so every step is incremental.
- `scripts/build_site.py` wraps the quiz into a full page in `docs/`, which GitHub Pages serves at https://sreeraagmohan.github.io/tbb-quiz/.
- `.github/workflows/daily.yml` runs every day at 08:00 IST: fetches new issues, writes and checks their questions, rebuilds `docs/` and pushes. On Sundays it also runs the repeat check. It needs two repository secrets, `BEEHIIV_API_KEY` and `ANTHROPIC_API_KEY`.
- `.env` holds the beehiiv and Anthropic API keys for local runs (gitignored, never commit it).

## Rebuild

```
python3 scripts/fetch_issues.py
python3 scripts/extract_stories.py
python3 scripts/build_questions.py
```

## Steps

1. Fetch the archive. Done: 201 posts, 180 daily issues, 669 stories (15 Dec 2025 to 1 Oct 2026).
2. Sample questions from 10 issues for review. Done: 44 questions.
3. Generate and verify questions for the full archive. Done: September 2026 by hand (`data/questions/2026-09.json`), the rest with `scripts/generate_questions.py` (`data/questions/generated.json`).
4. Deploy the quiz. Done: GitHub Pages at https://sreeraagmohan.github.io/tbb-quiz/, updated daily by GitHub Actions.
5. Add email sign-in, cross-device sync and the subscribe opt-in.
6. Daily job to add questions from each new issue. Done: `.github/workflows/daily.yml`.

## Where we left off (2 Oct 2026)

- Full archive generated: 958 questions (44 sample + 49 September by hand + 865 generated), live at https://claude.ai/artifact/4t6yT1uS38zNyC8QzE6nJR (shared with anyone who has the link).
- API spend so far: $24.79 of the $100 credit (writing, two checks per question, and one dedupe pass).
- Known issue: in statements and pairs questions the last option ("1, 2 and 3", "All three", "Both", "Neither", "None") is correct in only about 4% of questions, so an aspirant could learn to rule it out. Fix proposed: rewrite a share of them so all statements are true, then re-check.
- To regenerate after prompt changes, delete the relevant files in `data/gen/write/` and `data/gen/check/`, then:

```
.venv/bin/python scripts/generate_questions.py write
.venv/bin/python scripts/generate_questions.py check
.venv/bin/python scripts/generate_questions.py collect
.venv/bin/python scripts/generate_questions.py dedupe
python3 scripts/build_questions.py
```

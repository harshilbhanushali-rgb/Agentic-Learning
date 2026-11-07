# Naren's first real test: specific questions work, generic ones don't

**Source:** Naren's recorded test session, 2026-11-04, prod (old router). Full cases, his
verdicts and how to replay: `../../golden/README.md` and `../../golden/naren-2026-11-04.json`.

## What he found

11 questions answered + 1 timeout: 4 right, 3 right with gaps, 1 partly right, 2 wrong,
1 wrongly declined.

- **Specific questions get good answers** (ATS integration, Craigslist, organic traffic).
- **Generic, sales-style questions get answered too narrowly.** "How does tracking work",
  "how do I get started", "what do I need for tracking setup" each got one narrow call's
  answer (down-funnel IDs; job-feed setup; campaign segmentation). He wants a
  same-breadth overview, or a clarifying question first.
- **The why** is what he values most in campaign-management answers.
- **Certified sources:** he wants Cortex/product documentation behind the answers, not only
  his calls.

## Why this matters for scoping

This is a different failure from `answer-failure-modes.md`. There, a specific question
retrieves the right topic and answers a different question. Here, a *broad* question
retrieves one narrow exchange, because any single exchange in a call is narrower than
the question. Picking a better single exchange can't fix it. The answer needs several
exchanges or a non-call source, which is what COMPOSE's gather step and a documentation
source are for. Check this before scoping either.

Also seen: one answer repeated an out-of-date pricing fact from Naren's own 2024 call. The
grounding check can't catch stale facts, because the quote is real.

## What happened next (2026-11-07)

Measured in `ask-naren/golden/README.md`. The new engine with the 2026-11-07 fixes answers the broad
questions (01, 07, 12) and the wrongly declined one (06) in every run, and scored 16-19 of 22 against
prod's 10. Two things this finding raised are **not** fixed:

- **The why for campaign results (03).** Naren's reasoning ("track down the funnel, then optimize
  towards interviews and shortlists") is in his calls and reached the writer in every run, inside a
  playbook about a different situation. A writer principle to use reasons from anywhere in the
  material did not get it into the answer. One case is thin evidence; more campaign-management
  questions from Naren, or a documentation source, are the better next input.
- **The stale pricing fact (05)** still appears in some runs. The grounding check cannot catch it
  and no prompt rule can know a fact is out of date; it needs the fact marked stale or a
  documentation source.

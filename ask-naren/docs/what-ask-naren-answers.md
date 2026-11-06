# What Ask Naren answers

A guide for the CS team. Nineteen kinds of question, with a real example of each.

---

## What it is

Ask Naren is an internal tool. You describe a client situation in your own words, and it
finds the closest comparable moment in **Naren's real recorded calls** and answers from
that.

It is not a chatbot with opinions about recruitment marketing. It is a way of asking "has
Naren been here before, and what did he actually do?" — and getting back his real words,
with the call they came from.

## How it works, in three steps

1. **It reads your message** to work out what you are asking — a reply to a client, the
   general play for a situation, a real example, or something about the corpus itself.
2. **It searches Naren's calls** for the closest moment. What it searches on is the
   *client's* side of the situation, which is why giving the client's actual words helps
   more than summarising them.
3. **It answers from what it found**, and shows you the verbatim line of Naren's that the
   answer rests on plus the call it came from.

## The one rule everything else follows from

**It only answers from what Naren actually said.**

Before any generated answer reaches you, the tool checks that the quote it is showing you
appears **word for word** in the real transcript. If that check fails, you do not get a
softened answer — you get told there is no grounded answer.

That is also where its limits come from. If nothing close enough exists in Naren's calls,
it declines instead of improvising something plausible. A decline is the tool working, not
failing.

## About the examples below

**The questions are made up for this guide.** None of them is taken from a transcript, a
real client email, or anyone's actual message to the tool. They are written the way a CSM
actually types, about the kind of thing that actually comes up.

**The answers are real.** Each one is exactly what the running service returned when asked
that question, including the quotes, the client names and the call dates. Nothing is
polished. Long answers are trimmed and the trim is marked `[…]` — nothing else is changed.

Client names and call dates appear because the tool deliberately shows them: a quote you
cannot trace is a claim you cannot check.

---

# The nineteen

## A. Answering a live client message

### 1. Reply to a client — `reply_to_client`

The core one. A client has said something and you need to respond.

> **You ask:** the client just emailed saying their cost per application doubled month over
> month and they want to know what we're doing about it

**Answer**
> Reassure the client that our campaign strategy and budget allocations are not set in
> stone. Emphasize that we do not take a 'set it and forget it' approach; instead, we are
> actively hands-on, consistently evaluating metrics, and continuously optimizing the setup.
> Remind them that there is an initial learning period where the system adapts and learns
> what drives real candidate conversions and qualified applicants for their specific needs.

**What Naren actually said**
> "this is not set in stone by any means as well. Right? Like, we're consistently gonna be
> evaluating this. We're consistently gonna be making sure that we're adapting, to to some
> of these metrics as well."

**Situation** Application volume and prioritization · **Source** Joveo Demo Rescheduled ·
3 January 2025

---

### 2. Compare your own reply — `contrast_my_reply`

You have already drafted or sent something. This sets it against Naren's closest real reply
to the same client turn.

> **You ask:** the client asked whether we can write candidate data back into their ats or
> if it has to be a manual export. i told them i thought we could push it but that i would
> confirm with the integration team. how does that compare to how naren handles it

**Answer**
> Naren addresses the capability directly by explaining Joveo's ATS-agnostic approach and
> specifically mentioning the requirement of an API for 'bidirectional integration', along
> with examples of past integrations. Unlike the CSM, Naren does not express uncertainty or
> defer the question to confirm with an integration team.

**What Naren actually said**
> "As long as they have the ability to to provide us the API and set up, a bidirectional
> integration, we can do that as well."

**Situation** ATS integration and API mapping · **Source** Joveo CRM Demo For Cielo
Employer Brandi · 10 October 2024

**It will not tell you that you were wrong.** That is a judgement it has no instrument for.
It shows you one real moment where Naren faced the same thing, and leaves the comparison to
you.

---

### 3. Follow up in the same conversation — `follow_up`

A short question that only means something as a continuation. It is answered from the call
the last answer came from, with **no new search** — so it stays on the same source.

> **You ask** (straight after example 2): and if they push back on that

**Answer**
> If the client pushes back, you can reassure them that we haven't come across an ATS where
> this hasn't worked. You can also share specific examples of platforms we've integrated
> with in the past, such as Salesforce or iCIMS, to demonstrate that we are truly ATS
> agnostic as long as they can provide API access or authentication.

**What Naren actually said**
> "We've done this in the past for Salesforce."

**Source** Joveo CRM Demo For Cielo Employer Brandi · 10 October 2024 — the same call as
example 2

**If the follow-up goes beyond that call, it says so** rather than searching for a new
source and quietly changing the subject. When that happens, ask it as a fresh question
instead.

---

## B. The play for a kind of situation

These answer "how is this handled in general", not "what do I say to this client right
now". Most are assembled from what is on file rather than written fresh.

### 4. The general play — `procedure`

> **You ask:** whats the general play when a client asks how long the ats integration is
> actually going to take on their side

**Answer**
> When dealing with ATS integration and API mapping discussions, Naren runs the play in the
> following order:
>
> 1. **Specify custom ATS field requirements and configuration rules for candidate data
>    writeback** — identify necessary custom fields or endpoints in the target ATS for
>    screening questions and define workflow configuration rules.
> 2. **Offer alternative tracking and reconciliation mechanisms when native ATS integration
>    is unviable** — passing pre-existing source IDs as parameters, capturing leads via the
>    apply flow, or running scheduled reconciliation hits against endpoints.
> 3. **Enforce job feed data integrity and highlight API submission failure risks** —
>    clarify that job feed data is ingested as sacrosanct, and warn that reposting jobs
>    under outdated templates risks API application submission failures.
> 4. **Delineate system responsibility boundaries and automated data delivery mechanisms** —
>    distinguish what the ATS controls from what external partners control.

**What Naren actually said**
> "We can push the information so you don't have to extract it. Agree. Like, just agree can
> push."

**Source** External Deloitte Gedu · Discussion · 10 April 2025

**Read the quote carefully on a "play" answer.** It covers **one** of those four moves, not
all four. The others were checked against transcripts when the play was built, not when you
asked. That is a real difference from example 1, where the quote covers essentially the
whole answer.

---

### 5. What order to do things in — `sequence`

> **You ask:** what order should i do things in when a client says their spend is pacing too
> fast

**Answer** — Budget allocation and testing
> 1. Structure initial budget testing across channels with pre-configured campaign rules
> 2. Implement macro pacing, cap rules, and run-rate thresholds to control budget spend
> 3. Align spend reallocation with volume trade-offs and publisher pricing mechanics

No quote here, and that is deliberate: nothing was written for you, so there is nothing to
verify. These are the recorded steps, reproduced.

---

### 6. How Naren phrases it — `phrasing`

> **You ask:** how does naren phrase it when a client asks whether we are tied to particular
> job boards

**Answer** — Job board budget and direct agreements

| The phrase | What he actually said | Call |
| --- | --- | --- |
| agnostic in terms of publishers | "So we're we're agnostic in in just in terms of publishers as well." | Ashley S Joveo · 11 April 2024 |
| dedicated budgets for those dedicated roles | "We could always have, like, dedicated budgets for those dedicated roles that start boosting these jobs with, like, higher CPCs." | Joveo Zapid Hire Implementation Start Co · 19 October 2023 |
| they will still charge you for the click | "Yeah. No. They they they will still charge you for the click, Grace." | *(call recorded only by ID)* |

`[…2 more phrases]`

**Know what this gives you.** These are the **situation's** characteristic phrases, not
phrases picked to answer your exact wording. The first one answers the question directly;
the others are other things Naren says in that same territory. Useful for tone, not a
script.

---

### 7. What usually goes wrong — `pitfalls`

> **You ask:** what usually goes wrong when we are agreeing a go live date with a client

**Answer** — Testing and implementation timeline

**1. Accepting proposed target go-live dates without verifying that key outstanding
dependencies and stakeholder approvals have been resolved.**
> "They haven't proposed it yet, but they, like, did a sheet of all the outstanding actions,
> and at the top, it says propose go live date September 19th, and the second I saw that I
> said, there's no way."
> — Uber Corporate · Connect · 12 September 2023

**2. Failing to anticipate client user hesitation or friction during tool adoption and
timeline transitions.**
> "So don't be shocked if half my team goes deer in the headlights. […] Some of my
> recruiters been with me for 3 years, so this will be different for them."
> — Joveo Indeed Continued Conversation Plac · 15 May 2024

---

### 8. When does this play apply — `scenario_check`

> **You ask:** when does the play for handling large volumes of incoming applications apply

**Answer** — Application volume and prioritization
> An account manager recognizes this scenario when clients raise challenges regarding
> filtering, prioritizing, and managing high volumes of incoming job applications within
> their recruitment workflow. Clients often discuss ATS integration mechanics, easy-apply
> flows from platforms like Indeed or ZipRecruiter, and auto-parsing rules or screening
> parameters such as commute distance. They may also express concerns about missing
> candidate data, inaccurate source attribution, or recruiter fatigue from manually
> reviewing dozens of applications.

Deliberately **not** a yes/no. Whether it fits your client is a judgement it only has your
one sentence for.

---

### 9. How solid is this play — `play_confidence`

> **You ask:** how solid is the play for a client threatening to churn, how much is it based
> on

**Answer** — Vendor transition and partnership evaluation

| | |
| --- | --- |
| Moves in the play | **5** |
| Verbatim quotes behind them | **16** |
| Moments considered when it was built | 50 *(at the builder's cap)* |

> The moves and quotes are what this play actually rests on today. The evidence count is how
> many moments were considered when it was built, before the verbatim check dropped any — so
> it says how much was looked at, not whether the play is right for your client.

The tool writes that caveat itself. Lead with the first two numbers; the third is capped and
can be misleading read alone.

---

### 10. How do I get better at this — `improve_at_move`

> **You ask:** how do i get better at defining the testing scope and integration timeline
> with a client

**Answer** — Testing and implementation timeline

**Move: Define testing scope, integration timelines, and milestone feasibility**

*What doing it well looks like:* the account manager explicitly details SIT/UAT testing
procedures, integration duration expectations, and validates timeline projections based on
preliminary test results.

*Naren doing it:*
> "So just, again, to recap what the SIT scope would be. Right? Like, the job that we
> receive. Right? We're going to do a test publishing so that Jenny and team can verify that
> on the job board itself."
> — External Deloitte Gedu · Job Aggrega · 30 May 2025

> "We still have, like, for us, the integration process takes about a week or two weeks.
> Right? Two weeks. So yeah. I I would actually factor in two weeks for us to test and and
> have everything done."
> — *(call recorded only by ID)*

`[…1 more quote, plus the pitfalls around this move]`

**Watch for one thing.** This answer said it had matched your words to **one specific move**.
If it cannot, it gives you the whole play instead and says so — so check which you are
looking at before assuming it understood the specific thing you asked.

---

## C. Show me the evidence

### 11. Show me a real example — `show_exchange`

No summary, no paraphrase — the stored exchange, verbatim.

> **You ask:** show me a real example of a client pushing back on applicant quality

**The client said**
> "I just wanted to — that's where we track these KPIs, see if they catch these things. […]
> I'd love to go a little bit deeper on the quality problem because the data is telling me
> one thing. On the ground, people tell me another thing, and ultimately, applicant quality,
> the data shows up 4 weeks later when they get become a hire. Right? So I'm just wondering
> if you have any actual numerical numbers to go around that."

**Naren replied**
> "Yeah. So two parts to it, Chris. Right. So one is just the KPI that you exactly brought
> up. Right? Because that's also what we're tracking of the lagging indicators. Like, the
> cost per interview, right, which is slightly earlier than the cost per hire. […] we're not
> seeing any significant spikes in the cost per interview standpoint. Right? It's more of the
> feedback from recruiters. […] I think it's also driven by the applicant volume."

---

### 12. What happened next — `what_happened_next`

The exchange, and then the turns that followed it in the same call.

> **You ask:** what happened after a client asked why we need to know their budget up front

**The client said**
> "Can I just clarify? So what does knowing the budgets allow you to do in your end?"

**Naren replied**
> "So from the standpoint of certain publishers that we'll actually be setting up on our
> end […] getting a sense of the budget gives us also the visibility into, okay, do we need
> 6 publishers as opposed to 8 or 9 or so on. […] Our campaign planning is a lot more
> accurate when we get some foresight with the budgets."

**Then, next in the call — the client said**
> "So would we not be choosing the campaign parameters and the publishers ourselves? […]
> would the self service not allow us to do that?"

**And Naren replied**
> "So you could definitely have a say in the volume of publishers or what are the publishers
> as well, Steph. But since those will be managed by Joveo […] we wanna make sure that we're
> not essentially turning on 10 publishers or 15 publishers for a 3,000 or 4,000 campaign."

If nothing followed it, it tells you that outright rather than handing you an empty list.

---

### 13. Do you have anything on this — `coverage_check`

Ask before you rely on it.

> **You ask:** do you have anything on clients asking us to sponsor hard to fill nursing
> roles

**Answer**
> **Nearest situation:** Niche talent scarcity and budget reallocation — managing campaign
> spend allocation to prioritize hard-to-fill niche roles over easier-to-source positions.
>
> **Drawn from 26 calls** · evidence: **solid**
>
> Closest moment: Touchmark · Weekly Connect · 10 June 2025

Note what it did *not* do: it has nothing specifically about nursing, so it named the
situation it does cover and let you judge the fit. The count is the useful part — "solid" is
a reading aid, not a guarantee.

---

### 14. Which clients has this come up with — `where_else_seen`

> **You ask:** which accounts have raised issues about our reporting not matching their ats

**Answer** — Dashboard access and reporting

| Account | Exchanges | Calls |
| --- | --- | --- |
| Uber | 7 | 6 |
| Cielotalent | 2 | 2 |
| Springhealth | 2 | 1 |
| Allegisgroup, Buyerads, Hirevalueinc, Hopeleighmarketing, Jacksonnursing, Justeattakeaway, Nasrecruitment, Thecontractorconsultants, Ups, Zapidhire | 1 each | 1 each |

Plus several calls whose client the recorded data does not state — listed by filename rather
than guessed at.

**Read the small print on this one.** Of the neighbouring exchanges it scanned, **only one
actually shared this situation.** So that account list is wider than the evidence for it.
The tool reports that number precisely so you can tell a genuine book-wide pattern from a
loose neighbourhood — and this example is the loose kind.

It also gives the client count as a **range**, never a single number, because a call whose
client cannot be identified might be a new client or one already on the list.

---

## D. Preparing for a call

### 15. What should I expect — `call_prep`

> **You ask:** i have a quarterly review tomorrow with a client whose applications are down
> and whose spend is over, what should i expect to come up

**Answer** — from the 25 nearest exchanges, 11 situations appeared. The three most
represented:

**1. Downstream activation and cost metrics** — 5 exchanges, play on file (4 steps)
- First step: define and validate downstream conversion stage requirements and calculation
  rules
- A real moment: *"This is just paid clicks. Right? It wouldn't include any organic traffic
  that's coming in…"* — Uber Corporate · Connect NA Latam · 31 October 2023

**2. Campaign-level performance tracking** — 4 exchanges, play on file (3 steps)
- First step: implement standardized campaign parameter structures and tracking solutions to
  eliminate attribution gaps
- A real moment: *"How are we tracking against the CPA target that we set at the start."* —
  Zapid Hire · Weekly Sync · 29 January 2024

**3. Reliance on major social and professional networks** — 3 exchanges, play on file
- First step: optimize existing major platform slot inventory through targeted filtering and
  performance-based allocation
- A real moment: *"So the whole deck was just pretty much like, here's the value that
  LinkedIn brought…"* — Uber Corp Global · Connect · 12 August 2024

> The situations that come up most in the exchanges nearest to what you described, each with
> its recorded play and one real moment to read. Nothing here is written for you — it is what
> is on file, so the judgement about your client stays yours.

It says "11 situations found" and shows three, so you know the list was trimmed rather than
exhaustive. Where a situation has **no** recorded play, it says that too — which is different
from the play being empty.

---

## E. What is in here at all

### 16. What can you help with — `discovery`

> **You ask:** what kinds of situations can you actually help me with

**Answer** — all **34** situations it covers, with a one-line description each. A sample:

- **ATS integration and API mapping** — navigating technical requirements for ATS
  integration, including custom fields and requisition status
- **Contract and legal review** — navigating corporate legal and procurement processes for
  contract, MSA and SOW execution
- **XML feed setup and ingestion** — client requirements, file formatting and technical
  ingestion for XML job feeds
- **Niche talent scarcity and budget reallocation** — prioritising hard-to-fill niche roles
  over easier-to-source positions
- **Attribution and funnel tracking** — multi-touch attribution and funnel complexities
- **Pricing and fee structures** — commission percentages, media spend markup, management
  models

`[…28 more]`

It cannot invent a 35th. This list is read from stored rows, so what you see is exactly
what exists.

### 17. What comes up most — `frequency`

> **You ask:** what comes up most often on calls

**Answer**

| # | Situation | Calls it was drawn from |
| --- | --- | --- |
| 1 | Contract and legal review | 102 |
| 2 | Budget allocation and testing | 101 |
| 3 | XML feed setup and ingestion | 90 |
| 4 | ATS integration and API mapping | 88 |
| 5 | Landing page and conversion setup | 87 |

`[…7 more shown — it lists the top 12 of the 34 situations, not all of them]`

> Ranked by how many of Naren's recorded calls each situation was drawn from. That is a fact
> about this corpus, not about how often clients raise it.

**That qualifier matters.** It reflects which calls were recorded and mined, not what your
book of business is actually dealing with.

---

## F. When it asks you something back, or will not answer

### 18. It asks you for more — `clarify`

If your message names a topic but not what the client actually said, it asks — because a
search on a bare summary reaches a different part of the corpus than a search on real words.

> **You ask:** client is annoyed about reporting

**It replies**
> Could you share the client's actual words or specific complaint about reporting?

Not a failure. It is the difference between searching for "reporting" and searching for what
your client is actually unhappy about.

### 19. It declines, and rewording will not help — `out_of_scope`

> **You ask:** what is our standard contract notice period and can a client exit mid-term

**It replies**
> Ask Naren answers from what Naren said on real client calls, so it cannot answer questions
> about Joveo's product, pricing or contract terms. Rewording this will not help — the answer
> is not in his calls to find.

Facts about Joveo — contract terms, current pricing, what the product does today — are not
what this tool holds. Ask a product owner or check the docs.

---

# The three ways it says no

They look similar and mean completely different things.

| What you see | What it means | What to do |
| --- | --- | --- |
| **No grounded answer** | Nothing in Naren's calls is close enough | Reword using the client's own words — or accept there is no answer here |
| **Ask Naren is busy** | Too many people asking at once | Ask the same thing again in a moment. Nothing is wrong |
| **Ask Naren is unavailable** | Something broke on our side | Tell someone. Rewording will not help |

A real "no grounded answer", from an earlier run of this same guide:

> **Asked:** whats the general play when a client wants to pause spend halfway through a
> quarter
>
> **Reply:** No close match in Naren's calls. Nothing in his history is near enough to this
> situation to answer from, so Ask Naren is declining rather than guessing.

**Busy is rare.** The tool answers about six people at once and queues the rest; at this
team's size the queue is normally empty. If you do see it, it tells you roughly how long.

---

# How to ask well

**Give the client's actual words where you have them.** That is what gets searched. "The
client said our reporting doesn't match what they see in their ATS" finds more than "client
unhappy with reporting".

**Say what kind of answer you want.** "What do I reply" and "what's the general play" and
"show me a real example" go down three different paths.

**A follow-up can be short.** Once it has answered, "and if they push back on that" works —
it stays on the same call. But a genuinely new situation needs to be asked as a new
question, even in the same conversation.

**Check the source line.** It names a real client and a real date. If that call looks
nothing like your situation, the answer probably is not about your situation either.

---

# Honest limits

**It is right most of the time, not all of the time.** On a measured sample of 36 invented
situations, it gave an answer to 24 and declined the other 12; of the 24 answers, a blind
reader judged 19 right. Treat that as the shape of the thing, not a percentage to quote —
the measurement is sample-specific by design.

**The one way it goes wrong is worth knowing.** Every wrong answer in that measurement had
the *same shape*: the exchange it found was on the right general topic and answered a
different question. It does not usually produce nonsense; it produces a confident, well-
sourced answer to a question next to yours.

This happened while writing this guide. Three real examples:

| Asked | What came back |
| --- | --- |
| how does Naren phrase telling a client their cost-per-hire target is unrealistic | phrases about publisher agnosticism, dedicated budgets and duplicate job postings |
| what goes wrong when a client asks for a discount after a bad month | pitfalls about go-live dates and recruiter tool adoption |
| when does the play for **low** applicant volume apply | the play for **high** applicant volume |

Each is confidently worded and correctly sourced. **The defence is the quote and the source
line** — read them and ask whether that moment is really your situation. If it is not, the
answer is not either.

**The corpus is mostly implementation and onboarding.** ATS integrations, XML feeds, pixels,
landing pages, contracts, publisher lists, go-live timelines. Questions about that ground
land well. Questions about mid-flight performance escalations — spend pacing, quality
complaints, discount requests — are thinner and decline more often. `coverage_check` is the
cheap way to find out before you rely on it.

This is measured, not an impression: exactly one of the twelve most-supported situations is
about a running campaign's performance, and the other eleven are about getting a client
contracted, integrated, configured and live. The reason is that recorded calls skew toward
scheduled, multi-party meetings — kickoffs, integration syncs, MSA reviews, go-live planning
— while a campaign going wrong in week six gets handled in a Slack thread nobody recorded.
Written up in `findings/corpus-is-onboarding-not-escalation.md`.

**On a "play" answer, one quote covers one step.** The others were verified when the play
was built rather than when you asked. "This rests on something Naren really said" is true on
both paths; "every line here was checked against a transcript just now" is only true of the
direct-reply answers.

**It does not know your account.** No dashboard, no spend, no open roles. It knows Naren's
calls. It is a source of precedent, not a source of client data.

**It will not tell you whether you were right.** Even when comparing your reply, it shows
you one real moment rather than a verdict.

**It takes a few seconds to well over a minute**, depending on the question type and how
loaded the model gateway is. Answers assembled from stored rows come back fastest; anything
written fresh takes longest. Past about half a minute it gives up and says so rather than
leaving you on a spinner.

---

*Questions in this guide are invented. Answers are verbatim from the running service,
trimmed only where marked. Generated against the live corpus of Naren's recorded calls.*

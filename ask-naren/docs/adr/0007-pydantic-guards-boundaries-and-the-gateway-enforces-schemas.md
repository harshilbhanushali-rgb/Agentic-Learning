# Pydantic guards boundaries, and the gateway's schema enforcement is real

Ask Naren is growing new inputs that are not the single validated string it has today: an
**intake** call whose output is model-authored (#14), and a **thread** supplied by the caller
(#15). Both are untrusted in a way nothing in the current request path is. Pydantic v2 is
already a dependency of `Brain` and was unused. Two questions had to be settled together:
where pydantic applies, and whether the gateway can constrain a model's output shape at all.

We decided: **pydantic validates data crossing a trust boundary; plain dataclasses hold
internal shapes; and intake asks the gateway for a schema-constrained response** because that
enforcement was measured to be real.

## The boundary rule

| what | guarded by | why |
| --- | --- | --- |
| Intake's model output (#14) | pydantic | Model-authored, and no grounding gate sits behind it to catch a bad shape |
| The thread in a request (#15) | pydantic | Nested caller-supplied data |
| The response body | pydantic -- **decided, not yet done** | Makes "a clarify has no `answer` field" structurally impossible rather than test-enforced |
| `retrieval.Match`, `grounding.GateResult` | **stay frozen dataclasses** | Built by our own code from data we already hold. Nothing untrusted crosses here |
| Brain's Layer A-D dicts | **untouched** | Thousands of call sites, `storage.py` returns dicts throughout. No bug, no ticket, enormous blast radius |

**`Match` is the case that will tempt someone to "finish the migration". Do not.** Its `pair`
field is a raw `kb_pairs` row, so a pydantic `Match` would validate the wrapper while its
contents stayed unchecked -- something that reads as validated and is not, which is worse than
an honest dataclass. Making it real means modelling Brain's row schema, which drags
`storage.py` into Ask Naren's types. It is also built once per candidate inside `topk`; that
is one object today at `DEFAULT_K = 1`, and fifty per query if the wide-window work in issue #9
ever ships.

**The response body row is owed, not optional.** #14 shipped `IntakeDecision` and left every
response builder returning a plain dict, so "a clarify carries no `answer` field" is still
enforced by a test rather than by a type. That is the weaker of the two and the row exists to
say so. It was deferred because converting the builders touches every response the service can
emit, which is a poor thing to bundle into the ticket that introduced intake -- not because the
decision softened. It needs its own ticket.

**What would change this:** `Match` or `GateResult` being reconstructed from outside our own
code -- deserialised from a cache, sent between processes, or read back from an artifact. Then
it is crossing a boundary and pydantic is correct. Nothing does that today.

## THE ANSWERING PATH IS EXEMPT, AND THIS IS NOT NEGOTIABLE

`build_prompt`, `build_candidates_prompt` and `build_playbook_prompt` keep asking for JSON in
prose, and their calls keep sending `response_format: {"type": "json_object"}` exactly as they
do now. **Do not attach a schema to them.** A schema changes the request body, a changed
request can change what the model returns, and the ~80% accuracy figure was measured on the
current body. The gain would be validating a shape the grounding gate already checks the
substance of; the cost is a re-measurement that costs real generation spend. Schemas apply to
NEW calls only.

## The gateway measurement (2026-09-08, `gemini-3.6-flash`, VPN up)

`chat_json` sends `response_format: {"type": "json_object"}`, which forces *valid JSON* and
constrains nothing else. The open question was whether this LiteLLM deployment also honours
`{"type": "json_schema", ...}`, or merely accepts the flag and ignores it -- the worst outcome,
because it would look like it works.

Two runs of each arm, `temperature=0.0`, `no-cache`, with a **negative control**:

| arm | prompt | result (x2) |
| --- | --- | --- |
| schema, `additionalProperties: false`, one property | demanded FOUR mandatory keys | `['intent']` |
| **control**: no schema, `json_object` | the same four-key demand | `['category','confidence','intent','notes']` |
| schema with `enum: [reply_to_client, clarify]` | demanded the value `BANANA` | `reply_to_client` |

**Keys and enum values are both enforced.** The control is what makes that readable: the bait
does produce extra keys when no schema is attached, so their absence under one is enforcement
rather than an agreeable model. The control also returned `intent: "complaint"` -- an invented
value the enum makes impossible.

Consequence for #14: intake can trust the SHAPE of what comes back and spend its one retry on
content rather than on parsing. It still validates in Python, because enforcement is a property
of a gateway deployment that can change under us and a silent regression there would otherwise
surface as a wrong intent rather than an error.

## What this measurement does NOT establish

**That the intent is CORRECT.** A schema constrains the shape and the permitted values; it says
nothing about whether `reply_to_client` was the right label for that message. That is what
intake's labelled-accuracy measurement is for, and no amount of schema enforcement substitutes
for it.

A first run against an unstable VPN produced a single non-JSON response under `json_schema` and
briefly looked like evidence against it. It was a flaky socket. Numbers here come only from the
clean run, and the arms were repeated twice each for that reason.

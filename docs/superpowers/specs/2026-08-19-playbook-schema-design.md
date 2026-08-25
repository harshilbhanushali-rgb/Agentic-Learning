# Playbook schema + storage + loader — design and FROZEN GATES (2026-08-19)

Handoff: `Brain/HANDOFF_SHIP_LAYER_AB_2026-08-19.md` §2.2 ("the highest-value remaining item").
Predecessors: `2026-08-18-scenario-playbook-trial-design.md` (the canonical playbook JSON
schema, §5), `2026-08-19-routing-playbook-ab-design.md` (the 22 trial documents).

**Gates below are pre-registered BEFORE any code was written.** Nothing here is negotiable
after the fact; at any gate failure the run stops and the operator gets fallback options.

## 1. The problem

Layer C is *validated* but not *shippable*. `db/schema.sql` has no playbook table, so
`pbv_playbooks_snapped.json` (10 documents: 5 validated + 5 placebo twins) and the 22
routing-trial documents (`rt_*`, `rte_*`) have nowhere to land. `rubrics`, `gap_events` and
`milestone_performance` are EMPTY BY DESIGN — they were keyed to the pre-`union_base` taxonomy
and were deleted with it — so Layer D stays regressed until Layer C ships.

## 2. Operator decisions taken (2026-08-19, before code)

1. **`scenario_id` is a NOT NULL FK to `scenarios`, exactly like `rubrics`.** Playbooks are
   outputs of one taxonomy and die with it; the JSON artifacts on disk are the archive.
   **Consequence, and it is load-bearing:** `playbooks` MUST join the children-first delete
   chain in `ops/ship_union_taxonomy.py`, or the next taxonomy replacement is REFUSED by
   Postgres (every FK is ON DELETE NO ACTION). Covered by G-P7.
2. **JSONB blobs with positional move ids**, following the `rubrics` precedent that already
   survived Layer D wiring — not normalized `playbook_moves`/`playbook_citations` tables.

## 3. Measured facts the design rests on (verified 2026-08-19, zero spend)

- 32 documents across 5 artifacts, one stable shape. Per-document:
  `{scenario, arm, donor?, n_evidence, playbook{...}, snap_log?}`; per-artifact: `identity`.
- `playbook` = `{situation_signature, arc, key_moves[{name, criterion, evidence[{quote, call,
  account}]}], signature_language, pitfalls_and_variants, layer_d_checks}`.
- **All 11 distinct `scenario` keys and all 5 placebo `donor` keys resolve** against the live
  `union_base` map, so the NOT NULL FK is satisfiable for every document. (G-P1 re-verifies
  this against Postgres, not against the artifact.)
- `arm` on `rt_*`/`rte_*` is the ROUTING arm (`concat`/`r1`); on `pbv_*` it is `real`/`placebo`.
  `(scenario_key, arm)` is collision-free across all 32 today **only because E1 used a disjoint
  topic set** — an E2 re-running `concat` on the original topics would collide. Therefore
  `source_artifact` is part of the uniqueness key.
- `key_moves` counts range 3..5 (the schema's floor is 3, ceiling 6).

## 4. Design

```sql
CREATE TABLE playbooks (
    playbook_id           SERIAL PRIMARY KEY,
    scenario_id           INTEGER NOT NULL REFERENCES scenarios(scenario_id),
    scenario_key          TEXT NOT NULL,
    arm                   TEXT NOT NULL,
    status                TEXT NOT NULL CHECK (status IN ('live','trial','placebo','superseded')),
    source_artifact       TEXT NOT NULL,
    donor_scenario_key    TEXT,
    n_evidence            INTEGER NOT NULL,
    situation_signature   TEXT NOT NULL,
    arc                   JSONB NOT NULL DEFAULT '[]',
    key_moves             JSONB NOT NULL DEFAULT '[]',
    signature_language    JSONB NOT NULL DEFAULT '[]',
    pitfalls_and_variants JSONB NOT NULL DEFAULT '[]',
    layer_d_checks        JSONB NOT NULL DEFAULT '[]',
    snap_log              JSONB,
    identity              JSONB NOT NULL DEFAULT '{}',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (scenario_key, arm, source_artifact)
);
CREATE UNIQUE INDEX idx_playbooks_one_live
    ON playbooks (scenario_key) WHERE status = 'live';
```

**`move_id` is the ARRAY POSITION (`M1..Mn`), assigned by the loader**, never taken from the
model — the same rule as `milestone_id` (`v2/layer_c.py:399`) and coverage-area ids
(`shared/coverage_areas.py:40`), and for the same reason: a model-chosen id lets a re-run
silently repoint a person's history at different criteria. `key_moves` order is load-bearing.

**Status assignment (frozen).** `pbv_playbooks_snapped.json` arm `real` → `live` (this is the
validated set: PB0 5/5, PB2 4/5 pooled 11-4); arm `placebo` → `placebo`; every `rt_*`/`rte_*`
document → `trial`. Production reads MUST filter `status='live'`; the placebo twins and the
UNRESOLVED `r1` documents are in the same table and are not production content.

## 5. FROZEN GATES

| Gate | Statement | Fail action |
| --- | --- | --- |
| **G-P1** | Every document's `scenario_key` resolves to a live `scenarios.scenario_id` **read from Postgres**. | REFUSE the whole load. No partial writes. |
| **G-P2** | Round-trip fidelity: re-reading each row from Postgres and stripping loader-added `move_id`s reproduces the artifact's `playbook` object byte-identically (`json.dumps(sort_keys=True)`). | STOP, report the diff. |
| **G-P3** | Exactly 32 rows land: 10 + 5 + 5 + 6 + 6 by source artifact. No document silently dropped. | STOP. |
| **G-P4** | At most one `status='live'` row per `scenario_key`; a second is refused by the DB, not by application code. | STOP. |
| **G-P5** | `move_id` is dense, 1-based, `M1..Mn`, `n == len(key_moves)`, for all 32 documents; no model-supplied id is ever honoured. | STOP. |
| **G-P6** | Idempotence: a second `--apply` yields the same 32 rows, identical content, zero duplicates. | STOP. |
| **G-P7** | `ops/ship_union_taxonomy.py`'s children-first delete chain includes `playbooks`, so a future taxonomy replacement is not refused by the FK. | STOP. |

## 6. Non-goals (explicitly out of scope)

- Wiring Layer D against `layer_d_checks` or `key_moves`. `layer_d_checks` is descriptive only
  (trial spec §5) and `milestone_performance` is keyed to `rubrics`, not `playbooks`. A future
  `move_performance` table would key to `(playbook_id, move_id)`; nothing here presumes it.
- Re-reading E1, re-synthesizing any document, or any chat spend whatsoever. **This work is
  zero-spend: it loads documents that already exist.**
- Promoting any `trial` document to `live`. The routing A/B settled `concat`, and `r1` is
  UNRESOLVED; those 22 documents land as evidence, not as product.

## 7. BLIND CODE AUDIT (one, strong model, before the harness wrote anything)

Nine findings. Two HIGH, both of which would have fired on the very first `--apply`. Seven
fixed; one recorded and deliberately left alone as out of scope.

| # | Sev | Finding | Disposition |
| --- | --- | --- | --- |
| 1 | HIGH | The loader created the table via `db/init_db.py`, which opens its OWN connection from the raw `DATABASE_URL` and so **skips the `hostaddr` DNS workaround** — `*.neon.tech` is REFUSED by the system resolver on this network. The first `--apply` would have died at schema creation, *after* printing three PASS lines, reading like a partial success. | FIXED — the DDL is now extracted from a marked block in `db/schema.sql` and executed over the loader's own already-corrected connection. Markers keep exactly one definition; a test asserts the extraction finds it and pulls in nothing else. |
| 2 | HIGH | Adding `playbooks` to `SNAPSHOT_TABLES` **breaks `ship_union_taxonomy.py` on any database that lacks the table** — `counts()` runs before the dry-run guard, so `UndefinedTable` aborts even a dry run. Until the load succeeded, the taxonomy migration tool was unrunnable; and finding #1 blocked the load. A deadlock between the two changes. | FIXED — `existing()` resolves both `SNAPSHOT_TABLES` and `DELETE_ORDER` against `to_regclass` at run time, order preserved, skips printed. All six call sites now use the filtered lists. |
| 3 | MED | Running the full `schema.sql` takes `ACCESS EXCLUSIVE` on five live tables for its dozen `ADD COLUMN IF NOT EXISTS` statements — **the lock is acquired BEFORE `IF NOT EXISTS` is evaluated**, so it blocks concurrent work even with nothing to do. A long embedding job was running against the same database. | FIXED by the same change as #1, plus `SET lock_timeout = '5s'` so the DDL fails fast rather than queueing an exclusive request that blocks every reader behind it. |
| 4 | MED | **G-P6 was narrated, not enforced**, and on a first load (`before == 0`) neither branch fired, so the run could reach "SHIPPED" with no idempotence verdict at all. | FIXED — the loader now replays all 32 upserts and REFUSES if the row count moves. Made it a real gate of one invocation. |
| 5 | MED | **G-P4 passed vacuously at zero live rows** (`len(live) == len(set(live))` is trivially true when empty); the 5/5/22 split was printed, not asserted; and `verify()` never read back `scenario_id`, `status`, `arm`, `n_evidence` or `donor` — `scenario_id` being the exact field the FK design and the GOTCHAS "synthetic row index" trap are about. | FIXED — the status histogram is asserted against a frozen constant, and G-P2 now compares `scenario_id` against the resolved live id plus four scalar fields per document. |
| 6 | MED | `get_playbook_for_scenario` used `LIMIT 1` with no `ORDER BY` and no arm filter. Safe at `status='live'` because of the partial index, but **at `status='trial'` every scenario has both a `concat` and an `r1` row**, so a caller could silently receive the `r1` arm — UNRESOLVED and never shipped. The `rubrics` precedent it mirrors is safe only because `rubrics.scenario_id` is UNIQUE; `playbooks` deliberately is not. | FIXED — added an optional `arm` parameter, deterministic `ORDER BY arm, source_artifact`, and a RAISE when the filter matches more than one row instead of returning an arbitrary one. |
| 7 | MED | `check_move_ids` tested `"move_id" in m` after the call, which cannot distinguish loader mutation from an artifact legitimately carrying model-supplied ids — a future artifact would abort the load pointing the operator at the wrong file. The spec says such an id is *overwritten*, not an error. | FIXED — snapshots the moves before the call and compares, so it detects mutation and only mutation. |
| 8 | MED | **Pre-existing, in `ship_union_taxonomy.py`:** its "deletes and the load run in ONE transaction" guarantee is already false. `connect()` there is not autocommit, but `storage.upsert_scenario` ends with `conn.commit()`, so the first of the 259 upserts commits the children-first DELETEs and the later `conn.rollback()` cannot restore anything. Adding `playbooks` to `DELETE_ORDER` widens what that already-committed delete destroys by one table. | **NOT FIXED — recorded and escalated.** Out of scope here, the script has already run, and the snapshot schema (`pre_union_20260819`) is the real safety net rather than the transaction. Flagged to the operator; fixing it needs a `commit=False` path through the storage helpers. |
| 9 | LOW | `--apply --skip-init` on a database without the table printed a message claiming `--apply` would create it, then died 30 lines later at `SELECT count(*)`. | FIXED — refuses immediately with an accurate message. |

**Audit quality note.** The audit also verified several things are genuinely sound rather than
merely present, which is the useful half of a clean report: G-P2 is capable of failing (it
scanned all 32 bodies — zero floats, one non-ASCII string, no lone surrogates, so JSONB
normalization does not make the comparison vacuous); the per-row write model's
partial-failure claim is TRUE (dying on document 17 leaves 16 rows and a re-run fixes it);
`upsert_playbook` is a genuine `DO UPDATE` and not the `insert_kb_pair` `DO NOTHING` shape
that bit this project recently; and the tests are not tautological (`_ExplodingConn` proves
validation precedes DB access by reachability, not by mocking).

## 8. RESULT — all gates PASSED, 2026-08-19

```
[write] upserted 32 documents; playbooks 0 -> 32
[G-P6] PASS — replaying all 32 upserts left the count at 32
[G-P3] PASS — 32 rows, per-artifact {rt_concat: 5, pbv_snapped: 10, rt_r1: 5, rte_concat: 6, rte_r1: 6}
[G-P2] PASS — all 32 documents round-trip byte-identically, with scenario_id/status/arm/
              n_evidence/donor verified against the load plan
[G-P5] PASS — every stored move_id is its array position
[G-P4] PASS — 5 live playbooks over 5 scenarios, histogram {trial: 22, placebo: 5, live: 5},
              enforced by idx_playbooks_one_live
```

**G-P4 was then proven at the DATABASE level, not merely asserted.** The gate as written only
checks that the index exists in `pg_indexes`, which is weaker than the claim. A separate probe
attempted the violation for real — promoting an existing `trial` row for
`application_volume_and_prioritization` to `live` while a live document already existed:

```
[PROVEN] Postgres REFUSED the second live playbook:
         duplicate key value violates unique constraint "idx_playbooks_one_live"
[after]  32 rows, 5 live   [clean] rollback verified, nothing changed
```

**G-P7** is covered by tests (`playbooks` present in `DELETE_ORDER`, positioned before
`scenarios`, present in `SNAPSHOT_TABLES`) plus the `existing()` filter that keeps the
migration runnable on databases that predate the table.

**LAYER C IS SHIPPED.** 36 tests, zero chat spend, zero embeddings, zero published artifacts
overwritten.

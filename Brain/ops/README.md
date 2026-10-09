# ops/ — maintenance and auxiliary runners

Standalone CLI entry points. Nothing in the pipeline imports any of these, and this
directory is deliberately **not** a Python package (no `__init__.py`) — see the warning
below for why that matters.

Run them from `Brain/`, not from inside this directory:

```bash
python ops/clear_data.py              # wipe Postgres pipeline tables + checkpoints
python ops/clear_ego_trap_data.py     # wipe only the Ego Trap / Layer D tables
python ops/rerun_layer_c.py           # re-run Layer C for specific scenarios
python ops/backfill_scenarios.py      # reassign scenario_keys on existing kb_pairs
python ops/backfill_speaker_roster.py # rebuild the speaker roster
python ops/fetch_avoma_recordings.py  # pull call recordings from Avoma
python ops/run_ego_trap.py            # batch-run the Ego Trap gap analysis
```

PowerShell run recipes (`run_full_pipeline_postfix.ps1`, `run_subset150_postfix.ps1`)
each `Set-Location` to `Brain/` themselves, so they can be invoked from anywhere.

## ⚠️ `clear_data.py` and `clear_ego_trap_data.py` have no `__main__` guard

They execute their `DELETE FROM` statements at **import** time. Importing either one —
including from a test, a REPL, or an "import every module in this directory" sweep —
destroys live data. That is why this directory is not a package: there is no
`ops.clear_data` to import by accident. Verify these files with `py_compile`, never by
importing them.

## Path anchoring

Every script here resolves `Brain/` as `Path(__file__).resolve().parent.parent`. When
these lived at `Brain/` root they used `Path(__file__).parent`, so the move required
fixing 11 such references — `clear_data.py` would otherwise have looked for
`ops/checkpoints.db` and `run_ego_trap.py` for `ops/csm_recordings/`.

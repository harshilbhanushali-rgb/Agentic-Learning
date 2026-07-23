from __future__ import annotations
import os

# "gemma" (Option A) or "similarity" (Option B) — see Ego_trap.md Step 0.
STEP_0_MODE = os.environ.get("STEP_0_MODE", "similarity")

# Gate for writing raw per-call gap JSON to gap_events (aggregate tables always update).
ENABLE_GAP_EVENTS = os.environ.get("ENABLE_GAP_EVENTS", "true").strip().lower() == "true"

# Option B (embedding similarity) cosine-similarity cutoff for a signal match.
# No RESPONSE_WINDOW_SECONDS — these transcripts carry no timestamps, so "did the CSM
# respond" is turn-adjacency based (see transcript_parser.turns_until_next_client), not
# time-window based.
SIMILARITY_THRESHOLD = float(os.environ.get("EGO_TRAP_SIMILARITY_THRESHOLD", "0.75"))

# Step 3 (Gemma scoring): number of signals scored together in a single milestone/soft-skill
# Gemma call, instead of one call per milestone/skill per signal.
GEMMA_BATCH_SIZE = int(os.environ.get("EGO_TRAP_GEMMA_BATCH_SIZE", "4"))

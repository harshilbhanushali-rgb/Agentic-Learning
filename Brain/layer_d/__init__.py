"""Layer D redesign: gap analysis against playbooks (2026-08-20).

Scores CSM calls against the live Layer C playbooks (key_moves, positional M1..Mn)
and, with the SAME instrument, Naren's own routed moments from kb_pairs -- so a gap
is a rate difference against a measured benchmark, never an absolute score.

Spec: docs/superpowers/specs/2026-08-20-layer-d-redesign-design.md
Predecessor: ego_trap/ (rubric-era, dark since the union taxonomy replacement).
ego_trap/transcript_parser.py, csm_registry.py and signal_check.py's similarity
machinery are imported from there rather than copied; they move here when the
rubric-era modules retire.
"""

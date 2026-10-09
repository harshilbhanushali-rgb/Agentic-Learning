# Context Map

## Contexts

- [Ask Naren](./ask-naren/CONTEXT.md): internal tool that answers a CSM's situation grounded in Naren's closest real historical response
- `frontend/` and `Brain/`: no `CONTEXT.md` yet — created lazily once a term in that context is first resolved

## Relationships

- **Ask Naren → Brain**: Ask Naren reads Brain's Layer B `kb_pairs` (and, in its playbook-augmented prompt variant, Layer C playbooks) as its knowledge source. It does not write back to Brain's pipeline.

## Where Ask Naren's code lives

Ask Naren is its own context but its runtime lives **inside `Brain/`**, because it reuses Brain's storage, gateway and embedder modules directly rather than reimplementing retrieval, embedding or generation:

- `Brain/ask_naren/` — the service: retrieval pool, the grounding gate, generation, HTTP.
- `Brain/ops/serve_ask_naren.py` — the entry point. `--ask "<situation>"` answers one situation and exits, which is the cheapest end-to-end check.
- `Brain/tests/test_ask_naren_*.py` — its tests, following Brain's pytest conventions.
- `ask-naren/` — everything that is *not* runtime: the glossary, the ADRs, the spec, the throwaway prototype, and the audit harnesses that measured the answers.

The no-write-back relationship above is enforced rather than assumed: the service reads Postgres once at startup through a connection Postgres itself refuses to write through, then **closes it before serving a single request**. While answering, Ask Naren holds no database handle at all.

# Context Map

## Contexts

- [Ask Naren](./ask-naren/CONTEXT.md): internal tool that answers a CSM's situation grounded in Naren's closest real historical response
- `frontend/` and `Brain/`: no `CONTEXT.md` yet — created lazily once a term in that context is first resolved

## Relationships

- **Ask Naren → Brain**: Ask Naren reads Brain's Layer B `kb_pairs` (and, in its playbook-augmented prompt variant, Layer C playbooks) as its knowledge source. It does not write back to Brain's pipeline.

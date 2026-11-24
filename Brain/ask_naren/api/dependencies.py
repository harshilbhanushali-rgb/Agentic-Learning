"""What `build_app` was given -- the answerer, the readiness check and the admission gate --
handed to the routes through FastAPI's dependency system."""
from __future__ import annotations

from typing import Annotated, Awaitable, Callable, Optional

from fastapi import Depends, Request

from ask_naren.api import admission

#: The answerer takes the situation AND the thread it arrived in (issue #15), and is AWAITED
#: (issue #30). Still ONE callable -- the layer did not grow a second entry point for a
#: multi-turn request, because a thread is not a different kind of question, it is context
#: on the same one.
Answerer = Callable[[str, tuple], Awaitable[dict]]

#: Whether the service can answer yet. Separate from liveness on purpose: a process that is
#: up but not able to answer is not a dead one, and an ingress that cannot tell the
#: difference will kill something that is merely starting.
ReadyCheck = Callable[[], bool]

#: GET /verify: `(all checks passed, report)`. Optional -- a process built without one answers
#: 404 `not_configured`. See ask_naren/verification.py.
Verifier = Callable[[], Awaitable[tuple[bool, dict]]]


# Read from `app.state`, where `build_app` put them, rather than closed over -- so the routes
# are defined once at module level, and a test that wants a different gate passes one to
# `build_app` instead of patching anything.

def _gate(request: Request) -> admission.Admission:
    return request.app.state.gate


def _answerer(request: Request) -> Answerer:
    return request.app.state.answerer


def _is_ready(request: Request) -> ReadyCheck:
    return request.app.state.is_ready


def _verifier(request: Request) -> "Verifier | None":
    return request.app.state.verify


def _setup(request: Request):
    """The POST /admin/setup jobs (ask_naren/db/admin_setup.SetupJobs), or None when it is off."""
    return request.app.state.setup


GateDep = Annotated[admission.Admission, Depends(_gate)]
AnswererDep = Annotated[Answerer, Depends(_answerer)]
ReadyDep = Annotated[ReadyCheck, Depends(_is_ready)]
# A real type, not a string: FastAPI evaluates this annotation in the ROUTES module.
VerifierDep = Annotated[Optional[Verifier], Depends(_verifier)]
SetupDep = Annotated[Optional[object], Depends(_setup)]

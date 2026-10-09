"""The declines THIS layer writes -- busy, out of time, broken -- as exceptions.

An answerer's own declines (`no_close_match` and the rest) are answers and travel as its
response. These three are about the service, not the question, and each one is raised from
wherever under `/ask` it is discovered and turned into its response by ONE handler
(`handlers.refused`).
"""
from __future__ import annotations

from ask_naren.api.models import Declined

# *** THREE WAYS OF SAYING NO, AND THEY MUST STAY DISTINGUISHABLE (issue #32). ***
#
# A capacity problem wearing a quality problem's clothes is the main hazard here: if "too
# many questions right now" arrived as a no-close-match, the tool would look like it was
# working perfectly and simply declining a lot, and the decline rate calibration reads
# would be measuring load. So each one differs in THREE places at once -- the HTTP status an
# operator watches, the reason code an engineer greps, and the sentence a CSM reads:
#
#   service_error       503  something broke on our side            -> tell someone
#   service_busy        429  too many questions right now           -> ask again in a moment
#   deadline_exceeded   504  this one ran out of time               -> ask again
#   (no_close_match)    200  nothing in Naren's calls is close      -> rephrase, or accept
#
# The first three are all `outcome: declined` in the body, which is the shape the fault
# already used: the frontend then needs no new render path, and its reason->copy table is
# exhaustive over the union, so a new reason is a BUILD failure rather than a busy response
# quietly rendering as "no grounded answer".
SERVICE_ERROR = "service_error"
_SERVICE_ERROR_MESSAGE = (
    "Ask Naren could not reach its knowledge base just now. Nothing was answered -- this "
    "is a fault on our side, not a 'no close match'. Try again in a moment."
)

SERVICE_BUSY = "service_busy"
_SERVICE_BUSY_MESSAGE = (
    "Ask Naren is answering as many people as it can right now, and could not get to this "
    "one in time to be useful. Nothing is wrong with your question and nothing is broken "
    "-- ask again in about {seconds} seconds."
)

DEADLINE_EXCEEDED = "deadline_exceeded"
_DEADLINE_MESSAGE = (
    "Ask Naren did not finish this one in time, and stopped rather than leave you waiting "
    "on a spinner. Nothing you typed caused it -- ask again."
)


class Refusal(Exception):
    """A decline written by this layer rather than by the answerer: busy, out of time, or
    broken. Raised from anywhere under `/ask` and turned into its response by ONE handler,
    `handlers.refused`, so the status, the reason code and the sentence cannot be assembled in two
    places and drift apart.

    The body is built through `models.Declined`, so what this layer writes is checked
    against the same schema `/docs` publishes.
    """

    status: int

    def __init__(self, reason: str, message: str, *, headers: dict | None = None,
                 **extra) -> None:
        super().__init__(reason)
        self.body = Declined(outcome="declined", reason=reason, message=message,
                             **extra).model_dump(exclude_none=True)
        self.headers = headers or {}


class ServiceBusy(Refusal):
    """REFUSED ON ARRIVAL, having waited for nothing. 429 and not 503: a busy lunchtime must
    not look like an outage to whatever counts 5xx, and `Retry-After` carries the same
    estimate as the prose for anything reading headers rather than sentences."""

    status = 429

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(SERVICE_BUSY,
                         _SERVICE_BUSY_MESSAGE.format(seconds=retry_after_seconds),
                         headers={"Retry-After": str(retry_after_seconds)},
                         retry_after_seconds=retry_after_seconds)


class DeadlineExceeded(Refusal):
    status = 504

    def __init__(self) -> None:
        super().__init__(DEADLINE_EXCEEDED, _DEADLINE_MESSAGE)


class ServiceFault(Refusal):
    """Something broke on our side. Reported generically: the underlying message could name
    internal hosts, and it is not something a CSM can act on. The 503 is what tells an
    operator this was a fault rather than a decline."""

    status = 503

    def __init__(self) -> None:
        super().__init__(SERVICE_ERROR, _SERVICE_ERROR_MESSAGE)

"""Turning an internal call filename into a citation a CSM recognises (issue #4).

WHAT THE CORPUS ACTUALLY LOOKS LIKE, measured 2026-08-27 over the 6,496 coachable
kb_pairs -- the only calls Ask Naren can cite:

  68.7%  dated, with a slug:  20230503_uber_joveo_weekly_performance_review_d18cc178.txt
  31.3%  an opaque UUID:      015a5979-4c9f-44ae-9b9d-f642529a5478.txt   (323 distinct calls)

There is NO recorded meeting subject anywhere -- not in the schema (`calls` holds filename
and imported_at, nothing else), not in the transcripts (Brain/CLAUDE.md: "no participant
header block"), and not in any sidecar. Issue #4's text assumed one existed. What IS
recorded, beside each transcript, is a `<stem>.speakers.json` naming the participants, and
their email domains identify the account.

WHY THIS RESOLVER IS DELIBERATELY CONSERVATIVE. Of the 323 opaque calls, 267 carry exactly
one external participant domain, 40 carry two to four, and 16 carry none. One measured
example lists both `reckitt.com` and `pinksquid.com` -- a brand and its agency. Picking the
"most likely" one would print an agency's name where a CSM expects the client's, on a
citation whose whole purpose is to be verifiable. So:

  * an account is named only where the recorded data states it unambiguously;
  * a date is parsed only from the filename's own YYYYMMDD prefix;
  * anything else falls back to the RAW FILENAME, which is honest and still traceable.

A wrong label is worse than an opaque one. The raw filename, pair_id and scenario stay in
the response either way (see answering._citation), so an engineer tracing a bad answer is
never worse off than before this module existed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Mapping

SEPARATOR = " · "

# 20230503_uber_joveo_weekly_performance_review_d18cc178.txt
_DATED = re.compile(r"^(?P<date>\d{8})_(?P<slug>.+?)_(?P<hash>[0-9a-f]{6,})$")
# 20260515_joveo_na_integration_sandbox_work  -- dated, no trailing content hash
_DATED_NO_HASH = re.compile(r"^(?P<date>\d{8})_(?P<slug>.+)$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

# The separator that splits an account from a meeting subject in the dated convention:
# "<account>_joveo_<subject>". Only this form is treated as naming an account. A slug that
# merely STARTS with "joveo_" does not -- "joveo_emea_integration_sandbox_work" would yield
# the account "EMEA", which is a region, not a client.
_ACCOUNT_SPLIT = "_joveo_"

_MONTHS = ("January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December")

# Tokens that read wrong in Title Case. Small and literal on purpose -- a general
# abbreviation rule would start inventing capitalisation for client names.
_UPPER = {"emea", "apac", "na", "us", "uk", "qbr", "roi", "cpl", "cpa", "cph", "ats",
          "seo", "sla", "api", "ai", "kpi", "crm", "hr", "it", "b2b", "faq"}

# Domain labels that are never the registrable name, so the label before them is.
_PUBLIC_SUFFIX_HEADS = {"co", "com", "net", "org", "ac", "gov", "edu"}


def humanize(slug: str) -> str:
    """`weekly_performance_review` -> `Weekly Performance Review`."""
    words = []
    for token in slug.split("_"):
        if not token:
            continue
        words.append(token.upper() if token.lower() in _UPPER else token.capitalize())
    return " ".join(words)


def format_date(yyyymmdd: str) -> str | None:
    """`20230503` -> `3 May 2023`. None when the digits are not a real date -- a filename
    starting with eight digits is not proof that they are one."""
    try:
        year, month, day = (int(yyyymmdd[0:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:8]))
    except ValueError:
        return None
    if not (1 <= month <= 12 and 1 <= day <= 31 and 2000 <= year <= 2100):
        return None
    return f"{day} {_MONTHS[month - 1]} {year}"


def account_from_domain(domain: str) -> str | None:
    """`reckitt.com` -> `Reckitt`, `contractors.scale.com` -> `Scale`.

    Takes the registrable label rather than the leading one, so a departmental subdomain
    does not become the account name.
    """
    labels = [p for p in domain.lower().strip(".").split(".") if p]
    if len(labels) < 2:
        return None
    name = labels[-2]
    if name in _PUBLIC_SUFFIX_HEADS and len(labels) >= 3:
        name = labels[-3]
    if not name or not re.match(r"^[a-z0-9-]+$", name):
        return None
    return humanize(name.replace("-", "_"))


def resolve_label(call_filename: str,
                  account_index: Mapping[str, str] | None = None) -> str:
    """The one function callers use. Never raises, never returns empty: the raw filename is
    always an acceptable answer, and is the answer whenever resolution would have to guess.

    `account_index` maps a call filename to an account name and is built by
    build_account_index from the recorded participant sidecars. Without it, opaque-UUID
    calls resolve to their raw filename -- which is what happens on any machine where the
    recordings directory is absent, and is why that absence degrades rather than breaks.
    """
    raw = (call_filename or "").strip()
    if not raw:
        return ""
    stem = raw[:-4] if raw.lower().endswith(".txt") else raw

    dated = _DATED.match(stem) or _DATED_NO_HASH.match(stem)
    if dated:
        date = format_date(dated.group("date"))
        if date:
            slug = dated.group("slug")
            parts = []
            if _ACCOUNT_SPLIT in slug:
                account, subject = slug.split(_ACCOUNT_SPLIT, 1)
                parts = [humanize(account), humanize(subject)]
            else:
                # No unambiguous account. The whole slug becomes the subject rather than
                # having its leading tokens promoted to a client name they may not be.
                parts = [humanize(slug)]
            return SEPARATOR.join([p for p in parts if p] + [date])

    if _UUID.match(stem):
        account = (account_index or {}).get(raw) or (account_index or {}).get(stem)
        if account:
            # No date exists for these at all -- nothing in the filename or the sidecar
            # carries one. The short id keeps the citation distinguishable when one account
            # contributes several calls.
            return f"{account}{SEPARATOR}call {stem[:8]}"

    return raw


def build_account_index(directories: Iterable[Path]) -> dict[str, str]:
    """Map `<uuid>.txt` -> account name, from the `<stem>.speakers.json` sidecars.

    ONLY calls with exactly ONE external participant domain are included. Two or more is
    the ambiguous case this module refuses to resolve (a brand and its agency are both
    "external"), and zero means nothing was recorded to resolve from. Excluded calls are
    simply absent, so resolve_label falls back to the raw filename for them.

    Directories are read once, at startup, by the caller that builds the pool -- the same
    place and the same lifetime. Nothing here is read while a request is being answered.
    """
    index: dict[str, str] = {}
    for directory in directories:
        try:
            sidecars = sorted(Path(directory).glob("*.speakers.json"))
        except OSError:
            continue  # an absent or unreadable corpus directory is not an error here
        for sidecar in sidecars:
            stem = sidecar.name[: -len(".speakers.json")]
            if stem in index or f"{stem}.txt" in index:
                continue
            account = _account_from_sidecar(sidecar)
            if account:
                index[f"{stem}.txt"] = account
    return index


def _account_from_sidecar(path: Path) -> str | None:
    try:
        speakers = json.loads(path.read_text(encoding="utf-8")).get("speakers") or []
    except (OSError, json.JSONDecodeError, AttributeError):
        return None
    domains = set()
    for speaker in speakers:
        if speaker.get("is_rep"):
            continue
        email = (speaker.get("email") or "")
        if "@" not in email:
            continue                       # placeholder rows: the corpus has email == "db"
        domain = email.rsplit("@", 1)[1].lower()
        if not domain or "joveo" in domain:
            continue
        domains.add(domain)
    if len(domains) != 1:
        return None
    return account_from_domain(next(iter(domains)))

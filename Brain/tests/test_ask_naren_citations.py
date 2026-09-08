"""ask_naren/citations.py -- turning an internal call filename into something a CSM
recognises, on hand-built filenames (issue #4).

The rule under test is CONSERVATIVE by decision: resolve what the recorded data states
unambiguously, and fall back to the raw filename rather than infer. A citation naming the
wrong company is worse than one naming a file -- ~5% of the opaque-UUID calls have several
external participant domains (measured 2026-08-27: 40 of 323, one example carrying both a
brand and its agency), so guessing would print an agency where a CSM expects the client.
"""
import json

from ask_naren import citations


# -- a dated filename carrying an account -----------------------------------------------

def test_a_dated_filename_resolves_to_account_subject_and_date():
    label = citations.resolve_label("20230503_uber_joveo_weekly_performance_review_d18cc178.txt")
    assert label == "Uber · Weekly Performance Review · 3 May 2023"


def test_a_multi_word_account_keeps_its_words():
    assert citations.resolve_label("20230509_uber_corporate_joveo_connect_409d34b7.txt") == (
        "Uber Corporate · Connect · 9 May 2023")


def test_a_dated_filename_without_the_joveo_separator_names_no_account():
    """`joveo_na_integration_sandbox_work` splits into no account at all -- promoting its
    leading tokens would yield the "account" NA, which is a region. The slug becomes the
    subject and the citation simply does not claim a client."""
    label = citations.resolve_label("20260515_joveo_na_integration_sandbox_work_bfd8c347.txt")
    assert label == "Joveo NA Integration Sandbox Work · 15 May 2026"


def test_a_dated_filename_with_no_content_hash_still_resolves():
    assert citations.resolve_label("20230512_zoe_joveo_sync_dash_review.txt") == (
        "Zoe · Sync Dash Review · 12 May 2023")


def test_eight_leading_digits_that_are_not_a_date_fall_back_to_the_filename():
    """A filename starting with eight digits is not proof they are a date. Rendering
    "99 Undecimber" would be an invented label."""
    assert citations.resolve_label("20239999_acme_joveo_sync_a1b2c3d4.txt") == (
        "20239999_acme_joveo_sync_a1b2c3d4.txt")


# -- an opaque UUID, resolved only from recorded participants ----------------------------

UUID_FILE = "015a5979-4c9f-44ae-9b9d-f642529a5478.txt"


def test_an_opaque_uuid_resolves_to_the_recorded_account_and_a_short_id():
    """No date exists for these anywhere -- not in the filename, not in the sidecar. The
    short id keeps two calls with the same account distinguishable."""
    label = citations.resolve_label(UUID_FILE, {UUID_FILE: "Reckitt"})
    assert label == "Reckitt · call 015a5979"


def test_an_opaque_uuid_with_nothing_recorded_falls_back_to_the_filename():
    """Also the behaviour on any machine without the recordings directory: the index is
    empty and every UUID citation degrades to its raw filename rather than breaking."""
    assert citations.resolve_label(UUID_FILE, {}) == UUID_FILE
    assert citations.resolve_label(UUID_FILE) == UUID_FILE


# -- neither convention -----------------------------------------------------------------

def test_a_filename_matching_no_convention_is_returned_as_is():
    assert citations.resolve_label("Call1.txt") == "Call1.txt"


def test_an_empty_filename_does_not_raise():
    assert citations.resolve_label("") == ""
    assert citations.resolve_label(None) == ""      # type: ignore[arg-type]


# -- domain to account ------------------------------------------------------------------

def test_a_departmental_subdomain_does_not_become_the_account():
    assert citations.account_from_domain("contractors.scale.com") == "Scale"


def test_a_two_part_public_suffix_is_not_mistaken_for_the_account():
    assert citations.account_from_domain("acme.co.uk") == "Acme"


def test_a_bare_hostname_resolves_to_nothing_rather_than_itself():
    assert citations.account_from_domain("localhost") is None


# -- the account index, built from recorded participant sidecars -------------------------

def _sidecar(directory, stem, emails_and_reps):
    (directory / f"{stem}.speakers.json").write_text(json.dumps({
        "meeting_uuid": stem,
        "speakers": [{"email": e, "name": e, "is_rep": r}
                     for e, r in emails_and_reps],
    }), encoding="utf-8")


def test_one_external_domain_names_the_account(tmp_path):
    _sidecar(tmp_path, "aaaaaaaa-1111-2222-3333-444444444444",
             [("naren@joveo.com", True), ("gabbie@reckitt.com", False),
              ("durga@reckitt.com", False)])
    index = citations.build_account_index([tmp_path])
    assert index == {"aaaaaaaa-1111-2222-3333-444444444444.txt": "Reckitt"}


def test_two_external_domains_are_left_unresolved(tmp_path):
    """THE conservative decision, and the reason this module exists in this shape. The
    measured example carried reckitt.com AND pinksquid.com -- a brand and its agency. There
    is nothing in the recorded data that says which one the CSM would call "the account", so
    the call is excluded and its citation stays the raw filename."""
    _sidecar(tmp_path, "bbbbbbbb-1111-2222-3333-444444444444",
             [("naren@joveo.com", True), ("gabbie@reckitt.com", False),
              ("laura@pinksquid.com", False)])
    assert citations.build_account_index([tmp_path]) == {}


def test_a_call_with_only_joveo_participants_is_left_unresolved(tmp_path):
    _sidecar(tmp_path, "cccccccc-1111-2222-3333-444444444444",
             [("naren@joveo.com", True), ("someone@joveo.com", False)])
    assert citations.build_account_index([tmp_path]) == {}


def test_a_placeholder_participant_row_is_not_read_as_a_domain(tmp_path):
    """The corpus really contains a speaker whose `email` is the literal string "db". An
    entry with no @ must not contribute a domain, or it would make a single-domain call look
    ambiguous and silently drop a resolvable one."""
    _sidecar(tmp_path, "dddddddd-1111-2222-3333-444444444444",
             [("naren@joveo.com", True), ("db", False), ("gabbie@reckitt.com", False)])
    assert citations.build_account_index([tmp_path]) == {
        "dddddddd-1111-2222-3333-444444444444.txt": "Reckitt"}


def test_an_absent_directory_is_not_an_error(tmp_path):
    """A machine without the (gitignored, machine-local) recordings corpus must still
    serve -- every UUID citation just degrades to its raw filename."""
    assert citations.build_account_index([tmp_path / "nope"]) == {}


def test_unreadable_json_is_skipped_rather_than_raising(tmp_path):
    (tmp_path / "eeeeeeee-1111-2222-3333-444444444444.speakers.json").write_text(
        "{not json", encoding="utf-8")
    assert citations.build_account_index([tmp_path]) == {}


# -- naming the ACCOUNT alone, for "where else has this come up" (issue #22) --------------
#
# `resolve_label` answers "what should this citation read as" and may be ugly, because it
# points at a call. `account_for` ASSERTS AN IDENTITY -- these exchanges are that client --
# so it reads only the recorded participants and never the filename.
#
# MEASURED, and the reason for the split: the dated convention is
# `<calendar title>_joveo_<subject>`, and the leading part is whatever the meeting was
# called. `20240613_review_joveo_proposal_amn_healthcare` would name the account "Review"
# when the client is AMN Healthcare, and `uber_corporate` / `uber_emea` /
# `uber_north_america` would be three accounts and one company.

def test_an_account_is_named_from_the_recorded_participants():
    assert citations.account_for(UUID_FILE, {UUID_FILE: "Reckitt"}) == "Reckitt"


def test_two_calls_with_the_same_account_resolve_to_the_same_name():
    """The point of the function: #22 counts exchanges per account, so two calls that are
    the same client must collapse to one entry rather than reading as two clients."""
    a, b = "call-one.txt", "call-two.txt"
    index = {a: "Uber", b: "Uber"}
    assert citations.account_for(a, index) == citations.account_for(b, index) == "Uber"


def test_a_calendar_title_in_the_filename_is_never_read_as_a_client():
    """THE FINDING THIS FUNCTION EXISTS AROUND. Every one of these is a real live filename
    shape, and the filename's leading tokens are a meeting title, not an account field.
    Reading them would put a wrong client name in an answer whose entire content is client
    names -- which #22 says is worse than an opaque one."""
    assert citations.account_for(
        "20240613_review_joveo_proposal_amn_healthcare_4d213b9c.txt") is None
    assert citations.account_for(
        "20240515_weekly_tech_huddle_joveo_demo_100a3db4.txt") is None
    assert citations.account_for(
        "20250514_this_january_joveo_ua_dashboard_demo_6c2c535f.txt") is None


def test_the_filename_cannot_split_one_client_into_several_accounts():
    """`uber_corporate`, `uber_emea` and `uber_north_america` are one company. Read from the
    filename they are three accounts, which turns one client's pattern into a fake spread --
    the precise thing #22 is asked to measure."""
    for name in ("20230509_uber_corporate_joveo_connect_409d34b7.txt",
                 "20230814_uber_emea_joveo_connect_2c1a0c7e.txt",
                 "20230920_uber_north_america_joveo_connect_3a9a70ea.txt"):
        assert citations.account_for(name) is None
    # With participants recorded, all three ARE one client.
    index = {n: "Uber" for n in (
        "20230509_uber_corporate_joveo_connect_409d34b7.txt",
        "20230814_uber_emea_joveo_connect_2c1a0c7e.txt",
        "20230920_uber_north_america_joveo_connect_3a9a70ea.txt")}
    assert {citations.account_for(n, index) for n in index} == {"Uber"}


def test_an_unresolvable_call_names_no_account_rather_than_guessing_one():
    """RETURNS None, NOT the filename. #22 must be able to tell "this is Uber" from "we
    cannot say", because the second becomes a raw filename in the answer and the first
    becomes a client name. A fallback baked in here would erase that distinction before the
    caller could act on it."""
    assert citations.account_for(UUID_FILE, {}) is None
    assert citations.account_for(UUID_FILE) is None
    assert citations.account_for("Call1.txt") is None
    assert citations.account_for("") is None


def test_the_citation_LABEL_still_reads_the_filename():
    """Deliberately unchanged. A citation LABEL points at a call, so an ugly one is harmless
    and a date plus a meeting subject is genuinely useful. Only the identity claim moved."""
    assert citations.resolve_label(
        "20240613_review_joveo_proposal_amn_healthcare_4d213b9c.txt").startswith("Review")

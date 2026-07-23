from preprocessing.transcript_parser import Turn, SpeakerRole
from v1.layer_b import extract_pairs


def _turn(idx, role, text, call_id="c1"):
    return Turn(index=idx, speaker_raw="X", role=role, text=text, call_id=call_id)


def test_basic_client_naren_pair():
    turns = [
        _turn(0, SpeakerRole.CLIENT, "What is your standard pricing structure for enterprise clients?"),
        _turn(1, SpeakerRole.NAREN,  "We price based on a CPApply model calculated per qualified candidate application."),
    ]
    pairs = extract_pairs(turns, db_call_id=1)
    assert len(pairs) == 1
    assert pairs[0]["trigger_text"] == "What is your standard pricing structure for enterprise clients?"
    assert "CPApply" in pairs[0]["response_text"]


def test_joveo_other_interjection_skipped():
    turns = [
        _turn(0, SpeakerRole.CLIENT,      "How exactly does your monthly billing cycle work for large accounts?"),
        _turn(1, SpeakerRole.NAREN,       "We bill monthly based on total qualified candidate volume delivered."),
        _turn(2, SpeakerRole.JOVEO_OTHER, "Right, exactly."),
        _turn(3, SpeakerRole.NAREN,       "And there are absolutely no additional setup fees involved either."),
        _turn(4, SpeakerRole.CLIENT,      "OK thanks."),
    ]
    pairs = extract_pairs(turns, db_call_id=1)
    assert len(pairs) == 1
    assert "monthly" in pairs[0]["response_text"]
    assert "setup fees" in pairs[0]["response_text"]


def test_no_naren_response_no_pair():
    turns = [
        _turn(0, SpeakerRole.CLIENT,      "Question?"),
        _turn(1, SpeakerRole.JOVEO_OTHER, "Not Naren."),
        _turn(2, SpeakerRole.CLIENT,      "Another question?"),
    ]
    pairs = extract_pairs(turns, db_call_id=1)
    assert len(pairs) == 0


def test_multi_consecutive_naren_turns_joined():
    turns = [
        _turn(0, SpeakerRole.CLIENT, "Could you explain in more detail exactly what Joveo actually does for employers?"),
        _turn(1, SpeakerRole.NAREN,  "Joveo is a leading programmatic recruitment advertising platform for employers."),
        _turn(2, SpeakerRole.NAREN,  "We work with 2000+ different job board publishers across many industries."),
        _turn(3, SpeakerRole.NAREN,  "And we continuously optimize campaign budgets in real time automatically."),
    ]
    pairs = extract_pairs(turns, db_call_id=1)
    assert len(pairs) == 1
    assert "2000+" in pairs[0]["response_text"]
    assert "real time" in pairs[0]["response_text"]

from preprocessing.segmenter import segment_into_clauses


def test_multi_idea_utterance():
    text = ("We tried programmatic before through an agency and it didn't work. "
            "I'm not sure we have the budget right now. "
            "Our team is pretty small so we'd need a lot of hand-holding.")
    clauses = segment_into_clauses(text)
    assert len(clauses) >= 2


def test_short_noise_filtered():
    assert segment_into_clauses("K.") == []
    assert segment_into_clauses("Yeah.") == []
    assert segment_into_clauses("I mean.") == []


def test_normal_sentence_preserved():
    text = "We are looking for a way to reduce our cost-per-apply."
    clauses = segment_into_clauses(text)
    assert len(clauses) == 1
    assert clauses[0] == text


def test_empty_string():
    assert segment_into_clauses("") == []

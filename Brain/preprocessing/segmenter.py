from __future__ import annotations
import spacy

_nlp = None


def _get_nlp():
    global _nlp
    if _nlp is None:
        _nlp = spacy.load("en_core_web_lg")
    return _nlp


def segment_into_clauses(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    nlp = _get_nlp()
    doc = nlp(text)
    clauses: list[str] = []
    for sent in doc.sents:
        sent_text = sent.text.strip()
        if len(sent) < 4:
            continue
        clauses.append(sent_text)
    return clauses

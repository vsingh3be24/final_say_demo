"""Semantic relationship mapping tests that do not download model weights."""

import numpy as np
from types import SimpleNamespace

from finalsay.models_iface.semantic_model import (
    SemanticComparisonModel,
    _content_sentences,
    _date_values,
)


def _model_with_scores(scores):
    model = SemanticComparisonModel()
    model._pair_probabilities = lambda _premise, _hypothesis: scores

    class _SameSentenceEncoder:
        def encode(self, texts, **_kwargs):
            return np.tile(np.asarray([[1.0, 0.0]], dtype=np.float32), (len(texts), 1))

    model._models = lambda: (_SameSentenceEncoder(), object())
    return model


def test_semantic_nli_maps_explicit_date_replacement_to_superseded():
    model = _model_with_scores(
        {"contradiction": 0.91, "entailment": 0.03, "neutral": 0.06}
    )
    label, _score, rationale, evidence = model.classify_with_evidence(
        "Examination is scheduled on 15 September.",
        "The examination was postponed and will now take place on 22 September instead.",
    )
    assert label == "superseded"
    assert "not calibrated probabilities" in evidence[0]
    assert "mapped to superseded" in rationale


def test_revised_schedule_subject_is_not_replacement_evidence_when_dates_match():
    model = _model_with_scores(
        {"contradiction": 0.01, "entailment": 0.97, "neutral": 0.02}
    )
    label, _score, _rationale, evidence = model.classify_with_evidence(
        "The End-Semester Examinations will commence from 15 December 2026.",
        "Subject: Revised Schedule for End-Semester Examinations\n"
        "The End-Semester Examinations will commence from 15 December 2026.",
    )
    assert label == "consistent"
    assert not any("replacement or rescheduling language" in item for item in evidence)


def test_date_parser_does_not_consume_from_as_a_month_name():
    assert _date_values("commence from 15 December 2026") == {(12, 15, 2026)}


def test_date_parser_handles_indian_dotted_deadlines():
    assert _date_values("Deadline extended up to 15.11.2026") == {(11, 15, 2026)}


def test_extension_word_outside_the_supported_claim_pair_does_not_change_label():
    model = SemanticComparisonModel()
    official_ref = "VII/2026/02 dated % September, 2026"
    official_topic = "The LLB supplementary form concerns May/June examination students"
    forwarded_ref = "Vili2028/03, Dated 130 July, 2028"
    forwarded_extension = "The regular NCWEB form deadline is extended until 15 July 2028"
    vectors = {
        official_ref: [1.0, 0.0],
        official_topic: [0.0, 1.0],
        forwarded_ref: [1.0, 0.0],
        forwarded_extension: [0.0, 1.0],
    }

    class _ClaimEncoder:
        def encode(self, texts, **_kwargs):
            return np.asarray([vectors[text] for text in texts], dtype=np.float32)

    model._models = lambda: (_ClaimEncoder(), object())
    model._pair_probabilities = lambda premise, hypothesis: (
        {"contradiction": 0.96, "entailment": 0.02, "neutral": 0.02}
        if premise == official_ref and hypothesis == forwarded_ref
        else {"contradiction": 0.1, "entailment": 0.1, "neutral": 0.8}
    )

    label, _score, _rationale, evidence = model.classify_with_evidence(
        f"Ref, No. Exam. {official_ref}\n{official_topic}",
        f"Ref, No. Exam. {forwarded_ref}\n{forwarded_extension}",
    )

    assert label == "contradictory"
    assert "official: ‘VII/2026/02 dated % September, 2026’" in evidence[1]


def test_claim_extraction_discards_subject_and_date_headers():
    claims = _content_sentences(
        "Subject: End Semester Examination Time Table for Autumn 2026-27\n"
        "Date: 12 October 2026\n"
        "The examination will be held for 12 days including weekends."
    )
    assert claims == ["The examination will be held for 12 days including weekends"]


def test_claim_pair_selection_uses_nli_to_avoid_a_misleading_cosine_match():
    model = SemanticComparisonModel()
    unrelated = "The exam timetable is enclosed for reference"
    matching = "Examinations are scheduled continuously for 12 days and include weekends"
    forwarded = "The examination timetable will run continuously for 12 days and include weekends"
    vectors = {
        unrelated: [1.0, 0.0],
        matching: [0.8, 0.6],
        forwarded: [1.0, 0.0],
    }

    class _Encoder:
        def encode(self, texts, **_kwargs):
            return np.asarray([vectors[text] for text in texts], dtype=np.float32)

    model._models = lambda: (_Encoder(), object())
    model._pair_probabilities = lambda premise, _hypothesis: (
        {"entailment": 0.01, "contradiction": 0.60, "neutral": 0.39}
        if premise == unrelated
        else {"entailment": 0.98, "contradiction": 0.01, "neutral": 0.01}
    )

    label, _score, _rationale, evidence = model.classify_with_evidence(
        f"Subject: Examination schedule\n{unrelated}\n{matching}", forwarded
    )

    assert label == "consistent"
    assert matching in evidence[1]


def test_claim_extraction_keeps_relevant_body_after_long_pdf_preamble():
    preamble = "\n".join(f"Timetable row {index} course allocation" for index in range(20))
    relevant = "The exam will be held for 12 days including Saturdays and Sundays."
    claims = _content_sentences(f"{preamble}\n{relevant}")
    assert relevant[:-1] in claims


def test_claim_extraction_joins_soft_wrapped_pdf_sentence():
    claims = _content_sentences(
        "As per the approved calendar, examinations are scheduled for 12 days\n"
        "and will be held on Saturdays and Sundays also."
    )
    assert claims == [
        "As per the approved calendar, examinations are scheduled for 12 days and will be held on Saturdays and Sundays also"
    ]


def test_supersession_uses_event_dates_not_notice_publication_date():
    model = _model_with_scores(
        {"contradiction": 0.91, "entailment": 0.03, "neutral": 0.06}
    )
    label, _score, _rationale, evidence = model.classify_with_evidence(
        "Date: 01 November 2026\n"
        "The End-Semester Examinations will commence from 15 December 2026.",
        "The exams have been postponed from 15 December 2026 and will now "
        "commence on 20 December 2026 instead.",
    )
    assert label == "superseded"
    assert "(12, 15, 2026)" in evidence[2]
    assert "(12, 20, 2026)" in evidence[2]


def test_semantic_nli_maps_date_conflict_without_replacement_to_contradictory():
    model = _model_with_scores(
        {"contradiction": 0.91, "entailment": 0.03, "neutral": 0.06}
    )
    label, *_ = model.classify_with_evidence(
        "Examination is scheduled on 15 September.",
        "The examination will take place on 20 September.",
    )
    assert label == "contradictory"


def test_semantic_nli_maps_entailment_and_neutral_to_consistent_and_unresolved():
    same = _model_with_scores(
        {"contradiction": 0.01, "entailment": 0.97, "neutral": 0.02}
    )
    unclear = _model_with_scores(
        {"contradiction": 0.15, "entailment": 0.1, "neutral": 0.75}
    )
    assert same.classify_with_evidence("Notice A", "Notice A")[0] == "consistent"
    assert unclear.classify_with_evidence("Notice A", "Unclear circular")[0] == "unresolved"


def test_semantic_candidate_rank_prioritizes_embedding_over_long_lexical_match():
    model = SemanticComparisonModel()
    query = "end semester examination timetable autumn 2026-27 for 12 days saturdays sundays"
    lexical_distractor = SimpleNamespace(
        id=1, issuer="", action=None,
        redacted_text=query + " calendar and registration information",
    )
    semantically_relevant = SimpleNamespace(
        id=2, issuer="", action=None,
        redacted_text="The final assessment schedule lists daily examination sessions.",
    )
    vectors = {
        query: np.asarray([1.0, 0.0], dtype=np.float32),
        lexical_distractor.redacted_text: np.asarray([0.8, 0.6], dtype=np.float32),
        semantically_relevant.redacted_text: np.asarray([1.0, 0.0], dtype=np.float32),
    }
    model.embed = lambda texts: np.stack([vectors[text] for text in texts])
    submission = SimpleNamespace(issuer="", action=None, redacted_text=query)

    ranked = model.rank_candidates(
        submission, [lexical_distractor, semantically_relevant]
    )

    assert ranked[0][0].id == semantically_relevant.id


def test_semantic_candidate_rank_uses_exact_notice_title_when_body_is_ambiguous():
    model = SemanticComparisonModel()
    submission = SimpleNamespace(
        id=10,
        title="CIRCULAR: Revised End-Semester Examination Schedule",
        issuer="",
        action=None,
        redacted_text="Issued by: University\nSubject: examination timetable",
    )
    generic_timetable = SimpleNamespace(
        id=11,
        title="CIRCULAR – Time Table for End Semester Examination",
        issuer="",
        action=None,
        redacted_text="Issued by: University\nSubject: examination timetable",
    )
    exact_notice = SimpleNamespace(
        id=12,
        title="Circular Revised End Semester Examination Schedule",
        issuer="",
        action=None,
        redacted_text="A longer scanned body with additional details.",
    )
    query = (
        "CIRCULAR: Revised End-Semester Examination Schedule\n"
        "Issued by: University\nSubject: examination timetable"
    )
    generic_text = (
        "CIRCULAR – Time Table for End Semester Examination\n"
        "Issued by: University\nSubject: examination timetable"
    )
    exact_text = (
        "Circular Revised End Semester Examination Schedule\n"
        "A longer scanned body with additional details."
    )
    vectors = {
        query: np.asarray([1.0, 0.0], dtype=np.float32),
        generic_text: np.asarray([1.0, 0.0], dtype=np.float32),
        exact_text: np.asarray([0.0, 1.0], dtype=np.float32),
    }
    model.embed = lambda texts: np.stack([vectors[text] for text in texts])

    ranked = model.rank_candidates(submission, [generic_timetable, exact_notice])

    assert ranked[0][0].id == exact_notice.id


def test_semantic_candidate_rank_prefers_explicit_revision_of_matching_title():
    model = SemanticComparisonModel()
    title = (
        "Passing and Promotion Criteria to the subsequent year with acquire at least "
        "28 Credits under NEP UGCF-2022"
    )
    submission = SimpleNamespace(
        title=title,
        issuer="",
        action=None,
        redacted_text="The new promotion rule applies to students from 2024 onwards.",
    )
    original = SimpleNamespace(
        id=1,
        title=title,
        issuer="",
        action=None,
        redacted_text="The new promotion rule applies to students from 2024 onwards.",
    )
    revised = SimpleNamespace(
        id=2,
        title=f"Revised {title}",
        issuer="",
        action=None,
        redacted_text="The revised promotion rule applies from 2025 onwards instead.",
    )
    query = "The new promotion rule applies to students from 2024 onwards."
    query = f"{title}\n{query}"
    original_text = f"{title}\nThe new promotion rule applies to students from 2024 onwards."
    revised_text = f"Revised {title}\nThe revised promotion rule applies from 2025 onwards instead."
    vectors = {
        query: np.asarray([1.0, 0.0], dtype=np.float32),
        original_text: np.asarray([1.0, 0.0], dtype=np.float32),
        revised_text: np.asarray([0.0, 1.0], dtype=np.float32),
    }
    model.embed = lambda texts: np.stack([vectors[text] for text in texts])

    ranked = model.rank_candidates(submission, [original, revised])

    assert ranked[0][0].id == revised.id


def test_claim_extraction_drops_notice_boilerplate_and_preserves_academic_policy():
    claims = _content_sentences(
        "NOTIFICATION\n13-27 (Appendix-99)\nfor kind information to:\n"
        "The revised promotion rule shall now apply to students admitted in 2025-2026."
    )
    assert claims == [
        "The revised promotion rule shall now apply to students admitted in 2025-2026"
    ]

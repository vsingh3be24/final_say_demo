"""Comparison tests: the 22-vs-15 Sept case, confidence gating to unresolved +
review_case creation, and relation-edge persistence with rationale."""

from __future__ import annotations

from sqlalchemy import select

from finalsay.models import RelationEdge, ReviewCase, Notice
from finalsay.models_iface.comparison_model import (
    MockComparisonModel,
    get_comparison_model,
)
from finalsay.services import comparison


def test_default_comparison_model_is_mock():
    model = get_comparison_model()
    assert model.name == "mock"


def test_postponed_22_vs_15_sept_not_consistent():
    model = MockComparisonModel()
    label, confidence, rationale = model.classify(
        "The exam is on 15 Sept.",
        "The exam is postponed to 22 Sept.",
    )
    assert label in ("contradictory", "superseded"), (label, rationale)
    assert label != "consistent"
    assert 0.0 <= confidence <= 1.0
    assert rationale


def _make_notice(db, kind, text, institution_id=1, action=None, audience=None):
    notice = Notice(
        kind=kind,
        institution_id=institution_id,
        issuer="Registrar",
        redacted_text=text,
        action=action,
        audience=audience,
    )
    db.add(notice)
    db.flush()
    return notice


def test_low_confidence_yields_unresolved_and_review_case(db_session):
    official = _make_notice(
        db_session,
        "official",
        "Library will operate on holiday hours next week.",
    )
    submission = _make_notice(
        db_session,
        "submission",
        "Cafeteria menu features seasonal vegetables.",
    )
    db_session.commit()

    # Deterministic low-confidence model to trigger gating.
    class _LowConf(MockComparisonModel):
        def classify(self, premise, hypothesis):
            return ("consistent", 0.3, "weak signal")

    outcome = comparison.classify_submission(
        db_session, submission, model=_LowConf(), threshold=0.6
    )
    db_session.commit()

    assert outcome.label == "unresolved"
    assert outcome.gated is True
    assert outcome.review_case is not None

    # A review_case row exists and points at the edge.
    cases = db_session.scalars(select(ReviewCase)).all()
    assert len(cases) == 1
    assert cases[0].edge_id == outcome.edge.id
    assert cases[0].status == "open"

    # The edge is persisted with rationale/model/status.
    edge = db_session.get(RelationEdge, outcome.edge.id)
    assert edge.label == "unresolved"
    assert edge.status == "unresolved"
    assert edge.model == "mock"
    assert edge.rationale
    assert "threshold" in edge.rationale.lower()


def test_model_unresolved_rationale_does_not_claim_high_score_is_below_threshold(db_session):
    official = _make_notice(
        db_session, "official", "The exam is scheduled on 15 Sept for all students."
    )
    submission = _make_notice(
        db_session, "submission", "The exam arrangements are described in this circular."
    )
    db_session.commit()

    class _Neutral(MockComparisonModel):
        def classify(self, premise, hypothesis):
            return ("unresolved", 0.99, "The model ranked neutral highest.")

    outcome = comparison.classify_submission(
        db_session, submission, model=_Neutral(), threshold=0.2
    )

    assert outcome.label == "unresolved"
    assert outcome.gated is True
    assert "routed to reviewer" in outcome.edge.rationale.lower()
    assert "below the threshold" not in outcome.edge.rationale.lower()


def test_high_confidence_persists_edge_without_review_case(db_session):
    official = _make_notice(
        db_session,
        "official",
        "The exam is scheduled on 15 Sept for all students.",
        action="exam on 15 Sept",
    )
    submission = _make_notice(
        db_session,
        "submission",
        "The exam is postponed to 22 Sept for all students.",
        action="exam postponed to 22 Sept",
    )
    db_session.commit()

    outcome = comparison.classify_submission(db_session, submission, threshold=0.6)
    db_session.commit()

    assert outcome.candidate is not None
    assert outcome.candidate.id == official.id
    assert outcome.label in ("contradictory", "superseded")
    assert outcome.review_case is None

    edge = db_session.get(RelationEdge, outcome.edge.id)
    assert edge.src_notice_id == submission.id
    assert edge.dst_notice_id == official.id
    assert edge.status == "auto"
    assert edge.rationale


def test_no_candidate_routes_to_unresolved(db_session):
    # Submission with no official notices in its institution.
    submission = _make_notice(
        db_session, "submission", "Some standalone submission.", institution_id=99
    )
    db_session.commit()

    outcome = comparison.classify_submission(db_session, submission)
    db_session.commit()

    assert outcome.label == "unresolved"
    assert outcome.review_case is not None


def test_semantic_retrieval_uses_wrapped_subject_to_find_same_notice_listing(db_session):
    unrelated = _make_notice(
        db_session,
        "official",
        "LLB supplementary examination forms for May/June 2026.",
    )
    unrelated.title = (
        "Filing up Supplementary Examination form for students who appeared in VI Term LLB"
    )
    matching = _make_notice(
        db_session,
        "official",
        "Official listing: Last date for filling up examination forms for regular NCWEB & SOL, "
        "Semester I/III/V/VII/IX, Session December 2026-2027 is extended upto 15.11.2026.",
    )
    matching.title = (
        "Notification regarding Last date for Filling up Examination form for Regular, "
        "NCWEB & SOL students for Session December 2026-2027 is extended upto"
    )
    matching.extraction_quality = "unknown"
    submission = _make_notice(
        db_session,
        "submission",
        "‘Subject: Filling up Examination form for Regular, NCWEB & SOL students for\n"
        "‘Session December 2026-2027 Examination of date reg.\n\n"
        "The last date is extended upto 15.07.2028.",
    )

    class _ObservedSemanticRanker(MockComparisonModel):
        def rank_candidates(self, _submission, officials):
            # Reproduce the observed embedding order: the longer but unrelated
            # LLB PDF ranks above the correct short portal listing.
            return [
                (unrelated, 0.399, 0.833),
                (matching, 0.12, 0.54),
            ]

    ranked = comparison.retrieve_candidates(
        db_session, submission, model=_ObservedSemanticRanker()
    )

    assert ranked[0].notice.id == matching.id
    assert ranked[0].title_similarity >= 0.45
    assert submission.title.startswith("Filling up Examination form for Regular, NCWEB & SOL")


def test_same_topic_official_extension_precedes_older_original_schedule(db_session):
    from datetime import date

    original = _make_notice(
        db_session,
        "official",
        "The examination-form schedule applies to Regular, NCWEB and SOL students.",
    )
    original.title = (
        "Filling up Examination form for Regular, NCWEB & SOL students for "
        "Session December 2026-2027"
    )
    original.published_on = date(2026, 9, 1)

    update = _make_notice(
        db_session,
        "official",
        "Official listing: Last date for filling up examination forms is extended upto 15.11.2026.",
    )
    update.title = (
        "Notification regarding Last date for Filling up Examination form for Regular, "
        "NCWEB & SOL students for Session December 2026-2027 is extended upto"
    )
    update.published_on = date(2026, 10, 13)
    update.extraction_quality = "listing_only"

    submission = _make_notice(
        db_session,
        "submission",
        "Subject: Filling up Examination form for Regular, NCWEB & SOL students for "
        "Session December 2026-2027",
    )
    submission.title = "Filling up Examination form for Regular, NCWEB & SOL students for Session December 2026-2027"

    class _SemanticRanker(MockComparisonModel):
        def rank_candidates(self, _submission, _officials):
            # The original's longer PDF body gives it a slightly stronger
            # semantic rank, as occurred for the real DU records.
            return [(original, 0.7291, 0.88), (update, 0.7286, 0.83)]

    ranked = comparison.retrieve_candidates(
        db_session, submission, model=_SemanticRanker()
    )

    assert ranked[0].notice.id == update.id
    assert ranked[0].title_similarity >= 0.45
    assert ranked[1].notice.id == original.id


def test_listing_only_match_is_not_auto_classified_from_partial_evidence(db_session):
    listing = _make_notice(
        db_session,
        "official",
        "Official listing: Revised exam-form deadline for Regular NCWEB & SOL students.",
    )
    listing.title = "Revised exam-form deadline for Regular NCWEB & SOL students"
    listing.extraction_quality = "unknown"
    submission = _make_notice(
        db_session,
        "submission",
        "Subject: Revised exam-form deadline for Regular NCWEB & SOL students\n"
        "The last date is extended to 15 November 2026.",
    )
    submission.title = "Revised exam-form deadline for Regular NCWEB & SOL students"

    class _OverconfidentModel(MockComparisonModel):
        def rank_candidates(self, _submission, officials):
            return [(listing, 0.9, 0.95)]

        def classify(self, _premise, _hypothesis):
            return "extended", 0.96, "Extension cue detected."

    outcome = comparison.classify_submission(
        db_session, submission, model=_OverconfidentModel()
    )

    assert outcome.label == "unresolved"
    assert outcome.gated is True
    assert outcome.review_case is not None
    assert "portal listing" in outcome.edge.rationale.lower()


def test_conflicting_schedule_dates_override_high_confidence_consistent_label(db_session):
    official = _make_notice(
        db_session,
        "official",
        "The final deadline is 10 November 2026.\n"
        "Last date for filling the examination form is extended up to 15 November 2026.",
    )
    official.title = "Revised examination form deadline for December semester students"
    official.extraction_quality = "extracted"
    submission = _make_notice(
        db_session,
        "submission",
        "The final deadline is 10 November 2026.\n"
        "Last date for filling the examination form is extended up to 22 November 2026.",
    )
    submission.title = "Examination form deadline for December semester students"

    class _MisleadingSemanticModel(MockComparisonModel):
        def rank_candidates(self, _submission, _officials):
            return [(official, 0.99, 0.99)]

        def classify(self, _premise, _hypothesis):
            return "consistent", 0.99, "The shared notice scope is entailed."

    outcome = comparison.classify_submission(
        db_session, submission, model=_MisleadingSemanticModel()
    )

    assert outcome.label == "unresolved"
    assert outcome.gated is True
    assert outcome.review_case is not None
    assert "date safety check" in " ".join(outcome.evidence).lower()
    assert "dates conflict" in outcome.rationale.lower()


def test_unavailable_semantic_models_keep_candidate_and_route_to_review(db_session):
    from finalsay.models_iface.semantic_model import SemanticModelUnavailable

    official = _make_notice(
        db_session,
        "official",
        "Official listing: End-semester examination schedule for December 2026.",
    )
    official.title = "End-semester examination schedule December 2026"
    official.extraction_quality = "listing_only"
    submission = _make_notice(
        db_session,
        "submission",
        "Subject: End-semester examination schedule December 2026\n"
        "The exam has been rescheduled to 5 December 2026.",
    )
    submission.title = "End-semester examination schedule December 2026"

    class _UnavailableSemanticModel:
        name = "semantic-unavailable-test"

        def rank_candidates(self, _submission, _officials):
            raise SemanticModelUnavailable("Model files are offline.")

        def classify_with_evidence(self, _premise, _hypothesis):
            raise SemanticModelUnavailable("Model files are offline.")

    outcome = comparison.classify_submission(
        db_session, submission, model=_UnavailableSemanticModel()
    )

    assert outcome.candidate is not None
    assert outcome.candidate.id == official.id
    assert outcome.label == "unresolved"
    assert outcome.confidence == 0.0
    assert outcome.review_case is not None
    assert "could not be loaded" in outcome.rationale

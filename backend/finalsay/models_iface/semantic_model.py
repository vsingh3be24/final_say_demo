"""Local semantic retrieval and NLI for institutional notice comparisons.

The embedding encoder retrieves likely notice topics; the NLI cross-encoder
then reads the official notice as premise and the forwarded notice as
hypothesis. Both models are lazy-loaded and run locally on CPU.
"""

from __future__ import annotations

import re
import hashlib
import threading
from functools import lru_cache
from typing import TYPE_CHECKING

import numpy as np

from finalsay.config import get_settings
from finalsay.models_iface.comparison_model import ComparisonModel

if TYPE_CHECKING:
    from finalsay.models import Notice


class SemanticModelUnavailable(RuntimeError):
    """Raised when local model weights or dependencies cannot be loaded."""


_MODEL_LOCK = threading.RLock()
_EMBEDDING_CACHE_LOCK = threading.RLock()
_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3,
    "march": 3, "apr": 4, "april": 4, "may": 5, "jun": 6,
    "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_MONTH_PATTERN = "|".join(
    re.escape(month)
    for month in sorted(_MONTHS, key=len, reverse=True)
)
_SEMANTIC_RANK_WEIGHT = 0.8
_MAX_CONTENT_CLAIMS = 64
_DATE_RE = re.compile(
    rf"\b(?:(\d{{1,2}})\s+({_MONTH_PATTERN})|({_MONTH_PATTERN})\s+(\d{{1,2}}))"
    r"(?:,?\s+(\d{4}))?\b",
    re.IGNORECASE,
)
_NUMERIC_DMY_DATE_RE = re.compile(
    r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{4})(?!\d)"
)
_NUMERIC_YMD_DATE_RE = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
_SUPERSESSION_RE = re.compile(
    r"\b(postpon(?:ed|ement)?|reschedul(?:ed|ing)?|instead|now\s+(?:be\s+)?"
    r"(?:held|take place|conducted|applicable|apply)|new date|earlier date|"
    r"previously\s+scheduled|revised schedule|moved to|in place of|"
    r"supersed(?:e|es|ed|ing)|replac(?:e|es|ed|ing) by|amend(?:ed|ment))\b",
    re.IGNORECASE,
)
_SPECIAL_RELATIONS = (
    ("cancelled", re.compile(r"\bcancel(?:led|ed|lation)?\b", re.IGNORECASE)),
    ("corrected", re.compile(r"\b(correction|erratum|corrected|rectif)\w*\b", re.IGNORECASE)),
    ("extended", re.compile(r"\b(extend|extension)\w*\b", re.IGNORECASE)),
)
_BOILERPLATE_RE = re.compile(
    r"^(?:issued\s+by\b|from\s*:|subject\s*:|date\s*:|to all\b|"
    r"attention\s*:|for queries\b|contact (?:the )?(?:office|registrar)\b|"
    r"office of\b|notification$|circular$|reg\.?$|"
    r"ref(?:erence)?(?:\s+no\.?|\s*:)|no\.?\s*(?:exam\b|[a-z0-9/.-]{5,})|"
    r"exam\s+[a-z0-9]+\s*\(conduct\)\s*/|"
    r"(?:for kind information|copy to\b|dean\(s\)?\b|director\(s\)?\b|"
    r"head\(s\)\b|principal\(s\)\b|all branches\b|"
    r"deputy/assistant registrar\b|this (?:is issued|notification is issued)\b)|"
    r"\d{1,2}(?:st|nd|rd|th)?\s+[a-z]+,?\s+\d{4}$|"
    r"university of [a-z][a-z .'-]+(?: examination)?$)",
    re.IGNORECASE,
)


def _date_values(text: str) -> set[tuple[int, int, int | None]]:
    dates: set[tuple[int, int, int | None]] = set()
    for match in _DATE_RE.finditer(text):
        day = int(match.group(1) or match.group(4))
        month_name = (match.group(2) or match.group(3)).lower()
        month = _MONTHS.get(month_name)
        if month is not None and 1 <= day <= 31:
            dates.add((month, day, int(match.group(5)) if match.group(5) else None))
    for match in _NUMERIC_DMY_DATE_RE.finditer(text):
        day, month, year = (int(part) for part in match.groups())
        if 1 <= month <= 12 and 1 <= day <= 31:
            dates.add((month, day, year))
    for match in _NUMERIC_YMD_DATE_RE.finditer(text):
        year, month, day = (int(part) for part in match.groups())
        if 1 <= month <= 12 and 1 <= day <= 31:
            dates.add((month, day, year))
    return dates


@lru_cache(maxsize=1)
def _load_models(embedding_model: str, nli_model: str):
    try:
        from sentence_transformers import CrossEncoder, SentenceTransformer

        embedding = SentenceTransformer(embedding_model, device="cpu")
        nli = CrossEncoder(nli_model, device="cpu", max_length=512)
        return embedding, nli
    except Exception as exc:  # noqa: BLE001 - report cleanly through the API
        raise SemanticModelUnavailable(
            "The local semantic models could not be loaded. Run the ML dependency "
            "install and allow the model weights to download once."
        ) from exc


class SemanticComparisonModel(ComparisonModel):
    """Sentence embedding retrieval with a local three-way NLI cross-encoder.

    NLI softmax outputs are retained as comparative model scores. They are not
    presented as calibrated probabilities. A separately validated minimum
    score gate is applied by the comparison service.
    """

    name = "semantic-nli-deberta-v3-small"

    def __init__(self, embedding_model: str | None = None, nli_model: str | None = None):
        settings = get_settings()
        self.embedding_model = embedding_model or settings.semantic_embedding_model
        self.nli_model = nli_model or settings.semantic_nli_model
        self._pair_score_cache: dict[tuple[str, str], dict[str, float]] = {}
        self._official_embedding_cache: dict[str, np.ndarray] = {}

    def _models(self):
        with _MODEL_LOCK:
            return _load_models(self.embedding_model, self.nli_model)

    def embed(self, texts: list[str]) -> np.ndarray:
        encoder, _ = self._models()
        with _MODEL_LOCK:
            vectors = encoder.encode(
                texts,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        return np.asarray(vectors, dtype=np.float32)

    @staticmethod
    def _notice_text(notice: "Notice") -> str:
        return "\n".join(
            part
            for part in (
                notice.issuer,
                getattr(notice, "title", None),
                notice.action,
                notice.redacted_text,
                getattr(notice, "supplemental_extracted_text", ""),
            )
            if part
        )

    def rank_candidates(self, submission: "Notice", officials: list["Notice"]):
        if not officials:
            return []
        texts = [self._notice_text(n)[:5000] for n in officials]
        query = self._notice_text(submission)[:5000]
        query_vector = self.embed([query])[0]
        semantic_scores = self._official_vectors(officials, texts) @ query_vector
        query_tokens = _tokens(query)
        lexical_scores = np.asarray(
            [_jaccard(query_tokens, _tokens(text)) for text in texts], dtype=np.float32
        )
        semantic_rank = np.argsort(np.argsort(-semantic_scores))
        lexical_rank = np.argsort(np.argsort(-lexical_scores))
        denom = max(1, len(officials) - 1)
        results = [
            (
                notice,
                # Embedding rank is the primary retrieval signal. Lexical rank
                # breaks close semantic ties but must not let a long unrelated
                # calendar beat a direct exam-timetable match on token count.
                (
                    0.4
                    * (
                        _SEMANTIC_RANK_WEIGHT
                        * (1.0 - float(semantic_rank[i]) / denom)
                        + (1.0 - _SEMANTIC_RANK_WEIGHT)
                        * (1.0 - float(lexical_rank[i]) / denom)
                    )
                    + 0.6
                    * float(
                        bool(_normalized_title(getattr(submission, "title", None)))
                        and _normalized_title(getattr(submission, "title", None))
                        == _normalized_title(getattr(notice, "title", None))
                    )
                ),
                float(semantic_scores[i]),
            )
            for i, notice in enumerate(officials)
        ]
        ranked = sorted(
            results,
            key=lambda item: (
                _explicit_revision_title_match(
                    getattr(submission, "title", None), getattr(item[0], "title", None)
                ),
                item[1],
            ),
            reverse=True,
        )
        return ranked

    def _official_vectors(self, officials: list["Notice"], texts: list[str]) -> np.ndarray:
        keys = [hashlib.sha256(text.encode("utf-8")).hexdigest() for text in texts]
        with _EMBEDDING_CACHE_LOCK:
            missing = list(dict.fromkeys(key for key in keys if key not in self._official_embedding_cache))
            if missing:
                text_by_key = {key: text for key, text in zip(keys, texts)}
                encoded = self.embed([text_by_key[key] for key in missing])
                self._official_embedding_cache.update(zip(missing, encoded))
            return np.stack([self._official_embedding_cache[key] for key in keys])

    def _pair_probabilities(self, premise: str, hypothesis: str) -> dict[str, float]:
        key = (premise, hypothesis)
        cached = self._pair_score_cache.get(key)
        if cached is not None:
            return cached
        _embedding, cross_encoder = self._models()
        with _MODEL_LOCK:
            scores = cross_encoder.predict(
                [(premise[:5000], hypothesis[:5000])],
                apply_softmax=True,
                show_progress_bar=False,
            )[0]
        config = cross_encoder.model.config
        labels = {int(index): str(label).lower() for index, label in config.id2label.items()}
        result = {labels[i]: float(scores[i]) for i in range(len(scores))}
        self._pair_score_cache[key] = result
        if len(self._pair_score_cache) > 512:
            self._pair_score_cache.pop(next(iter(self._pair_score_cache)))
        return result

    def classify(self, premise: str, hypothesis: str):
        label, score, rationale, _evidence = self.classify_with_evidence(
            premise, hypothesis
        )
        return label, score, rationale

    def classify_with_evidence(self, premise: str, hypothesis: str):
        official_units = _content_sentences(premise)
        forwarded_units = _content_sentences(hypothesis)
        encoder, _cross_encoder = self._models()
        with _MODEL_LOCK:
            claim_vectors = encoder.encode(
                [*official_units, *forwarded_units],
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        official_vectors = claim_vectors[: len(official_units)]
        forwarded_vectors = claim_vectors[len(official_units) :]
        similarities = official_vectors @ forwarded_vectors.T
        # A single cosine-best pair can be a notice title or a fragment from a
        # wrapped PDF line. Score a small set of close claim pairs with NLI and
        # choose the strongest supported relationship, with cosine as a tie
        # breaker. This avoids letting an unrelated but lexically similar
        # header override a substantive matching claim.
        flat_order = np.argsort(similarities.reshape(-1))[::-1]
        pair_count = min(5, len(flat_order))
        evaluations = []
        for flat_index in flat_order[:pair_count]:
            official_index, forwarded_index = np.unravel_index(
                int(flat_index), similarities.shape
            )
            claim_similarity = float(similarities[official_index, forwarded_index])
            official_claim = official_units[official_index]
            forwarded_claim = forwarded_units[forwarded_index]
            pair_probabilities = self._pair_probabilities(
                official_claim, forwarded_claim
            )
            relation_strength = max(
                pair_probabilities.get("entailment", 0.0),
                pair_probabilities.get("contradiction", 0.0),
            )
            pair_score = 0.85 * relation_strength + 0.15 * claim_similarity
            evaluations.append(
                (pair_score, claim_similarity, official_claim, forwarded_claim, pair_probabilities)
            )
        _pair_score, claim_similarity, official_claim, forwarded_claim, probabilities = max(
            evaluations, key=lambda item: item[0]
        )
        contradiction = probabilities.get("contradiction", 0.0)
        entailment = probabilities.get("entailment", 0.0)
        neutral = probabilities.get("neutral", 0.0)
        top_nli = max(probabilities, key=probabilities.get)
        confidence = probabilities[top_nli]

        # Use dates in the matched claims, not every date in the notice. A
        # notice publication date must not be mistaken for the event date.
        official_dates = _date_values(official_claim)
        forwarded_dates = _date_values(forwarded_claim)
        replacement_dates = forwarded_dates - official_dates
        dates_conflict = bool(official_dates and replacement_dates)
        # Restrict revision cues to extracted substantive claims. A title such
        # as "Revised Schedule" is not evidence that the event date changed;
        # otherwise the UI can report a replacement when both dates match.
        matched_pair = f"{official_claim} {forwarded_claim}"
        update_language = bool(_SUPERSESSION_RE.search(matched_pair))
        official_revision = bool(
            _REVISION_TITLE_RE.search(premise) and _SUPERSESSION_RE.search(premise)
        )
        special_relation = next(
            (
                relation
                for relation, pattern in _SPECIAL_RELATIONS
                if pattern.search(matched_pair)
            ),
            None,
        )

        if claim_similarity < 0.30:
            label = "unresolved"
        elif top_nli == "entailment":
            label = "consistent"
        elif top_nli == "contradiction":
            if update_language and (dates_conflict or official_revision):
                label = "superseded"
            else:
                label = special_relation or "contradictory"
        else:
            label = "unresolved"

        evidence = [
            f"NLI evidence scores (not calibrated probabilities): entailment {entailment:.3f}, "
            f"contradiction {contradiction:.3f}, neutral {neutral:.3f}.",
        ]
        evidence.append(
            f"Best NLI-supported claim pair (embedding cosine {claim_similarity:.3f}): "
            f"official: ‘{official_claim}’ / forwarded: ‘{forwarded_claim}’."
        )
        if official_dates or forwarded_dates:
            evidence.append(
                "Dates found: official "
                f"{sorted(official_dates) if official_dates else 'none'}; forwarded "
                f"{sorted(forwarded_dates) if forwarded_dates else 'none'}."
            )
        if update_language and (dates_conflict or official_revision):
            evidence.append("The official notice contains explicit revision or replacement language.")
        rationale = (
            f"Local NLI comparison ranked {top_nli} highest; relationship mapped to {label}. "
            "Scores are model ranking evidence, not calibrated probabilities."
        )
        return label, confidence, rationale, evidence


@lru_cache(maxsize=1)
def get_semantic_model() -> SemanticComparisonModel:
    return SemanticComparisonModel()


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 2}


def _normalized_title(title: str | None) -> str:
    """Normalize title punctuation so copied notice headings match reliably."""
    return " ".join(re.findall(r"[a-z0-9]+", (title or "").casefold()))


_REVISION_TITLE_RE = re.compile(
    r"\b(?:revised|revision|corrigendum|correction|corrected|amended|amendment|updated|update)\b",
    re.IGNORECASE,
)


def _explicit_revision_title_match(submission_title: str | None, official_title: str | None) -> bool:
    """Prefer a clearly marked revised notice over its matching original title."""
    submission_base = _REVISION_TITLE_RE.sub(" ", submission_title or "")
    official_base = _REVISION_TITLE_RE.sub(" ", official_title or "")
    return bool(
        _normalized_title(submission_title)
        and _REVISION_TITLE_RE.search(official_title or "")
        and not _REVISION_TITLE_RE.search(submission_title or "")
        and _normalized_title(submission_base)
        and _normalized_title(submission_base) == _normalized_title(official_base)
    )


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _content_sentences(text: str) -> list[str]:
    """Strip notice headers/footers and return short substantive claim units."""
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    joined_lines: list[str] = []
    continuation_start = re.compile(
        r"^(?:and|or|but|which|that|who|when|where|will|would|should|could|"
        r"may|might|is|are|was|were|be|been|being|to|for|of|in|on|with|as|from|by)\b",
        re.IGNORECASE,
    )
    incomplete_end = re.compile(
        r"\b(?:and|or|but|for|to|of|in|on|with|as|from|by|which|that|the|a|an)$",
        re.IGNORECASE,
    )
    for line in lines:
        if not line:
            continue
        if joined_lines:
            previous = joined_lines[-1]
            wrap = (
                not re.search(r"[.!?;:]$", previous)
                and not _BOILERPLATE_RE.match(line)
                and (continuation_start.match(line) or incomplete_end.search(previous))
            )
            if wrap:
                joined_lines[-1] = f"{previous} {line}"
                continue
        joined_lines.append(line)
    normalized = "\n".join(joined_lines)
    units = []
    for chunk in re.split(r"\n|(?<=[!?])\s+|(?<=[.])\s+(?=[A-Z])", normalized):
        sentence = re.sub(r"\s+", " ", chunk).strip(" \t:;,.!?-")
        if not sentence or _BOILERPLATE_RE.match(sentence):
            continue
        if sentence.lower().startswith("deadline:"):
            sentence = "The deadline is " + sentence.split(":", 1)[1].strip()
        if len(sentence) >= 12 and len(_tokens(sentence)) >= 3 and sentence not in units:
            units.append(sentence[:500])
    return units[:_MAX_CONTENT_CLAIMS] or [re.sub(r"\s+", " ", text).strip()[:500]]

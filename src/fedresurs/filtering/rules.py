from __future__ import annotations

import hashlib
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fedresurs.constants import ClassificationSource, FilterDecision

_WS_RE = re.compile(r"\s+")


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    text = value.lower().replace("ё", "е")
    text = _WS_RE.sub(" ", text)
    return text.strip()


@dataclass(slots=True)
class Decision:
    decision: str
    score: float
    reasons: list[str] = field(default_factory=list)
    source: str = ClassificationSource.REVIEW


@dataclass(slots=True)
class FilterConfig:
    trade_types: list[str]
    include_all_public_offers: bool
    classifier_include: list[str]
    classifier_exclude: list[str]
    text_include: list[re.Pattern[str]]
    text_negative: list[re.Pattern[str]]
    scan_fields: list[str]
    min_matches: int
    text_overrides_classifier: bool
    public_offer_requires_keyword: bool
    version: str

    @classmethod
    def load(cls, path: str | Path) -> "FilterConfig":
        source = Path(path)
        raw = source.read_bytes()
        data = tomllib.loads(raw.decode("utf-8"))

        scope = data.get("scope", {})
        classifiers = data.get("classifiers", {})
        text = data.get("text", {})
        heuristics = data.get("heuristics", {})

        return cls(
            trade_types=[str(value) for value in scope.get("trade_types", [])],
            include_all_public_offers=bool(scope.get("include_all_public_offers", True)),
            classifier_include=[
                normalize_text(str(value)) for value in classifiers.get("include_names", [])
            ],
            classifier_exclude=[
                normalize_text(str(value)) for value in classifiers.get("exclude_names", [])
            ],
            text_include=[
                re.compile(str(pattern), re.IGNORECASE)
                for pattern in text.get("include_patterns", [])
            ],
            text_negative=[
                re.compile(str(pattern), re.IGNORECASE)
                for pattern in text.get("negative_patterns", [])
            ],
            scan_fields=[str(value) for value in text.get("scan_fields", [])],
            min_matches=int(text.get("min_matches", 1)),
            text_overrides_classifier=bool(heuristics.get("text_overrides_classifier", True)),
            public_offer_requires_keyword=bool(heuristics.get("public_offer_requires_keyword", False)),
            version=hashlib.sha256(raw).hexdigest()[:16],
        )


def decide_trade(trade_type_code: str | None, config: FilterConfig) -> Decision:
    if trade_type_code and trade_type_code in config.trade_types:
        return Decision(FilterDecision.INCLUDE, 1.0, [f"trade_type:{trade_type_code}"], ClassificationSource.CLASSIFIER)
    if config.include_all_public_offers and trade_type_code == "PublicOffer":
        return Decision(FilterDecision.INCLUDE, 1.0, ["public_offer"], ClassificationSource.CLASSIFIER)
    return Decision(
        FilterDecision.EXCLUDE,
        0.0,
        [f"trade_type_not_selected:{trade_type_code}"],
        ClassificationSource.REVIEW,
    )


def _classifier_hits(classifiers: list[str], config: FilterConfig) -> tuple[list[str], list[str]]:
    normalized = [normalize_text(value) for value in classifiers]
    include_hits: list[str] = []
    exclude_hits: list[str] = []
    for value in normalized:
        include_hits.extend(name for name in config.classifier_include if name and name in value)
        exclude_hits.extend(name for name in config.classifier_exclude if name and name in value)
    return include_hits, exclude_hits


def _text_hits(texts: list[str], config: FilterConfig) -> tuple[int, int]:
    joined = "\n".join(value for value in texts if value)
    include = sum(1 for pattern in config.text_include if pattern.search(joined))
    negative = sum(1 for pattern in config.text_negative if pattern.search(joined))
    return include, negative


def decide_lot(
    *,
    classifiers: list[str],
    texts: list[str],
    config: FilterConfig,
) -> Decision:
    classifier_include, classifier_exclude = _classifier_hits(classifiers, config)
    text_include, text_negative = _text_hits(texts, config)

    if text_negative and not classifier_include:
        return Decision(
            FilterDecision.EXCLUDE,
            0.0,
            ["negative_text"] + [f"classifier_exclude:{value}" for value in classifier_exclude],
            ClassificationSource.TEXT,
        )

    if classifier_include:
        return Decision(
            FilterDecision.INCLUDE,
            1.0,
            [f"classifier:{value}" for value in classifier_include],
            ClassificationSource.CLASSIFIER,
        )

    if text_include >= config.min_matches and config.text_overrides_classifier:
        return Decision(
            FilterDecision.INCLUDE,
            0.7,
            [f"text_matches:{text_include}"],
            ClassificationSource.TEXT,
        )

    if classifier_exclude:
        return Decision(
            FilterDecision.EXCLUDE,
            0.0,
            [f"classifier_exclude:{value}" for value in classifier_exclude],
            ClassificationSource.CLASSIFIER,
        )

    return Decision(FilterDecision.REVIEW, 0.3, ["no_signals"], ClassificationSource.REVIEW)


def lot_texts(normalized_lot: dict[str, Any]) -> list[str]:
    return [
        str(normalized_lot.get("trade_object_text") or ""),
        str(normalized_lot.get("sale_agreement") or ""),
        str(normalized_lot.get("payment_info") or ""),
    ]


def lot_classifiers(normalized_lot: dict[str, Any]) -> list[str]:
    import json

    raw = normalized_lot.get("classifiers_json")
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in value] if isinstance(value, list) else []

from __future__ import annotations

from pathlib import Path

from fedresurs.constants import FilterDecision
from fedresurs.filtering.rules import FilterConfig, decide_lot, decide_trade

ROOT = Path(__file__).resolve().parents[1]


def config() -> FilterConfig:
    return FilterConfig.load(ROOT / "config" / "filters.toml")


def test_public_offer_is_selected():
    decision = decide_trade("PublicOffer", config())
    assert decision.decision == FilterDecision.INCLUDE


def test_other_trade_types_are_excluded_by_default():
    decision = decide_trade("OpenAuction", config())
    assert decision.decision == FilterDecision.EXCLUDE


def test_lot_classifier_wins():
    decision = decide_lot(classifiers=["Права требования"], texts=[], config=config())
    assert decision.decision == FilterDecision.INCLUDE
    assert decision.source == "classifier"


def test_lot_text_overrides_empty_classifier():
    decision = decide_lot(
        classifiers=[],
        texts=["Продажа дебиторской задолженности ООО Ромашка"],
        config=config(),
    )
    assert decision.decision == FilterDecision.INCLUDE
    assert decision.source == "text"


def test_lot_negative_text_excludes_without_positive_classifier():
    decision = decide_lot(
        classifiers=[],
        texts=["Кредиторская задолженность перед поставщиками"],
        config=config(),
    )
    assert decision.decision == FilterDecision.EXCLUDE


def test_unclassified_lot_goes_to_review():
    decision = decide_lot(classifiers=["Оборудование"], texts=["Станок токарный"], config=config())
    assert decision.decision == FilterDecision.REVIEW

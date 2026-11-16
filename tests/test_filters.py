from __future__ import annotations

from dataclasses import replace
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


def test_unclassified_lot_is_excluded_by_default():
    decision = decide_lot(classifiers=["Оборудование"], texts=["Станок токарный"], config=config())
    assert decision.decision == FilterDecision.EXCLUDE
    assert decision.source == "unmatched"


def test_unclassified_lot_can_be_kept_for_review():
    config_with_review = replace(config(), unmatched_decision="review")
    decision = decide_lot(
        classifiers=["Оборудование"], texts=["Станок токарный"], config=config_with_review
    )
    assert decision.decision == FilterDecision.REVIEW


def test_construction_claim_is_not_treated_as_receivable():
    decision = decide_lot(
        classifiers=["Земельные участки"],
        texts=["право требования на получение результатов работ по строительству жилого дома"],
        config=config(),
    )
    assert decision.decision == FilterDecision.EXCLUDE


def test_claim_against_debtor_is_included_by_text():
    decision = decide_lot(
        classifiers=[],
        texts=["Право требования к ООО «Должник» в размере 1 000 000 руб."],
        config=config(),
    )
    assert decision.decision == FilterDecision.INCLUDE
    assert decision.source == "text"

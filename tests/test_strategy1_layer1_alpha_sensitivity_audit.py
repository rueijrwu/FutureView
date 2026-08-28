import pandas as pd
import pytest

from futureview.strategy1_layer1_alpha_sensitivity_audit import summarize_alpha


def _classified():
    return pd.DataFrame({"state": ["high", "neutral", "neutral", "low"]})


def test_alpha_zero_removes_neutral_weight_mass():
    r = summarize_alpha(_classified(), 0.0)
    assert r["total_weight_mass"] == 2.0
    assert r["neutral_weight_share"] == 0.0
    assert r["extreme_weight_share"] == 1.0


def test_alpha_half_weights_neutral_at_half_strength():
    r = summarize_alpha(_classified(), 0.5)
    assert r["neutral_weight_mass"] == 1.0
    assert r["total_weight_mass"] == 3.0
    assert r["neutral_weight_share"] == pytest.approx(1.0 / 3.0)


def test_alpha_one_recovers_unweighted_sample_mass():
    r = summarize_alpha(_classified(), 1.0)
    assert r["total_weight_mass"] == 4.0
    assert r["effective_mass_fraction_vs_alpha1"] == 1.0
    assert r["neutral_weight_share"] == 0.5


def test_alpha_must_be_unit_interval():
    with pytest.raises(ValueError):
        summarize_alpha(_classified(), -0.1)
    with pytest.raises(ValueError):
        summarize_alpha(_classified(), 1.1)

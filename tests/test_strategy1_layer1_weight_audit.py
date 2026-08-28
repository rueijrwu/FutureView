from futureview.strategy1_layer1_weight_audit import assign_weight, has_true_reversal


def test_true_reversal_allows_neutral_gap():
    assert has_true_reversal(["high", "neutral", "neutral", "low"])
    assert has_true_reversal(["low", "neutral", "high"])


def test_return_to_same_extreme_is_not_reversal():
    assert not has_true_reversal(["high", "neutral", "high"])
    assert not has_true_reversal(["low", "neutral", "neutral", "low"])


def test_weight_1_for_mostly_neutral_without_reversal():
    states = ["neutral"] * 60 + ["high"] * 30
    weight, coverage, reversal = assign_weight(states, extreme_threshold=0.5)
    assert weight == 1
    assert coverage == 30 / 90
    assert reversal is False


def test_weight_2_for_stable_extreme_majority():
    states = ["neutral"] * 40 + ["high"] * 50
    weight, coverage, reversal = assign_weight(states, extreme_threshold=0.5)
    assert weight == 2
    assert coverage == 50 / 90
    assert reversal is False


def test_weight_3_for_true_reversal_even_if_extreme_coverage_low():
    states = ["neutral"] * 80 + ["high"] * 5 + ["low"] * 5
    weight, coverage, reversal = assign_weight(states, extreme_threshold=0.5)
    assert weight == 3
    assert coverage == 10 / 90
    assert reversal is True

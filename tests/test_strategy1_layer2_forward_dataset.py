import pandas as pd

from futureview.strategy1_layer2_forward_dataset import build_forward_dataset


def test_forward_dataset_is_adjacent_and_nonoverlapping():
    classified = pd.DataFrame([
        {"start_index": 100, "end_index": 129, "past_C": 0.1, "past_Q": 0.02, "state": "high", "past_entries": 2},
    ])
    out = build_forward_dataset(classified, n_rows=200, model_history=90)
    r = out.iloc[0]
    assert r.input_start == 10
    assert r.input_end == 99
    assert r.target_start == 100
    assert r.target_end == 129
    assert r.input_end + 1 == r.target_start


def test_forward_dataset_drops_insufficient_history():
    classified = pd.DataFrame([
        {"start_index": 50, "end_index": 79, "past_C": 0.1, "past_Q": 0.02, "state": "high", "past_entries": 2},
    ])
    out = build_forward_dataset(classified, n_rows=200, model_history=90)
    assert out.empty


def test_forward_dataset_preserves_targets():
    classified = pd.DataFrame([
        {"start_index": 100, "end_index": 129, "past_C": -0.12, "past_Q": 0.03, "state": "low", "past_entries": 4},
    ])
    out = build_forward_dataset(classified, n_rows=200, model_history=90)
    r = out.iloc[0]
    assert r.C == -0.12
    assert r.Q == 0.03
    assert r.state == "low"
    assert r.entry_count == 4

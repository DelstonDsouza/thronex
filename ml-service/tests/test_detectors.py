import joblib
import numpy as np
import pytest

from app.detectors import (
    AnomalyModel,
    Deviation,
    classify_severity,
    confirm,
    find_episodes,
)
from app.synthetic import inject_scenario, normal_telemetry

SEGMENTS = [
    ("latency_spike", 40, 60),
    ("error_spike", 90, 110),
    ("cpu_spike", 140, 160),
    ("traffic_drop", 190, 210),
]


@pytest.fixture(scope="module")
def model():
    return AnomalyModel.train(normal_telemetry(400, seed=1), version="test")


@pytest.fixture(scope="module")
def labelled():
    X = normal_telemetry(240, seed=2)  # fresh data the model has never seen
    truth = np.zeros(240, dtype=bool)
    for scenario, start, end in SEGMENTS:
        X = inject_scenario(X, start, end, scenario)
        truth[start:end] = True
    return X, truth


def test_detection_precision_recall_and_false_positive_rate(model, labelled):
    X, truth = labelled
    results = model.score(X)
    pred = np.array(confirm(results, min_consecutive=3))

    tp = int((truth & pred).sum())
    fp = int((~truth & pred).sum())
    fn = int((truth & ~pred).sum())
    tn = int((~truth & ~pred).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn)
    fpr = fp / (fp + tn)

    # Isolation Forest on its own, for transparency (reported, not asserted).
    forest_pred = np.array([r.forest_outlier for r in results])
    forest_recall = (truth & forest_pred).sum() / truth.sum()
    forest_fpr = (~truth & forest_pred).sum() / (~truth).sum()
    print(
        f"\nSYNTHETIC DATA | combined: precision={precision:.2f} recall={recall:.2f} "
        f"FPR={fpr:.3f} | Isolation Forest alone: recall={forest_recall:.2f} FPR={forest_fpr:.3f}"
    )

    assert precision >= 0.9
    assert recall >= 0.8
    assert fpr <= 0.02


def test_detection_delay_is_within_three_points(model, labelled):
    X, _ = labelled
    pred = confirm(model.score(X), min_consecutive=3)
    for _, start, end in SEGMENTS:
        first = next(i for i in range(start, end) if pred[i])
        assert first - start <= 3


def test_single_spike_is_not_confirmed(model):
    X = normal_telemetry(60, seed=3)
    X[30, 2] = 2.5  # one bad point only
    assert not any(confirm(model.score(X), min_consecutive=3))


def test_small_deviation_below_operational_gate_is_ignored(model):
    X = normal_telemetry(60, seed=4)
    X[20:40, 2] = 0.2  # latency 120 ms -> 200 ms: noticeable, but not significant
    assert find_episodes(model.score(X), min_consecutive=3) == []


def test_high_value_that_is_normal_for_this_service_is_not_an_anomaly():
    train = normal_telemetry(400, seed=5)
    train[:, 3] = 0.8 + np.random.default_rng(5).normal(0, 0.02, 400)  # always busy
    busy_model = AnomalyModel.train(train, version="busy")
    test = normal_telemetry(100, seed=6)
    test[:, 3] = 0.8 + np.random.default_rng(6).normal(0, 0.02, 100)
    assert find_episodes(busy_model.score(test), min_consecutive=3) == []


def test_traffic_drop_is_reported_on_request_rate(model):
    X = inject_scenario(normal_telemetry(60, seed=7), 20, 40, "traffic_drop")
    results = model.score(X)
    episodes = find_episodes(results, 3)
    assert len(episodes) == 1
    assert results[episodes[0][0]].deviations[0].metric == "request_rate"


def test_training_requires_enough_samples():
    with pytest.raises(ValueError):
        AnomalyModel.train(normal_telemetry(10, seed=1), version="tiny")


def test_training_requires_correct_shape():
    with pytest.raises(ValueError):
        AnomalyModel.train(np.zeros((100, 3)), version="bad")


def test_model_serialization_roundtrip(model, labelled, tmp_path):
    X, _ = labelled
    path = tmp_path / "model.joblib"
    joblib.dump(model, path)
    loaded = joblib.load(path)
    before = [r.forest_score for r in model.score(X)]
    after = [r.forest_score for r in loaded.score(X)]
    assert np.allclose(before, after)
    assert loaded.version == "test"


def test_severity_uses_operational_thresholds():
    heavy_errors = [Deviation("error_rate", 0.6, 0.0, 30.0)]
    assert classify_severity(heavy_errors) == "critical"
    mild = [Deviation("cpu_cores", 0.2, 0.05, 5.0)]
    assert classify_severity(mild) == "low"
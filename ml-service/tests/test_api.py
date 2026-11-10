import numpy as np
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import prometheus as prom
from app.store import ModelStore
from app.synthetic import inject_scenario, normal_telemetry

BODY = {"service": "payment-service", "environment": "staging"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "store", ModelStore(tmp_path))
    return TestClient(main.app)


def _fake_fetch(X):
    def fetch(service, environment, start, end, step):
        return start + step * np.arange(len(X)), X

    return fetch


def _train(client, monkeypatch):
    monkeypatch.setattr(prom, "fetch_matrix", _fake_fetch(normal_telemetry(120, seed=1)))
    return client.post("/train", json={**BODY, "minutes": 30})


def test_train_returns_version_and_baseline(client, monkeypatch):
    r = _train(client, monkeypatch)
    assert r.status_code == 200
    body = r.json()
    assert body["samples"] == 120
    assert 9 < body["baseline"]["request_rate"]["baseline"] < 11


def test_train_refuses_idle_service(client, monkeypatch):
    X = normal_telemetry(120, seed=1)
    X[:, 0] = 0.2  # health checks only
    monkeypatch.setattr(prom, "fetch_matrix", _fake_fetch(X))
    assert client.post("/train", json=BODY).status_code == 422


def test_detect_without_model_returns_404(client):
    assert client.post("/detect", json=BODY).status_code == 404


def test_detect_finds_latency_spike(client, monkeypatch):
    _train(client, monkeypatch)
    X = inject_scenario(normal_telemetry(60, seed=2), 40, 60, "latency_spike")
    monkeypatch.setattr(prom, "fetch_matrix", _fake_fetch(X))
    r = client.post("/detect", json={**BODY, "application": "Shop", "minutes": 15})
    assert r.status_code == 200
    anomalies = r.json()["anomalies"]
    assert len(anomalies) == 1
    a = anomalies[0]
    assert a["metric_name"] == "latency_p95"
    assert a["severity"] == "high"
    assert a["ongoing"] is True
    assert a["application"] == "Shop"
    assert "not a confirmed root cause" in a["explanation"]


def test_detect_on_normal_data_finds_nothing(client, monkeypatch):
    _train(client, monkeypatch)
    monkeypatch.setattr(prom, "fetch_matrix", _fake_fetch(normal_telemetry(60, seed=2)))
    r = client.post("/detect", json=BODY)
    assert r.status_code == 200
    assert r.json()["anomalies"] == []


def test_service_name_is_validated(client):
    r = client.post("/train", json={"service": "../evil", "environment": "staging"})
    assert r.status_code == 422
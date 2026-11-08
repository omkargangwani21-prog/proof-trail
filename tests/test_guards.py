import pytest
from core.paypal_client import PayPalClient
from app import ingest_api


def test_synthetic_sample_never_reaches_paypal():
    with pytest.raises(RuntimeError):
        PayPalClient.provide_evidence(None, "SYN-dev-clean-00", [], dry_run=False)


def test_autopoll_is_opt_in(monkeypatch):
    monkeypatch.delenv("PT_AUTOPOLL", raising=False)
    assert ingest_api.autopoll_enabled() is False
    monkeypatch.setenv("PT_AUTOPOLL", "1")
    monkeypatch.setenv("PT_MODE", "live-sandbox")
    assert ingest_api.autopoll_enabled() is True
    monkeypatch.setenv("PT_MODE", "replay")
    assert ingest_api.autopoll_enabled() is False

import os, pytest, requests
from core.paypal_client import PayPalClient, NonSandboxURL


def test_refuses_live_url():
    with pytest.raises(NonSandboxURL):
        PayPalClient(base="https://api-m.paypal.com", client_id="x", secret="y")


def test_dry_run_makes_no_network_call(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network call in dry run")
    monkeypatch.setattr(requests, "request", boom)
    monkeypatch.setattr(requests, "post", boom)
    c = PayPalClient(client_id="x", secret="y")
    out = c.provide_evidence("PP-R-TEST", [{"evidence_type": "PROOF_OF_FULFILLMENT", "notes": "n"}])
    assert out["dry_run"] is True and out["payload"]["evidences"][0]["evidence_type"] == "PROOF_OF_FULFILLMENT"


@pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="live sandbox test")
def test_live_get_dispute():
    d = PayPalClient().get_dispute("PP-R-GEH-10196749")
    assert d["dispute_id"] == "PP-R-GEH-10196749"
    assert d["reason"] == "MERCHANDISE_OR_SERVICE_NOT_RECEIVED"

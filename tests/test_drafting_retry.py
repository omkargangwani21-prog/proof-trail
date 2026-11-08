import json
from core.db import connect
from core import drafting


def conn_with_dispute(tmp_path):
    c = connect(str(tmp_path / "t.db"))
    c.execute("INSERT INTO disputes(paypal_dispute_id,reason,status,stage,amount_minor,currency,raw_json,origin)"
              " VALUES('PP-1','X','WAITING_FOR_SELLER_RESPONSE','CHARGEBACK',100,'USD',?,'sandbox')",
              (json.dumps({"dispute_id": "PP-1"}),))
    c.commit()
    return c


OK = {"draft_result": {"ok": True}, "verification": {"decision": "CONTEST"}, "bundle": {}}
BAD = {"draft_result": {"ok": False}, "verification": None, "bundle": {}}


def test_retries_with_a_fresh_cache_key(tmp_path, monkeypatch):
    monkeypatch.setattr(drafting, "save_draft", lambda conn, b, v: 7)
    calls = []

    def run(conn, gw, d, model, cache_salt=""):
        calls.append(cache_salt)
        return BAD if len(calls) == 1 else OK

    r = drafting.draft_dispute(conn_with_dispute(tmp_path), "PP-1", gw=object(), run=run)
    assert r == {"ok": True, "draft_id": 7, "decision": "CONTEST"}
    assert calls[0] == "" and calls[1] and calls[1] != calls[0]


def test_gives_up_after_three_tries(tmp_path, monkeypatch):
    monkeypatch.setattr(drafting, "save_draft", lambda conn, b, v: 7)
    calls = []

    def run(conn, gw, d, model, cache_salt=""):
        calls.append(cache_salt)
        return BAD

    r = drafting.draft_dispute(conn_with_dispute(tmp_path), "PP-1", gw=object(), run=run)
    assert r["ok"] is False and len(calls) == drafting.TRIES == 3

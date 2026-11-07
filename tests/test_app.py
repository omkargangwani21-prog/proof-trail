import json
from fastapi.testclient import TestClient
from app.main import due_label, draft_state, reason_label


def make(tmp_path, monkeypatch):
    monkeypatch.setenv("PT_DB", str(tmp_path / "t.db"))
    from app.main import app
    return TestClient(app)


def seed_dispute(conn, dispute_id="PP-TEST-1"):
    from core.case_builder import upsert_dispute
    dispute = json.load(open("dispute_sample.json", encoding="utf-8"))
    dispute["dispute_id"] = dispute_id
    upsert_dispute(conn, dispute)
    from core.submitter import EXTRA_SCHEMA
    conn.executescript(EXTRA_SCHEMA)
    conn.commit()
    return dispute


def test_empty_queue_and_sandbox_and_model_spend_copy(tmp_path, monkeypatch):
    response = make(tmp_path, monkeypatch).get("/disputes")
    assert response.status_code == 200
    assert "No disputes yet" in response.text
    assert "Sandbox" in response.text
    assert "Nothing here touches live PayPal" in response.text
    assert "Model spend" in response.text
    assert "Language-model credits used against the configured hard cap" in response.text


def test_queue_lists_a_dispute_in_plain_words(tmp_path, monkeypatch):
    client = make(tmp_path, monkeypatch)
    from core.db import connect
    conn = connect(str(tmp_path / "t.db"))
    dispute = seed_dispute(conn)
    conn.close()
    response = client.get("/disputes")
    assert response.status_code == 200
    assert dispute["dispute_id"] in response.text
    assert "No draft" in response.text
    assert "Item not received" in response.text
    assert client.get("/disputes/" + dispute["dispute_id"]).status_code == 200
    assert client.get("/disputes/NOPE").status_code == 404


def test_submitted_drafts_are_never_in_needs_action_group(tmp_path, monkeypatch):
    client = make(tmp_path, monkeypatch)
    from core.db import connect
    conn = connect(str(tmp_path / "t.db"))
    dispute = seed_dispute(conn)
    conn.execute("INSERT INTO draft_evidence(case_id,paypal_dispute_id,decision,payload_json,verification_json,status,created_at) "
                 "VALUES(1,?,?,?,?,?,?)", (dispute["dispute_id"], "CONTEST", "[]", "{}", "SUBMITTED_DRY_RUN", "2026-11-07"))
    conn.commit()
    conn.close()
    response = client.get("/disputes")
    assert response.status_code == 200
    assert "Dry run complete" in response.text
    assert "Answered or under review" in response.text
    assert "Needs action" not in response.text
    assert '<tr class="needs-action">' not in response.text


def test_workspace_reads_verification_and_exact_source_record(tmp_path, monkeypatch):
    client = make(tmp_path, monkeypatch)
    from core.db import connect
    conn = connect(str(tmp_path / "t.db"))
    dispute = seed_dispute(conn)
    did = conn.execute("SELECT id FROM disputes WHERE paypal_dispute_id=?", (dispute["dispute_id"],)).fetchone()[0]
    case_id = conn.execute("INSERT INTO cases(dispute_id,built_at,bundle_hash) VALUES(?,?,?)", (did, "2026-11-07", "hash")).lastrowid
    record = {"carrier": "UPS", "tracking_number": "1ZTEST000000000001", "shipped_at": "2026-11-05T12:00:00Z",
              "delivered_at": "2026-11-06T12:00:00Z", "delivery_status": "DELIVERED"}
    conn.execute("INSERT INTO source_records(record_id,case_id,kind,content_json,untrusted) VALUES(?,?,?,?,0)",
                 ("shp:123", case_id, "shipment", json.dumps(record)))
    verification = {"decision": "CONTEST", "recommendation": "Contest with verified claims.", "missing_evidence": [],
                    "l3_ran": True, "consistency_issues": [], "claims": [{
                        "claim": {"claim_id": "claim-1", "text": "The carrier marked delivery.", "type": "fulfillment",
                                  "source_refs": [{"record_id": "shp:123", "field": "delivery_status", "quoted_value": "DELIVERED"}],
                                  "confidence": 0.9}, "verdict": "VERIFIED", "reasons": []}]}
    payload = [{"evidence_type": "PROOF_OF_FULFILLMENT", "evidence_info": {"tracking_info": [{
        "carrier_name": "UPS", "tracking_number": "1ZTEST000000000001"}]}, "notes": "The carrier marked delivery."}]
    draft_id = conn.execute("INSERT INTO draft_evidence(case_id,paypal_dispute_id,decision,payload_json,verification_json,status,created_at) "
                            "VALUES(?,?,?,?,?,?,?)", (case_id, dispute["dispute_id"], "CONTEST", json.dumps(payload),
                                                      json.dumps(verification), "VERIFIED", "2026-11-07")).lastrowid
    conn.commit()
    conn.close()
    response = client.get("/disputes/" + dispute["dispute_id"])
    assert response.status_code == 200
    assert "The carrier marked delivery." in response.text
    assert "shp:123" in response.text
    assert "delivery_status" in response.text
    assert "DELIVERED" in response.text
    assert 'id="confirmDialog"' in response.text
    assert f'name="draft_id" value="{draft_id}"' in response.text


def test_dry_run_requires_acknowledgement_and_uses_existing_submitter(tmp_path, monkeypatch):
    client = make(tmp_path, monkeypatch)
    from core.db import connect
    conn = connect(str(tmp_path / "t.db"))
    dispute = seed_dispute(conn)
    payload = [{"evidence_type": "PROOF_OF_FULFILLMENT", "evidence_info": {"tracking_info": []}, "notes": "Verified sample claim."}]
    verification = {"decision": "CONTEST", "recommendation": "Contest.", "missing_evidence": [], "l3_ran": True,
                    "claims": [], "consistency_issues": []}
    draft_id = conn.execute("INSERT INTO draft_evidence(case_id,paypal_dispute_id,decision,payload_json,verification_json,status,created_at) "
                            "VALUES(1,?,?,?,?,?,?)", (dispute["dispute_id"], "CONTEST", json.dumps(payload),
                                                       json.dumps(verification), "VERIFIED", "2026-11-07")).lastrowid
    conn.commit()
    conn.close()
    rejected = client.post(f"/disputes/{dispute['dispute_id']}/submit", data={"draft_id": draft_id}, follow_redirects=False)
    assert rejected.status_code == 303
    conn = connect(str(tmp_path / "t.db"))
    assert conn.execute("SELECT status FROM draft_evidence WHERE id=?", (draft_id,)).fetchone()[0] == "VERIFIED"
    conn.close()
    submitted = client.post(f"/disputes/{dispute['dispute_id']}/submit",
                            data={"draft_id": draft_id, "approved": "yes"}, follow_redirects=False)
    assert submitted.status_code == 303
    page = client.get(submitted.headers["location"])
    assert "Dry run complete. No request was sent to PayPal." in page.text
    conn = connect(str(tmp_path / "t.db"))
    assert conn.execute("SELECT status FROM draft_evidence WHERE id=?", (draft_id,)).fetchone()[0] == "SUBMITTED_DRY_RUN"
    assert conn.execute("SELECT mode FROM submissions WHERE draft_id=?", (draft_id,)).fetchone()[0] == "dry_run"
    conn.close()


def test_only_built_screens_exist(tmp_path, monkeypatch):
    client = make(tmp_path, monkeypatch)
    for path in ("trail", "agent", "eval", "settings"):
        assert client.get("/" + path).status_code == 404
    assert "Not built yet" not in client.get("/disputes").text
    assert client.get("/", follow_redirects=False).status_code in (302, 307)


def test_due_labels():
    import datetime
    now = datetime.datetime(2026, 11, 7, tzinfo=datetime.timezone.utc)
    assert due_label(None, now) == ("Due date not provided", "neutral")
    assert due_label("2026-11-06T00:00:00Z", now) == ("Overdue", "removed")
    assert due_label("2026-11-09T12:00:00Z", now) == ("Due in 2d", "review")
    assert due_label("2026-11-20T00:00:00Z", now) == ("Due in 13d", "neutral")
    assert due_label("2026-11-07T05:00:00Z", now) == ("Due in 5h", "review")


def test_labels():
    assert draft_state(None)[0] == "No draft"
    assert draft_state({"status": "ABSTAIN"})[0] == "Recommend accepting"
    assert reason_label("MERCHANDISE_OR_SERVICE_NOT_RECEIVED") == "Item not received"
    assert reason_label("SOMETHING_NEW") == "Something new"





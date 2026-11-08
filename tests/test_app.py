import json
import pytest
from fastapi.testclient import TestClient
from app.main import common, display_ts, due_label, draft_state, paypal_status_label, pluralize, reason_label, source_bundle_partial, trail_status_text


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


def test_empty_queue_and_sandbox_copy(tmp_path, monkeypatch):
    response = make(tmp_path, monkeypatch).get("/disputes")
    assert response.status_code == 200
    assert "No disputes yet" in response.text
    assert "Sandbox" in response.text
    assert "Nothing here touches live PayPal" in response.text


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


def test_no_draft_workspace_offers_one_post_draft_action(tmp_path, monkeypatch):
    client = make(tmp_path, monkeypatch)
    from core.db import connect
    conn = connect(str(tmp_path / "t.db"))
    dispute = seed_dispute(conn)
    conn.close()
    page = client.get("/disputes/" + dispute["dispute_id"])
    assert page.status_code == 200
    assert 'action="/disputes/PP-TEST-1/draft"' in page.text
    assert page.text.count('class="draft-submit-form" data-draft-form') == 1
    assert "Draft evidence" in page.text
    assert "Asks the model to draft evidence from the records. Nothing is sent to PayPal." in page.text
    assert "Not checked until a draft exists." in page.text
    assert "No required evidence is missing." not in page.text
    assert '<ul class="check-list check-list--ok">' not in page.text
    assert "form.dataset.submitting==='true'" in page.text
    assert "button.disabled=true" in page.text
    assert "double" not in page.text.lower()


def test_draft_router_uses_fake_draft_once_and_redirects(tmp_path, monkeypatch):
    client = make(tmp_path, monkeypatch)
    from core.db import connect
    conn = connect(str(tmp_path / "t.db"))
    seed_dispute(conn)
    conn.close()
    calls = []
    def fake_draft(pid):
        calls.append(pid)
        return {"ok": True}
    monkeypatch.setattr("app.draft_api._draft", fake_draft)
    response = client.post("/disputes/PP-TEST-1/draft", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/disputes/PP-TEST-1?draft=ok"
    assert calls == ["PP-TEST-1"]
    page = client.get(response.headers["location"])
    assert 'role="status"' in page.text
    assert "Draft ready. Review each claim before approving." in page.text


def test_draft_router_error_and_queue_messages_are_announced(tmp_path, monkeypatch):
    client = make(tmp_path, monkeypatch)
    from core import drafting
    from core.db import connect
    conn = connect(str(tmp_path / "t.db"))
    dispute = seed_dispute(conn)
    conn.close()
    def not_ready(_pid):
        raise drafting.NotDraftable()
    monkeypatch.setattr("app.draft_api._draft", not_ready)
    response = client.post(f"/disputes/{dispute['dispute_id']}/draft", follow_redirects=False)
    assert response.headers["location"].endswith("?draft=notready")
    page = client.get(f"/disputes/{dispute['dispute_id']}?draft=notready")
    assert 'class="message message--error" role="alert"' in page.text
    assert "This dispute is not waiting for your response." in page.text
    assert "Drafting is paused: the model usage limit has been reached." in client.get(f"/disputes/{dispute['dispute_id']}?draft=budget").text
    queue = client.get("/disputes?draft=invalid")
    assert 'class="message message--error" role="alert"' in queue.text
    assert "That dispute ID is not valid." in queue.text


def test_failed_and_unexpected_draft_results_are_announced_as_errors(tmp_path, monkeypatch):
    client = make(tmp_path, monkeypatch)
    from core.db import connect
    conn = connect(str(tmp_path / "t.db"))
    seed_dispute(conn)
    conn.close()
    monkeypatch.setattr("app.draft_api._draft", lambda _pid: {"ok": False})
    failed = client.post("/disputes/PP-TEST-1/draft", follow_redirects=False)
    page = client.get(failed.headers["location"])
    assert "The model did not return a usable draft. Nothing was saved. Try again." in page.text
    assert 'class="message message--error" role="alert"' in page.text

    def raises(_pid):
        raise RuntimeError("private implementation detail")
    monkeypatch.setattr("app.draft_api._draft", raises)
    unexpected = client.post("/disputes/PP-TEST-1/draft", follow_redirects=False)
    page = client.get(unexpected.headers["location"])
    assert "Something went wrong while drafting. Nothing was saved." in page.text
    assert "private implementation detail" not in page.text
    assert 'class="message message--error" role="alert"' in page.text

    not_found = client.get("/disputes?draft=notfound")
    assert "The dispute was not found." in not_found.text
    assert 'class="message message--error" role="alert"' in not_found.text


def test_saved_draft_has_confirmed_draft_again_action(tmp_path, monkeypatch):
    client = make(tmp_path, monkeypatch)
    from core.db import connect
    conn = connect(str(tmp_path / "t.db"))
    dispute = seed_dispute(conn)
    conn.execute("INSERT INTO draft_evidence(case_id,paypal_dispute_id,decision,payload_json,verification_json,status,created_at) "
                 "VALUES(1,?,?,?,?,?,?)", (dispute["dispute_id"], "CONTEST", "[]", "{}", "VERIFIED", "2026-11-08"))
    conn.commit()
    conn.close()
    page = client.get("/disputes/" + dispute["dispute_id"])
    assert "Draft again" in page.text
    assert 'id="redraftDialog"' in page.text
    assert "This creates an additional draft for review. Nothing is sent to PayPal." in page.text
    assert 'method="post" action="/disputes/PP-TEST-1/draft"' in page.text
    assert "redraft.showModal()" in page.text
    assert "data-close-redraft" in page.text


def test_abstain_is_a_legitimate_no_contest_outcome_and_keeps_paypal_request_note(tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.FIXTURES_ENABLED", True)
    page = make(tmp_path, monkeypatch).get("/disputes/PP-DEV-1002?fixture=abstain")
    assert page.status_code == 200
    assert "No contest recommended" in page.text
    assert "Missing evidence: Proof of fulfillment." in page.text
    assert "PayPal also asked for: Proof of refund, Other. Not provided." in page.text
    assert "We recommend accepting this claim" not in page.text
    assert 'class="message message--error"' not in page.text


def test_ui_does_not_render_spend_figures(tmp_path, monkeypatch):
    page = make(tmp_path, monkeypatch).get("/eval")
    assert "Cost per run" not in page.text
    assert "USD per run" not in page.text
    assert "Model spend" not in page.text


@pytest.mark.parametrize("status", ["SUBMITTED", "SUBMITTED_DRY_RUN"])
def test_submitted_drafts_are_never_in_needs_action_group(tmp_path, monkeypatch, status):
    client = make(tmp_path, monkeypatch)
    from core.db import connect
    conn = connect(str(tmp_path / "t.db"))
    dispute = seed_dispute(conn)
    conn.execute("INSERT INTO draft_evidence(case_id,paypal_dispute_id,decision,payload_json,verification_json,status,created_at) "
                 "VALUES(1,?,?,?,?,?,?)", (dispute["dispute_id"], "CONTEST", "[]", "{}", status, "2026-11-07"))
    conn.commit()
    conn.close()
    response = client.get("/disputes")
    assert response.status_code == 200
    assert ("Dry run complete" if status == "SUBMITTED_DRY_RUN" else "Submitted to sandbox") in response.text
    assert "Answered or under review" in response.text
    assert "Needs action" not in response.text
    assert '<tr class="needs-action">' not in response.text
    assert 'data-label="Respond by"><div class="deadline"><span class="muted">—</span>' in response.text


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
    assert "Source record · 1" in response.text
    assert "shp:123" in response.text
    assert "delivery_status" in response.text
    assert "DELIVERED" in response.text
    assert 'id="confirmDialog"' in response.text
    assert 'id="approveCheck" required' in response.text
    assert 'id="submitButton" disabled' in response.text
    assert '<dialog class="confirm-dialog" id="confirmDialog"' in response.text
    assert "confirm.showModal()" in response.text
    assert "confirm?.close()" in response.text
    assert "confirm?.addEventListener('keydown'" in response.text
    assert "event.preventDefault();first.focus()" in response.text
    assert "event.preventDefault();last.focus()" in response.text
    assert "ack?.addEventListener('change'" in response.text
    assert "submitButton.disabled=!ack.checked" in response.text
    assert "data-close-confirm" in response.text
    assert "Review and submit (dry run)" in response.text
    assert '<strong>1</strong> verified claim used' in response.text
    assert '<strong>0</strong> claims excluded' in response.text
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


def test_built_screens_are_routed_and_future_pages_stay_hidden(tmp_path, monkeypatch):
    client = make(tmp_path, monkeypatch)
    assert client.get("/trail").status_code == 200
    assert client.get("/eval").status_code == 200
    assert client.get("/settings").status_code == 200
    assert client.get("/agent").status_code == 404
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


def test_partial_state_only_marks_missing_source_records():
    records = {"ord:2": {"kind": "order"}, "shp:2": {"kind": "shipment"}}
    verification = {"claims": [{"claim": {"source_refs": [
        {"record_id": "ord:2", "field": "amount", "quoted_value": "49.00 USD"},
        {"record_id": "shp:2", "field": "carrier", "quoted_value": "UPS"},
    ]}}]}
    assert not source_bundle_partial(records, verification)
    verification["claims"][0]["claim"]["source_refs"].append({"record_id": "shp:missing"})
    assert source_bundle_partial(records, verification)


def test_pluralization_and_single_event_chain_label():
    assert pluralize(1, "dispute") == "dispute"
    assert pluralize(0, "dispute") == "disputes"
    assert pluralize(2, "source record") == "source records"
    assert trail_status_text({"status": "VERIFIED", "events": 1}) == "Chain intact, 1 event"
    assert trail_status_text({"status": "VERIFIED", "events": 3}) == "Chain intact, 3 events"


def test_single_dispute_queue_uses_singular_count_copy(tmp_path, monkeypatch):
    client = make(tmp_path, monkeypatch)
    from core.db import connect
    conn = connect(str(tmp_path / "t.db"))
    dispute = seed_dispute(conn)
    conn.close()
    page = client.get("/disputes")
    assert "1 dispute on file" in page.text
    assert "1 needs a response" in page.text
    assert "1 need a response" not in page.text
    assert dispute["dispute_id"] in page.text


def test_workspace_citations_resolve_against_saved_case_records_without_false_partial_state(tmp_path, monkeypatch):
    client = make(tmp_path, monkeypatch)
    from core.db import connect
    conn = connect(str(tmp_path / "t.db"))
    dispute = seed_dispute(conn)
    dispute_pk = conn.execute("SELECT id FROM disputes WHERE paypal_dispute_id=?", (dispute["dispute_id"],)).fetchone()[0]
    case_id = conn.execute("INSERT INTO cases(dispute_id,built_at,bundle_hash) VALUES(?,?,?)",
                           (dispute_pk, "2026-11-08", "consistent-bundle")).lastrowid
    source_rows = [
        ("ord:2", "order", {"amount": "49.00 USD", "status": "COMPLETED"}),
        ("shp:2", "shipment", {"carrier": "UPS", "tracking_number": "TRACK-2"}),
    ]
    for record_id, kind, content in source_rows:
        conn.execute("INSERT INTO source_records(record_id,case_id,kind,content_json,untrusted) VALUES(?,?,?,?,0)",
                     (record_id, case_id, kind, json.dumps(content)))
    verification = {"decision": "CONTEST", "missing_evidence": [], "claims": [
        {"claim": {"claim_id": "claim-1", "text": "The order is complete.", "source_refs": [
            {"record_id": "ord:2", "field": "status", "quoted_value": "COMPLETED"}]},
         "verdict": "VERIFIED", "reasons": []},
        {"claim": {"claim_id": "claim-2", "text": "UPS carried the parcel.", "source_refs": [
            {"record_id": "shp:2", "field": "carrier", "quoted_value": "UPS"}]},
         "verdict": "VERIFIED", "reasons": []},
    ]}
    conn.execute("INSERT INTO draft_evidence(case_id,paypal_dispute_id,decision,payload_json,verification_json,status,created_at) "
                 "VALUES(?,?,?,?,?,?,?)", (case_id, dispute["dispute_id"], "CONTEST", "[]",
                                           json.dumps(verification), "VERIFIED", "2026-11-08"))
    conn.commit()
    conn.close()
    page = client.get(f"/disputes/{dispute['dispute_id']}")
    assert page.status_code == 200
    assert "Source records · 2" in page.text
    assert "COMPLETED" in page.text and "UPS" in page.text
    assert "One or more source records are unavailable" not in page.text
    assert 'class="message message--partial"' not in page.text






def test_paypal_status_and_timestamp_display_helpers():
    assert paypal_status_label("WAITING_FOR_SELLER_RESPONSE") == "Waiting for your response"
    assert paypal_status_label("UNDER_REVIEW") == "Under PayPal review"
    assert paypal_status_label("UNRECOGNIZED_ENUM") == "Other PayPal status"
    assert display_ts("2026-11-09T11:38:22.456789+00:00") == "Nov 9, 11:38 UTC"
    assert display_ts("2026-11-09T17:08:22.456789+05:30") == "Nov 9, 11:38 UTC"
    assert display_ts(None) == "Date not provided"


def test_submit_action_label_follows_mode(monkeypatch):
    monkeypatch.setenv("PT_MODE", "live-sandbox")
    monkeypatch.setenv("PT_SUBMIT_MODE", "dry-run")
    context = common(None, "disputes")
    assert context["action_label"] == "Review and submit (dry run)"
    monkeypatch.setenv("PT_SUBMIT_MODE", "sandbox-submit")
    context = common(None, "disputes")
    assert context["action_label"] == "Review and submit to PayPal sandbox"
    monkeypatch.setenv("PT_MODE", "replay")
    context = common(None, "disputes")
    assert context["action_label"] == "Review and submit (dry run)"



def test_trail_empty_state_and_dev_fixture(tmp_path, monkeypatch):
    client = make(tmp_path, monkeypatch)
    empty = client.get("/trail")
    assert empty.status_code == 200
    assert "No order trails yet" in empty.text
    assert "Tamper-evident, not tamper-proof." in empty.text
    monkeypatch.setattr("app.main.FIXTURES_ENABLED", True)
    listing = client.get("/trail?fixture=sample")
    assert listing.status_code == 200 and "DEMO-TRAIL-001" in listing.text
    sample = client.get("/trail?fixture=sample&order_ref=DEMO-TRAIL-001")
    assert sample.status_code == 200
    assert "DEMO-TRAIL-001" in sample.text
    assert "Chain intact, 3 events" in sample.text
    assert "Intent recorded by agent" in sample.text and "Cart recorded" in sample.text and "Payment recorded" in sample.text
    assert "Shopper text recorded by the agent; not independently verified." in sample.text
    assert "Shopper asked the agent" in sample.text
    assert "Buyer approved" not in sample.text and "does not make shopper text true" in sample.text
    assert "Run tamper test" in sample.text
    assert "prooftrail-ui-sample-key" not in sample.text


def test_trail_tamper_test_only_modifies_a_copy(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAIL_HMAC_KEY", "trail-test-secret-do-not-display")
    client = make(tmp_path, monkeypatch)
    from core.db import connect
    from core import trail as trail_module
    conn = connect(str(tmp_path / "t.db"))
    for event, summary in (("intent", "Shopper asked the agent: find a book"), ("cart", "One book in cart"),
                           ("payment", "Sandbox payment completed")):
        trail_module.record(conn, "ORDER-TRAIL-1", event, summary, key="trail-test-secret-do-not-display",
                            at="2026-11-06T09:00:00+00:00")
    original = trail_module.load_events(conn, "ORDER-TRAIL-1")
    original_hashes = [event["hash"] for event in original]
    conn.close()
    response = client.post("/trail/ORDER-TRAIL-1/tamper")
    assert response.status_code == 200
    assert "Chain altered at event 2: event content was changed" in response.text
    assert "Simulated on a copy. Stored data is unchanged." in response.text
    assert "Stored chain check: Chain intact, 3 events." in response.text
    assert "trail-test-secret-do-not-display" not in response.text
    conn = connect(str(tmp_path / "t.db"))
    after = trail_module.load_events(conn, "ORDER-TRAIL-1")
    assert [event["hash"] for event in after] == original_hashes
    assert trail_module.verify_chain(conn, "ORDER-TRAIL-1", key="trail-test-secret-do-not-display")["status"] == "VERIFIED"
    conn.close()


def test_eval_missing_summary_state_includes_generation_command(tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.EVAL_RESULTS_DIR", tmp_path / "results")
    response = make(tmp_path, monkeypatch).get("/eval")
    assert response.status_code == 200
    assert "No evaluation summary yet" in response.text
    assert "python -m eval.summary" in response.text


def test_eval_development_fixture_renders_summary_shape(tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.FIXTURES_ENABLED", True)
    monkeypatch.setattr("app.main.EVAL_RESULTS_DIR", tmp_path / "results")
    response = make(tmp_path, monkeypatch).get("/eval?fixture=sample")
    assert response.status_code == 200
    assert "Development sample" in response.text
    assert "Synthetic data. 95% intervals are case-level cluster bootstrap." in response.text
    assert "Runs with an unsupported claim" in response.text
    assert "95% interval" in response.text
    assert "Conflicting records" in response.text
    assert "Verified-system failures" in response.text
    assert "sample-commit" in response.text
    assert "Nov 7, 10:00 UTC" in response.text
    assert "win rate" not in response.text.lower()


def test_settings_shows_only_key_presence_not_secret_values(tmp_path, monkeypatch):
    secret_values = {
        "PAYPAL_CLIENT_ID": "paypal-client-id-SENTINEL-7351",
        "PAYPAL_CLIENT_SECRET": "paypal-client-secret-SENTINEL-9418",
        "NEBIUS_API_KEY": "nebius-secret-SENTINEL-2816",
        "TRAIL_HMAC_KEY": "trail-hmac-SENTINEL-6402",
        "PAYPAL_WEBHOOK_ID": "webhook-id-SENTINEL-5183",
    }
    for name, value in secret_values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("PAYPAL_BASE", "https://api-m.sandbox.paypal.com")
    monkeypatch.setenv("PT_MODE", "replay")
    response = make(tmp_path, monkeypatch).get("/settings")
    assert response.status_code == 200
    assert "Replay" in response.text
    assert "https://api-m.sandbox.paypal.com" in response.text
    assert "/webhooks/paypal" in response.text
    assert "public URL" in response.text
    assert "python -m core.poll" in response.text
    for name, value in secret_values.items():
        assert name in response.text
        assert "set" in response.text
        assert value not in response.text



def test_unauthorised_workspace_shows_requested_evidence_trail_limits_and_payload_note(tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.FIXTURES_ENABLED", True)
    client = make(tmp_path, monkeypatch)
    response = client.get("/disputes/PP-R-WVY-10197010?fixture=unauthorised&state=confirm")
    assert response.status_code == 200
    assert "Unauthorized transaction" in response.text
    assert "Chargeback" in response.text
    assert "PayPal also asked for: Proof of refund, Other. Not provided." in response.text
    assert 'class="request-note"' in response.text
    assert 'class="message message--error"' not in response.text
    assert "Chain intact, 3 events" in response.text
    assert "Intact (event records unchanged)" in response.text
    assert "Chain integrity" in response.text
    assert "Intent recorded by agent" in response.text
    assert "Shopper text recorded by the agent; not independently verified." in response.text
    assert "synthetic_demo" in response.text
    assert "This payload proves fulfillment. It does not by itself show the buyer authorized the purchase." in response.text
    assert "Buyer approved" not in response.text
    assert "approval" not in response.text.lower()


def test_eval_reads_dynamic_runs_and_keeps_model_panel_and_flag_labels_separate(tmp_path, monkeypatch):
    import json
    from app.dev_fixtures import eval_summary_data
    root = tmp_path / "results"
    main = eval_summary_data()
    main["run"].update({"model": "deepseek-ai/DeepSeek-V4-Flash-0731", "split": "test", "commit": "main-commit"})
    main["flagged_runs"] = [{"case_id": f"main-{i}"} for i in range(3)]
    main["failures"] = [
        {"case_id": "verified-failure-1", "rep": 2, "system": "verified", "decision": "ABSTAIN", "verdicts": ["removed"]},
        {"case_id": "baseline-failure-hidden", "rep": 1, "system": "baseline", "decision": "CONTEST", "verdicts": ["unsupported"]},
    ]
    main_folder = root / "test-DeepSeek-V4-Flash-0731"
    main_folder.mkdir(parents=True)
    (main_folder / "summary.json").write_text(json.dumps(main), encoding="utf-8")
    (main_folder / "flag-classification.json").write_text(json.dumps({
        "run": "test-DeepSeek-V4-Flash-0731", "classified_by": "author, after seeing the flags",
        "labels": {"REBUTTAL": "mentioned only to reject", "FALSE_POSITIVE": "phrase match"},
        "reclassified": [{"idx": [0, 1], "label": "REBUTTAL"}, {"idx": [2], "label": "FALSE_POSITIVE"}],
        "reading": "Raw flags are unchanged."}), encoding="utf-8")
    panel = eval_summary_data()
    panel["run"].update({"model": "Qwen/Qwen3-30B", "commit": "panel-commit"})
    panel["flagged_runs"] = [{"case_id": "p1"}, {"case_id": "p2"}]
    panel_folder = root / "test-Qwen3-30B"
    panel_folder.mkdir()
    (panel_folder / "summary.json").write_text(json.dumps(panel), encoding="utf-8")
    (panel_folder / "flag-classification.json").write_text(json.dumps({
        "run": "test-Qwen3-30B", "classified_by": "reviewer one", "labels": {"ADOPTED": "asserted"},
        "counts": {"ADOPTED": 1, "REBUTTAL": 1},
        "items": [{"idx": 0, "system": "baseline", "case_id": "p1", "rep": 1, "label": "ADOPTED"},
                  {"idx": 1, "system": "verified", "case_id": "p2", "rep": 2, "label": "REBUTTAL"}],
        "reading": "Raw counts stay visible."}), encoding="utf-8")
    unclassified = root / "test-new-model"
    unclassified.mkdir()
    (unclassified / "summary.json").write_text(json.dumps(eval_summary_data()), encoding="utf-8")

    monkeypatch.setattr("app.main.EVAL_RESULTS_DIR", root)
    response = make(tmp_path, monkeypatch).get("/eval")
    assert response.status_code == 200
    assert "Main ablation · test-DeepSeek-V4-Flash-0731" in response.text
    assert "Cross-model panel" in response.text
    assert "Qwen/Qwen3-30B" in response.text
    assert "Decision accuracy" in response.text and "95% CI" in response.text
    assert "Raw scorer flags" in response.text and "3" in response.text and "2" in response.text
    assert "3 Total classified: 3" in response.text or "Total classified: 3" in response.text
    assert "REBUTTAL" in response.text and "FALSE_POSITIVE" in response.text
    assert "author, after seeing the flags" in response.text
    assert "reviewer one" in response.text
    assert "not classified yet" in response.text
    assert "verified-failure-1" in response.text
    assert "baseline-failure-hidden" not in response.text
    assert "Synthetic sample values" in response.text
    assert "win rate" not in response.text.lower()
    assert "proves" not in response.text.lower()

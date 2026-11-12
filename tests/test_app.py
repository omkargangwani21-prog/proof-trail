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
    assert "Drafting… this can take up to a minute" in page.text
    assert "double" not in page.text.lower()


def test_draft_endpoint_ignores_duplicate_request_while_first_is_in_flight(tmp_path, monkeypatch):
    import concurrent.futures
    import threading
    client = make(tmp_path, monkeypatch)
    from core.db import connect
    conn = connect(str(tmp_path / "t.db"))
    seed_dispute(conn)
    conn.close()
    started, release = threading.Event(), threading.Event()
    calls = []

    def slow_fake_draft(pid):
        calls.append(pid)
        started.set()
        assert release.wait(3)
        return {"ok": True}

    monkeypatch.setattr("app.draft_api._draft", slow_fake_draft)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client.post, "/disputes/PP-TEST-1/draft", follow_redirects=False)
        assert started.wait(2)
        second = client.post("/disputes/PP-TEST-1/draft", follow_redirects=False)
        assert second.status_code == 303
        assert second.headers["location"] == "/disputes/PP-TEST-1?draft=busy"
        release.set()
        assert first.result(timeout=3).headers["location"] == "/disputes/PP-TEST-1?draft=ok"
    assert calls == ["PP-TEST-1"]
    busy_page = client.get("/disputes/PP-TEST-1?draft=busy")
    assert "Drafting is already in progress for this dispute. Wait for it to finish." in busy_page.text


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
    assert 'class="back-link" href="/disputes"' in page.text

    def raises(_pid):
        raise RuntimeError("private implementation detail")
    monkeypatch.setattr("app.draft_api._draft", raises)
    unexpected = client.post("/disputes/PP-TEST-1/draft", follow_redirects=False)
    page = client.get(unexpected.headers["location"])
    assert "Something went wrong while drafting. Nothing was saved." in page.text
    assert "private implementation detail" not in page.text
    assert 'class="message message--error" role="alert"' in page.text
    assert 'class="back-link" href="/disputes"' in page.text

    not_found = client.get("/disputes?draft=notfound")
    assert "The dispute was not found." in not_found.text
    assert 'class="message message--error" role="alert"' in not_found.text


def test_unknown_dispute_and_poller_or_database_errors_have_recovery_links(tmp_path, monkeypatch):
    client = make(tmp_path, monkeypatch)
    missing = client.get("/disputes/UNKNOWN-CASE")
    assert missing.status_code == 404
    assert "Case not found" in missing.text
    assert 'class="back-link" href="/disputes"' in missing.text
    assert "Traceback" not in missing.text

    poll_error = client.get("/disputes?refresh=error")
    assert "The dispute refresh failed. Check the PayPal connection, then try again." in poll_error.text
    assert 'action="/ingest/refresh"' in poll_error.text
    assert "Try refresh again" in poll_error.text

    monkeypatch.setattr("app.main.open_db", lambda: (_ for _ in ()).throw(RuntimeError("db-private-detail")))
    database_error = client.get("/disputes")
    assert database_error.status_code == 200
    assert "Disputes could not be loaded. Check the local database, then refresh." in database_error.text
    assert "Try loading disputes again" in database_error.text
    assert "db-private-detail" not in database_error.text
    assert "Traceback" not in database_error.text


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
    from app.dev_fixtures import case_data
    for variant in ("abstain", "partial"):
        assert case_data(variant)["verification"]["recommendation"] == "Do not contest on this evidence"
    monkeypatch.setattr("app.main.FIXTURES_ENABLED", True)
    page = make(tmp_path, monkeypatch).get("/disputes/PP-DEV-1002?fixture=abstain")
    assert page.status_code == 200
    assert "No contest recommended" in page.text
    assert "Missing evidence: Proof of fulfillment." in page.text
    assert "PayPal also asked for: Proof of refund, Other. Not provided." in page.text
    assert "We recommend accepting this claim" not in page.text
    assert "Not enough evidence to contest" in page.text
    assert "Recommend accepting" not in page.text
    assert "Reason not recorded for this draft." in page.text
    assert "Model’s rationale (not verified)" not in page.text
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
    assert "No required evidence is missing." in response.text
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
    assert "This payload contains fulfillment records only. It does not show the buyer authorized the purchase." in response.text
    assert "This payload proves fulfillment." not in response.text
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


def test_review_dialog_downloads_exact_stored_payload_json(tmp_path, monkeypatch):
    client = make(tmp_path, monkeypatch)
    from core.db import connect
    conn = connect(str(tmp_path / "t.db"))
    dispute = seed_dispute(conn)
    payload = [{"evidence_type": "PROOF_OF_FULFILLMENT", "evidence_info": {"tracking_info": []},
                "notes": "Fulfillment record · café"}]
    verification = {"decision": "CONTEST", "claims": [], "missing_evidence": []}
    draft_id = conn.execute(
        "INSERT INTO draft_evidence(paypal_dispute_id,decision,payload_json,verification_json,status,created_at) "
        "VALUES(?,?,?,?,?,?)",
        (dispute["dispute_id"], "CONTEST", json.dumps(payload, ensure_ascii=False),
         json.dumps(verification), "VERIFIED", "2026-11-09"),
    ).lastrowid
    conn.commit()
    conn.close()

    page = client.get(f"/disputes/{dispute['dispute_id']}")
    assert "Download payload JSON" in page.text
    assert f"/disputes/{dispute['dispute_id']}/payload.json?draft_id={draft_id}" in page.text
    downloaded = client.get(f"/disputes/{dispute['dispute_id']}/payload.json?draft_id={draft_id}")
    expected = json.dumps(payload, indent=2, ensure_ascii=False)
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].startswith("application/json")
    assert downloaded.headers["content-disposition"] == f'attachment; filename="{dispute["dispute_id"]}-payload.json"'
    assert downloaded.text == expected
    assert client.get(f"/disputes/OTHER/payload.json?draft_id={draft_id}").status_code == 404


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
    assert draft_state({"status": "ABSTAIN"}) == ("Not contesting", "review", "Review")
    assert reason_label("MERCHANDISE_OR_SERVICE_NOT_RECEIVED") == "Item not received"
    assert reason_label("SOMETHING_NEW") == "Something new"


@pytest.mark.parametrize(("reason", "message", "missing", "issues"), [
    ("consistency", "The records contradict each other, so ProofTrail did not contest.", [],
     ["Order amount differs from captured amount."]),
    ("missing_evidence", "Required evidence is missing: Proof of refund.", ["PROOF_OF_REFUND"], []),
    ("model_abstained", "The model chose not to contest.", [], []),
    ("model_recommended_accept", "The model recommended accepting the claim.", [], []),
])
def test_non_contest_workspace_explains_recorded_reason_and_rationale(
        tmp_path, monkeypatch, reason, message, missing, issues):
    client = make(tmp_path, monkeypatch)
    from core.db import connect
    conn = connect(str(tmp_path / "t.db"))
    dispute = seed_dispute(conn)
    verification = {
        "decision": "ABSTAIN", "decision_reasons": [reason], "drafter_decision": "ABSTAIN",
        "rationale": "<img src=x onerror=alert(1)> " + ("Supporting rationale. " * 20),
        "missing_evidence": missing, "consistency_issues": issues, "claims": [],
    }
    conn.execute(
        "INSERT INTO draft_evidence(paypal_dispute_id,decision,payload_json,verification_json,status,created_at) "
        "VALUES(?,?,?,?,?,?)",
        (dispute["dispute_id"], "ABSTAIN", "[]", json.dumps(verification), "ABSTAIN", "2026-11-09"),
    )
    conn.commit()
    conn.close()

    page = client.get(f"/disputes/{dispute['dispute_id']}")
    assert page.status_code == 200
    assert "Why this decision" in page.text
    assert message in page.text
    assert "Reason not recorded for this draft." not in page.text
    assert "Order amount differs from captured amount." in page.text if issues else True
    assert "Model’s rationale (not verified):" in page.text
    assert '<details class="decision-rationale">' in page.text
    assert "&lt;img src=x onerror=alert(1)&gt;" in page.text
    assert "<img src=x onerror=alert(1)>" not in page.text
    assert "…" in page.text


def test_abstain_queue_shows_neutral_reason_tags_or_no_tag_when_unknown(tmp_path, monkeypatch):
    client = make(tmp_path, monkeypatch)
    from core.db import connect
    conn = connect(str(tmp_path / "t.db"))
    reasons = ["consistency", "missing_evidence", "model_abstained", "model_recommended_accept", None]
    for index, reason in enumerate(reasons):
        pid = f"PP-ABSTAIN-{index}"
        dispute = seed_dispute(conn, pid)
        verification = {"decision": "ABSTAIN", "decision_reasons": [reason] if reason else []}
        conn.execute(
            "INSERT INTO draft_evidence(paypal_dispute_id,decision,payload_json,verification_json,status,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (dispute["dispute_id"], "ABSTAIN", "[]", json.dumps(verification), "ABSTAIN", "2026-11-09"),
        )
    conn.commit()
    conn.close()

    page = client.get("/disputes")
    assert page.text.count("Not contesting") == len(reasons)
    for tag in ("records conflict", "evidence missing", "model abstained", "model recommended accept"):
        assert f'class="reason-tag">{tag}</span>' in page.text
    assert page.text.count('class="reason-tag">') == 4
    assert "Not enough evidence to contest" not in page.text


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


def test_origin_tabs_and_new_marker_refresh_markup(tmp_path, monkeypatch):
    client = make(tmp_path, monkeypatch)
    from core.db import connect
    conn = connect(str(tmp_path / "t.db"))
    seed_dispute(conn, "PP-LIVE-1")
    seed_dispute(conn, "PP-SAMPLE-1")
    conn.execute("UPDATE disputes SET origin='sandbox' WHERE paypal_dispute_id='PP-LIVE-1'")
    conn.execute("UPDATE disputes SET origin='synthetic_sample' WHERE paypal_dispute_id='PP-SAMPLE-1'")
    conn.commit()
    conn.close()

    all_page = client.get("/disputes")
    assert "PP-LIVE-1" in all_page.text and "PP-SAMPLE-1" in all_page.text
    assert all_page.text.count("Synthetic sample") == 1
    assert 'href="/disputes?filter=all" aria-current="page"' in all_page.text
    assert 'setInterval(refresh,20000)' in all_page.text
    assert "new-tag" in all_page.text and "data-pid" in all_page.text
    live_page = client.get("/disputes?filter=sandbox")
    assert "PP-LIVE-1" in live_page.text and "PP-SAMPLE-1" not in live_page.text
    sample_page = client.get("/disputes?filter=samples")
    assert "PP-SAMPLE-1" in sample_page.text and "PP-LIVE-1" not in sample_page.text
    assert 'href="/disputes?filter=samples" aria-current="page"' in sample_page.text


def test_synthetic_sample_detail_forces_dry_run_copy_and_server_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("PT_SUBMIT_MODE", "sandbox-submit")
    client = make(tmp_path, monkeypatch)
    from core.db import connect
    conn = connect(str(tmp_path / "t.db"))
    dispute = seed_dispute(conn, "PP-SAMPLE-2")
    conn.execute("UPDATE disputes SET origin='synthetic_sample' WHERE paypal_dispute_id=?", (dispute["dispute_id"],))
    verification = {"decision": "CONTEST", "missing_evidence": [], "requested_not_provided": [], "claims": []}
    payload = [{"evidence_type": "PROOF_OF_FULFILLMENT", "evidence_info": {"tracking_info": []}, "notes": "Synthetic"}]
    draft_id = conn.execute(
        "INSERT INTO draft_evidence(paypal_dispute_id,decision,payload_json,verification_json,status,created_at) VALUES(?,?,?,?,?,?)",
        (dispute["dispute_id"], "CONTEST", json.dumps(payload), json.dumps(verification), "VERIFIED", "2026-11-08"),
    ).lastrowid
    conn.commit()
    conn.close()

    page = client.get(f"/disputes/{dispute['dispute_id']}")
    assert "Synthetic sample" in page.text
    assert "Generated for demonstration. Submissions are dry run only." in page.text
    assert "Approve and run dry run" in page.text
    assert "Approve and submit to PayPal sandbox" not in page.text

    calls = []
    monkeypatch.setattr("app.main.approve", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.main.submit", lambda *args, **kwargs: calls.append(kwargs["dry_run"]))
    result = client.post(f"/disputes/{dispute['dispute_id']}/submit",
                         data={"draft_id": draft_id, "approved": "yes"}, follow_redirects=False)
    assert result.status_code == 303
    assert calls == [True]


def test_app_uses_opt_in_ingest_lifespan_without_polling_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("PT_AUTOPOLL", raising=False)
    monkeypatch.setenv("PT_MODE", "live-sandbox")
    make(tmp_path, monkeypatch)
    from app import ingest_api
    from app.main import app
    started = []

    async def unexpected_poll():
        started.append(True)

    monkeypatch.setattr(ingest_api, "_poll_loop", unexpected_poll)
    with TestClient(app):
        pass
    assert not started
    import threading
    monkeypatch.setenv("PT_AUTOPOLL", "1")
    polled = threading.Event()

    async def fake_poll_loop():
        polled.set()
        import asyncio
        await asyncio.Event().wait()

    monkeypatch.setattr(ingest_api, "_poll_loop", fake_poll_loop)
    with TestClient(app):
        assert polled.wait(1)



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


def test_activity_lists_audit_and_submission_rows_newest_first(tmp_path, monkeypatch):
    client = make(tmp_path, monkeypatch)
    from core.db import connect
    conn = connect(str(tmp_path / "t.db"))
    dispute = seed_dispute(conn, "PP-ACTIVITY-1")
    payload = [{"evidence_type": "PROOF_OF_FULFILLMENT", "notes": "Test"}]
    draft_id = conn.execute(
        "INSERT INTO draft_evidence(paypal_dispute_id,decision,payload_json,verification_json,status,created_at) "
        "VALUES(?,?,?,?,?,?)",
        (dispute["dispute_id"], "CONTEST", json.dumps(payload), "{}", "SUBMITTED_DRY_RUN", "2026-11-09"),
    ).lastrowid
    payload_hash = "abcdef0123456789"
    for actor, action, at, detail in [
        ("system", "draft_saved", "2026-11-09T02:00:00Z", {"decision": "CONTEST"}),
        ("merchant", "approved", "2026-11-09T02:01:00Z", {"payload_hash": payload_hash}),
        ("merchant", "submitted_dry_run", "2026-11-09T02:02:00Z", {"payload_hash": payload_hash}),
    ]:
        conn.execute("INSERT INTO audit_log(actor,action,entity,entity_id,detail_json,at) VALUES(?,?,?,?,?,?)",
                     (actor, action, "draft", str(draft_id), json.dumps(detail), at))
    conn.execute("INSERT INTO submissions(draft_id,mode,payload_hash,response_json,submitted_at) VALUES(?,?,?,?,?)",
                 (draft_id, "dry_run", payload_hash, "{}", "2026-11-09T02:02:00Z"))
    conn.commit()
    conn.close()

    page = client.get("/trail?view=activity")
    assert page.status_code == 200
    assert "The audit log is append-only." in page.text
    assert 'aria-current="page">Activity</a>' in page.text
    for action in ("draft_saved", "approved", "submitted_dry_run"):
        assert action in page.text
    assert page.text.index("submitted_dry_run") < page.text.index("approved") < page.text.index("draft_saved")
    assert payload_hash[:8] in page.text
    assert payload_hash not in page.text
    assert f'href="/disputes/{dispute["dispute_id"]}"' in page.text


def test_activity_empty_state_is_designed(tmp_path, monkeypatch):
    page = make(tmp_path, monkeypatch).get("/trail?view=activity")
    assert page.status_code == 200
    assert "No activity recorded yet." in page.text
    assert "The audit log is append-only." in page.text


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


def test_system_status_hides_credential_names_values_and_service_urls(tmp_path, monkeypatch):
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
    assert "System status" in response.text
    assert "Replay" in response.text
    assert "Disabled during offline replay" in response.text
    assert "https://api-m.sandbox.paypal.com" not in response.text
    assert "/webhooks/paypal" not in response.text
    assert "public URL" in response.text
    for name, value in secret_values.items():
        assert name not in response.text
        assert value not in response.text


def test_browser_security_headers_are_set(tmp_path, monkeypatch):
    monkeypatch.setenv("PT_MODE", "replay")
    response = make(tmp_path, monkeypatch).get("/settings")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
    csp = response.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp



def test_unauthorised_workspace_shows_requested_evidence_trail_limits_and_payload_note(tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.FIXTURES_ENABLED", True)
    client = make(tmp_path, monkeypatch)
    response = client.get("/disputes/PP-R-WVY-10197010?fixture=unauthorised&state=confirm")
    assert response.status_code == 200
    assert "Unauthorized transaction" in response.text
    assert "Chargeback" in response.text
    assert "PayPal also asked for: Proof of refund, Other. Not provided." in response.text
    assert "No required evidence is missing." not in response.text
    assert 'class="request-note"' in response.text
    assert 'class="message message--error"' not in response.text
    assert "Chain intact, 3 events" in response.text
    assert "Intact (event records unchanged)" in response.text
    assert "Chain integrity" in response.text
    assert "Intent recorded by agent" in response.text
    assert "Shopper text recorded by the agent; not independently verified." in response.text
    assert "synthetic_demo" in response.text
    assert "This payload contains fulfillment records only. It does not show the buyer authorized the purchase." in response.text
    assert "This payload proves fulfillment." not in response.text
    assert "Buyer approved" not in response.text
    assert "approval" not in response.text.lower()
    assert "Not enough evidence to contest" in response.text
    assert "No trusted buyer-authorization record is available" in response.text
    assert "Submission blocked" in response.text


def test_legacy_unauthorised_draft_is_blocked_before_approval_or_submission(tmp_path, monkeypatch):
    client = make(tmp_path, monkeypatch)
    monkeypatch.setenv("PT_SUBMIT_MODE", "sandbox-submit")
    from core.db import connect
    conn = connect(str(tmp_path / "t.db"))
    dispute = seed_dispute(conn)
    conn.execute("UPDATE disputes SET reason='UNAUTHORISED' WHERE paypal_dispute_id=?", (dispute["dispute_id"],))
    did = conn.execute("SELECT id FROM disputes WHERE paypal_dispute_id=?", (dispute["dispute_id"],)).fetchone()["id"]
    case_id = conn.execute("INSERT INTO cases(dispute_id,built_at,bundle_hash) VALUES(?,?,?)",
                           (did, "2026-11-12", "legacy-unauthorized" )).lastrowid
    verification = {"decision": "CONTEST", "claims": [{
        "claim": {"type": "fulfillment", "source_refs": [{"record_id": "shp:old"}]},
        "verdict": "VERIFIED",
    }]}
    draft_id = conn.execute(
        "INSERT INTO draft_evidence(case_id,paypal_dispute_id,decision,payload_json,verification_json,status,created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (case_id, dispute["dispute_id"], "CONTEST",
         json.dumps([{"evidence_type": "PROOF_OF_FULFILLMENT", "notes": "delivered"}]),
         json.dumps(verification), "VERIFIED", "2026-11-12"),
    ).lastrowid
    conn.commit()
    conn.close()

    monkeypatch.setattr("app.main.PayPalClient", lambda: pytest.fail("PayPal client must not be constructed"))
    response = client.post(f"/disputes/{dispute['dispute_id']}/submit",
                           data={"draft_id": draft_id, "approved": "yes"}, follow_redirects=False)
    assert response.status_code == 303
    blocked = client.get(response.headers["location"])
    assert "trusted buyer-authorization record" in blocked.text
    assert "Submission is blocked" in blocked.text
    conn = connect(str(tmp_path / "t.db"))
    assert conn.execute("SELECT COUNT(*) FROM approvals WHERE draft_id=?", (draft_id,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM submissions WHERE draft_id=?", (draft_id,)).fetchone()[0] == 0
    conn.close()


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


def test_eval_renders_seven_runs_and_single_repeat_consistency_notice(tmp_path, monkeypatch):
    from app.dev_fixtures import eval_summary_data
    root = tmp_path / "seven-runs"
    model_names = [
        "deepseek-ai/DeepSeek-V4-Flash-0731", "deepseek-ai/DeepSeek-V4-Pro-0813",
        "deepseek-ai/DeepSeek-V4.1-Flash", "zai-org/GLM-5.3-Flash",
        "Qwen/Qwen3-235B-A22B-Instruct-2507", "Qwen/Qwen3-30B-A3B-Instruct-2507",
        "openai/gpt-oss-120b",
    ]
    for index, model_name in enumerate(model_names):
        folder = root / ("test-" + model_name.split("/")[-1])
        folder.mkdir(parents=True)
        summary = eval_summary_data()
        summary["run"].update({"model": model_name, "repeats": 1 if "V4-Pro" in model_name else 5})
        if "V4-Pro" in model_name:
            summary["consistency"] = {"baseline": None, "cited": None, "verified": None}
        (folder / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        (folder / "flag-classification.json").write_text(json.dumps({
            "classified_by": f"author {index}", "counts": {"REBUTTAL": 1}, "labels": {},
        }), encoding="utf-8")

    monkeypatch.setattr("app.main.EVAL_RESULTS_DIR", root)
    page = make(tmp_path, monkeypatch).get("/eval")
    assert page.status_code == 200
    for model_name in model_names:
        assert model_name in page.text
    assert page.text.count("Classified by the author with an AI assistant, not independent.") == 7
    assert page.text.count("Synthetic data. 95% intervals are case-level cluster bootstrap.") >= 8
    assert "Consistency" in page.text
    assert "Baseline: n/a (single repeat per case)" in page.text
    assert "Baseline: Not reported" not in page.text


def test_eval_page_renders_all_seven_checked_in_test_runs(tmp_path, monkeypatch):
    page = make(tmp_path, monkeypatch).get("/eval")
    assert page.status_code == 200
    expected = (
        "test-DeepSeek-V4-Flash-0731", "test-DeepSeek-V4-Pro-0813", "test-DeepSeek-V4.1-Flash",
        "test-GLM-5.3-Flash", "test-Qwen3-235B-A22B-Instruct-2507",
        "test-Qwen3-30B-A3B-Instruct-2507", "test-gpt-oss-120b",
    )
    for run in expected:
        assert run in page.text
    assert "post-test safety rules for buyer-written citations and authorization evidence" in page.text
    assert "These frozen results do not measure those rules" in page.text
    assert "Baseline: n/a (single repeat per case)" in page.text
    assert page.text.count("Classified by the author with an AI assistant, not independent.") == 7
    assert page.text.count("Synthetic data. 95% intervals are case-level cluster bootstrap.") >= 8


def test_replay_mode_blocks_model_and_paypal_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("PT_MODE", "replay")
    calls = []
    monkeypatch.setattr("app.draft_api._draft", lambda pid: calls.append(("draft", pid)))
    monkeypatch.setattr("app.ingest_api._fetch", lambda pid: calls.append(("fetch", pid)))
    monkeypatch.setattr("app.ingest_api._refresh", lambda: calls.append(("refresh", None)))
    monkeypatch.setattr("app.ingest_api._webhook", lambda *args: calls.append(("webhook", args)))
    client = make(tmp_path, monkeypatch)

    draft = client.post("/disputes/PP-TEST-1/draft", follow_redirects=False)
    fetch = client.post("/ingest/fetch", data={"dispute_id": "PP-TEST-1"}, follow_redirects=False)
    refresh = client.post("/ingest/refresh", follow_redirects=False)
    webhook = client.post("/webhooks/paypal", content=b"{}")

    assert draft.headers["location"] == "/disputes/PP-TEST-1?draft=replay"
    assert fetch.headers["location"] == "/disputes?refresh=replay"
    assert refresh.headers["location"] == "/disputes?refresh=replay"
    assert webhook.status_code == 503
    assert "disabled in replay mode" in webhook.json()["error"]
    assert calls == []


def test_replay_seed_refuses_the_project_database(monkeypatch):
    from scripts.replay_seed import seed_replay
    monkeypatch.setenv("PT_DB", "data/prooftrail.db")
    with pytest.raises(RuntimeError, match="separate replay database"):
        seed_replay()


def test_replay_mode_opens_synthetic_walkthrough_without_external_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("PT_MODE", "replay")
    monkeypatch.setattr("app.main.FIXTURES_ENABLED", True)
    client = make(tmp_path, monkeypatch)
    from scripts.replay_seed import seed_replay
    pid = seed_replay()

    home = client.get("/", follow_redirects=False)
    queue = client.get("/disputes")
    workspace = client.get(f"/disputes/{pid}")
    unauthorized_workspace = client.get("/disputes/DEMO-UNAUTHORISED-001")
    trail_page = client.get("/trail")
    eval_page = client.get("/eval")
    settings = client.get("/settings")

    assert home.headers["location"] == "/disputes"
    assert "Offline replay" in queue.text
    assert pid in queue.text and "Synthetic sample" in queue.text and "Draft ready" in queue.text
    assert "DEMO-UNAUTHORISED-001" in queue.text
    assert "VERIFIED" in workspace.text and "Download payload JSON" in workspace.text
    assert "Synthetic sample" in unauthorized_workspace.text
    assert "Not enough evidence to contest" in unauthorized_workspace.text
    assert "No trusted buyer-authorization record is available" in unauthorized_workspace.text
    assert "Missing evidence: a trusted buyer-authorization record." in unauthorized_workspace.text
    assert "PayPal also asked for: Proof of refund, Other. Not provided." in unauthorized_workspace.text
    assert "No contest recommended." in unauthorized_workspace.text
    assert 'id="openConfirm"' not in unauthorized_workspace.text
    assert "Draft again" not in workspace.text
    assert "Synthetic replay case. The draft and verdicts are precomputed" in workspace.text
    assert "DEMO-TRAIL-001" in trail_page.text
    assert "Synthetic data. 95% intervals are case-level cluster bootstrap." in eval_page.text
    assert "Replay" in settings.text

    blocked = client.post(f"/disputes/{pid}/draft", follow_redirects=False)
    assert blocked.headers["location"] == f"/disputes/{pid}?draft=replay"
    after = client.get(blocked.headers["location"])
    assert "Replay mode is offline" in after.text

    from core.db import connect
    conn = connect(str(tmp_path / "t.db"))
    draft_id = conn.execute("SELECT id FROM draft_evidence WHERE paypal_dispute_id=?", (pid,)).fetchone()["id"]
    payload_response = client.get(f"/disputes/{pid}/payload.json?draft_id={draft_id}")
    assert payload_response.status_code == 200
    assert '"evidence_type": "PROOF_OF_FULFILLMENT"' in payload_response.text
    conn.close()
    submitted = []

    class FakePayPal:
        def provide_evidence(self, dispute_id, evidences, dry_run=True):
            submitted.append((dispute_id, evidences, dry_run))
            return {"dry_run": True}

    monkeypatch.setattr("app.main.PayPalClient", FakePayPal)
    result = client.post(f"/disputes/{pid}/submit", data={"draft_id": draft_id, "approved": "yes"},
                         follow_redirects=False)
    assert result.status_code == 303
    assert submitted and submitted[0][2] is True
    conn = connect(str(tmp_path / "t.db"))
    assert conn.execute("SELECT mode FROM submissions WHERE draft_id=?", (draft_id,)).fetchone()["mode"] == "dry_run"
    assert conn.execute("SELECT status FROM draft_evidence WHERE id=?", (draft_id,)).fetchone()["status"] == "SUBMITTED_DRY_RUN"
    assert conn.execute("SELECT action FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()["action"] == "submitted_dry_run"
    conn.close()

    assert seed_replay() == pid
    assert "DEMO-UNAUTHORISED-001" in client.get("/disputes/DEMO-UNAUTHORISED-001").text
    conn = connect(str(tmp_path / "t.db"))
    assert conn.execute("SELECT COUNT(*) FROM draft_evidence WHERE paypal_dispute_id=?", (pid,)).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM disputes WHERE origin='synthetic_sample'").fetchone()[0] == 9
    conn.close()


def test_default_verifier_cap_sends_any_buyer_text_citation_to_review():
    from core.schemas import Claim, SourceRef
    from core.verifier import check_claim

    records = {
        "ord:test": {"record_id": "ord:test", "kind": "order", "untrusted": False,
                     "content": {"status": "COMPLETED"}},
        "msg:test": {"record_id": "msg:test", "kind": "buyer_message", "untrusted": True,
                     "content": {"text": "I never received the parcel"}},
    }
    claim = Claim(
        claim_id="c1", text="The buyer message says they never received the parcel.",
        type="other", confidence=1.0,
        source_refs=[SourceRef(record_id="ord:test", field="status", quoted_value="COMPLETED"),
                     SourceRef(record_id="msg:test", field="text", quoted_value="I never received the parcel")],
    )
    default = check_claim(claim, records, "COMPLETED", cap=None)
    frozen_eval_behavior = check_claim(claim, records, "COMPLETED", cap=False)

    assert default[0] == "NEEDS_REVIEW"
    assert any("buyer-written text" in reason for reason in default[1])
    assert frozen_eval_behavior == ("PASS", [])

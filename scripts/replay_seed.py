"""Seed an isolated replay database with synthetic cases and one fixed draft.

The caller must set PT_DB to a fresh replay database. This code uses the real
case builder, deterministic verifier and submitter, but never calls a model or
PayPal.
"""
import datetime
import json
import os
from pathlib import Path

from core.db import connect
from core.case_builder import build_case
from core.samples import load_all
from core.schemas import Claim, Draft, SourceRef
from core.submitter import EXTRA_SCHEMA, save_draft
from core.verifier import verify


def _records(conn, case_id):
    rows = conn.execute(
        "SELECT record_id,kind,content_json,untrusted FROM source_records WHERE case_id=? ORDER BY record_id",
        (case_id,),
    ).fetchall()
    return [{"record_id": row["record_id"], "kind": row["kind"],
             "content": json.loads(row["content_json"]), "untrusted": bool(row["untrusted"])}
            for row in rows]


def _seed_unauthorized_walkthrough(conn, source_records):
    """Add a synthetic chargeback showing why delivery is not authorization."""
    pid = "DEMO-UNAUTHORISED-001"
    existing = conn.execute(
        "SELECT c.id AS case_id FROM disputes d JOIN cases c ON c.dispute_id=d.id "
        "WHERE d.paypal_dispute_id=?", (pid,)
    ).fetchone()
    if existing:
        draft_exists = conn.execute(
            "SELECT 1 FROM draft_evidence WHERE paypal_dispute_id=?", (pid,)
        ).fetchone()
        if draft_exists:
            return
        bundle = {"case_id": f"c_{existing['case_id']}", "dispute": None,
                  "records": _records(conn, existing["case_id"]), "required_evidence": ["PROOF_OF_FULFILLMENT"]}
        bundle["dispute"] = next(r for r in bundle["records"] if r["kind"] == "dispute")
    else:
        order_record = next(r for r in source_records if r["kind"] == "order")
        shipment = next(r for r in source_records if r["kind"] == "shipment"
                        and r["content"].get("tracking_number") and r["content"].get("shipped_at"))
        order = order_record["content"]
        now_dt = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
        now = now_dt.isoformat().replace("+00:00", "Z")
        dispute = {
            "dispute_id": pid,
            "reason": "UNAUTHORISED",
            "status": "WAITING_FOR_SELLER_RESPONSE",
            "dispute_life_cycle_stage": "CHARGEBACK",
            "dispute_amount": {"value": order["amount"].split()[0],
                                "currency_code": order["amount"].split()[1]},
            "seller_response_due_date": (now_dt + datetime.timedelta(days=8)).isoformat().replace("+00:00", "Z"),
            "create_time": now,
            "update_time": now,
            "disputed_transactions": [{"seller_transaction_id": order["capture_id"]}],
            "evidences": [{"evidence_type": "PROOF_OF_FULFILLMENT", "source": "REQUESTED_FROM_SELLER"},
                          {"evidence_type": "PROOF_OF_REFUND", "source": "REQUESTED_FROM_SELLER"},
                          {"evidence_type": "OTHER", "source": "REQUESTED_FROM_SELLER"}],
            "messages": [{"posted_by": "BUYER", "content": "I do not recognize or authorize this payment.",
                          "time_posted": now}],
        }
        bundle = build_case(conn, dispute, origin="synthetic_sample")
        bundle["required_evidence"] = ["PROOF_OF_FULFILLMENT", "PROOF_OF_REFUND", "OTHER"]

    shipment = next(r for r in bundle["records"] if r["kind"] == "shipment"
                    and r["content"].get("tracking_number"))
    content = shipment["content"]
    draft = Draft(
        decision="CONTEST",
        rationale="Synthetic replay draft cites shipment details only.",
        claims=[Claim(
            claim_id="replay-unauthorized-claim-1",
            text=f"The shipment record lists tracking number {content['tracking_number']} with {content['carrier']}.",
            type="fulfillment", confidence=0.99,
            source_refs=[SourceRef(record_id=shipment["record_id"], field="carrier",
                                   quoted_value=content["carrier"]),
                         SourceRef(record_id=shipment["record_id"], field="tracking_number",
                                   quoted_value=content["tracking_number"])],
        )],
        missing_evidence=[],
    )
    result = verify(bundle, draft, judge=lambda _text, _cited: True)
    if result["decision"] != "ABSTAIN" or not result.get("authorization_missing"):
        raise RuntimeError("Unauthorized replay walkthrough did not abstain on missing authorization evidence")
    result["drafter_decision"] = "CONTEST"
    result["rationale"] = "Synthetic replay draft cites shipment details only."
    save_draft(conn, bundle, result)


def seed_replay():
    db_path = os.environ.get("PT_DB")
    live_db = Path(__file__).resolve().parents[1] / "data" / "prooftrail.db"
    if not db_path or Path(db_path).expanduser().resolve() == live_db.resolve():
        raise RuntimeError("PT_DB must point to a separate replay database")
    conn = connect(db_path)
    try:
        conn.executescript(EXTRA_SCHEMA)
        load_all(conn)
        cases = conn.execute(
            "SELECT d.paypal_dispute_id,c.id AS case_id FROM disputes d "
            "JOIN cases c ON c.dispute_id=d.id WHERE d.origin='synthetic_sample' ORDER BY d.id"
        ).fetchall()
        for case in cases:
            pid, case_id = case["paypal_dispute_id"], case["case_id"]
            records = _records(conn, case_id)
            dispute_record = next((record for record in records if record["kind"] == "dispute"), None)
            shipment = next((record for record in records if record["kind"] == "shipment"
                             and record["content"].get("tracking_number")
                             and record["content"].get("shipped_at")
                             and record["content"].get("delivery_status") in
                             {"IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED"}), None)
            if not dispute_record or not shipment:
                continue
            existing = conn.execute(
                "SELECT id FROM draft_evidence WHERE paypal_dispute_id=? ORDER BY id LIMIT 1", (pid,)
            ).fetchone()
            if existing:
                _seed_unauthorized_walkthrough(conn, records)
                return pid
            content = shipment["content"]
            refs = [SourceRef(record_id=shipment["record_id"], field="carrier",
                              quoted_value=content["carrier"]),
                    SourceRef(record_id=shipment["record_id"], field="tracking_number",
                              quoted_value=content["tracking_number"])]
            draft = Draft(
                decision="CONTEST",
                rationale="Precomputed synthetic replay draft; no model call was made.",
                claims=[Claim(
                    claim_id="replay-claim-1",
                    text=f"The shipment record lists tracking number {content['tracking_number']} with {content['carrier']}.",
                    type="fulfillment", confidence=0.99, source_refs=refs,
                )], missing_evidence=[],
            )
            dispute_json = json.loads(conn.execute(
                "SELECT raw_json FROM disputes WHERE paypal_dispute_id=?", (pid,)
            ).fetchone()["raw_json"])
            required = [item["evidence_type"] for item in dispute_json.get("evidences", [])
                        if item.get("source") == "REQUESTED_FROM_SELLER"]
            bundle = {"case_id": f"c_{case_id}", "dispute": dispute_record,
                      "records": records, "required_evidence": required}
            result = verify(bundle, draft, judge=lambda _text, _cited: True)
            if result["decision"] != "CONTEST":
                continue
            result["drafter_decision"] = "CONTEST"
            result["rationale"] = "Precomputed synthetic replay draft; no model call was made."
            save_draft(conn, bundle, result)
            _seed_unauthorized_walkthrough(conn, records)
            return pid
        raise RuntimeError("No synthetic sample has a usable fulfillment record for the replay draft")
    finally:
        conn.close()


if __name__ == "__main__":
    print("Seeded replay case:", seed_replay())

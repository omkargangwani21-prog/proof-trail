"""Seed an isolated replay database with synthetic cases and one fixed draft.

The caller must set PT_DB to a fresh replay database. This code uses the real
case builder, deterministic verifier and submitter, but never calls a model or
PayPal.
"""
import json
import os
from pathlib import Path

from core.db import connect
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
            return pid
        raise RuntimeError("No synthetic sample has a usable fulfillment record for the replay draft")
    finally:
        conn.close()


if __name__ == "__main__":
    print("Seeded replay case:", seed_replay())

import datetime
from dotenv import load_dotenv
load_dotenv()
from core.db import connect
from core import trail

conn = connect()
ref = "ord:demo-" + datetime.datetime.now().strftime("%H%M%S")
trail.record(conn, ref, "intent", "Buy a desk lamp for under 60 USD", {"max_usd": 60})
trail.record(conn, ref, "cart", "Desk lamp x1, 49.00 USD", {"total": "49.00"})
trail.record(conn, ref, "payment", "Payment captured, 49.00 USD", {"capture_id": "DEMO"})
events = trail.load_events(conn, ref)
for e in events:
    print(e["seq"], e["event"].ljust(8), "hash", e["hash"][:12], "prev", e["prev_hash"][:12], "|", e["summary"])
print("real chain  :", trail.verify_events(events))
print("tamper demo :", trail.verify_events(trail.tampered(events, 2, summary="Desk lamp x9, 441.00 USD")))

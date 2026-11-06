import os, sqlite3

DB_PATH = os.environ.get("PT_DB", "data/prooftrail.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY AUTOINCREMENT, paypal_order_id TEXT, capture_id TEXT UNIQUE,
  buyer_ref TEXT, amount_minor INTEGER, currency TEXT, status TEXT, created_at TEXT, origin TEXT);
CREATE TABLE IF NOT EXISTS order_items(
  id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER REFERENCES orders(id),
  sku TEXT, name TEXT, qty INTEGER, unit_minor INTEGER);
CREATE TABLE IF NOT EXISTS shipments(
  id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER REFERENCES orders(id),
  carrier TEXT, tracking_number TEXT, shipped_at TEXT, delivered_at TEXT,
  delivery_status TEXT, data_origin TEXT);
CREATE TABLE IF NOT EXISTS policies(
  id INTEGER PRIMARY KEY AUTOINCREMENT, version TEXT, text TEXT, effective_from TEXT);
CREATE TABLE IF NOT EXISTS disputes(
  id INTEGER PRIMARY KEY AUTOINCREMENT, paypal_dispute_id TEXT UNIQUE, reason TEXT, status TEXT,
  stage TEXT, amount_minor INTEGER, currency TEXT, due_at TEXT, raw_json TEXT,
  created_at TEXT, updated_at TEXT, origin TEXT);
CREATE TABLE IF NOT EXISTS dispute_messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT, dispute_id INTEGER REFERENCES disputes(id),
  author_role TEXT, text TEXT, posted_at TEXT, untrusted INTEGER DEFAULT 1,
  UNIQUE(dispute_id, author_role, posted_at, text));
CREATE TABLE IF NOT EXISTS cases(
  id INTEGER PRIMARY KEY AUTOINCREMENT, dispute_id INTEGER UNIQUE REFERENCES disputes(id),
  built_at TEXT, bundle_hash TEXT);
CREATE TABLE IF NOT EXISTS source_records(
  record_id TEXT, case_id INTEGER REFERENCES cases(id), kind TEXT, content_json TEXT,
  untrusted INTEGER, PRIMARY KEY(record_id, case_id));
"""


def connect(path=None):
    p = path or DB_PATH
    if p != ":memory:":
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    c = sqlite3.connect(p)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.executescript(SCHEMA)
    return c

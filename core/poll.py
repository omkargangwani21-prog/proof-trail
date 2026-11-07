import argparse, json, time
from core.db import connect
from core.paypal_client import PayPalClient
from core.ingest import poll_once


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--every", type=int, default=60)
    a = ap.parse_args()
    client = PayPalClient()
    while True:
        conn = connect()
        try:
            res = poll_once(conn, client)
        except Exception as e:
            res = {"error": type(e).__name__ + ": " + str(e)[:200]}
        finally:
            conn.close()
        print(time.strftime("%H:%M:%S"), json.dumps(res))
        if a.once:
            break
        time.sleep(a.every)


if __name__ == "__main__":
    main()

"""Mint an AeroLift API key (basic or pro tier).

Usage:
    python scripts/mint_key.py --label "Acme Energy" --tier pro
    python scripts/mint_key.py --label "Historian SCADA" --field "SB-1"
    python scripts/mint_key.py --label "Dev" --db-url sqlite:///./aerolift.db

The raw key is printed ONCE - store it in the client's secret manager.
Only its SHA-256 hash is persisted, so it cannot be recovered later.

Env/args: DATABASE_URL env var or --db-url flag selects the database
(default sqlite:///./aerolift.db).
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    parser = argparse.ArgumentParser(
        description="Mint an API key for AeroLift Analytics.")
    parser.add_argument("--label", required=True,
                        help="operator or service name, e.g. 'Acme Energy'")
    parser.add_argument("--field", default=None,
                        help="field/block name (optional metadata)")
    parser.add_argument("--tier", choices=["basic", "pro"],
                        default="basic",
                        help="basic = monitoring; pro = nodal/forecast/ML")
    parser.add_argument("--db-url", default=None,
                        help="override DATABASE_URL for this run")
    args = parser.parse_args()

    if args.db_url:
        os.environ["DATABASE_URL"] = args.db_url

    from api import auth, models
    from api.database import SessionLocal, init_db

    init_db()
    raw_key = auth.generate_raw_key()
    session = SessionLocal()
    try:
        row = models.ApiKey(key_hash=auth.hash_key(raw_key),
                            label=args.label,
                            field_name=args.field,
                            tier=args.tier)
        session.add(row)
        session.commit()
        key_id = row.id
    finally:
        session.close()

    print("API key created: id={} tier={} label={}".format(
        key_id, args.tier, args.label))
    print("X-API-Key (copy now - shown only once):")
    print(raw_key)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Apply Resend SMTP settings to relay-7 listmonk.

Run on relay-7 with RESEND_API_KEY set, or pass --key-file pointing to a root-only file.
Does not print secrets.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Any


DB_CONTAINER = "listmonk-db"
DB_USER = "listmonk"
DB_NAME = "listmonk"


def run_psql(sql: str) -> str:
    proc = subprocess.run(
        [
            "sudo",
            "docker",
            "exec",
            "-i",
            DB_CONTAINER,
            "psql",
            "-U",
            DB_USER,
            "-d",
            DB_NAME,
            "-v",
            "ON_ERROR_STOP=1",
            "-Atc",
            sql,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "psql failed")
    return proc.stdout.strip()


def load_key(args: argparse.Namespace) -> str:
    key = args.api_key or os.environ.get("RESEND_API_KEY", "")
    if args.key_file:
        key = open(args.key_file, encoding="utf-8").read().strip()
    key = key.strip().strip('"').strip("'")
    if not key:
        raise ValueError("missing Resend API key: set RESEND_API_KEY, --api-key, or --key-file")
    if not (key.startswith("re_") or key.startswith("resend_")):
        raise ValueError("provided key does not look like a Resend API key")
    return key


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def jsonb_literal(value: Any) -> str:
    return sql_literal(json.dumps(value, separators=(",", ":"))) + "::jsonb"


def apply_settings(args: argparse.Namespace) -> None:
    key = load_key(args)
    smtp = [
        {
            "host": "smtp.resend.com",
            "port": args.port,
            "enabled": True,
            "password": key,
            "tls_type": "TLS" if args.port in (465, 2465) else "STARTTLS",
            "username": "resend",
            "max_conns": args.max_conns,
            "idle_timeout": "15s",
            "wait_timeout": "5s",
            "auth_protocol": "login",
            "email_headers": [],
            "from_addresses": [args.from_email],
            "hello_hostname": args.hello_hostname,
            "max_msg_retries": 2,
            "msg_retry_delay": "1s",
            "tls_skip_verify": False,
        }
    ]
    updates = {
        "smtp": smtp,
        "app.from_email": f"{args.from_name} <{args.from_email}>",
        "app.site_name": args.site_name,
        "app.root_url": args.root_url,
        "app.notify_emails": [args.notify_email] if args.notify_email else [],
    }
    sql_parts = []
    for key_name, value in updates.items():
        sql_parts.append(
            "insert into settings(key, value, updated_at) values "
            f"({sql_literal(key_name)}, {jsonb_literal(value)}, now()) "
            "on conflict(key) do update set value=excluded.value, updated_at=now();"
        )
    run_psql("\n".join(sql_parts))


def verify() -> None:
    rows = run_psql(
        "select key, case when key='smtp' then "
        "jsonb_set(value, '{0,password}', '\"<REDACTED>\"'::jsonb)::text "
        "else value::text end "
        "from settings where key in ('smtp','app.from_email','app.site_name','app.root_url') order by key;"
    )
    print(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Configure listmonk on relay-7 to send via Resend SMTP")
    parser.add_argument("--api-key", help="Resend API key; prefer RESEND_API_KEY or --key-file")
    parser.add_argument("--key-file", help="Root-only file containing Resend API key")
    parser.add_argument("--from-email", default="field-report@theoforgesolutions.com")
    parser.add_argument("--from-name", default="Operator Field Report")
    parser.add_argument("--notify-email", default="")
    parser.add_argument("--site-name", default="Operator Field Report")
    parser.add_argument("--root-url", default="http://100.100.46.52:9000")
    parser.add_argument("--hello-hostname", default="theoforgesolutions.com")
    parser.add_argument("--port", type=int, default=465)
    parser.add_argument("--max-conns", type=int, default=2)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        apply_settings(args)
        verify()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

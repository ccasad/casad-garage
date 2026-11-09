"""Command-line tasks.

    python -m app.cli invite --admin                 # first sign-in for ADMIN_EMAIL
    python -m app.cli invite --email a@b.com --name "Alex"
    python -m app.cli stats                          # usage counts as JSON (no names)

`invite` prints a one-time invite link. Both use DATABASE_URL (and `invite` APP_BASE_URL)
from the environment. The app factory runs `stats` to report who uses each app.
"""

import argparse
import json

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_engine
from app.invites import create_invite, invite_url
from app.stats import summary


def invite(args: argparse.Namespace) -> None:
    settings = get_settings()
    if args.admin:
        if not settings.admin_email:
            raise SystemExit("Set ADMIN_EMAIL to create the admin invite.")
        email, role = settings.admin_email, "admin"
    elif args.email:
        email, role = args.email, "member"
    else:
        raise SystemExit("Pass --admin or --email.")

    name = args.name or email.split("@")[0].title()
    with Session(get_engine()) as db:
        token = create_invite(db, email=email, display_name=name, role=role)
        db.commit()
    print(f"Invite for {name} <{email}> ({role}), valid for 7 days:")
    print(invite_url(token))


def stats(_args: argparse.Namespace) -> None:
    with Session(get_engine()) as db:
        print(json.dumps(summary(db)))


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(required=True)

    invite_cmd = commands.add_parser("invite", help="create a one-time passkey setup link")
    invite_cmd.add_argument("--admin", action="store_true", help="invite ADMIN_EMAIL as admin")
    invite_cmd.add_argument("--email", help="member's email address")
    invite_cmd.add_argument("--name", help="display name (defaults from the email)")
    invite_cmd.set_defaults(func=invite)

    stats_cmd = commands.add_parser("stats", help="print usage counts as JSON (no names)")
    stats_cmd.set_defaults(func=stats)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

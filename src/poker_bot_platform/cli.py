from __future__ import annotations

import argparse
import asyncio
import getpass
import os

from poker_bot_platform.auth.service import bootstrap_admin
from poker_bot_platform.auth.sqlalchemy import SqlAlchemyAuthRepository
from poker_bot_platform.config import Settings
from poker_bot_platform.persistence import create_database_components


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="poker-platform")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check", help="validate that the application imports")
    bootstrap = subparsers.add_parser(
        "bootstrap-admin",
        help="create the first explicit administrator account",
    )
    bootstrap.add_argument("--email", required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "check":
        print("poker platform import: ok")
    elif args.command == "bootstrap-admin":
        password = os.environ.get("POKER_ADMIN_PASSWORD") or getpass.getpass("Admin password: ")
        asyncio.run(_bootstrap_admin(args.email, password))


async def _bootstrap_admin(email: str, password: str) -> None:
    settings = Settings()
    engine, sessions, _tables = create_database_components(settings.database_url)
    try:
        account = await bootstrap_admin(
            SqlAlchemyAuthRepository(sessions),
            email,
            password,
        )
        print(f"admin ready: {account.email}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    main()

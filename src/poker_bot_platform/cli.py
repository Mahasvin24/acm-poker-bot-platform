from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="poker-platform")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check", help="validate that the application imports")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "check":
        print("poker platform import: ok")


if __name__ == "__main__":
    main()

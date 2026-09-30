from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

from dsl_export.console_client import ConsoleApiError, ConsoleSession
from log_search.searcher import LogSearchError, search_case_logs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Search a Dify root workflow by case number and export its run tree."
    )
    parser.add_argument("--endpoint", required=True, help="Dify Console URL")
    parser.add_argument("--app", required=True, help="Exact root application name")
    parser.add_argument("--case-num", required=True, help="Case number to search")
    parser.add_argument("--workspace", help="Workspace name")
    parser.add_argument("--output", default="dify-log-search", help="Output directory")
    parser.add_argument("--profile-dir", help="Persistent browser profile directory")
    parser.add_argument("--login-timeout", type=int, default=600)
    parser.add_argument("--max-results", type=int, default=20)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    hostname = urlparse(args.endpoint).hostname
    if not hostname:
        print(f"error: invalid endpoint {args.endpoint!r}", file=sys.stderr)
        return 2
    profile_dir = (
        Path(args.profile_dir)
        if args.profile_dir
        else Path.cwd() / ".dify-profile" / hostname
    )
    try:
        with ConsoleSession(
            args.endpoint, profile_dir, login_timeout=args.login_timeout
        ) as client:
            if args.workspace:
                client.switch_workspace(args.workspace)
            manifest = search_case_logs(
                client,
                args.app,
                args.case_num,
                args.output,
                max_results=args.max_results,
            )
    except (ConsoleApiError, LogSearchError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        f"Found {len(manifest['root_run_ids'])} root run(s) and "
        f"exported {manifest['run_count']} complete run log(s)."
    )
    return 0
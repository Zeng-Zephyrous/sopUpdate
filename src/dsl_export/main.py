from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

from dsl_export.console_client import ConsoleApiError, ConsoleSession
from dsl_export.exporter import ExportError, export_complete_dsl


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Export one Dify app selected by exact name and tag, including "
            "all referenced workflow-tool DSLs."
        )
    )
    parser.add_argument(
        "--endpoint",
        required=True,
        help="Dify Console URL, for example https://dify-devs.example.com",
    )
    parser.add_argument("--name", required=True, help="Exact Dify app name")
    parser.add_argument("--tag", required=True, help="Exact Dify app tag")
    parser.add_argument(
        "--login-timeout",
        type=int,
        default=600,
        help="Seconds to wait when interactive browser login is needed (default: 600)",
    )
    parser.add_argument(
        "--output",
        default="dify-dsl-export",
        help="Output directory (default: dify-dsl-export)",
    )
    parser.add_argument(
        "--workspace",
        help="Workspace name; omit to use the account's current workspace",
    )
    parser.add_argument(
        "--profile-dir",
        help="Persistent browser profile directory (default: .dify-profile/<host>)",
    )
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
            args.endpoint,
            profile_dir,
            login_timeout=args.login_timeout,
        ) as client:
            if args.workspace:
                print(f"Switching to workspace {args.workspace!r}...")
                client.switch_workspace(args.workspace)
            print(f"Exporting {args.name!r} with tag {args.tag!r}...")
            manifest = export_complete_dsl(
                client,
                args.name,
                args.tag,
                args.output,
            )
    except (ConsoleApiError, ExportError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        f"Exported {manifest['workflow_count']} DSL(s): 1 root + "
        f"{manifest['dependency_count']} dependencies -> {args.output}"
    )
    unresolved = manifest["unresolved_workflow_references"]
    if unresolved:
        print(
            f"warning: {len(unresolved)} workflow reference(s) could not be resolved",
            file=sys.stderr,
        )
    return 0

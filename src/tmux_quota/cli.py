"""Small command-line interface; desktop applications are never required."""

import argparse
from dataclasses import asdict
import json
import math
import os
import re
from pathlib import Path
import sys
import time

from . import __version__
from .cache import collect
from .render import PALETTES, render
from .source import PROVIDERS, SourceError, parse_input


def positive(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return result


def label(value: str) -> tuple[str, str]:
    key, sep, text = value.partition("=")
    provider, colon, slot = key.partition(":")
    if not sep or not text.strip() or not colon or provider not in PROVIDERS or not slot.isdigit():
        raise argparse.ArgumentTypeError("expected claude:7=work or codex:4=lab")
    return (f"{provider}:{int(slot)}", text)


def color(value: str) -> tuple[str, str]:
    key, sep, text = value.partition("=")
    valid = text == "default" or re.fullmatch(r"#[0-9a-fA-F]{6}", text)
    if re.fullmatch(r"colour\d{1,3}", text):
        valid = int(text[6:]) <= 255
    if not sep or key not in PALETTES["terminal"] or not valid:
        raise argparse.ArgumentTypeError(
            "expected ROLE=default, ROLE=colour0..255, or ROLE=#RRGGBB; "
            "roles: green, blue, amber, red, unknown, track, text")
    return key, text


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="ccswap quota bars and pace colors for tmux")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--provider", choices=("all", *PROVIDERS), default="all")
    p.add_argument("--format", choices=("tmux", "plain", "json"), default="tmux")
    p.add_argument("--theme", choices=tuple(PALETTES), default="terminal",
                   help="terminal palette by default; dark/light are opt-in Tokyo Night presets")
    p.add_argument("--color", type=color, action="append", default=[], metavar="ROLE=COLOR",
                   help="override a foreground role; repeat for multiple colors")
    p.add_argument("--width", type=int, choices=range(1, 33), default=6, metavar="1..32")
    p.add_argument("--ascii", action="store_true", help="use ASCII bars and separators")
    p.add_argument("--active-only", action="store_true")
    p.add_argument("--label", type=label, action="append", default=[], metavar="PROVIDER:SLOT=NAME")
    p.add_argument("--stdin", action="store_true", help="render JSON input without running ccswap or caching")
    p.add_argument("--ccswap", default="ccswap", metavar="PATH", help="ccswap executable (no shell command)")
    p.add_argument("--timeout", type=positive, default=20, metavar="SECONDS", help="per-provider timeout (default: 20)")
    p.add_argument("--cache-ttl", type=positive, default=60, metavar="SECONDS")
    p.add_argument("--max-age", type=positive, default=600, metavar="SECONDS")
    p.add_argument("--cache-dir", type=Path, default=Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "tmux-quota")
    p.add_argument("--no-cache", action="store_true", help="fetch each invocation; avoid in a tmux status line")
    p.add_argument("--quiet", action="store_true", help="suppress diagnostics on stderr")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    providers = PROVIDERS if args.provider == "all" else (args.provider,)
    errors = []
    try:
        if args.stdin:
            accounts = parse_input(json.load(sys.stdin), providers, time.time())
        else:
            accounts, errors = collect(providers, args.ccswap, args.timeout,
                                       None if args.no_cache else args.cache_dir.expanduser(),
                                       args.cache_ttl)
    except (SourceError, ValueError, OSError) as exc:
        # JSON decoder messages contain no account payload, only line/column.
        accounts, errors = [], [str(exc)]
    now = time.time()
    if args.format == "json":
        rows = []
        for account in accounts:
            row = asdict(account)
            row.pop("identity", None)  # Cache ownership tags are not public output.
            row["label"] = dict(args.label).get(f"{account.provider}:{account.number}", account.label)
            for raw, window in zip(row["windows"], account.windows):
                raw["pace"] = window.pace(now, args.max_age)
                raw["available"] = window.available(now, args.max_age)
            rows.append(row)
        print(json.dumps({"schemaVersion": 1, "accounts": rows, "errors": errors}, allow_nan=False))
    else:
        print(render(accounts, now=now, theme=args.theme, format=args.format,
                     width=args.width, ascii_only=args.ascii, max_age=args.max_age,
                     labels=dict(args.label), active_only=args.active_only,
                     scoped_providers=providers, colors=dict(args.color)))
    if not args.quiet:
        for error in errors:
            print(f"tmux-quota: {error}", file=sys.stderr)
    return 1 if errors and not accounts else 0

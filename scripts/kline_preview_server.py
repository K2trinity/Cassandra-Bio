from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7917
FORMAL_HOST = "0.0.0.0"
FORMAL_PORT = 7897
DEFAULT_TICKER = "MRNA"


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def preview_url(
    host: str,
    port: int,
    ticker: str = DEFAULT_TICKER,
    public_host: str | None = None,
) -> str:
    display_host = (public_host or "").strip()
    if not display_host:
        display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    return f"http://{display_host}:{port}/kline/{ticker.strip().upper() or DEFAULT_TICKER}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the optimized K-line preview server from this checkout."
    )
    parser.add_argument(
        "--formal",
        action="store_true",
        help="Bind the optimized checkout on the formal development address profile.",
    )
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--public-host")
    parser.add_argument("--ticker", default=DEFAULT_TICKER)
    args = parser.parse_args(argv)

    if args.formal:
        args.host = args.host or FORMAL_HOST
        args.port = args.port or FORMAL_PORT
    else:
        args.host = args.host or DEFAULT_HOST
        args.port = args.port or DEFAULT_PORT

    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = project_root()
    os.chdir(root)
    sys.path.insert(0, str(root))

    from app import app, config, socketio  # noqa: PLC0415

    config.HOST = args.host
    config.PORT = args.port

    print(f"K-line optimized preview root: {root}", flush=True)
    print(
        f"K-line optimized preview URL: {preview_url(args.host, args.port, args.ticker, args.public_host)}",
        flush=True,
    )
    socketio.run(
        app,
        host=args.host,
        port=args.port,
        debug=False,
        allow_unsafe_werkzeug=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

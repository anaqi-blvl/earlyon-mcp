"""Command line entry point: ``earlyon-mcp serve | refresh | status``."""
from __future__ import annotations

import argparse
import json
import logging
import sys

from .config import Config


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="earlyon-mcp", description="EarlyON calendar MCP server")
    p.add_argument("command", nargs="?", default="serve", choices=["serve", "refresh", "status"],
                   help="serve (stdio MCP, default) | refresh (one-shot fetch) | status (print DB status)")
    args = p.parse_args(argv)
    if args.command == "serve":
        from .server import run
        run()
        return 0
    cfg = Config.from_env()
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(message)s")
    if args.command == "refresh":
        from .refresh import refresh_once
        res = refresh_once(cfg)
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
    from . import db, queries
    with db.connect(cfg.db_path) as conn:
        print(json.dumps(queries.status(conn), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

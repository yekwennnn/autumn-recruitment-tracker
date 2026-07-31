#!/usr/bin/env python3
"""Compatibility wrapper around the unified resume commands."""
from __future__ import annotations

import sys

try:
    from jobctl import main
except ImportError:
    from .jobctl import main


def translate(argv):
    if not argv:
        return ["resume", "list"]
    command = argv[0]
    mapping = {
        "import-original": "import",
        "register": "register",
        "list": "list",
        "set-base": "set-base",
    }
    if command not in mapping:
        raise SystemExit(f"不支持的 resume_store 命令：{command}")
    return ["resume", mapping[command], *argv[1:]]


if __name__ == "__main__":
    main(translate(sys.argv[1:]))

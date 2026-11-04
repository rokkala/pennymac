#!/usr/bin/env python3
"""Thin wrapper: python scripts/demo_setup.py --data-dir DIR --kit PATH [--force] [--scale compact|full]."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lbp.cli import _demo_setup  # noqa: E402


def main() -> int:
    # Translate --kit / flags into cli argv shape (already argparse-compatible).
    return _demo_setup(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())

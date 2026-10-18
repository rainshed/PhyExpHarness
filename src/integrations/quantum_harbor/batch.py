#!/usr/bin/env python3
"""Compatibility command; sequential batch implementation belongs to the platform."""
import sys
from pathlib import Path
if __package__ in (None, ''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from src.control import legacy_batch as _implementation
if __name__ == '__main__':
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation

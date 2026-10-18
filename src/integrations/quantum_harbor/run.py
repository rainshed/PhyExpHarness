#!/usr/bin/env python3
"""Historical command; defaults are resolved by the platform compatibility entry."""
import sys
from pathlib import Path
if __package__ in (None, ''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from src.control import legacy_run as _implementation
if __name__ == '__main__':
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation

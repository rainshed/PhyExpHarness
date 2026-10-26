#!/usr/bin/env python3
"""Agent-friendly local setup and first-experiment entry point."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.onboarding.cli import main

if __name__ == '__main__':
    raise SystemExit(main())

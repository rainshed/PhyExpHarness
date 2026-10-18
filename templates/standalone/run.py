#!/usr/bin/env python3
from pathlib import Path
from src.execution.host.single_run import main
if __name__ == '__main__':
    raise SystemExit(main(bundle_root=Path(__file__).resolve().parent))

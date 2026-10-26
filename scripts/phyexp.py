#!/usr/bin/env python3
"""Agent-friendly local setup and first-experiment entry point."""
import sys
import json
from pathlib import Path
if sys.version_info < (3, 11):
    print(json.dumps({'schemaVersion':1,'command':'bootstrap','status':'failed','error':{'code':'python_version','message':'请使用 Python 3.13 运行安装入口。'}}))
    raise SystemExit(1)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.onboarding.cli import main

if __name__ == '__main__':
    raise SystemExit(main())

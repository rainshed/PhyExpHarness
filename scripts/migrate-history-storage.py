#!/usr/bin/env python3
"""Plan/apply/resume or restore explicit historical storage deduplication."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.control.history_storage import plan, apply, restore
from src.control.paths import data_dir

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('action', choices=['plan', 'apply', 'restore'])
parser.add_argument('--session', required=True, type=Path)
parser.add_argument('--data-dir', type=Path)
parser.add_argument('--bundle')
args = parser.parse_args()
if args.action == 'plan':
    result = plan(data_dir(args.data_dir), args.session)
    print(json.dumps({'bundles': len(result['bundles']), 'excluded': len(result['excluded']), 'session': str(args.session)}, ensure_ascii=False))
elif args.action == 'apply':
    print(json.dumps(apply(args.session), ensure_ascii=False))
else:
    if not args.bundle:parser.error('--bundle is required for restore')
    print(json.dumps(restore(args.session, args.bundle), ensure_ascii=False))

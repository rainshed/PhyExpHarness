"""Operator-only NFS policy, inspection and explicit restoration commands."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.evidence.cold import ColdArchive
from src.evidence.objects import atomic_json

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--data',type=Path,required=True)
sub=parser.add_subparsers(dest='action',required=True)
sub.add_parser('status')
configure=sub.add_parser('configure');configure.add_argument('policy',type=Path)
restore=sub.add_parser('restore');restore.add_argument('relative',help='File or directory relative to the local data root')
sub.add_parser('restore-all',help='Restore every archived body and its original local aliases; disable eviction first')
sub.add_parser('run',help='One archive pass, sharing the background worker lease')
args=parser.parse_args();cold=ColdArchive(args.data)
if args.action=='configure':
    old=cold.policy;cold.policy=json.loads(args.policy.read_text());cold.validate()
    if cold.index.exists() and old and any(cold.policy[k]!=old[k] for k in ('root','instance')):
        raise ValueError('An existing archive cannot be repointed; restore and migrate it explicitly')
    cold.root().mkdir(parents=True,exist_ok=True,mode=0o700)
    atomic_json(cold.policy_file,cold.policy)
elif args.action=='restore':
    target=cold.safe(args.relative)
    cold.restore_path(target);cold.restore_tree(target)
elif args.action=='restore-all':
    if cold.configured() and cold.policy.get('evict'):raise ValueError('Disable eviction before restoring the complete archive')
    if cold.index.exists():
        with cold.db() as db:
            bodies=[r[0] for r in db.execute('SELECT sha FROM bodies')]
            aliases=[r[0] for r in db.execute('SELECT path FROM aliases')]
        for sha in bodies:cold.materialize(sha)
        for relative in aliases:cold.restore_path(cold.safe(relative))
elif args.action=='run':
    from src.control.archive import work
    work(cold.data)
print(json.dumps(cold.snapshot(),ensure_ascii=False,indent=2))

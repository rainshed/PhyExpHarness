"""Prewarm the same image cache used automatically when creating a Campaign."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.control.store import PUBLIC_TASKS
from src.control.task_images import prepare_task_images
from src.execution.host.single_run import write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--quantum-harbor', type=Path, required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--task', choices=PUBLIC_TASKS)
    selection.add_argument('--all', action='store_true', help='Prepare all five public tasks')
    parser.add_argument('--cache', type=Path, help='Shared cache; default: output parent (or output directory for --all)')
    parser.add_argument('--output', type=Path, required=True, help='Lock file, or directory with --all')
    args = parser.parse_args()
    cache = args.cache or (args.output if args.all else args.output.parent)
    locks = prepare_task_images(args.quantum_harbor.resolve(), PUBLIC_TASKS if args.all else [args.task],
                                cache, cache/'preparation.log')
    for task, lock in locks.items():
        destination = args.output/(task+'.json') if args.all else args.output
        destination.parent.mkdir(parents=True, exist_ok=True)
        write_json(destination, lock)
    print(json.dumps(locks if args.all else locks[args.task], indent=2))


if __name__ == '__main__':
    main()

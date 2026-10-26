"""Synthetic metadata for unit tests; never an official task or scorer."""
from pathlib import Path


def make_tasks(root, tasks):
    root = Path(root)
    for name in tasks:
        task = root/'harbor_tasks'/name
        task.mkdir(parents=True, exist_ok=True)
        (task/'task.toml').write_text('[agent]\ntimeout_sec = 3600\n[environment]\nbuild_timeout_sec = 600\n[verifier]\ntimeout_sec = 300\n')
        (task/'instruction.md').write_text('Synthetic unit-test task; no model execution or official score.\n')
    return root

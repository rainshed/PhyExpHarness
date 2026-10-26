#!/usr/bin/env python3
"""Real control/UI/CLI in isolated data, synthetic task metadata, no model or Docker calls."""
import json
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def main():
    with tempfile.TemporaryDirectory(prefix='phyexp-onboarding-contract-') as tmp:
        folder = Path(tmp); data = folder/'data'; quantum = folder/'synthetic-quantum'
        task = quantum/'harbor_tasks/time_budgeted_hamlearn_10q'
        task.mkdir(parents=True)
        (task/'task.toml').write_text('[agent]\ntimeout_sec = 3600\n')
        env = {k:v for k,v in os.environ.items() if not k.startswith(('PHYEXP_', 'DSH_'))}
        env.update(PHYEXP_DATA_DIR=str(data), PHYEXP_CODEX_AUTH_FILE=str(folder/'absent-auth.json'))
        def run(*args, expected=0):
            result = subprocess.run([sys.executable, 'scripts/phyexp.py', *args, '--json'], cwd=ROOT, env=env, capture_output=True, text=True, timeout=150)
            if result.returncode != expected:
                raise AssertionError(f'{args[0]} exited {result.returncode}: {result.stdout}\n{result.stderr}')
            return json.loads(result.stdout)
        control_port, ui_port = port(), port()
        started = False
        try:
            first = run('start', '--quantum-harbor', str(quantum), '--control-port', str(control_port), '--ui-port', str(ui_port))
            started = True
            second = run('start')
            assert first['control'] == first['ui'] == second['control'] == second['ui'] == 'ready'
            assert {k:v['pid'] for k,v in first['processes'].items()} == {k:v['pid'] for k,v in second['processes'].items()}
            assert 'token=' not in json.dumps(first)
            assert run('status')['status'] == 'passed'
            assert run('models')['credentialStates']['openai-codex'] == 'missing'
            assert run('tasks')['tasks'][0]['requiredTimeSeconds'] > 3600
            init = ('experiment','init','--session','contract','--solver','openai-codex','gpt-6-sol','--meta','openai-codex','gpt-6-astra')
            plan = run(*init); replay = run(*init)
            assert plan['config'] == replay['config'] and replay['reused']
            assert plan['config']['maxTrials'] == plan['config']['concurrency'] == 1
            assert run('experiment','status','--session','contract',expected=3)['status'] == 'pending'
            # init must not create an activity or call a model. stop-local refuses active activities.
            run('stop-local'); started = False
            assert run('status',expected=3)['control'] == 'unavailable'
            print(json.dumps({'status':'passed','modelRequests':0,'scope':'real local control/UI start, repeat, init, status, clean stop; synthetic task metadata'}))
        finally:
            if started:
                run('stop-local')


if __name__ == '__main__': main()

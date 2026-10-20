"""Actual control API + native workbench, with a local model and no experiment execution."""
import argparse
import sys
import threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.control.service import ControlService
from src.control.server import make_app
from model_provider import server

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('--data-dir', type=Path, required=True)
parser.add_argument('--port', type=int, default=18512)
parser.add_argument('--provider-port', type=int, default=18513)
args = parser.parse_args()
remote = server(args.provider_port)
threading.Thread(target=remote.serve_forever, daemon=True).start()
service = ControlService(ROOT, args.data_dir, ROOT.parent/'Quantum-Harbor', f'http://127.0.0.1:{args.port}')
service._prepare_h0 = lambda campaign: service.store.candidate(campaign,
    {'id': 'provider-ui-fixture', 'path': '/fixture/no-experiment', 'plugins': []},
    'UI 验证夹具，未运行科学实验', check={'status': 'passed', 'fixture': True})
import uvicorn
uvicorn.run(make_app(service, supervise=False), host='127.0.0.1', port=args.port, log_level='warning')

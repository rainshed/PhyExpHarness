"""Prepare exact CLI/SDK images for isolated reference contract tests (no model calls)."""
import argparse
import json
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.control.reference.runtime import prepare_image
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',default='phyexp-runner:0.2.1-rc.2');p.add_argument('--output',type=Path,default=ROOT/'.runtime/reference-acceptance');a=p.parse_args()
a.output.mkdir(parents=True,exist_ok=True)
base=subprocess.check_output(['docker','image','inspect',a.base,'--format','{{.Id}}'],text=True).strip()
rows={h:prepare_image(ROOT,a.output,h,base,a.output/(h+'-build.log')) for h in ('dsh-standard','codex','claude-code')}
(a.output/'images.json').write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps({'status':'prepared','receipt':str(a.output/'images.json'),'realModelCalls':0}))

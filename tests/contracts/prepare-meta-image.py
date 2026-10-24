"""Prepare explicit native + legacy Meta fixture dependencies, without replacing production tags."""
import argparse,hashlib,json,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from src.control.meta_native_composition import prepare_image

p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
args.output.mkdir(parents=True,exist_ok=True)
base=prepare_image(ROOT,args.output/'cache')
package=ROOT/'node_modules/@deepseek-ai/dsh-tool-cordis'
locked=json.loads((ROOT/'package-lock.json').read_text())['packages']['node_modules/@deepseek-ai/dsh-tool-cordis']
assert json.loads((package/'package.json').read_text())['version']==locked['version']
# The current native Meta no longer uses this historical package. Only the
# fixture image adds it, so old contract tests do not accidentally use H0's SDK image.
inputs={'base':base,'package':{k:locked[k] for k in ('version','resolved','integrity')},
        'files':{str(f.relative_to(package)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(package.rglob('*')) if f.is_file()}}
key=hashlib.sha256(json.dumps(inputs,sort_keys=True).encode()).hexdigest();tag='phyexp-contract-meta:'+key
context=args.output/key;context.mkdir(exist_ok=True)
shutil.copytree(package,context/'package',dirs_exist_ok=True)
(context/'Dockerfile').write_text('FROM '+base+'\nCOPY package/ /opt/phyexp/node_modules/@deepseek-ai/dsh-tool-cordis/\n')
with (context/'build.log').open('w') as log:
 subprocess.run(['docker','build','-t',tag,str(context)],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=600)
image=subprocess.check_output(['docker','image','inspect',tag,'--format','{{.Id}}'],text=True).strip()
receipt={'image':image,'inputs':inputs,'scope':'scripted native/legacy contracts only; no scientific execution change'}
(args.output/'receipt.json').write_text(json.dumps(receipt,indent=2));print(image)

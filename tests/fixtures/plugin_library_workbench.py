"""Disposable UI acceptance instance. Synthetic builds and no model execution."""
import argparse,json,sys,tempfile,time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from src.control.service import ControlService
from src.control.server import make_app
from src.control.store import Refused
from src.control.h0 import defaults
from src.execution.bundle.project import source_tar,SourceFiles
from src.execution.bundle.manifest import digest
from tests.fixtures.benchmark_tasks import make_tasks
import uvicorn

class DemoService(ControlService):
    def create(self,config,key,*args,**kwargs):return super().create({**config,'fixture':True},key,*args,**kwargs)
    def _prepare_h0(self,campaign):return self.build_candidate(campaign,[],'H0 · 合成界面验收')
    def control(self,campaign,action,*args,**kwargs):
        if action in ('start','resume'):raise Refused('这是合成界面验收实例；模型执行已禁用。')
        return super().control(campaign,action,*args,**kwargs)

def seed(service):
    lib=service.plugin_library;defaults(service)
    model={'provider':'openai-codex','model':'gpt-6-sol','reasoningEffort':'medium'}
    cfg={'fixture':True,'solver':model,'meta':model,'tasks':['time_budgeted_hamlearn_10q'],'wallTimeSeconds':3600,'concurrency':1,'executionContract':'harbor-process-v1',
         'executionResources':json.loads((ROOT/'schemas/execution/process-resources.json').read_text())}
    for i in range(2):
        c=service.store.create({**cfg,'name':'合成来源活动 '+str(i+1)},'origin-'+str(i))
        if service.store.list('candidates',c['id']):continue
        root=service.workspace(c['id'])/'helper';root.mkdir(exist_ok=True)
        import shutil
        shutil.copytree(ROOT/'templates/harness/default',root,dirs_exist_ok=True)
        directory=root/'plugins/context-note';directory.mkdir(exist_ok=True)
        manifest={'name':'context-note','version':'1.0.0','displayName':'任务上下文说明','functionSummary':'合成样例：验证版本来源、配置和组合操作','mechanism':'加载后保留配置，不改变科学求解行为。','limitations':['仅用于界面验收，不证明任务效果'],
                  'assembly':{'contract':'dsh-plugin-v1','entry':'index.mjs','requires':[],'conflicts':[],
                  'configSchema':{'type':'object','properties':{'note':{'type':'string'}},'additionalProperties':False},'defaultConfig':{'note':'合成说明'}}}
        (directory/'plugin.json').write_text(json.dumps(manifest,ensure_ascii=False));(directory/'index.mjs').write_text("export const name='context-note';export function apply(ctx,config){}\n// synthetic revision "+str(i))
        spec=json.loads((root/'harness.json').read_text());spec['plugins']=[{'name':'context-note','path':'plugins/context-note','config':{'note':'origin'}}];spec['runtimeConfig']['plugins']=[];(root/'harness.json').write_text(json.dumps(spec))
        candidate=service.build_candidate(c['id'],[],'未采用的合成版本',project_path='helper')
        if i:
            (directory/'index.mjs').write_text('export const invalid = ; // failed synthetic revision')
            with patch('src.execution.bundle.project.build',side_effect=RuntimeError('合成构建错误：语法不完整')):
                try:service.build_candidate(c['id'],[],'失败快照',project_path='helper')
                except RuntimeError:pass
    files=SourceFiles();files['index.mjs']=b'// historical framework-specific source'
    lib.save(files,{'name':'legacy-example','version':'0.1','displayName':'旧框架样例'}, {'kind':'fixture'})

def seed_pagination(library,count):
    for i in range(count):
        files=SourceFiles();files['index.mjs']=b'export function apply(){}'
        library.save(files,{'name':'pagination-fixture','displayName':'分页验收样例','version':str(i+1),
                            'assembly':{'contract':'dsh-plugin-v1','entry':'index.mjs'}},{'kind':'fixture'})

def main():
    p=argparse.ArgumentParser();p.add_argument('--data-dir',type=Path,required=True);p.add_argument('--port',type=int,default=18572);p.add_argument('--pagination-versions',type=int,default=0);args=p.parse_args()
    args.data_dir.mkdir(parents=True,exist_ok=True)
    service=DemoService(ROOT,args.data_dir,make_tasks(args.data_dir/'synthetic-tasks',['time_budgeted_hamlearn_10q','logical_cnot_decoder_calibration']),f'http://127.0.0.1:{args.port}')
    # Isolated fixture capacity; production policy is unchanged.
    service.storage.configure({'minFreeBytes':128*1024**2,'criticalFreeBytes':64*1024**2,'resumeMarginBytes':16*1024**2})
    def built(contents,spec,cache,log,resources,**kwargs):
        folder=args.data_dir/'synthetic-builds';folder.mkdir(exist_ok=True)
        body=source_tar(contents);artifact=folder/(digest(body)+'.tar');artifact.write_bytes(body)
        return artifact,{'status':'passed','fixture':True,'artifactSha256':digest(body),'inputs':{'sources':{n:digest(v) for n,v in contents.items()},'sourceModes':contents.modes}}
    with patch('src.execution.bundle.project.build',side_effect=built):
        seed(service)
        seed_pagination(service.plugin_library,args.pagination_versions)
        print(json.dumps({'fixture':True,'models':'disabled','url':service.base_url}),flush=True)
        try:uvicorn.run(make_app(service),host='127.0.0.1',port=args.port,log_level='warning')
        finally:service.pool.shutdown()
if __name__=='__main__':main()

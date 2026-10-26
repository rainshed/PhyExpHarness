"""Thin Harbor adapter: deploy a candidate process, supervise, preserve native exit semantics."""
import asyncio
import base64
import json
import os
import re
import secrets
import shlex
import subprocess
import tempfile
import time
from pathlib import Path
from harbor.agents.base import BaseAgent
from harbor.agents.installed.base import NonZeroAgentExitCodeError
from harbor.trial.errors import AgentTimeoutError
from ...bundle.manifest import resolve
from ...host.task_network import restrict_main
from ...host.task_time import start_solver_clock, ActivityDeadlineError
from ...process.binding import binding


async def docker(*args, check=True):
    process = await asyncio.create_subprocess_exec('docker', *map(str,args), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await process.communicate()
    if check and process.returncode: raise RuntimeError('Container operation failed: '+err.decode()[-4000:])
    return out.decode().strip()


class ProcessHarborAgent(BaseAgent):
    @staticmethod
    def name(): return 'phyexp-harbor-process'
    def version(self): return '1.0.0'
    def __init__(self,*args,bundle_root,deadline,benchmark_time=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.resolved=resolve(bundle_root);self.bundle=self.resolved.manifest
        self.recipe=json.loads(self.resolved.asset('recipe.json').read_text())
        if self.model_name != self.recipe['provider']+'/'+self.recipe['model']: raise ValueError('Fixed Solver mismatch')
        self.deadline=float(deadline);self.activity_deadline=self.deadline;self.timing=benchmark_time
        self.logs=self.logs_dir.parent/'phyexp';self.logs.mkdir(parents=True,exist_ok=True)
        self.broker=None
    def save(self,name,value): (self.logs/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    async def setup(self,environment):
        project=self.logs_dir.parent.name  # Actual session identity comes from Harbor, not candidate input.
        project=environment.session_id.lower()
        if not re.match('[a-z0-9]',project): project='0'+project
        project=re.sub('[^a-z0-9_-]','-',project)
        containers={}
        for role in ('main','qsim'):
            ids=(await docker('ps','-q','--filter','label=com.docker.compose.project='+project,'--filter','label=com.docker.compose.service='+role)).split()
            if len(ids)!=1: raise RuntimeError('Expected one task '+role+' container')
            containers[role]=ids[0]
        self.main=containers['main'];self.qsim=containers['qsim']
        self.task_resources={}
        for role,container in containers.items():
            host=json.loads(await docker('inspect',container))[0]['HostConfig']
            self.task_resources[role]={key:host.get(key) for key in ('Memory','NanoCpus','CpuQuota','CpuPeriod','PidsLimit','CapDrop','SecurityOpt','PidMode')}
        self.save('task-resources.json',self.task_resources)
        info=json.loads(await docker('inspect',self.main))[0]
        if info['HostConfig'].get('PidMode')=='host': raise RuntimeError('Candidate requires a private PID namespace')
        self.network=await asyncio.to_thread(restrict_main,self.main,self.qsim,os.environ.get('PHYEXP_LAUNCH_ID'))
        self.save('isolation.json',{**containers,'network':self.network,'runContract':'harbor-process-v1','bundleId':self.bundle['id']})
        self.save('load-receipt.json',{'bundleId':self.bundle['id'],'sources':self.bundle['sources'],
            'artifact':self.bundle['artifact'],'project':self.bundle['project'],'adapter':self.bundle['adapter']})
        (self.logs/'container-images.txt').write_text(await docker('inspect',self.main,self.qsim,'--format','{{json .Name}} {{json .Image}}'))
        await environment.upload_file(self.resolved.asset('candidate.tar'),'/tmp/phyexp-candidate.tar')
        command="import tarfile,hashlib; p='/tmp/phyexp-candidate.tar'; assert hashlib.file_digest(open(p,'rb'),'sha256').hexdigest()=="+repr(self.bundle['buildReceipt']['artifactSha256'])+"; tarfile.open(p).extractall('/opt/harness',filter='data')"
        result=await environment.exec(command='python3 -c '+shlex.quote(command),cwd='/app',timeout_sec=120)
        if result.return_code: raise RuntimeError('Candidate deployment failed: '+str(result.stderr))
    async def run(self,instruction,environment,context):
        if self.timing:
            timing=start_solver_clock(self.timing,self.activity_deadline,time.time(),self.recipe.get('timePolicy'))
            self.deadline=timing['solverDeadline'];self.save('timing.json',timing)
        endpoints=[{'name':s.name,'transport':s.transport,'url':s.url} for s in self.mcp_servers]
        resources=self.recipe['processResources']
        (self.logs/'instruction.md').write_text(instruction)
        runtime={'bundleId':self.bundle['id'],'model':self.recipe['model'],'provider':self.recipe['provider'],'status':'running'}
        self.save('runtime-summary.json',runtime)
        credentials=binding(self.recipe,self.deadline)
        # Opaque, random Trial credential with a non-account payload. Native
        # Codex protocol clients decode the account claim locally before HTTP;
        # the broker authenticates exact bytes and replaces upstream headers.
        encoded=base64.b64encode(json.dumps({'https://api.openai.com/auth':{'chatgpt_account_id':'trial'},'exp':self.deadline}).encode()).decode()
        token='eyJhbGciOiJIUzI1NiJ9.'+encoded+'.'+secrets.token_urlsafe(48)
        self.broker='phyexp-broker-'+secrets.token_hex(12)
        egress='phyexp-egress-'+secrets.token_hex(12)
        process=None
        with tempfile.TemporaryDirectory(prefix='phyexp-model-') as temp:
            temp=Path(temp);os.chmod(temp,0o700)
            config={'binding':credentials,'token':token,'deadline':int(self.deadline*1000),
                    'requestBytes':resources['broker']['requestBytes'],'audit':'/audit/gateway-audit.jsonl'}
            (temp/'binding.json').write_text(json.dumps(config));(temp/'binding.json').chmod(0o600)
            (temp/'broker.mjs').write_bytes(self.resolved.asset('src/execution/process/broker.mjs').read_bytes())
            try:
                caps=resources['broker']
                await docker('network','create','--label','phyexp.launch='+os.environ.get('PHYEXP_LAUNCH_ID',self.logs.parent.name),egress)
                await docker('run','-d','--name',self.broker,'--label','phyexp.launch='+os.environ.get('PHYEXP_LAUNCH_ID',self.logs.parent.name),
                    '--network',egress,
                    '--user','0:0','--cap-drop=ALL','--security-opt=no-new-privileges','--read-only',
                    '--cpus',caps['cpus'],'--memory',caps['memoryBytes'],'--pids-limit',caps['pids'],
                    '-v',str(temp)+':/broker:ro','-v',str(self.logs)+':/audit:rw',
                    '--entrypoint','node',resources['brokerImage'],'/broker/broker.mjs','/broker/binding.json')
                await docker('network','connect','--alias','model-broker',self.network,self.broker)
                broker_info=json.loads(await docker('inspect',self.broker))[0]
                address=broker_info['NetworkSettings']['Networks'][self.network]['IPAddress']
                self.save('model-lease.json',{'deadline':self.deadline,'broker':self.broker,
                    'model':self.recipe['model'],'resources':caps,'image':broker_info['Image']})
                # Readiness is transport-only; it makes no provider/model request.
                for _ in range(100):
                    if '"ready":true' in await docker('logs',self.broker): break
                    state=json.loads(await docker('inspect',self.broker))[0]['State']
                    if not state['Running']: raise RuntimeError('Model broker exited during startup')
                    await asyncio.sleep(.05)
                else: raise TimeoutError('Model broker did not become ready')
                public={'runContract':'harbor-process-v1','bundleId':self.bundle['id'], 'instruction':instruction,
                    'workspace':'/app','mcpServers':endpoints,'deadline':self.deadline,'outputDirectory':'/tmp/phyexp-output',
                    'solver':{k:self.recipe[k] for k in ('provider','model','reasoningEffort','maxTokens') if k in self.recipe},
                    'modelChannel':{'url':'http://'+address+':8080','protocol':credentials['protocol'],
                                    'codexSubscription':credentials.get('codexSubscription',False)},
                    'resources':{**resources,'task':self.task_resources},'config':self.bundle['project'].get('runtimeConfig',{})}
                self.save('environment.json',public)
                # Only the short Trial token enters main. Its host copy is ephemeral.
                public['modelChannel']['token']=token
                (temp/'context.json').write_text(json.dumps(public))
                await environment.upload_file(temp/'context.json','/tmp/phyexp-context.json')
                entry=self.bundle['project']['entrypoint'];argv=['/opt/harness/'+entry[0],*entry[1:]]
                # argv is executed in main, never interpreted by the host shell.
                args=['docker','exec','-w','/app','-e','PHYEXP_CONTEXT=/tmp/phyexp-context.json',self.main,*argv]
                if time.time()>=self.deadline:raise asyncio.TimeoutError('Deadline reached during process preparation')
                with (self.logs/'candidate.stdout').open('wb') as stdout,(self.logs/'candidate.stderr').open('wb') as stderr:
                    process=await asyncio.create_subprocess_exec(*args,stdout=stdout,stderr=stderr)
                    code=await asyncio.wait_for(process.wait(),max(.001,self.deadline-time.time()))
                runtime.update(status='completed' if code==0 else 'nonzero_exit',exitCode=code)
                if code:runtime['failureDetectedAt']=time.time()
                if code: raise NonZeroAgentExitCodeError('Candidate exited '+str(code)+'; see phyexp/candidate.stderr')
            except (asyncio.TimeoutError,asyncio.CancelledError):
                runtime['status']='timed_out' if time.time()>=self.deadline else 'cancelled'
                if runtime['status']=='timed_out':
                    if self.timing and timing.get('deadlineCause')=='campaign_deadline':
                        runtime['status']='campaign_deadline'
                        raise ActivityDeadlineError('Activity deadline reached during Solver execution')
                    raise AgentTimeoutError('Benchmark solver deadline reached')
                raise
            except Exception as error:
                if runtime['status']=='running':runtime.update(status='error',exception={'type':type(error).__name__,'message':str(error)})
                raise
            finally:
                if self.timing:
                    timing['solverFinishedAt']=time.time();self.save('timing.json',timing)
                # External process ownership: all candidate children share main's
                # private PID namespace. kill(-1) excludes PID 1 and the caller;
                # no task sidecar or other Trial shares this namespace.
                await docker('rm','-f',self.broker,check=False)
                await docker('network','rm',egress,check=False)
                await docker('exec',self.main,'/bin/kill','-KILL','-1',check=False)
                if process and process.returncode is None:
                    process.terminate()
                    try: await asyncio.wait_for(process.wait(),5)
                    except asyncio.TimeoutError: process.kill();await process.wait()
                self.save('runtime-summary.json',runtime)
                # Candidate diagnostics are optional, and cannot veto verification.
                (self.logs/'candidate-output').mkdir(exist_ok=True)
                copied=await docker('cp',self.main+':/tmp/phyexp-output/.',str(self.logs/'candidate-output'),check=False)
                events=self.logs/'candidate-output/events.json'
                if events.is_file(): (self.logs/'events.json').write_bytes(events.read_bytes())

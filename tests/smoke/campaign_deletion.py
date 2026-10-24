"""Real engine deletion smoke: only uniquely named synthetic resources, no models."""
import argparse
import json
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from src.control.service import ControlService


def docker(*args):return subprocess.check_output(['docker',*args],text=True,stderr=subprocess.PIPE).strip()


def run(image,build_image=None):
    token='phyexp-delete-test-'+uuid.uuid4().hex[:12]
    names={key:token+'-'+key for key in ('owned','keep','volume','keep-volume','network')}
    service=None
    with tempfile.TemporaryDirectory(prefix='phyexp-delete-engine-') as temporary:
        data=Path(temporary).resolve()
        try:
            service=ControlService(ROOT,data,ROOT.parent/'Quantum-Harbor','http://127.0.0.1:1')
            model={'provider':'openai-codex','model':'gpt-6-sol','reasoningEffort':'medium'}
            c=service.store.create({'name':'engine deletion fixture','solver':model,'meta':model,'tasks':['time_budgeted_hamlearn_10q'],
                'concurrency':1,'wallTimeSeconds':3600,'maxRounds':1,'maxTrials':1},token)['id']
            output=data/'trials'/token;output.mkdir(parents=True)
            (output/'provenance.json').write_text('{"fixture":true}')
            service.store.put('trials',{'id':'trial-'+token,'campaignId':c,'state':'finished','output':str(output),'launchId':token})
            docker('network','create','--internal','--label','phyexp.launch='+token,names['network'])
            docker('volume','create','--label','com.docker.compose.project='+token,names['volume'])
            docker('volume','create','--label','com.docker.compose.project='+token+'-keep',names['keep-volume'])
            docker('run','-d','--rm','--entrypoint','sh','--name',names['owned'],'--label','com.docker.compose.project='+token,
                   '--network',names['network'],'--mount','type=bind,source='+str(output)+',target=/fixture',
                   '--mount','type=volume,source='+names['volume']+',target=/data',image,'-c','sleep 120')
            docker('run','-d','--rm','--entrypoint','sh','--name',names['keep'],'--label','com.docker.compose.project='+token+'-keep',
                   '--network','none','--mount','type=volume,source='+names['keep-volume']+',target=/data',image,'-c','sleep 120')
            assert docker('inspect',names['owned'],'--format','{{.State.Running}}')=='true'
            preview=service.deletions.preview(c)
            assert not preview['blockers'],preview
            service.deletions.request(c,preview['expectedRevision'],token)
            service.deletions.advance(c)
            assert service.store.deletion(c)['state']=='deleted',service.store.deletion(c)
            assert not output.exists()
            assert names['owned'] not in docker('ps','-a','--format','{{.Names}}').splitlines()
            assert names['volume'] not in docker('volume','ls','--format','{{.Name}}').splitlines()
            assert names['network'] not in docker('network','ls','--format','{{.Name}}').splitlines()
            assert docker('inspect',names['keep'],'--format','{{.State.Running}}')=='true'
            assert names['keep-volume'] in docker('volume','ls','--format','{{.Name}}').splitlines()
            if build_image:
                from src.execution.bundle.project import freeze_project
                config={'name':'v3 build deletion fixture','solver':model,'meta':model,'tasks':['time_budgeted_hamlearn_10q'],
                        'concurrency':1,'wallTimeSeconds':3600,'maxRounds':1,'maxTrials':1}
                build_campaign=service.store.create(config,token+'-build')['id']
                source=data/'campaigns'/build_campaign/'project';source.mkdir(parents=True)
                (source/'harness.json').write_text(json.dumps({'runContract':'harbor-process-v1','entrypoint':['run.sh'],
                    'build':{'image':build_image,'argv':['sh','-c','chmod +x run.sh'],'locks':[]}}))
                (source/'run.sh').write_text('#!/bin/sh\nexit 0\n')
                resources=json.loads((ROOT/'schemas/execution/process-resources.json').read_text())['build']
                with (source.parent/'build.log').open('w') as log:
                    bundle=freeze_project(ROOT,data/'objects/sha256',source,{'fixture':True},data/'cache/project-builds',log,resources,
                        on_publish=lambda path,kind:service.store.track_artifact(build_campaign,path,kind))
                service.store.candidate(build_campaign,bundle,'real isolated build',check={'status':'passed'})
                assert list((data/'cache/project-builds').glob('*.tar'))
                preview=service.deletions.preview(build_campaign);assert not preview['blockers'],preview
                service.deletions.request(build_campaign,preview['expectedRevision'],token+'-delete-build')
                service.deletions.advance(build_campaign)
                assert service.store.deletion(build_campaign)['state']=='deleted',service.store.deletion(build_campaign)
                assert not source.exists()
                assert not any((data/'cache/project-builds').iterdir())
                assert not any((data/'objects/sha256').iterdir())
                assert docker('inspect',names['keep'],'--format','{{.State.Running}}')=='true'
            return {'status':'passed','ownedContainerVolumeNetworkRemoved':True,'unrelatedResourcesPreserved':True,
                    'v3BuildDeleted':bool(build_image),'modelCalls':0}
        finally:
            if service:service.pool.shutdown(wait=True)
            for kind,keys in [('container',('owned','keep')),('volume',('volume','keep-volume')),('network',('network',))]:
                for key in keys:subprocess.run(['docker',kind,'rm',*(['-f'] if kind=='container' else []),names[key]],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--image',default='phyexp-runner:0.2.1-rc.2')
    parser.add_argument('--build-image',help='Optional local shell image for a real v3 build/cache deletion check')
    args=parser.parse_args();print(json.dumps(run(args.image,args.build_image)))

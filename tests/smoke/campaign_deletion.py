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


def run(image):
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
            return {'status':'passed','ownedContainerVolumeNetworkRemoved':True,'unrelatedResourcesPreserved':True,'modelCalls':0}
        finally:
            if service:service.pool.shutdown(wait=True)
            for kind,keys in [('container',('owned','keep')),('volume',('volume','keep-volume')),('network',('network',))]:
                for key in keys:subprocess.run(['docker',kind,'rm',*(['-f'] if kind=='container' else []),names[key]],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--image',default='phyexp-runner:0.2.1-rc.2')
    print(json.dumps(run(parser.parse_args().image)))

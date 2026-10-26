"""Complete candidate development through the existing check/freeze operations."""
import json
import shutil
import time
from pathlib import Path
from .operations import workspace_path
from .store import Refused, identity
from src.execution.bundle.project import freeze_project
from src.execution.bundle.manifest import infrastructure_identity, verify
from src.execution.host.models import campaign_route
from src.execution.host.task_time import POLICY


def build_candidate(service,campaign,project_path,description,parent=None,display_name=None,check_only=False,research_refs=None):
    service.store.writable(campaign)
    activity=service.store.get('campaigns',campaign);config=activity['config']
    initial_state=activity['state']
    def cancelled():
        if service.store.deletion(campaign):return True
        current=service.store.get('campaigns',campaign)
        return (current['state']!=initial_state and current['state'] in ('paused','closing','finished','failed','deleting') or
                current.get('deadline') is not None and time.time()>=current['deadline'])
    workspace=service.workspace(campaign)
    if project_path is None:
        project=workspace/'h0'
        if not project.exists(): shutil.copytree(service.source/'templates/harness/default',project)
    else:
        project=workspace_path(workspace,project_path.removeprefix('/work/plugins/'))
    if not project.is_dir(): raise Refused('Candidate project directory is missing')
    recipe={**config['solver'],'providerConfig':campaign_route(config,'solver'),'timePolicy':config.get('executionTimePolicy',{}).get('version',POLICY),
            'processResources':config['executionResources']}
    logs=service.data/'campaigns'/campaign/'checks'/identity('check');logs.mkdir(parents=True)
    try:
        with (logs/'build.log').open('w') as log:
            frozen=freeze_project(service.source,service.data/'objects/sha256',project,recipe,service.data/'cache/project-builds',log,
                config['executionResources']['build'],cancel=cancelled,on_publish=lambda path,kind:service.store.track_artifact(campaign,path,kind))
        previous=service.store.list('candidates',campaign)
        if previous and infrastructure_identity(verify(previous[0]['bundlePath']))!=infrastructure_identity(frozen['manifest']):
            raise Refused('External runtime contract changed; use a new activity for the new conditions')
        check={'status':'passed','checkKind':'isolated-build-and-entrypoint','evidence':str(logs),
               'build':frozen['manifest']['buildReceipt'],'generalization':'not_verified','realModelCalls':0}
        (logs/'assembly.json').write_text(json.dumps(check,indent=2))
    except Exception as error:
        error.check_files=[service.meta_api.files.publish(campaign,'check:'+logs.name+':'+p.name,p.read_bytes(),
            kind='check',source={'archive':p.name}) for p in sorted(logs.iterdir()) if p.is_file()]
        raise
    if check_only:
        files=[service.meta_api.files.publish(campaign,'check:'+logs.name+':'+p.name,p.read_bytes(),
            kind='check',source={'archive':p.name},version=frozen['id']) for p in sorted(logs.iterdir()) if p.is_file()]
        return {'checkId':logs.name,'status':'passed','bundleId':frozen['id'],'files':files,'trialCreated':False}
    row=service.store.candidate(campaign,frozen,description,parent,check,research_refs)
    row.update(project=frozen['manifest']['project'],candidateSources=frozen['manifest']['sources'],
               executionContract='harbor-process-v1')
    if display_name: row['displayName']=display_name.strip()[:80]
    return service.store.put('candidates',row)

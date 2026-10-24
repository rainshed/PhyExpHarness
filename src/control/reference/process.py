"""Bind an explicitly authorized reference model to the same complete candidate.

Only this optional control plugin selects a reference. The candidate's source,
artifact and execution contract are retained; the primary Solver is unchanged.
"""
import hashlib,json
from pathlib import Path
from ..store import Refused
from .catalog import uses_codex_host
from src.execution.bundle.freeze import _publish
from src.execution.bundle.manifest import resolve,canonical,digest


def model_route(snapshot):
    call=snapshot['call'];config=snapshot.get('config',{})
    if uses_codex_host(snapshot):
        return {'adapter':'pi-ai','auth':{'type':'codex'},'models':[{'id':call['model']}]}
    profile=config.get('providers',{}).get(call['provider'],config)
    deepseek=snapshot['adapter']=='deepseek-api-key'
    api='anthropic-messages' if deepseek else profile.get('api')
    base=profile.get('baseURL') or ('https://api.deepseek.com/anthropic' if deepseek else None)
    if api not in ('anthropic-messages','openai-responses','openai-completions') or not base:
        raise Refused('Complete candidate model channel requires an explicit supported HTTP/SSE route for this reference model')
    return {'adapter':'deepseek' if deepseek else 'pi-ai','api':api,'baseURL':base,
            'headers':profile.get('headers',{}),'auth':{'type':'api-key','env':'PHYEXP_REFERENCE_NATIVE_KEY'},
            'models':profile.get('models',[{'id':call['model']}])}


def bind_model(service,campaign,candidate,snapshot,model_ref):
    resolved=resolve(candidate['bundlePath']);raw=json.loads((Path(candidate['bundlePath'])/'bundle.json').read_text())
    recipe=json.loads(resolved.asset('recipe.json').read_text())
    for key in ('provider','model','reasoningEffort','maxTokens'):recipe.pop(key,None)
    recipe.update({k:v for k,v in snapshot['call'].items() if k in ('provider','model','reasoningEffort','maxTokens')},providerConfig=model_route(snapshot))
    recipe_bytes=canonical(recipe)+b'\n';raw['recipeDigest']=digest(recipe_bytes)
    raw.pop('id');raw['id']=digest(canonical(raw))
    path=_publish(service.data/'objects/sha256',raw['id'],{'bundle.json':canonical(raw)+b'\n','recipe.json':recipe_bytes},
                  lambda path,kind:service.store.track_artifact(campaign,path,kind),'bundle')
    # Reference bindings reuse the candidate's existing sibling content objects.
    if resolve(path).manifest['artifact']!=resolved.manifest['artifact']:raise Refused('Reference changed the candidate artifact')
    env={}
    if not uses_codex_host(snapshot):
        credential=json.loads((service.references.catalog.root/'credentials'/(model_ref+'.json')).read_text())
        if not isinstance(credential.get('value'),str) or not credential['value']:raise Refused('Reference credential is unavailable')
        env['PHYEXP_REFERENCE_NATIVE_KEY']=credential['value']
    return {'bundleId':raw['id'],'bundlePath':str(path),'executionContract':'harbor-process-v1'},env


def prepare_harness_base(service,campaign):
    """Keep an explicit, versioned legacy preset for existing reference CLIs.

    It is an alternate reference Harness, never a fallback for the v3 candidate.
    """
    from src.execution.bundle.freeze import freeze
    from src.execution.host.models import campaign_route
    from ..execution_cache import prepare_runtime
    from ..runner_images import prepare_runner_image
    c=service.store.get('campaigns',campaign);cfg=c['config']
    recipe=json.loads((service.source/'recipes/h0-sol.json').read_text())
    recipe.update(cfg['solver'],providerConfig=campaign_route(cfg,'solver'),modules=[])
    if 'reasoningEffort' not in cfg['solver']:recipe.pop('reasoningEffort',None)
    recipe['timePolicy']='benchmark-time-v1';recipe.pop('agentTimeoutSec',None);recipe.pop('commandTimeoutSec',None)
    bundle=freeze(service.source,service.data/'objects/sha256',recipe,[],service.knowledge_for(campaign).manifest,
                  on_publish=lambda path,kind:service.store.track_artifact(campaign,path,kind))
    runtime=prepare_runtime(bundle['path'],service.data/'cache')
    log_path=service.data/'campaigns'/campaign/'reference-base.log'
    with log_path.open('w') as log:prepare_runner_image(runtime,service.data/'runner-locks',log)
    with service.store.connection(True) as db:
        current=service.store._get(db,'campaigns',campaign)
        current['config']['referenceBindings']['baseBundle']={'bundleId':bundle['id'],'bundlePath':bundle['path'],'executionContract':'legacy-reference-preset-v2'}
        service.store._save(db,'campaigns',current)
    return bundle['manifest']

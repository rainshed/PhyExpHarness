"""Trusted deployment catalog. Snapshots contain routing facts and credential references only."""
import copy
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from jsonschema import Draft7Validator

HERE=Path(__file__).parent
SCHEMA=json.loads((HERE/'provider-config.schema.json').read_text())

def validate_provider_config(config):
    error=next(Draft7Validator(SCHEMA).iter_errors(config),None)
    if error:raise ValueError('Invalid provider configuration at '+'.'.join(map(str,error.absolute_path)))
    for id,route in config['providers'].items():
        auth=route['auth']['type']
        if id=='openai-codex':
            if route['adapter']!='pi-ai' or auth!='codex' or 'api' in route or 'baseURL' in route or route.get('preflightURL')!='https://chatgpt.com/backend-api/codex/responses':
                raise ValueError('openai-codex must retain the original Codex subscription route')
        elif auth=='codex':raise ValueError('Codex authentication is only supported on openai-codex')
        elif not route.get('baseURL'):raise ValueError('baseURL is required for '+id)
        if route['adapter']=='pi-ai' and id!='openai-codex' and not route.get('api'):
            raise ValueError('An explicit supported api is required for '+id)
        if route['adapter']=='deepseek' and (id!='deepseek-official' or auth!='api-key' or 'api' in route or 'compat' in route or 'transport' in route):
            raise ValueError('Native DeepSeek requires deepseek-official and api-key authentication')
        for key in ['baseURL','preflightURL']:
            if key not in route:continue
            u=urlsplit(route[key])
            if not u.hostname or u.username is not None or u.password is not None or u.query or u.fragment or not (u.scheme=='https' or u.scheme=='http' and u.hostname in ['localhost','127.0.0.1','::1']):
                raise ValueError('Endpoint must be HTTPS or loopback HTTP without credentials/query/fragment: '+id)
        ids=set()
        for model in route['models']:
            if model['id'] in ids:raise ValueError('Duplicate model in '+id)
            ids.add(model['id'])
            efforts=model['reasoningEfforts']
            if efforts is False:
                if 'defaultReasoningEffort' in model:raise ValueError('Non-reasoning model cannot declare an effort default')
            else:
                if model.get('defaultReasoningEffort') not in efforts:raise ValueError('Invalid defaultReasoningEffort in '+id)
                if any(v=='' or v is None and k!='off' for k,v in efforts.items()):raise ValueError('Invalid reasoning effort mapping in '+id)
                if route['adapter']=='pi-ai' and set(efforts)=={'off'}:raise ValueError('Use false for a non-reasoning model')
            if route['adapter']=='deepseek' and (efforts is False or any(k not in ['off','low','high','max'] or v!=k for k,v in efforts.items()) or 'compat' in model):
                raise ValueError('Native DeepSeek supports off/low/high/max without protocol overrides')
    return config

def load_model_config(path=None):
    config=json.loads((HERE/'model-catalog.json').read_text())
    path=path or os.environ.get('PHYEXP_MODEL_CONFIG')
    if path:
        extra=json.loads(Path(path).expanduser().read_text())
        # Validate the file's structure before merging; provider semantics apply to the complete result.
        error=next(Draft7Validator(SCHEMA).iter_errors(extra),None)
        if error:raise ValueError('Invalid provider configuration at '+'.'.join(map(str,error.absolute_path)))
        for id,route in extra['providers'].items():
            if len({m['id'] for m in route['models']})!=len(route['models']):raise ValueError('Duplicate model in '+id)
            if id in config['providers']:
                previous=config['providers'][id]
                models={m['id']:m for m in previous['models']}
                models.update({m['id']:m for m in route['models']})
                config['providers'][id]={**previous,**route,'models':list(models.values())}
            else:config['providers'][id]=route
    return validate_provider_config(config)

def provider_route(model,config=None):
    config=load_model_config() if config is None else config
    route=config['providers'].get(model.get('provider')) if isinstance(model,dict) else None
    entry=next((m for m in route['models'] if m['id']==model.get('model')),None) if route else None
    if entry is None:raise ValueError('Unsupported model configuration')
    return copy.deepcopy({**route,'models':[entry]})

def model_catalog(config=None):
    config=load_model_config() if config is None else config
    return [dict(provider=id,model=m['id'],name=m.get('name',m['id']),reasoningEfforts=list(m['reasoningEfforts']) if m['reasoningEfforts'] else [],
                 defaultReasoningEffort=m.get('defaultReasoningEffort'),**{k:m[k] for k in ['version','versionPolicy'] if k in m})
            for id,route in config['providers'].items() for m in route['models']]

def supported_model(model,config=None):
    if not isinstance(model,dict):return False
    try:route=provider_route(model,config)
    except ValueError:return False
    efforts=route['models'][0]['reasoningEfforts']
    return model.get('reasoningEffort') in efforts if efforts else model.get('reasoningEffort') is None


def campaign_model_config(config):
    """Budget edits and legacy resumes use the activity's trusted snapshots, not a newer deployment file."""
    routes={}
    for role in ['solver','meta']:
        model=config[role]
        route=config.get('modelRoutes',{}).get(role)
        if route is None:
            route=provider_route(model,json.loads((HERE/'model-catalog.json').read_text()))
        id=model['provider']
        if id in routes:
            route={**route,'models':list({m['id']:m for m in [*routes[id]['models'],*route['models']]}.values())}
        routes[id]=route
    return validate_provider_config({'schemaVersion':1,'providers':routes})


def campaign_route(config,role):
    route=config.get('modelRoutes',{}).get(role)
    return copy.deepcopy(route) if route else provider_route(config[role],json.loads((HERE/'model-catalog.json').read_text()))

"""Host-only Node network policy; isolated Runner never receives these settings."""
import os

def provider_environment(source=None):
    env=dict(os.environ if source is None else source)
    if any(env.get(k) for k in ['HTTPS_PROXY','https_proxy','HTTP_PROXY','http_proxy']):
        env.setdefault('NODE_USE_ENV_PROXY','1')
    for name in ['NO_PROXY','no_proxy']:
        existing=env.get(name,'')
        env[name]=','.join(x for x in [existing,'127.0.0.1','localhost','::1'] if x)
    return env

def network_preflight(model=None,route=None,environment=None):
    """Unauthenticated HEAD only: catches host connection failures without spending a Trial/model call."""
    import json,subprocess
    from .models import provider_route
    model=model or {'provider':'openai-codex','model':'gpt-6-sol','reasoningEffort':'medium'}
    route=route or provider_route(model)
    environment=provider_environment() if environment is None else environment
    if route['auth']['type']=='api-key' and not environment.get(route['auth']['env'],'').strip():
        raise RuntimeError(route['auth']['env']+' is required in the host environment')
    endpoint=route.get('preflightURL') or route['baseURL']
    script='fetch('+json.dumps(endpoint)+',{method:"HEAD",signal:AbortSignal.timeout(10000)}).then(r=>console.log(JSON.stringify({reachable:true,httpStatus:r.status,modelCall:false}))).catch(e=>{console.log(JSON.stringify({reachable:false,error:e.cause?.code||e.message,modelCall:false}));process.exitCode=1})'
    result=subprocess.run(['node','-e',script],env=environment,capture_output=True,text=True,timeout=15)
    if result.returncode:raise RuntimeError('Provider network preflight failed before Trial admission: '+result.stdout.strip())
    return json.loads(result.stdout)

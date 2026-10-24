"""Build an allowlisted, content-addressed SDK reference from the installed execution version."""
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]
SOURCES={
 'system-prompt':'@deepseek-ai/dsh-system-prompt/lib/types/index.d.ts',
 'tool-schema':'@deepseek-ai/dsh-tools/lib/types/schema.d.ts',
 'tools':'@deepseek-ai/dsh-tools/lib/types/index.d.ts',
 'llm':'@deepseek-ai/dsh-llm/lib/types/index.d.ts',
 'agent-runtime':'@deepseek-ai/dsh-agent/lib/types/runtime-types.d.ts',
 'llm-retry-policy':'@deepseek-ai/dsh-llm/lib/types/retry-policy.d.ts',
 'llm-types':'@deepseek-ai/dsh-llm/lib/types/types.d.ts',
 'session':'@deepseek-ai/dsh-session/lib/types/index.d.ts',
 'cordis':'@deepseek-ai/cordis/src/context.ts',
}
API={'agent/request-error':'agent-runtime','ctx.systemPrompt.context':'system-prompt','ctx.systemPrompt.section':'system-prompt','ctx.tools.register':'tools','tools/pre-execute':'tools','tools/post-execute':'tools','tools/result':'tools','LlmAdapter':'llm','ctx.llm.registerAdapter':'llm','ctx.llm.stream':'llm'}
GUIDES=('README.md','plugin-design.md','tools.md','subagents.md','request-recovery.md','resource-planning.md')
def build(destination):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    docs={}
    for key,source in SOURCES.items():
        p=ROOT/'node_modules'/source;text=p.read_text()
        digest=hashlib.sha256(text.encode()).hexdigest()
        (destination/(key+'.txt')).write_text(text)
        docs[key]={'file':key+'.txt','source':source,'sha256':digest}
    for key,source in {'overview':'knowledge/plugin-sdk/README.md','plugin-manifest':'schemas/execution/plugin.schema.json','example-echo':'knowledge/plugin-sdk/examples/echo.mjs'}.items():
        text=(ROOT/source).read_text();(destination/(key+'.txt')).write_text(text)
        docs[key]={'file':key+'.txt','source':source,'sha256':hashlib.sha256(text.encode()).hexdigest()}
    for name in GUIDES:
        key='guides/'+name;source='knowledge/plugin-sdk/'+key
        text=(ROOT/source).read_text(encoding='utf-8')
        target=destination/key;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(text,encoding='utf-8')
        docs[key]={'file':key,'source':source,'sha256':hashlib.sha256(text.encode()).hexdigest()}
    version=json.loads((ROOT/'node_modules/@deepseek-ai/dsh/package.json').read_text())['version']
    profile={'dshVersion':version,'profile':'sdk-minimal','extensionVersion':2,'tools':['bash','mcp__qsim__*'],'isolated':True}
    profile['assets']={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ['src/execution/runner/assets/sdk-minimal.yml','src/execution/runner/boot.mjs','src/execution/runner/isolated.mjs','src/execution/runner/gateway_plugin.mjs','src/execution/runner/request_recovery.mjs','src/execution/adapters/quantum_harbor/container_tool.mjs']}
    profile['assets'].update({str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'src/execution/recovery').glob('*.mjs'))})
    fingerprint=hashlib.sha256(json.dumps(profile,sort_keys=True).encode()).hexdigest()
    manifest={'schemaVersion':1,'dshVersion':version,'profile':profile,'profileDigest':fingerprint,'documents':docs,'api':API,'verification':'declarations; native behavior checked separately in M0 contracts'}
    manifest['id']=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
    (destination/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest
if __name__=='__main__':
    import sys
    print(build(sys.argv[1])['id'])

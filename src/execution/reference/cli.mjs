// Pure adapter launch contract; all native user/config directories are fresh.
export function cliLaunch(config,port){
 const root=`http://127.0.0.1:${port}`,model=config.fixedModel.model;
 const mcp={task:{command:'node',args:['/opt/phyexp/src/execution/reference/task-mcp.mjs',root]}};
 for(const c of config.mcpConnections||[])mcp[c.name]={type:'http',url:root+'/mcp/'+c.name};
 const env={PATH:'/opt/reference-cli/node_modules/.bin:/opt/phyexp/node_modules/.bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',HOME:'/work/home',TMPDIR:'/tmp',LANG:'C.UTF-8',NO_COLOR:'1'};
 if(config.harness==='codex'){
  const settings={model,model_provider:'reference',approval_policy:'never',sandbox_mode:'danger-full-access',
   model_providers:{reference:{name:'Frozen reference',base_url:root,env_key:'PHYEXP_REFERENCE_KEY',wire_api:'responses',request_max_retries:0,stream_max_retries:0}},
   mcp_servers:Object.fromEntries(Object.entries(mcp).map(([id,c])=>[id,c.type?{url:c.url}:c]))};
  if(config.fixedModel.reasoningEffort!==undefined)settings.model_reasoning_effort=config.fixedModel.reasoningEffort;
  return {executable:'codex',args:['exec','--json','--ephemeral','--ignore-user-config','--skip-git-repo-check',...Object.entries(settings).flatMap(([k,v])=>['-c',k+'='+toml(v)]),'-'],
   env:{...env,CODEX_HOME:'/work/home/codex',PHYEXP_REFERENCE_KEY:'isolated-reference'},input:config.prompt};
 }
 if(config.harness!=='claude-code')throw new Error('Unknown reference CLI');
 // Single-UID rootless Podman maps its unprivileged host user to container UID 0.
 // Use normal explicit tool grants so Claude's root bypass guard stays intact.
 const allowedTools=['Bash','Read','Write','Edit','Glob','Grep','NotebookEdit','TodoWrite','Agent','Task','Skill','ToolSearch',
  ...Object.keys(mcp).map(name=>'mcp__'+name+'__*')];
 return {executable:'claude',args:['-p','--output-format','stream-json','--verbose','--include-partial-messages','--no-session-persistence','--setting-sources','',
  '--strict-mcp-config','--mcp-config',JSON.stringify({mcpServers:mcp}),'--model',model,'--permission-mode','dontAsk','--allowedTools',allowedTools.join(',')],
  env:{...env,CLAUDE_CONFIG_DIR:'/work/home/claude',ANTHROPIC_BASE_URL:root,ANTHROPIC_API_KEY:'isolated-reference',
   ANTHROPIC_MODEL:model,ANTHROPIC_SMALL_FAST_MODEL:model,ANTHROPIC_DEFAULT_HAIKU_MODEL:model,ANTHROPIC_DEFAULT_SONNET_MODEL:model,ANTHROPIC_DEFAULT_OPUS_MODEL:model,
   CLAUDE_CODE_SUBAGENT_MODEL:model,CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC:'1',CLAUDE_CODE_DISABLE_AUTO_MEMORY:'1',
   ...(config.fixedModel.maxTokens!==undefined?{CLAUDE_CODE_MAX_OUTPUT_TOKENS:String(config.fixedModel.maxTokens)}:{})},input:config.prompt};
}
function toml(value){
 if(Array.isArray(value))return '['+value.map(toml).join(',')+']';
 if(value&&typeof value==='object')return '{'+Object.entries(value).map(([k,v])=>JSON.stringify(k)+'='+toml(v)).join(',')+'}';
 return JSON.stringify(value);
}

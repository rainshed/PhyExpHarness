"""Conservative external wire support; native execution retains every setting."""
def external_settings_issue(snapshot,solver,route):
    if snapshot:
        if snapshot['adapter']=='deepseek-api-key':return None
        call=snapshot['call'];profile=snapshot['config'].get('providers',{}).get(call['provider'],{})
    else:
        if route.get('adapter')=='deepseek':return None
        call=solver;profile=route
    for field in ('thinkingBudgets','cacheRetention'):
        if profile.get(field) is not None:return '原生 '+field+' 设置尚未验证外部 Harness 等价映射；可使用 DeepSeek 标准模式'
    if profile.get('transport') not in (None,'auto','sse'):return '外部 Harness 暂未验证此原生传输设置'
    effort=call.get('reasoningEffort',profile.get('reasoning'))
    if profile.get('api')=='anthropic-messages' and effort not in (None,'off'):
        return '此原生 Anthropic 推理设置的等价映射尚未验证；可使用 DeepSeek 标准模式'
    model=next((m for m in profile.get('models',[]) if m.get('id')==call.get('model')), {})
    levels=model.get('reasoningEfforts')
    if isinstance(levels,dict) and effort in levels and levels[effort] not in (None,effort):
        return '原生模型声明了自定义推理值映射，暂不允许外部 Harness 近似转换'
    return None

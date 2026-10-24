"""Provider authentication is evaluated only by the trusted host supervisor."""
import base64
import json
import os
import time
from pathlib import Path


def binding(recipe, deadline):
    route = recipe['providerConfig']
    model = {k: recipe[k] for k in ('model', 'reasoningEffort', 'maxTokens') if k in recipe}
    if route['auth']['type'] == 'codex':
        auth = json.loads(Path(os.environ.get('PHYEXP_CODEX_AUTH_FILE', Path.home()/'.codex/auth.json')).read_text())
        token = auth['tokens']['access_token']
        part = token.split('.')[1]
        claims = json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))
        if claims['exp'] < deadline + 30: raise ValueError('Model credential expires before the Trial deadline')
        account = claims['https://api.openai.com/auth']['chatgpt_account_id']
        return {'model': model, 'protocol': 'responses', 'codexSubscription': True,
                'baseURL': 'https://chatgpt.com/backend-api/codex',
                'headers': {'authorization': 'Bearer '+token, 'chatgpt-account-id': account,
                            'originator': 'codex_cli_rs', 'OpenAI-Beta': 'responses=experimental'}}
    secret = os.environ.get(route['auth']['env'], '').strip()
    if not secret: raise ValueError('Provider credential is unavailable')
    protocol = ('anthropic' if route['adapter']=='deepseek' or route.get('api')=='anthropic-messages'
                else 'responses' if route.get('api')=='openai-responses' else 'completions')
    headers = {'x-api-key':secret, 'anthropic-version':'2023-06-01'} if protocol=='anthropic' else {'authorization':'Bearer '+secret}
    return {'model':model, 'protocol':protocol, 'baseURL':route['baseURL'], 'headers':headers,
            'deepseek':route['adapter']=='deepseek'}

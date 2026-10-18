import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

// Short-lived authentication bridge. It never rotates or modifies Codex's login.
export function createChatGPTCredentials({ minimumValidityMs = 240_000 } = {}) {
  const authPath = process.env.PHYEXP_CODEX_AUTH_FILE || path.join(os.homedir(), '.codex/auth.json');
  const auth = JSON.parse(fs.readFileSync(authPath, 'utf8'));
  if (auth.auth_mode && auth.auth_mode !== 'chatgpt') throw new Error('Codex is not using ChatGPT authentication');
  const token = auth.tokens?.access_token;
  if (!token) throw new Error('No ChatGPT access token; run codex login first');
  const claims = JSON.parse(Buffer.from(token.split('.')[1], 'base64url').toString());
  const expires = claims.exp * 1000;
  if (!Number.isFinite(expires) || expires < Date.now() + minimumValidityMs) {
    throw new Error('ChatGPT access token expires too soon; refresh your Codex login first');
  }
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'phyexp-auth-'));
  const credentialFile = path.join(temp, 'credentials.json');
  try {
    fs.chmodSync(temp, 0o700);
    fs.writeFileSync(credentialFile, JSON.stringify({
      version: 1, refs: {}, records: {
        'llm-pi-ai/openai-codex': {
          kind: 'grant', payload: { type: 'oauth', access: token, refresh: '', expires },
        },
      },
    }), { mode: 0o600 });
  } catch (error) {
    fs.rmSync(temp, { recursive: true, force: true });
    throw error;
  }
  return {
    credentialFile,
    description: 'existing ChatGPT access token; no API key; no refresh token copied',
    redact: text => String(text).split(token).join('[REDACTED]'),
    dispose: () => fs.rmSync(temp, { recursive: true, force: true }),
  };
}

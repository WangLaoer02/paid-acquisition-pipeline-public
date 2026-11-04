// Attach only. Never launches/navigates/closes Chrome or copies authentication data.
import fs from 'node:fs';

const input = JSON.parse(fs.readFileSync(0, 'utf8'));
let ws;
try {
  const endpoint = new URL(input.endpoint);
  if (endpoint.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(endpoint.hostname) || endpoint.username || endpoint.password || endpoint.pathname !== '/' || endpoint.search || endpoint.hash) {
    throw new Error('CDP_ENDPOINT_MUST_BE_LOOPBACK_HTTP_ROOT');
  }
  const response = await fetch(new URL('/json/list', endpoint), {signal: AbortSignal.timeout(4000)});
  if (!response.ok) throw new Error('CDP_DISCOVERY_FAILED');
  const targets = (await response.json()).filter(t => t.type === 'page' && (() => {
    try { return new URL(t.url).origin === 'http://ai.cn.sy.backend.example.invalid'; } catch { return false; }
  })());
  const selected = input.target_id ? targets.filter(t => t.id === input.target_id) : targets;
  if (selected.length !== 1) throw new Error(selected.length ? 'MULTIPLE_AI_TABS: specify --target-id' : 'AI_TAB_NOT_FOUND');
  const socketUrl = new URL(selected[0].webSocketDebuggerUrl);
  if (!['127.0.0.1', 'localhost', '[::1]'].includes(socketUrl.hostname) || socketUrl.protocol !== 'ws:') throw new Error('NON_LOCAL_CDP_SOCKET');
  ws = new WebSocket(socketUrl);
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => { ws.close(); reject(new Error('CDP_CONNECT_TIMEOUT')); }, 8000);
    ws.addEventListener('open', () => { clearTimeout(timer); resolve(); }, {once: true});
    ws.addEventListener('error', () => { clearTimeout(timer); reject(new Error('CDP_CONNECT_FAILED')); }, {once: true});
  });
  const value = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => { ws.close(); reject(new Error('OUTCOME_UNKNOWN: never replay a submission automatically')); }, input.timeout_ms || 120000);
    ws.addEventListener('message', event => {
      const message = JSON.parse(String(event.data));
      if (message.id !== 1) return;
      clearTimeout(timer);
      if (message.error || message.result?.exceptionDetails) {
        const detail = message.result?.exceptionDetails?.exception?.description?.split('\n')[0];
        reject(new Error(detail || 'BROWSER_OPERATION_FAILED'));
      }
      else resolve(message.result?.result?.value);
    });
    ws.addEventListener('close', () => { clearTimeout(timer); reject(new Error('CDP_DISCONNECTED: inspect original task before resubmitting')); }, {once: true});
    ws.send(JSON.stringify({id: 1, method: 'Runtime.evaluate', params: {expression: input.expression, awaitPromise: true, returnByValue: true}}));
  });
  process.stdout.write(JSON.stringify(value) + '\n');
} catch (error) {
  process.stderr.write(String(error.message) + '\n');
  process.exitCode = 1;
} finally {
  ws?.close();
}

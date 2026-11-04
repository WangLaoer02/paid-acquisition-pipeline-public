// Executes inside the existing authenticated AI backend tab. Does not read cookies.
async function runRyai(spec) {
  const origin = 'http://ai.cn.sy.backend.example.invalid';
  if (location.origin !== origin) throw new Error('WRONG_ORIGIN: 请使用已登录的荣耀 AI 页面');
  const reads = new Set(['sessions', 'sessionDetail', 'sessionMessages', 'quotaSummary', 'taskStatus', 'assetList', 'subjectList', 'subjectTagList', 'audioCloneList', 'audioCloneDetail', 'audioTtsHistory']);
  const writes = new Set(['send', 'upload']);
  const result = {checked_at: new Date().toISOString(), source: origin, command: spec.command};
  if (spec.operation === 'models') {
    if (!window.AI_MODEL_OPTIONS_BY_TYPE) throw new Error('MODEL_CONFIG_MISSING');
    return {...result, ok: true, execution_state: 'read', response: window.AI_MODEL_OPTIONS_BY_TYPE};
  }
  if (spec.operation === 'download') {
    const media = new URL(spec.url);
    if (!['http:', 'https:'].includes(media.protocol)) throw new Error('INVALID_MEDIA_URL');
    const params = new URLSearchParams({_c: 'aiModel', _a: 'downloadMedia', url: spec.url, name: spec.name});
    const a = document.createElement('a');
    a.href = '/data/?' + params;
    a.download = spec.name;
    document.body.appendChild(a); a.click(); a.remove();
    return {...result, ok: true, execution_state: 'download_requested', filename: spec.name};
  }
  const mutates = writes.has(spec.action);
  if (!reads.has(spec.action) && !mutates) throw new Error('ACTION_NOT_ALLOWLISTED');
  if (mutates && spec.execute !== true) throw new Error('EXECUTE_REQUIRED');
  const params = new URLSearchParams({_c: 'aiModel', _a: spec.action});
  for (const [key, value] of Object.entries(spec.query || {})) {
    if (key === '_c' || key === '_a') throw new Error('RESERVED_QUERY_KEY');
    if (Array.isArray(value)) value.forEach(x => params.append(key, String(x)));
    else params.set(key, String(value));
  }
  const options = {credentials: 'same-origin', redirect: 'error'};
  if (spec.action === 'upload') {
    const raw = atob(spec.upload.base64);
    const bytes = Uint8Array.from(raw, c => c.charCodeAt(0));
    const fd = new FormData();
    fd.append('file', new Blob([bytes], {type: spec.upload.mime}), spec.upload.name);
    fd.append('type', spec.upload.type); fd.append('model', spec.upload.model);
    options.method = 'POST'; options.body = fd;
  } else if (mutates) {
    options.method = 'POST'; options.headers = {'Content-Type': 'application/json'};
    options.body = JSON.stringify(spec.body);
  }
  const response = await fetch('/data/?' + params, options);
  if (!response.ok) throw new Error('BACKEND_HTTP_' + response.status);
  const rawBody = await response.text();
  let payload;
  try { payload = JSON.parse(rawBody); }
  catch (_) { throw new Error('AUTH_OR_NON_JSON: 页面登录态或接口响应需核查'); }
  if (!payload || typeof payload !== 'object' || typeof payload.ok !== 'boolean')
    throw new Error('UNEXPECTED_BACKEND_JSON');
  return {...result, ok: payload.ok === true, execution_state: payload.ok === true ? (mutates ? 'submitted' : 'read') : 'rejected', response: payload};
}

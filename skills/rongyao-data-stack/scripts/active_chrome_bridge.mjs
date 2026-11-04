#!/usr/bin/env node
/** Windows/macOS active-Chrome bridge for read-only 荣耀 backend exports. */

import fs from "node:fs";
import path from "node:path";
import childProcess from "node:child_process";
import crypto from "node:crypto";
import { pathToFileURL } from "node:url";

const ALLOWED_HOST = "data.houtai.cn.sy.backend.example.invalid";
const LOGIN_ORIGIN = "http://power.houtai.backend.example.invalid/";
const LIGHT_PAGE = `http://${ALLOWED_HOST}/market/`;
const MARKET_PATH = "/marketng/?_c=adopenplatformSource&_a=index";
const MAX_EXPORT_BYTES = 32 * 1024 * 1024;
const PAGE_BASE64_CHUNK_BYTES = 32766;
const CDP_CHUNK_CHARS = 8 * 1024;

function fail(message) {
  throw new Error(message);
}

function parseArgs(argv) {
  const [command = "", ...rest] = argv;
  const options = {};
  for (let index = 0; index < rest.length; index += 1) {
    const item = rest[index];
    if (!item.startsWith("--")) fail(`unexpected argument: ${item}`);
    const key = item.slice(2);
    const next = rest[index + 1];
    if (next === undefined || next.startsWith("--")) options[key] = true;
    else {
      options[key] = next;
      index += 1;
    }
  }
  return { command, options };
}

function required(options, name) {
  const value = String(options[name] ?? "").trim();
  if (!value) fail(`missing --${name}`);
  return value;
}

function safeUrl(candidate, allowedPaths = null) {
  const parsed = new URL(candidate, `http://${ALLOWED_HOST}/`);
  if (parsed.protocol !== "http:" || parsed.hostname !== ALLOWED_HOST) {
    fail(`blocked non-allowlisted URL: ${parsed.origin}`);
  }
  if (allowedPaths && !allowedPaths.some((prefix) => parsed.pathname.startsWith(prefix))) {
    fail(`blocked non-allowlisted path: ${parsed.pathname}`);
  }
  return parsed.href;
}

function statePayload(port, pid, profileDir) {
  return {
    version: 1,
    port: Number(port),
    pid: Number(pid),
    profileDir: path.resolve(profileDir),
    createdAt: new Date().toISOString(),
  };
}

function writeJson(file, payload) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(payload, null, 2) + "\n", { encoding: "utf8", mode: 0o600 });
  try { fs.chmodSync(file, 0o600); } catch {}
}

function readState(file) {
  if (!fs.existsSync(file)) return null;
  const parsed = JSON.parse(fs.readFileSync(file, "utf8"));
  if (!Number.isInteger(Number(parsed.port)) || Number(parsed.port) < 1) return null;
  return parsed;
}

function processAlive(pid) {
  const numericPid = Number(pid);
  if (!Number.isInteger(numericPid) || numericPid < 1) return false;
  try {
    process.kill(numericPid, 0);
    return true;
  } catch (error) {
    return error?.code === "EPERM";
  }
}

async function fetchJson(url, timeoutMs = 4000) {
  const response = await fetch(url, { signal: AbortSignal.timeout(timeoutMs) });
  if (!response.ok) fail(`DevTools HTTP ${response.status}`);
  return await response.json();
}

function profileDevToolsPort(profileDir) {
  if (!profileDir) return null;
  const activePortFile = path.join(path.resolve(profileDir), "DevToolsActivePort");
  if (!fs.existsSync(activePortFile)) return null;
  const port = Number(fs.readFileSync(activePortFile, "utf8").split(/\r?\n/, 1)[0]);
  return Number.isInteger(port) && port > 0 ? port : null;
}

async function inspectDevTools(port) {
  const version = await fetchJson(`http://127.0.0.1:${port}/json/version`);
  const targets = await fetchJson(`http://127.0.0.1:${port}/json/list`);
  return {
    browser: version.Browser ?? null,
    hasLoginPage: targets.some((item) => String(item.url ?? "").includes("backend.example.invalid")),
  };
}

class CdpClient {
  constructor(url) {
    this.url = url;
    this.ws = null;
    this.nextId = 1;
    this.pending = new Map();
  }

  async connect(timeoutMs = 10000) {
    await new Promise((resolve, reject) => {
      const ws = new WebSocket(this.url);
      const timer = setTimeout(() => { ws.close(); reject(new Error("CDP websocket timeout")); }, timeoutMs);
      ws.onopen = () => {
        clearTimeout(timer);
        this.ws = ws;
        resolve();
      };
      ws.onerror = () => {
        clearTimeout(timer);
        reject(new Error("CDP websocket connection failed"));
      };
      ws.onmessage = (event) => {
        const message = JSON.parse(String(event.data));
        if (!message.id || !this.pending.has(message.id)) return;
        const pending = this.pending.get(message.id);
        this.pending.delete(message.id);
        clearTimeout(pending.timer);
        if (message.error) pending.reject(new Error(`${pending.method}: ${message.error.message}`));
        else pending.resolve(message.result ?? {});
      };
      ws.onclose = () => {
        clearTimeout(timer);
        this.ws = null;
        reject(new Error("CDP websocket closed"));
        for (const pending of this.pending.values()) {
          clearTimeout(pending.timer);
          pending.reject(new Error("CDP websocket closed"));
        }
        this.pending.clear();
      };
    });
  }

  send(method, params = {}, timeoutMs = 30000) {
    if (!this.ws || this.ws.readyState !== 1) return Promise.reject(new Error("CDP client not connected"));
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`${method} timed out`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer, method });
      try { this.ws.send(JSON.stringify({ id, method, params })); }
      catch (error) { clearTimeout(timer); this.pending.delete(id); reject(error); }
    });
  }

  close() {
    try { this.ws?.close(); } catch {}
  }
}

async function sessionInfo(stateFile) {
  const state = readState(stateFile);
  if (!state) return { ok: true, active: false, reason: "state_missing" };
  const profilePort = profileDevToolsPort(state.profileDir);
  const ports = [...new Set([Number(state.port), profilePort].filter((item) => Number.isInteger(item) && item > 0))];
  let lastError = null;
  for (const port of ports) {
    try {
      const inspected = await inspectDevTools(port);
      return {
        ok: true,
        active: true,
        port,
        pid: state.pid,
        profileDir: state.profileDir,
        rebound: port !== Number(state.port),
        ...inspected,
      };
    } catch (error) {
      lastError = error;
    }
  }
  return {
    ok: true,
    active: false,
    reason: processAlive(state.pid) ? "devtools_unreachable" : "process_missing",
    port: state.port,
    pid: state.pid,
    profileDir: state.profileDir,
    detail: String(lastError?.message ?? lastError ?? "DevTools unavailable"),
  };
}

async function openSession(options) {
  const chromePath = path.resolve(required(options, "chrome"));
  const profileDir = path.resolve(required(options, "profile-dir"));
  const stateFile = path.resolve(required(options, "state-file"));
  const existing = await sessionInfo(stateFile);
  if (existing.active) {
    if (existing.rebound) writeJson(stateFile, statePayload(existing.port, existing.pid || 0, profileDir));
    return { ...existing, reused: true, loginOrigin: LOGIN_ORIGIN, startUrl: LIGHT_PAGE };
  }
  const profilePort = profileDevToolsPort(profileDir);
  if (profilePort) {
    try {
      const inspected = await inspectDevTools(profilePort);
      const state = statePayload(profilePort, existing.pid || 0, profileDir);
      writeJson(stateFile, state);
      return { ok: true, active: true, reused: true, rebound: true, ...state, ...inspected, loginOrigin: LOGIN_ORIGIN, startUrl: LIGHT_PAGE };
    } catch {}
  }
  if (existing.reason === "devtools_unreachable") fail("ACTIVE_SESSION_UNREACHABLE: existing process preserved");
  if (!fs.existsSync(chromePath)) fail(`Chrome not found: ${chromePath}`);
  fs.mkdirSync(profileDir, { recursive: true });
  // No parent-owned stderr pipe: Chrome must survive a short-lived CLI worker.
  const chrome = childProcess.spawn(chromePath, [
    "--no-first-run", "--no-default-browser-check", "--start-minimized",
    "--remote-debugging-port=0", `--user-data-dir=${profileDir}`, LIGHT_PAGE,
  ], { detached: true, stdio: "ignore", windowsHide: false });
  chrome.unref();
  let exited = false;
  chrome.once("exit", () => { exited = true; });
  let port;
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    if (exited) fail("CHROME_EXITED_BEFORE_DEVTOOLS");
    const candidate = profileDevToolsPort(profileDir);
    if (candidate) {
      try { await inspectDevTools(candidate); port = candidate; break; } catch {}
    }
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  if (!port) fail("CHROME_DEVTOOLS_START_TIMEOUT: original process preserved");
  const state = statePayload(port, chrome.pid, profileDir);
  writeJson(stateFile, state);
  return { ok: true, active: true, reused: false, ...state, loginOrigin: LOGIN_ORIGIN, startUrl: LIGHT_PAGE };
}

async function createLightTarget(port) {
  const version = await fetchJson(`http://127.0.0.1:${port}/json/version`);
  const browser = new CdpClient(version.webSocketDebuggerUrl);
  await browser.connect();
  let created;
  try {
    created = await browser.send("Target.createTarget", { url: LIGHT_PAGE, background: true, newWindow: false });
  } catch (error) {
    browser.close();
    if (process.env.RONGYAO_CAPTURE_BACKGROUND === "1" && /no browser is open/i.test(error.message)) {
      throw new Error("LOGIN_REQUIRED: 专用 Chrome 没有打开的窗口，请点击网页的打开专用登录窗口恢复；未提交数据查询。");
    }
    throw error;
  }
  const targetId = created.targetId;
  for (let attempt = 0; attempt < 40; attempt += 1) {
    const targets = await fetchJson(`http://127.0.0.1:${port}/json/list`);
    const target = targets.find((item) => item.id === targetId && item.webSocketDebuggerUrl);
    if (target) return { browser, target, targetId };
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  browser.close();
  fail("new Chrome target did not become ready");
}

function isLoginUrl(value) {
  try {
    const url = new URL(value);
    return url.hostname === "power.houtai.backend.example.invalid"
      || url.hostname === "accounts.feishu.cn" || url.hostname === "passport.feishu.cn";
  } catch { return false; }
}

async function presentLoginTarget(browser, page, targetId) {
  // Keep an in-progress SSO redirect intact. Only navigate a backend data page
  // when the login failure was detected by its background fetch.
  const current = await page.send("Runtime.evaluate", { expression: "location.href", returnByValue: true }, 3000).catch(() => null);
  let backendPage = false;
  try { backendPage = new URL(current?.result?.value).hostname === ALLOWED_HOST; } catch {}
  if (backendPage) await page.send("Page.navigate", { url: LOGIN_ORIGIN }, 5000).catch(() => null);
  const window = await browser.send("Browser.getWindowForTarget", { targetId }, 3000).catch(() => null);
  if (window?.windowId !== undefined) {
    await browser.send("Browser.setWindowBounds", { windowId: window.windowId, bounds: { windowState: "normal" } }, 3000).catch(() => null);
  }
  await browser.send("Target.activateTarget", { targetId }, 3000).catch(() => null);
  await page.send("Page.bringToFront", {}, 3000).catch(() => null);
}

async function finishCaptureTarget(browser, page, targetId, cacheKey, loginRequired) {
  try {
    await page.send("Runtime.evaluate", { expression: `delete globalThis[${JSON.stringify(cacheKey)}]`, returnByValue: true }, 5000).catch(() => null);
    if (loginRequired && process.env.RONGYAO_CAPTURE_BACKGROUND !== "1") await presentLoginTarget(browser, page, targetId);
    else await browser.send("Target.closeTarget", { targetId }, 5000).catch(() => null);
  } finally {
    // Close protocol sockets only; a manual login page belongs to the user now.
    page.close();
    browser.close();
  }
}

async function showLogin(options) {
  const status = await sessionInfo(path.resolve(required(options, "state-file")));
  if (!status.active) fail(`ACTIVE_SESSION_REQUIRED: ${status.reason}`);
  const version = await fetchJson(`http://127.0.0.1:${status.port}/json/version`);
  const browser = new CdpClient(version.webSocketDebuggerUrl);
  let page;
  try {
    await browser.connect();
    const targets = await fetchJson(`http://127.0.0.1:${status.port}/json/list`);
    let target = targets.find(item => item.type === "page" && isLoginUrl(item.url) && item.webSocketDebuggerUrl);
    const reused = Boolean(target);
    if (!target) {
      const created = await browser.send("Target.createTarget", { url: LOGIN_ORIGIN, newWindow: true });
      for (let attempt = 0; attempt < 40; attempt += 1) {
        const pages = await fetchJson(`http://127.0.0.1:${status.port}/json/list`);
        target = pages.find(item => item.id === created.targetId && item.webSocketDebuggerUrl);
        if (target) break;
        await new Promise(resolve => setTimeout(resolve, 100));
      }
      if (!target) fail("LOGIN_TARGET_NOT_READY");
    }
    page = new CdpClient(target.webSocketDebuggerUrl);
    await page.connect();
    await presentLoginTarget(browser, page, target.id);
    return { ok: true, active: true, loginWindowOpen: true, reused, targetId: target.id, authenticated: null };
  } finally { page?.close(); browser.close(); }
}

function exportExpression(filters, cacheKey) {
  const payload = JSON.stringify(filters);
  const cacheKeyLiteral = JSON.stringify(cacheKey);
  return `(async () => {
    const filters = ${payload};
    const maxBytes = ${MAX_EXPORT_BYTES};
    const marketUrl = new URL(filters.marketPath, location.origin).href;
    const market = await fetch(marketUrl, { credentials: 'include', headers: { Accept: 'text/html,application/xhtml+xml' } });
    const html = await market.text();
    if (market.url.includes('power.houtai.backend.example.invalid') || /[_?&]c=login|飞书登录|feishu/i.test(html)) {
      throw new Error('LOGIN_REQUIRED');
    }
    const configMatch = html.match(/var\\s+_pageConfig\\s*=\\s*(\\{.*?\\});\\s*\\/\\*\\s*\\{search/s);
    const randMatch = html.match(/var\\s+_initRand\\s*=\\s*'([^']*)'/);
    const dataMatch = html.match(/var\\s+_getDataUrl\\s*=\\s*'([^']+)'/);
    if (!configMatch || !randMatch || !dataMatch) throw new Error('PAGE_CONFIG_CHANGED');
    const config = JSON.parse(configMatch[1]);
    const search = { date: '', page: 1, pagesize: config.pagesize || 20, sort: '', desc: '', rand_num: randMatch[1] || '' };
    for (const field of (config.search || [])) {
      if (field.type === 'button') continue;
      search[field.key] = Object.prototype.hasOwnProperty.call(field, 'default') ? field.default : (field.multiple ? [] : '');
    }
    Object.assign(search, {
      date: filters.dateRange,
      date2: filters.materialRange,
      gid: [String(filters.gid)],
      date_group: filters.dateGroup,
      group: filters.group,
      source_video_type: '1',
      record_type: '3',
      filter: '1',
      page: 1,
    });
    const optionKeys = (value) => {
      const candidates = [value?.info?.category_list, value?.info?.pkid_list, value?.info, value];
      for (const candidate of candidates) {
        if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) continue;
        const keys = Object.keys(candidate).filter((key) => /^\d+$/.test(key));
        if (keys.length) return keys;
      }
      return [];
    };
    const categoryValues = [];
    const pkidValues = [];
    for (const gid of (Array.isArray(search.gid) ? search.gid : [search.gid])) {
      const categoryResponse = await fetch(new URL('/market/api/ApiGetCategory.php?gid=' + encodeURIComponent(gid), location.origin), { credentials: 'include', headers: { Accept: 'application/json' } });
      const pkidResponse = await fetch(new URL('/market/api/ApiGetAllPkList.php?gid=' + encodeURIComponent(gid), location.origin), { credentials: 'include', headers: { Accept: 'application/json' } });
      categoryValues.push(...optionKeys(await categoryResponse.json()));
      pkidValues.push(...optionKeys(await pkidResponse.json()));
    }
    search.category = [...new Set(categoryValues)];
    search.pkid = [...new Set(pkidValues)];
    if (search.operation_client && String(search.operation_client).length) {
      const operations = Array.isArray(search.operation_client) ? search.operation_client : [search.operation_client];
      const pcidUrl = new URL('/marketng/api/ApiGetPcidList.php?operation_client=' + encodeURIComponent(operations.join(',')), location.origin);
      const pcidResponse = await fetch(pcidUrl, { credentials: 'include', headers: { Accept: 'application/json' } });
      const pcidJson = await pcidResponse.json();
      search.pcid = Object.keys((((pcidJson || {}).info || {}).pcid_list) || {});
    }
    const body = new URLSearchParams();
    for (const [key, value] of Object.entries(search)) body.set('search[' + key + ']', Array.isArray(value) ? value.join(',') : String(value ?? ''));
    body.set('search[page_component_version]', '1');
    body.set('search[submit]', '1');
    const dataUrl = new URL(dataMatch[1].replaceAll('\\\\/', '/'), location.origin);
    if (dataUrl.origin !== location.origin) throw new Error('BLOCKED_CROSS_ORIGIN_DATA_URL');
    const queryResponse = await fetch(dataUrl, {
      method: 'POST', credentials: 'include',
      headers: { Accept: 'application/json', 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'X-Requested-With': 'XMLHttpRequest' },
      body: body.toString(),
    });
    const queryText = await queryResponse.text();
    let queryResult;
    try { queryResult = JSON.parse(queryText); } catch { throw new Error('QUERY_RETURNED_NON_JSON'); }
    if (!queryResult.status) throw new Error('QUERY_STATUS_FALSE');
    const info = queryResult.info || {};
    if (!info.rand) throw new Error('QUERY_MISSING_RAND');
    const exportUrl = new URL('/marketng/?_c=adopenplatformSource&_a=index&ac=export&rand=' + encodeURIComponent(String(info.rand)), location.origin);
    const exported = await fetch(exportUrl, { credentials: 'include', headers: { Accept: 'text/csv,application/vnd.ms-excel,*/*' } });
    const buffer = await exported.arrayBuffer();
    if (buffer.byteLength > maxBytes) throw new Error('EXPORT_TOO_LARGE');
    const bytes = new Uint8Array(buffer);
    const prefix = new TextDecoder().decode(bytes.slice(0, 256)).toLowerCase();
    if (prefix.includes('<html') || prefix.includes('<!doctype html')) throw new Error('EXPORT_RETURNED_HTML');
    let base64 = '';
    const encodeChunkBytes = ${PAGE_BASE64_CHUNK_BYTES};
    for (let offset = 0; offset < bytes.length; offset += encodeChunkBytes) {
      base64 += btoa(String.fromCharCode(...bytes.subarray(offset, offset + encodeChunkBytes)));
    }
    globalThis[${cacheKeyLiteral}] = { base64 };
    return {
      ok: true, bytes: bytes.length, base64Length: base64.length,
      contentType: exported.headers.get('content-type') || '',
      query: { count: info.count ?? null, totalpage: info.totalpage ?? null, pagesize: info.pagesize ?? null },
    };
  })()`;
}

function queryExpression(batch, cacheKey) {
  const payload = JSON.stringify(batch);
  const cacheKeyLiteral = JSON.stringify(cacheKey);
  return `(async () => {
    const batch = ${payload};
    const timeoutMs = Math.max(5000, Number(batch.timeout_ms || 180000));
    const maxBytes = ${MAX_EXPORT_BYTES};
    const started = performance.now();
    const fetchTimed = async (url, init = {}) => {
      const response = await fetch(url, { ...init, signal: AbortSignal.timeout(timeoutMs), credentials: 'include' });
      if (!response.ok) throw new Error('HTTP_' + response.status);
      return response;
    };
    const marketUrl = new URL(batch.marketPath, location.origin).href;
    const market = await fetchTimed(marketUrl, { headers: { Accept: 'text/html,application/xhtml+xml' } });
    const html = await market.text();
    if (market.url.includes('power.houtai.backend.example.invalid') || /[_?&]c=login|飞书登录|feishu/i.test(html)) {
      throw new Error('LOGIN_REQUIRED');
    }
    const configMatch = html.match(/var\\s+_pageConfig\\s*=\\s*(\\{.*?\\});\\s*\\/\\*\\s*\\{search/s);
    const randMatch = html.match(/var\\s+_initRand\\s*=\\s*'([^']*)'/);
    const dataMatch = html.match(/var\\s+_getDataUrl\\s*=\\s*'([^']+)'/);
    if (!configMatch || !randMatch || !dataMatch) throw new Error('PAGE_CONFIG_CHANGED');
    const config = JSON.parse(configMatch[1]);
    const dataUrl = new URL(dataMatch[1].replaceAll('\\\\/', '/'), location.origin);
    if (dataUrl.origin !== location.origin) throw new Error('BLOCKED_CROSS_ORIGIN_DATA_URL');
    const base = { date: '', page: 1, pagesize: config.pagesize || 20, sort: '', desc: '', rand_num: randMatch[1] || '' };
    for (const field of (config.search || [])) {
      if (field.type === 'button') continue;
      base[field.key] = Object.prototype.hasOwnProperty.call(field, 'default') ? field.default : (field.multiple ? [] : '');
    }
    const dependencyCache = new Map();
    let cacheHits = 0;
    let cacheMisses = 0;
    const optionKeys = (value) => {
      const candidates = [
        value?.info?.category_list, value?.info?.pkid_list, value?.info?.pcid_list,
        value?.info, value,
      ];
      for (const candidate of candidates) {
        if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) continue;
        const numeric = Object.keys(candidate).filter((key) => /^\\d+$/.test(key));
        if (numeric.length) return numeric;
      }
      return [];
    };
    const dependency = async (kind, value) => {
      const key = kind + ':' + value;
      if (dependencyCache.has(key)) {
        cacheHits += 1;
        return [...(await dependencyCache.get(key))];
      }
      const pending = (async () => {
        let url;
        if (kind === 'category') url = '/market/api/ApiGetCategory.php?gid=' + encodeURIComponent(value);
        else if (kind === 'pkid') url = '/market/api/ApiGetAllPkList.php?gid=' + encodeURIComponent(value);
        else if (kind === 'pcid') url = '/marketng/api/ApiGetPcidList.php?operation_client=' + encodeURIComponent(value);
        else throw new Error('UNKNOWN_DEPENDENCY_' + kind);
        const response = await fetchTimed(new URL(url, location.origin), { headers: { Accept: 'application/json' } });
        const parsed = await response.json();
        return optionKeys(parsed);
      })();
      if (dependencyCache.size < 64) dependencyCache.set(key, pending);
      cacheMisses += 1;
      try {
        const values = await pending;
        if (dependencyCache.has(key)) dependencyCache.set(key, values);
        return [...values];
      } catch (error) {
        dependencyCache.delete(key);
        throw error;
      }
    };
    const unique = (values) => [...new Set(values.map(String).filter(Boolean))];
    const prepare = async (request) => {
      const search = { ...base, ...(request.search || {}) };
      const gids = Array.isArray(search.gid) ? search.gid.map(String) : String(search.gid || '').split(',').filter(Boolean);
      search.gid = unique(gids);
      if (request.expand_gid_dependencies) {
        if (!Array.isArray(request.search?.category) || !request.search.category.length) {
          search.category = unique((await Promise.all(gids.map((gid) => dependency('category', gid)))).flat());
        }
        if (!Array.isArray(request.search?.pkid) || !request.search.pkid.length) {
          search.pkid = unique((await Promise.all(gids.map((gid) => dependency('pkid', gid)))).flat());
        }
      }
      if (request.expand_pcid && search.operation_client && (!Array.isArray(request.search?.pcid) || !request.search.pcid.length)) {
        const operations = Array.isArray(search.operation_client) ? search.operation_client : String(search.operation_client).split(',');
        search.pcid = await dependency('pcid', operations.join(','));
      }
      search.page = 1;
      search.rand_num = '';
      return search;
    };
    const submit = async (search, isSubmit) => {
      const body = new URLSearchParams();
      for (const [key, value] of Object.entries(search)) {
        body.set('search[' + key + ']', Array.isArray(value) ? value.join(',') : String(value ?? ''));
      }
      body.set('search[page_component_version]', '1');
      if (isSubmit) body.set('search[submit]', '1');
      const response = await fetchTimed(dataUrl, {
        method: 'POST',
        headers: { Accept: 'application/json', 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'X-Requested-With': 'XMLHttpRequest' },
        body: body.toString(),
      });
      const text = await response.text();
      let result;
      try { result = JSON.parse(text); } catch { throw new Error('QUERY_RETURNED_NON_JSON'); }
      if (!result?.status) throw new Error('QUERY_STATUS_FALSE');
      return result;
    };
    const scalarSummary = (value) => {
      const output = {};
      if (!value || typeof value !== 'object') return output;
      for (const [key, item] of Object.entries(value)) {
        if (item === null || ['string', 'number', 'boolean'].includes(typeof item)) output[key] = item;
      }
      return output;
    };
    const fingerprint = async (value) => {
      if (!value || !globalThis.crypto?.subtle?.digest) return null;
      try {
        const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(String(value)));
        return [...new Uint8Array(digest)].slice(0, 6).map((item) => item.toString(16).padStart(2, '0')).join('');
      } catch { return null; }
    };
    const executeOnce = async (request) => {
      const itemStarted = performance.now();
      const search = await prepare(request);
      const first = await submit(search, true);
      const firstInfo = first.info || {};
      const rand = String(firstInfo.rand || '');
      const totalPages = Math.max(1, Number(firstInfo.totalpage || 1));
      if (request.all_pages && totalPages > Number(request.max_pages || 20)) {
        throw new Error('PAGES_EXCEED_LIMIT_' + totalPages);
      }
      const rows = request.include === 'rows' ? [...(firstInfo.data || [])] : [];
      if (rows.length > Number(request.max_rows || 5000)) throw new Error('ROWS_EXCEED_LIMIT');
      let pagesCompleted = 1;
      if (request.all_pages) {
        if (!rand) throw new Error('QUERY_MISSING_RAND');
        for (let page = 2; page <= totalPages; page += 1) {
          const paging = { ...search, page, rand_num: rand };
          const result = await submit(paging, false);
          const info = result.info || {};
          const returnedRand = String(info.rand || rand);
          if (returnedRand !== rand) throw new Error('PAGINATION_RAND_CHANGED');
          rows.push(...(info.data || []));
          pagesCompleted += 1;
          if (rows.length > Number(request.max_rows || 5000)) throw new Error('ROWS_EXCEED_LIMIT');
        }
      }
      const identityFilters = {};
      for (const key of ['category', 'source_type', 'source_direction', 'role', 'self_tag', 'keyword', 'negative_keyword']) {
        const value = search[key];
        if (value !== undefined && value !== '' && (!Array.isArray(value) || value.length)) identityFilters[key] = value;
      }
      return {
        id: request.id,
        ok: true,
        status: 'confirmed_response',
        transport: 'active_chrome_page_context',
        identity: {
          entry: '新素材2.0', gid: search.gid, date: search.date, date2: search.date2,
          date_group: search.date_group, group: search.group,
          source_video_type: search.source_video_type, record_type: search.record_type,
          filter: search.filter, filters: identityFilters,
        },
        summary: scalarSummary(firstInfo.sum),
        query: { count: firstInfo.count ?? null, totalpage: totalPages, pagesize: firstInfo.pagesize ?? null, pages_completed: pagesCompleted },
        rows: request.include === 'rows' ? rows : null,
        export_preflight: { ready: Boolean(rand), session_fingerprint: await fingerprint(rand) },
        elapsed_ms: Math.round((performance.now() - itemStarted) * 100) / 100,
      };
    };
    const execute = async (request) => {
      try { return { ...(await executeOnce(request)), attempts: 1 }; }
      catch (error) {
        return { id: request.id, ok: false, status: request.high_cost ? 'backend_unhealthy' : 'missing',
          error: String(error?.message || error), summary: null, rows: null, attempts: 1, replayed: false };
      }
    };
    const requests = batch.requests || [];
    const ids = new Set();
    const signatures = new Set();
    for (const request of requests) {
      const signature = JSON.stringify(request.search, Object.keys(request.search || {}).sort());
      if (ids.has(request.id) || signatures.has(signature)) throw new Error('DUPLICATE_REQUEST');
      ids.add(request.id); signatures.add(signature);
    }
    if (requests.some((item) => item.high_cost || item.search?.group === 'material_serial_number') && requests.length > 1) {
      throw new Error('HIGH_COST_SINGLE_REQUEST_REQUIRED');
    }
    const workerCount = requests.some((item) => item.high_cost) ? 1 : Math.max(1, Math.min(6, Number(batch.concurrency || 1), requests.length));
    const results = new Array(requests.length);
    let cursor = 0;
    const worker = async () => {
      while (true) {
        const index = cursor++;
        if (index >= requests.length) return;
        results[index] = await execute(requests[index]);
      }
    };
    await Promise.all(Array.from({ length: workerCount }, worker));
    const output = {
      ok: results.every((item) => item?.ok),
      transport: 'active_chrome_page_context',
      results,
      cache: { scope: 'single_run_metadata_only', max_entries: 64, hits: cacheHits, misses: cacheMisses },
      concurrency: workerCount,
      page_defaults: { date2: base.date2 ?? null },
      elapsed_ms: Math.round((performance.now() - started) * 100) / 100,
    };
    const bytes = new TextEncoder().encode(JSON.stringify(output));
    if (bytes.length > maxBytes) throw new Error('QUERY_RESULT_TOO_LARGE');
    let base64 = '';
    const encodeChunkBytes = ${PAGE_BASE64_CHUNK_BYTES};
    for (let offset = 0; offset < bytes.length; offset += encodeChunkBytes) {
      base64 += btoa(String.fromCharCode(...bytes.subarray(offset, offset + encodeChunkBytes)));
    }
    globalThis[${cacheKeyLiteral}] = { base64 };
    return { ok: true, bytes: bytes.length, base64Length: base64.length };
  })()`;
}

async function readChunkedPayload(page, cacheKey, result) {
  if (!result?.ok || !Number.isInteger(result.base64Length) || result.base64Length <= 0) {
    fail("page query returned no data");
  }
  let base64 = "";
  for (let offset = 0; offset < result.base64Length; offset += CDP_CHUNK_CHARS) {
    const end = Math.min(offset + CDP_CHUNK_CHARS, result.base64Length);
    const chunkResult = await page.send("Runtime.evaluate", {
      expression: `globalThis[${JSON.stringify(cacheKey)}]?.base64.slice(${offset}, ${end})`,
      returnByValue: true,
    });
    if (chunkResult.exceptionDetails) fail("page query chunk read failed");
    const chunk = chunkResult.result?.value;
    if (typeof chunk !== "string" || chunk.length !== end - offset) fail(`page query chunk truncated at ${offset}`);
    base64 += chunk;
  }
  const raw = Buffer.from(base64, "base64");
  if (raw.length !== result.bytes) fail(`page query byte length mismatch: expected ${result.bytes}, received ${raw.length}`);
  return raw;
}


function writeAtomic(file, raw) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const temporary = file + '.partial-' + crypto.randomUUID();
  try {
    fs.writeFileSync(temporary, raw, { mode: 0o600 });
    fs.renameSync(temporary, file);
  } finally { if (fs.existsSync(temporary)) fs.unlinkSync(temporary); }
}

async function recoverChunkedPayload(page, cacheKey, result) {
  try { return await readChunkedPayload(page, cacheKey, result); }
  catch (error) {
    if (!/CDP|websocket|timed out|not connected/i.test(String(error.message))) throw error;
    page.close();
    await page.connect();
    return await readChunkedPayload(page, cacheKey, result);
  }
}

async function queryData(options) {
  const stateFile = path.resolve(required(options, "state-file"));
  const requestFile = path.resolve(required(options, "request-file"));
  const status = await sessionInfo(stateFile);
  if (!status.active) fail(`ACTIVE_SESSION_REQUIRED: ${status.reason}`);
  const batch = JSON.parse(fs.readFileSync(requestFile, "utf8"));
  batch.marketPath = safeUrl(options["market-path"] || MARKET_PATH, ["/marketng/"]);
  batch.timeout_ms = Math.max(5000, Number(options.timeout || batch.timeout_ms || 180000));
  const { browser, target, targetId } = await createLightTarget(status.port);
  const page = new CdpClient(target.webSocketDebuggerUrl);
  const cacheKey = `__rongyaoQuery_${crypto.randomUUID().replaceAll("-", "")}`;
  let loginRequired = false;
  try {
    await page.connect();
    await page.send("Page.enable");
    await page.send("Runtime.enable");
    for (let attempt = 0; attempt < 60; attempt += 1) {
      const ready = await page.send("Runtime.evaluate", { expression: "({ready:document.readyState,host:location.hostname,href:location.href})", returnByValue: true });
      const value = ready.result?.value ?? {};
      if (value.host === ALLOWED_HOST && (value.ready === "interactive" || value.ready === "complete")) break;
      if (String(value.href ?? "").includes("power.houtai.backend.example.invalid")) fail("LOGIN_REQUIRED");
      await new Promise((resolve) => setTimeout(resolve, 500));
      if (attempt === 59) fail("LIGHT_PAGE_NOT_READY");
    }
    const evaluated = await page.send("Runtime.evaluate", {
      expression: queryExpression(batch, cacheKey), awaitPromise: true, returnByValue: true,
    }, Number(options.timeout || 180000) * Math.max(1, Number(batch.requests?.length || 1)));
    if (evaluated.exceptionDetails) fail(evaluated.exceptionDetails.exception?.description || evaluated.exceptionDetails.text || "page query failed");
    const raw = await recoverChunkedPayload(page, cacheKey, evaluated.result?.value);
    return JSON.parse(raw.toString("utf8"));
  } catch (error) {
    loginRequired = String(error?.message || error).includes("LOGIN_REQUIRED");
    throw error;
  } finally {
    await finishCaptureTarget(browser, page, targetId, cacheKey, loginRequired);
  }
}

async function exportData(options) {
  const stateFile = path.resolve(required(options, "state-file"));
  const output = path.resolve(required(options, "output"));
  const status = await sessionInfo(stateFile);
  if (!status.active) fail(`ACTIVE_SESSION_REQUIRED: ${status.reason}`);
  const filters = {
    marketPath: safeUrl(options["market-path"] || MARKET_PATH, ["/marketng/"]),
    dateRange: required(options, "date-range"),
    materialRange: required(options, "material-range"),
    gid: required(options, "gid"),
    dateGroup: options["date-group"] || "tenyear",
    group: options.group || "mid",
  };
  if (!/^\d{4}\/\d{2}\/\d{2}-\d{4}\/\d{2}\/\d{2}$/.test(filters.dateRange)) fail("invalid date range");
  if (!/^\d{4}\/\d{2}\/\d{2}-\d{4}\/\d{2}\/\d{2}$/.test(filters.materialRange)) fail("invalid material range");
  if (!/^\d+$/.test(filters.gid)) fail("invalid gid");
  const { browser, target, targetId } = await createLightTarget(status.port);
  const page = new CdpClient(target.webSocketDebuggerUrl);
  const cacheKey = `__rongyaoExport_${crypto.randomUUID().replaceAll("-", "")}`;
  let loginRequired = false;
  try {
    await page.connect();
    await page.send("Page.enable");
    await page.send("Runtime.enable");
    for (let attempt = 0; attempt < 60; attempt += 1) {
      const ready = await page.send("Runtime.evaluate", { expression: "({ready:document.readyState,host:location.hostname,href:location.href})", returnByValue: true });
      const value = ready.result?.value ?? {};
      if (value.host === ALLOWED_HOST && (value.ready === "interactive" || value.ready === "complete")) break;
      if (String(value.href ?? "").includes("power.houtai.backend.example.invalid")) fail("LOGIN_REQUIRED");
      await new Promise((resolve) => setTimeout(resolve, 500));
      if (attempt === 59) fail("LIGHT_PAGE_NOT_READY");
    }
    const evaluated = await page.send("Runtime.evaluate", {
      expression: exportExpression(filters, cacheKey),
      awaitPromise: true,
      returnByValue: true,
    }, Number(options.timeout || 240000));
    if (evaluated.exceptionDetails) {
      fail(evaluated.exceptionDetails.exception?.description || evaluated.exceptionDetails.text || "page export failed");
    }
    const result = evaluated.result?.value;
    if (!result?.ok || !Number.isInteger(result.base64Length) || result.base64Length <= 0) {
      fail("page export returned no data");
    }
    let base64 = "";
    for (let offset = 0; offset < result.base64Length; offset += CDP_CHUNK_CHARS) {
      const end = Math.min(offset + CDP_CHUNK_CHARS, result.base64Length);
      const chunkResult = await page.send("Runtime.evaluate", {
        expression: `globalThis[${JSON.stringify(cacheKey)}]?.base64.slice(${offset}, ${end})`,
        returnByValue: true,
      });
      if (chunkResult.exceptionDetails) fail("page export chunk read failed");
      const chunk = chunkResult.result?.value;
      if (typeof chunk !== "string" || chunk.length !== end - offset) {
        fail(`page export chunk truncated at ${offset}`);
      }
      base64 += chunk;
    }
    if (base64.length !== result.base64Length) fail("page export base64 length mismatch");
    const raw = Buffer.from(base64, "base64");
    if (raw.length !== result.bytes) {
      fail(`page export byte length mismatch: expected ${result.bytes}, received ${raw.length}`);
    }
    fs.mkdirSync(path.dirname(output), { recursive: true });
    writeAtomic(output, raw);
    return {
      ok: true,
      file: output,
      bytes: raw.length,
      transportVerified: true,
      chunkChars: CDP_CHUNK_CHARS,
      contentType: result.contentType,
      filters: {
        entry: "新素材2.0", gid: filters.gid, game: filters.gid === "193" ? "忍界大战" : "未知",
        dateRange: filters.dateRange, materialRange: filters.materialRange,
        dateGroup: filters.dateGroup, group: filters.group,
        sourceVideoType: "视频", recordType: "新注册", filter: "是",
      },
      query: result.query,
      source: "active Chrome session via CDP page context",
    };
  } catch (error) {
    loginRequired = String(error?.message || error).includes("LOGIN_REQUIRED");
    throw error;
  } finally {
    await finishCaptureTarget(browser, page, targetId, cacheKey, loginRequired);
  }
}

function selfTest() {
  const state = statePayload(9222, 1234, path.join(process.cwd(), "profile"));
  const stateKeys = Object.keys(state).sort();
  const expected = ["createdAt", "pid", "port", "profileDir", "version"].sort();
  if (JSON.stringify(stateKeys) !== JSON.stringify(expected)) fail("state contains unexpected fields");
  safeUrl(`http://${ALLOWED_HOST}${MARKET_PATH}`, ["/marketng/"]);
  let blocked = false;
  try { safeUrl("https://example.com/"); } catch { blocked = true; }
  if (!blocked) fail("URL allowlist self-test failed");
  if (PAGE_BASE64_CHUNK_BYTES % 3 !== 0) fail("page Base64 chunk size must be divisible by 3");
  if (CDP_CHUNK_CHARS >= 32768) fail("CDP chunk size must stay below the observed serialization limit");
  const expression = queryExpression({ requests: [], timeout_ms: 5000, marketPath: MARKET_PATH }, "__test");
  if (!expression.includes("single_run_metadata_only") || expression.includes("localStorage") || expression.includes("document.cookie")) {
    fail("query expression safety self-test failed");
  }
  return {
    ok: true,
    stateKeys,
    allowedHost: ALLOWED_HOST,
    maxExportBytes: MAX_EXPORT_BYTES,
    pageBase64ChunkBytes: PAGE_BASE64_CHUNK_BYTES,
    cdpChunkChars: CDP_CHUNK_CHARS,
  };
}

async function main() {
  const { command, options } = parseArgs(process.argv.slice(2));
  let result;
  if (command === "open") result = await openSession(options);
  else if (command === "login") result = await showLogin(options);
  else if (command === "status") result = await sessionInfo(path.resolve(required(options, "state-file")));
  else if (command === "export") result = await exportData(options);
  else if (command === "query") result = await queryData(options);
  else if (command === "self-test") result = selfTest();
  else fail("command must be open, status, query, export, or self-test");
  process.stdout.write(JSON.stringify(result) + "\n");
}

export { queryExpression, exportExpression, readChunkedPayload, recoverChunkedPayload, CdpClient, writeAtomic, sessionInfo, queryData, exportData, finishCaptureTarget, showLogin };

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) main().catch((error) => {
  process.stderr.write(String(error?.stack || error?.message || error) + "\n");
  process.exit(1);
});

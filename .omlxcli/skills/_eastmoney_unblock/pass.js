"use strict";

const { spawn } = require("child_process");
const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");
const BROWSER_LOCK_FILE = path.join(__dirname, "browser_unblock.lock");
const BROWSER_LOCK_TTL_MS = 3 * 60 * 1000;
const COOKIE_JAR = new Map();

function readSetCookies(headers) {
  if (!headers) return [];
  if (typeof headers.getSetCookie === "function") {
    const arr = headers.getSetCookie();
    if (Array.isArray(arr)) return arr;
  }
  const one = headers.get("set-cookie");
  return one ? [one] : [];
}

function updateCookieJar(headers) {
  const setCookies = readSetCookies(headers);
  for (const line of setCookies) {
    const first = String(line || "").split(";")[0] || "";
    const idx = first.indexOf("=");
    if (idx <= 0) continue;
    const k = first.slice(0, idx).trim();
    const v = first.slice(idx + 1).trim();
    if (!k) continue;
    COOKIE_JAR.set(k, v);
  }
}

function buildCookieHeader() {
  const items = [];
  for (const [k, v] of COOKIE_JAR.entries()) items.push(`${k}=${v}`);
  return items.join("; ");
}

async function emFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (!headers.has("User-Agent")) {
    headers.set(
      "User-Agent",
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    );
  }
  if (!headers.has("Accept")) headers.set("Accept", "*/*");
  const cookieLine = buildCookieHeader();
  if (cookieLine) headers.set("Cookie", cookieLine);
  const response = await fetch(url, { ...options, headers, redirect: "follow" });
  updateCookieJar(response.headers);
  return response;
}

function encrypt(n) {
  let e;
  let t = "e98ae8878c264a7e";
  function r(s) {
    if (/^[\x00-\x7f]*$/.test(s)) return s;
    const out = [];
    for (let i = 0, j = 0; i < s.length; i++, j++) {
      const o = s.charCodeAt(i);
      if (o < 128) out[j] = s.charAt(i);
      else if (o < 2048) out[j] = String.fromCharCode(192 | (o >> 6), 128 | (o & 63));
      else out[j] = String.fromCharCode(224 | (o >> 12), 128 | ((o >> 6) & 63), 128 | (o & 63));
    }
    return out.join("");
  }
  function i(x) { return 4294967295 & x; }
  function o(n0, e0, t0, r0, i0, o0) {
    return (t0 >>> 5 ^ e0 << 2) + (e0 >>> 3 ^ t0 << 4) ^ (n0 ^ e0) + (o0[3 & r0 ^ i0] ^ t0);
  }
  function a(s, keepLen) {
    let out;
    const len = s.length;
    let n = len >> 2;
    if ((len & 3) !== 0) n++;
    out = keepLen ? new Array(n + 1) : new Array(n);
    if (keepLen) out[n] = len;
    for (let k = 0; k < len; k++) out[k >> 2] |= s.charCodeAt(k) << ((k & 3) << 3);
    return out;
  }
  if (n == null || n.length === 0) return n;
  n = r(n);
  t = r(t);
  const data = a(n, true);
  const key = a(t, false);
  if (key.length < 4) key.length = 4;
  const d = data.length;
  const u = d - 1;
  let z = data[u], y, sum = 0;
  let q = Math.floor(6 + 52 / d);
  while (q-- > 0) {
    sum = i(sum + 2654435769);
    const e1 = (sum >>> 2) & 3;
    for (let p = 0; p < u; p++) {
      y = data[p + 1];
      z = data[p] = i(data[p] + o(sum, y, z, p, e1, key));
    }
    y = data[0];
    z = data[u] = i(data[u] + o(sum, y, z, u, e1, key));
  }
  let out = "";
  for (let k = 0; k < data.length; k++) {
    out += String.fromCharCode(data[k] & 255, (data[k] >>> 8) & 255, (data[k] >>> 16) & 255, (data[k] >>> 24) & 255);
  }
  return out;
}

async function getContextId() {
  const response = await emFetch("https://i.eastmoney.com/websitecaptcha/api/getcontextid", {
    method: "POST",
    headers: {
      Referer: "https://www.eastmoney.com/",
      Origin: "https://www.eastmoney.com",
    },
  });
  const data = await response.json();
  return data && data.returncode === 0 ? data.contextid : "";
}

async function getCaptcha(ctxid) {
  const str = `appid=202503141611|ctxid=${ctxid}|a=quoteapi|p=|r=${Math.random()}`;
  const request = Buffer.from(encrypt(str), "binary").toString("base64");
  const encoded = encodeURIComponent(request);
  const url = `https://smartvcode2.eastmoney.com/Titan/api/captcha/get?callback=cb&ctxid=${ctxid}&request=${encoded}&_=${Date.now()}`;
  const response = await emFetch(url, {
    method: "GET",
    headers: { Referer: "https://quote.eastmoney.com/" },
  });
  const data = await response.text();
  const m = data.match(/cb\((.*)\);/);
  if (!m || !m[1]) return null;
  const res = JSON.parse(m[1]);
  return { type: res.Data.CaptchaType, info: JSON.parse(res.Data.CaptchaInfo) };
}

async function validate(ctxid, type, track, distance, t) {
  const str = `appid=202503141611|ctxid=${ctxid}|type=${type}|u=${distance}|d=${track}|a=quoteapi|p=|t=${t}|r=${Math.random()}`;
  const request = Buffer.from(encrypt(str), "binary").toString("base64");
  const encoded = encodeURIComponent(request);
  const url = `https://smartvcode2.eastmoney.com/Titan/api/captcha/Validate?callback=cb&ctxid=${ctxid}&request=${encoded}&_=${Date.now()}`;
  const response = await emFetch(url, {
    method: "GET",
    headers: { Referer: "https://quote.eastmoney.com/" },
  });
  const data = await response.text();
  const m = data.match(/cb\((.*)\);/);
  if (!m || !m[1]) return null;
  const res = JSON.parse(m[1]);
  return { returnCode: res.ReturnCode, data: JSON.parse(res.Data ? res.Data.Result : "{}") };
}

async function valid(ctxid, validateResult) {
  const body = new URLSearchParams();
  body.append("contextid", ctxid);
  body.append("validateresult", validateResult);
  await emFetch("https://i.eastmoney.com/websitecaptcha/api/valid", {
    method: "POST",
    body,
    headers: {
      Referer: "https://quote.eastmoney.com/",
      Origin: "https://quote.eastmoney.com",
    },
  });
}

async function checkBlocked() {
  const url = "https://i.eastmoney.com/websitecaptcha/api/checkuser?callback=wsc_checkuser";
  const response = await emFetch(url, {
    method: "GET",
    headers: { Referer: "https://quote.eastmoney.com/" },
  });
  const text = await response.text();
  const m = text.match(/wsc_checkuser\((.*)\)/);
  if (!m || !m[1]) {
    return { ok: false, blocked: null, reason: "checkuser_parse_failed" };
  }
  const data = JSON.parse(m[1]);
  return { ok: true, blocked: Boolean(data.block), raw: data };
}

function getSliderTrace(captchaUrl, sliderUrl) {
  return new Promise((resolve, reject) => {
    const py = path.join(__dirname, "gen_track.py");
    const proc = spawn("python3", [py, captchaUrl, sliderUrl]);
    let output = "";
    let err = "";
    proc.stdout.on("data", (d) => { output += d.toString(); });
    proc.stderr.on("data", (d) => { err += d.toString(); });
    proc.on("close", (code) => {
      if (code !== 0) return reject(new Error(err || `python exit ${code}`));
      try {
        const res = JSON.parse(output.trim());
        if (!res.success) return reject(new Error(res.error || "gen track failed"));
        resolve({ distance: res.distance, trace: res.trace });
      } catch (e) {
        reject(e);
      }
    });
    proc.on("error", reject);
  });
}

function runBrowserFallback() {
  return new Promise((resolve) => {
    const py = path.join(__dirname, "browser_unblock.py");
    const proc = spawn("python3", [py], { stdio: ["ignore", "pipe", "pipe"] });
    let out = "";
    let err = "";
    proc.stdout.on("data", (d) => { out += d.toString(); });
    proc.stderr.on("data", (d) => { err += d.toString(); });
    proc.on("close", (code) => {
      resolve({ code: Number(code || 0), out: out.trim(), err: err.trim() });
    });
    proc.on("error", (e) => {
      resolve({ code: 9, out: "", err: String(e) });
    });
  });
}

function preflightCheck() {
  const genTrack = path.join(__dirname, "gen_track.py");
  const browserFallback = path.join(__dirname, "browser_unblock.py");
  if (!fs.existsSync(genTrack)) {
    return { ok: false, code: "missing_gen_track", detail: genTrack };
  }
  if (!fs.existsSync(browserFallback)) {
    return { ok: false, code: "missing_browser_fallback", detail: browserFallback };
  }
  const py = spawnSync("python3", ["--version"], { encoding: "utf-8" });
  if (py.error || py.status !== 0) {
    return { ok: false, code: "python3_unavailable", detail: String(py.error || py.stderr || py.stdout || "") };
  }
  return { ok: true };
}

function acquireBrowserFallbackLock() {
  const now = Date.now();
  try {
    if (fs.existsSync(BROWSER_LOCK_FILE)) {
      const raw = fs.readFileSync(BROWSER_LOCK_FILE, "utf-8");
      let lockedAt = 0;
      try {
        const obj = JSON.parse(raw || "{}");
        lockedAt = Number(obj.locked_at_ms || 0);
      } catch {
        lockedAt = 0;
      }
      if (lockedAt > 0 && now - lockedAt > BROWSER_LOCK_TTL_MS) {
        fs.unlinkSync(BROWSER_LOCK_FILE);
      }
    }
  } catch {
    // ignore stale lock cleanup errors, continue to lock attempt
  }
  try {
    const fd = fs.openSync(BROWSER_LOCK_FILE, "wx");
    const payload = JSON.stringify({
      pid: process.pid,
      locked_at_ms: now,
      locked_at_iso: new Date(now).toISOString(),
    });
    fs.writeFileSync(fd, payload);
    fs.closeSync(fd);
    return true;
  } catch {
    return false;
  }
}

function releaseBrowserFallbackLock() {
  try {
    if (fs.existsSync(BROWSER_LOCK_FILE)) fs.unlinkSync(BROWSER_LOCK_FILE);
  } catch {
    // ignore lock cleanup errors
  }
}

async function main() {
  const preflight = preflightCheck();
  if (!preflight.ok) {
    throw new Error(`preflight_failed code=${preflight.code} detail=${String(preflight.detail || "").slice(0, 220)}`);
  }
  // 先打开门户页建立站点会话，贴近“人工打开页面后再滑块验证”的真实路径。
  await emFetch("https://www.eastmoney.com/", {
    method: "GET",
    headers: { Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8" },
  });
  const before = await checkBlocked();
  if (!before.ok) {
    throw new Error(before.reason || "check_block_before_failed");
  }
  if (!before.blocked) {
    console.log(JSON.stringify({ ok: true, action: "skip_not_blocked" }));
    return;
  }

  const maxAttempts = 3;
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    const ctxid = await getContextId();
    if (!ctxid) {
      continue;
    }
    const init = await getCaptcha(ctxid);
    if (!init || init.type !== "init") {
      continue;
    }
    await validate(ctxid, init.type, "", "", 0);
    const slide = await getCaptcha(ctxid);
    if (!slide || !slide.info || !slide.info.static_servers || !slide.info.bg || !slide.info.slice) {
      continue;
    }
    const captchaUrl = `https://${slide.info.static_servers[0]}/${slide.info.bg}`;
    const sliderUrl = `https://${slide.info.static_servers[0]}/${slide.info.slice}`;
    const result = await getSliderTrace(captchaUrl, sliderUrl);
    const baseDistance = Number(result.distance);
    const distanceCandidates = [baseDistance, baseDistance - 2, baseDistance - 1, baseDistance + 1, baseDistance + 2]
      .filter((x) => Number.isFinite(x) && x >= 0);
    for (const distance of distanceCandidates) {
      const trace = String(result.trace || "").replace(`,${baseDistance},`, `,${distance},`);
      const times = String(trace).split(",");
      const total = times[times.length - 1];
      const check = await validate(ctxid, slide.type, trace, String(distance), total);
      if (!(check && check.returnCode === "0" && check.data && check.data.validate)) {
        continue;
      }
      await valid(ctxid, check.data.validate);
      await new Promise((r) => setTimeout(r, 300));
      const after = await checkBlocked();
      if (after.ok && after.blocked === false) {
        console.log(JSON.stringify({ ok: true, action: "unblocked", attempt, distance }));
        return;
      }
    }
    await new Promise((r) => setTimeout(r, 350));
  }

  const finalState = await checkBlocked();
  if (finalState.ok && finalState.blocked === false) {
    console.log(JSON.stringify({ ok: true, action: "unblocked_after_retry" }));
    return;
  }
  if (!acquireBrowserFallbackLock()) {
    throw new Error("browser_fallback_locked_by_other_process");
  }
  let fb = null;
  try {
    fb = await runBrowserFallback();
  } finally {
    releaseBrowserFallbackLock();
  }
  if (fb.code === 0) {
    const final2 = await checkBlocked();
    if (final2.ok && final2.blocked === false) {
      console.log(JSON.stringify({ ok: true, action: "unblocked_by_browser_fallback", detail: fb.out || null }));
      return;
    }
  }
  throw new Error(`still_blocked_after_browser_fallback code=${fb.code} stderr=${(fb.err || "").slice(0, 220)}`);
}

main().catch((err) => {
  const msg = err && err.message ? String(err.message) : String(err);
  console.error(msg);
  process.exitCode = 2;
});


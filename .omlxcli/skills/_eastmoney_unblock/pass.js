"use strict";

const { spawn } = require("child_process");
const path = require("path");

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
  const response = await fetch("https://i.eastmoney.com/websitecaptcha/api/getcontextid", { method: "POST", redirect: "follow" });
  const data = await response.json();
  return data && data.returncode === 0 ? data.contextid : "";
}

async function getCaptcha(ctxid) {
  const str = `appid=202503141611|ctxid=${ctxid}|a=quoteapi|p=|r=${Math.random()}`;
  const request = Buffer.from(encrypt(str), "binary").toString("base64");
  const encoded = encodeURIComponent(request);
  const url = `https://smartvcode2.eastmoney.com/Titan/api/captcha/get?callback=cb&ctxid=${ctxid}&request=${encoded}&_=${Date.now()}`;
  const response = await fetch(url, { method: "GET", redirect: "follow" });
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
  const response = await fetch(url, { method: "GET", redirect: "follow" });
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
  await fetch("https://i.eastmoney.com/websitecaptcha/api/valid", {
    method: "POST",
    body,
    redirect: "follow",
  });
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

async function main() {
  const ctxid = await getContextId();
  if (!ctxid) return;
  const init = await getCaptcha(ctxid);
  if (!init || init.type !== "init") return;
  await validate(ctxid, init.type, "", "", 0);
  const slide = await getCaptcha(ctxid);
  if (!slide || !slide.info) return;
  const captchaUrl = `https://${slide.info.static_servers[0]}/${slide.info.bg}`;
  const sliderUrl = `https://${slide.info.static_servers[0]}/${slide.info.slice}`;
  const result = await getSliderTrace(captchaUrl, sliderUrl);
  const times = String(result.trace).split(",");
  const total = times[times.length - 1];
  const check = await validate(ctxid, slide.type, result.trace, result.distance, total);
  if (check && check.returnCode === "0" && check.data && check.data.validate) {
    await valid(ctxid, check.data.validate);
  }
}

main().catch(() => {
  process.exitCode = 0;
});


/** 将 `/api/...` 解析为与当前 UI 同部署前缀下的绝对 URL（避免子路径反代时误请求站点根 `/api`）。 */
export function resolveApiUrl(path) {
  const rel = String(path || "").replace(/^\/+/, "");
  const uiDir = new URL("../", import.meta.url);
  return new URL(`../${rel}`, uiDir).href;
}

export async function api(path, options = {}) {
  const res = await fetch(resolveApiUrl(path), {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const requestId = res.headers.get("x-request-id") || "";
    let payload = null;
    try {
      payload = await res.json();
    } catch {
      payload = { message: await res.text() };
    }
    const err = new Error(payload?.message || "请求失败");
    err.status = res.status;
    err.errorCode = payload?.error_code || "HTTP_ERROR";
    err.requestId = payload?.request_id || requestId;
    throw err;
  }
  if (res.status === 204) return null;
  return res.json();
}

export async function fetchModelsForVendor(vendorId) {
  const q = new URLSearchParams({ vendor_id: String(vendorId || "").trim() });
  return api(`/api/models?${q.toString()}`);
}

export async function probeVendor(apiBase, apiKey) {
  return api("/api/vendors/probe", {
    method: "POST",
    body: JSON.stringify({ api_base: apiBase, api_key: apiKey }),
  });
}

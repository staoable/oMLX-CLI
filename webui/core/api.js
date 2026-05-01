export async function api(path, options = {}) {
  const res = await fetch(path, {
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

export async function fetchModelsForBase(apiBase) {
  const base = (apiBase || "").trim() || "http://127.0.0.1:8000/v1";
  const q = new URLSearchParams({ api_base: base });
  return api(`/api/models?${q.toString()}`);
}

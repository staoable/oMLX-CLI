import {
  DEFAULT_MODEL,
  SIDEBAR_STORAGE_KEY,
  ARCHIVED_SESSIONS_KEY,
  state,
  el,
} from "/ui/core/state.js";
import { api, fetchModelsForVendor, probeVendor, resolveApiUrl } from "/ui/core/api.js";
import { escapeHtml, renderMarkdown, renderMetricsFooter, enhanceCodeBlocks } from "/ui/core/markdown.js";
import { readSseEvents } from "/ui/core/stream.js";

function formatApiError(err) {
  if (!err) return "未知错误";
  const msg = err.message || String(err);
  const low = msg.toLowerCase();
  if (
    err.name === "TypeError" &&
    (low.includes("failed to fetch") || low.includes("load failed") || low.includes("networkerror"))
  ) {
    return "无法连接后端（网络层失败）。请确认：① 已通过 uvicorn 提供的地址打开界面（例如 http://127.0.0.1:端口/ui/ ，勿用本地 file://）；② 地址栏主机、端口与终端启动服务一致；③ 若挂在反向代理子路径下，需保证 /ui 与 /api 由同一应用转发。";
  }
  const code = err.errorCode ? ` [${err.errorCode}]` : "";
  const rid = err.requestId ? ` (request_id=${err.requestId})` : "";
  return `${msg}${code}${rid}`;
}

function scrollChatToBottom() {
  const wrap = el("chatScroll");
  requestAnimationFrame(() => {
    wrap.scrollTop = wrap.scrollHeight;
  });
}

function setSending(v) {
  state.sending = v;
  const btn = el("sendBtn");
  btn.disabled = v;
  el("messageInput").readOnly = v;
  el("attachBtn").disabled = v;
}

function setModalVisible(v) {
  el("confirmModal").hidden = !v;
}

function openConfirmModal(command, reason) {
  state.pendingConfirm = { command, reason };
  el("confirmCommand").textContent = command || "";
  el("confirmReason").textContent = reason || "该命令需要你确认后才执行。";
  setModalVisible(true);
}

function closeConfirmModal() {
  state.pendingConfirm = null;
  setModalVisible(false);
}

function resizeComposer() {
  const ta = el("messageInput");
  ta.style.height = "auto";
  ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`;
}

function updateTitleControls() {
  const has = Boolean(state.currentSessionId);
  el("editTitleBtn").disabled = !has;
}

function initSidebar() {
  const collapsed = localStorage.getItem(SIDEBAR_STORAGE_KEY) === "1";
  el("app").classList.toggle("app--sidebar-collapsed", collapsed);
  syncSidebarToggleUi(collapsed);
}

function syncSidebarToggleUi(collapsed) {
  const btn = el("sidebarToggle");
  btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
  btn.textContent = collapsed ? "⟩" : "⟨";
  btn.title = collapsed ? "展开侧栏" : "折叠侧栏";
}

function toggleSidebar() {
  const app = el("app");
  const next = !app.classList.contains("app--sidebar-collapsed");
  app.classList.toggle("app--sidebar-collapsed", next);
  localStorage.setItem(SIDEBAR_STORAGE_KEY, next ? "1" : "0");
  syncSidebarToggleUi(next);
}

function appendUserMessage(text) {
  const article = document.createElement("article");
  article.className = "message message--user";
  article.setAttribute("aria-label", "用户消息");
  article.innerHTML = `
    <div class="message__avatar" aria-hidden="true">我</div>
    <div class="message__bubble">
      <div class="markdown-body">${renderMarkdown(text)}</div>
      <div class="message-attachments"></div>
    </div>
  `;
  el("chatList").appendChild(article);
  enhanceCodeBlocks(article.querySelector(".markdown-body"));
  scrollChatToBottom();
  return article;
}

function renderMessageAttachments(container, attachments) {
  if (!container) return;
  const list = (attachments || []).filter((a) => a && a.name);
  container.innerHTML = "";
  if (!list.length) return;
  for (const a of list) {
    const chip = document.createElement("span");
    chip.className = "attachment-chip attachment-chip--sent";
    const size = Number(a.size || 0);
    chip.textContent = `${a.name}${size > 0 ? ` (${Math.round(size / 1024)}KB)` : ""}`;
    container.appendChild(chip);
  }
}

function appendAssistantMessage(text, { error = false, metrics = null } = {}) {
  const article = document.createElement("article");
  article.className = error
    ? "message message--assistant message--error"
    : "message message--assistant";
  article.setAttribute("aria-label", error ? "错误" : "助手消息");
  const footer = !error && metrics ? renderMetricsFooter(metrics) : "";
  const bodyMd = error ? `<p>${escapeHtml(text)}</p>` : renderMarkdown(text);
  article.innerHTML = `
    <div class="message__avatar" aria-hidden="true">${error ? "!" : "AI"}</div>
    <div class="message__bubble">
      <div class="markdown-body">${bodyMd}</div>
      ${footer}
    </div>
  `;
  el("chatList").appendChild(article);
  if (!error) enhanceCodeBlocks(article.querySelector(".markdown-body"));
  scrollChatToBottom();
}

function renderObservabilityPanel() {
  const panel = el("obsPanel");
  if (!panel) return;
  const data = state.currentSessionObservability || { executions: [], contextInjections: [] };
  const filter = el("obsExecStatusFilter")?.value || "all";
  const executions = (data.executions || [])
    .filter((r) => filter === "all" || String(r.status || "") === filter)
    .slice(0, 12);
  const injections = (data.contextInjections || []).slice(0, 12);
  panel.innerHTML = `
    <section class="obs-col">
      <div class="obs-title">执行审计（最近 ${executions.length} 条）</div>
      <div class="obs-list" id="obsExecList"></div>
    </section>
    <section class="obs-col">
      <div class="obs-title">上下文注入（最近 ${injections.length} 条）</div>
      <div class="obs-list" id="obsCtxList"></div>
    </section>
  `;
  const execList = panel.querySelector("#obsExecList");
  if (!executions.length) {
    execList.innerHTML = '<div class="obs-empty">暂无执行记录</div>';
  } else {
    executions.forEach((r) => {
      const div = document.createElement("div");
      div.className = "obs-item";
      const duration = Number(r.duration_ms || 0);
      const reason = String(r.reason || "");
      const stdout = String(r.stdout || "");
      const stderr = String(r.stderr || "");
      div.innerHTML = `
        <div class="obs-item__head">
          <span>${escapeHtml(r.exec_type || "-")} · ${escapeHtml(r.status || "-")}</span>
          <span>exit=${escapeHtml(String(r.exit_code ?? "-"))}</span>
        </div>
        <div class="obs-item__cmd">${escapeHtml(r.command || "")}</div>
        <div class="obs-item__meta">
          duration=${escapeHtml(duration ? `${duration.toFixed(1)}ms` : "-")}
          ${reason ? ` · reason=${escapeHtml(reason)}` : ""}
        </div>
        <details class="obs-item__detail">
          <summary>查看输出详情</summary>
          <pre>stdout:\n${escapeHtml(stdout || "(empty)")}\n\nstderr:\n${escapeHtml(stderr || "(empty)")}</pre>
        </details>
      `;
      execList.appendChild(div);
    });
  }
  const ctxList = panel.querySelector("#obsCtxList");
  if (!injections.length) {
    ctxList.innerHTML = '<div class="obs-empty">暂无上下文注入记录</div>';
  } else {
    injections.forEach((r) => {
      const div = document.createElement("div");
      div.className = "obs-item";
      div.innerHTML = `
        <div class="obs-item__head">
          <span>${escapeHtml(r.source || "-")} · ${escapeHtml(r.role || "-")}</span>
          <span>${escapeHtml(String(r.char_count ?? 0))} chars</span>
        </div>
        <div>${r.dropped ? "已裁剪" : "已注入"}${r.reason ? ` · ${escapeHtml(r.reason)}` : ""}</div>
      `;
      ctxList.appendChild(div);
    });
  }
}

async function refreshObservability() {
  if (!state.currentSessionId) return;
  try {
    const [executions, contextInjections] = await Promise.all([
      api(`/api/sessions/${state.currentSessionId}/executions?limit=120`),
      api(`/api/sessions/${state.currentSessionId}/context-injections?limit=120`),
    ]);
    state.currentSessionObservability = { executions, contextInjections };
    renderObservabilityPanel();
  } catch (e) {
    appendAssistantMessage(`观测数据刷新失败: ${formatApiError(e)}`, { error: true });
  }
}

function beginAssistantStream() {
  const article = document.createElement("article");
  article.className = "message message--assistant message--streaming";
  article.setAttribute("aria-label", "助手正在回复");
  article.innerHTML = `
    <div class="message__avatar" aria-hidden="true">AI</div>
    <div class="message__bubble">
      <div class="markdown-body"><p class="thread-empty" style="padding:0;margin:0;font-size:14px;">正在输入…</p></div>
      <details class="exec-timeline" open>
        <summary class="exec-timeline__summary">
          <span class="exec-timeline__title">执行时间线</span>
          <span class="exec-timeline__hint">展开 / 折叠</span>
        </summary>
        <div class="exec-steps"></div>
      </details>
    </div>
  `;
  el("chatList").appendChild(article);
  state.streamingMdEl = article.querySelector(".markdown-body");
  state.streamingStepsEl = article.querySelector(".exec-steps");
  scrollChatToBottom();
}

function updateStreamingMarkdown(text) {
  if (!state.streamingMdEl) return;
  const body = (text || "").trim()
    ? renderMarkdown(text)
    : '<p class="thread-empty" style="padding:0;margin:0;">正在输入…</p>';
  state.streamingMdEl.innerHTML = body;
  enhanceCodeBlocks(state.streamingMdEl);
  scrollChatToBottom();
}

function endAssistantStream() {
  const node = state.streamingMdEl;
  state.streamingMdEl = null;
  state.streamingStepsEl = null;
  if (node) {
    const article = node.closest(".message");
    if (article) article.classList.remove("message--streaming");
  }
}

function removeStreamingPlaceholder() {
  if (!state.streamingMdEl) return;
  const article = state.streamingMdEl.closest(".message");
  if (article) article.remove();
  state.streamingMdEl = null;
  state.streamingStepsEl = null;
}

function appendTraceRow(ev) {
  if (!state.streamingStepsEl) return;
  const div = document.createElement("div");
  div.className = "exec-trace-row";
  const action = String(ev.action || "trace");
  const tid = ev.turn_id ? String(ev.turn_id).slice(0, 12) : "";
  div.textContent = `[agent_trace] ${action}${tid ? " · " + tid : ""}`;
  state.streamingStepsEl.appendChild(div);
  scrollChatToBottom();
}

function appendExecStep(step) {
  if (!state.streamingStepsEl) return;
  const div = document.createElement("div");
  div.className = "exec-step";
  const cmd = escapeHtml(step.command || "");
  if (step.type === "exec_step") {
    div.innerHTML = `<div>执行命令</div><div class="exec-step__cmd">$ ${cmd}</div>`;
  } else {
    const exitCode = Number(step.exit_code ?? 0);
    const shortOut = String(step.stdout || "").slice(0, 280);
    const shortErr = String(step.stderr || "").slice(0, 280);
    div.innerHTML =
      `<div>命令结果</div><div class="exec-step__cmd">$ ${cmd}</div>` +
      `<div class="exec-step__meta">exit_code=${exitCode}` +
      `${shortOut ? ` · stdout: ${escapeHtml(shortOut)}` : ""}` +
      `${shortErr ? ` · stderr: ${escapeHtml(shortErr)}` : ""}</div>`;
  }
  state.streamingStepsEl.appendChild(div);
  scrollChatToBottom();
}

function renderSessions() {
  const list = el("sessionList");
  list.innerHTML = "";
  state.sessions.forEach((s) => {
    const row = document.createElement("div");
    row.className =
      "session-row" +
      (s.id === state.currentSessionId ? " active" : "") +
      (s.archived ? " session-row--archived" : "");
    row.setAttribute("role", "listitem");

    const main = document.createElement("button");
    main.type = "button";
    main.className = "session-main";
    main.innerHTML = `<span class="session-title">${escapeHtml(s.title)}</span><span class="session-meta">${escapeHtml(s.model)}</span>`;
    main.onclick = () => selectSession(s.id);

    const del = document.createElement("button");
    del.type = "button";
    del.className = "session-del";
    del.innerText = "删除";
    del.setAttribute("aria-label", `删除会话 ${s.title}`);
    del.onclick = (ev) => deleteSession(s.id, ev);

    row.appendChild(main);
    row.appendChild(del);
    list.appendChild(row);
  });
}

function fillModelSelect(models, currentModel) {
  const sel = el("modelSelect");
  sel.innerHTML = "";
  let want = (currentModel || "").trim() || DEFAULT_MODEL;
  const uniq = [...new Set((models || []).filter(Boolean))];
  if (!uniq.includes(want)) {
    const opt = document.createElement("option");
    opt.value = want;
    opt.textContent = `${want}（不在服务端列表）`;
    sel.appendChild(opt);
  }
  for (const id of uniq) {
    const opt = document.createElement("option");
    opt.value = id;
    opt.textContent = id;
    sel.appendChild(opt);
  }
  if (!sel.options.length) {
    const opt = document.createElement("option");
    opt.value = want;
    opt.textContent = want;
    sel.appendChild(opt);
  }
  sel.value = want;
}

async function refreshModelDropdown() {
  const vendorId = (el("vendorSelect")?.value || "").trim();
  const current = el("modelSelect").value || DEFAULT_MODEL;
  if (!vendorId) {
    fillModelSelect([], current);
    return;
  }
  try {
    const data = await fetchModelsForVendor(vendorId);
    fillModelSelect(data.models || [], current);
  } catch (e) {
    console.warn(e);
    fillModelSelect([], el("modelSelect").value || DEFAULT_MODEL);
    appendAssistantMessage(`模型列表刷新失败: ${formatApiError(e)}`, { error: true });
  }
}

async function fillSessionVendorSelect(selectedId) {
  const sel = el("vendorSelect");
  if (!sel) return;
  let list = [];
  try {
    list = await api("/api/vendors");
  } catch {
    list = [];
  }
  const keep = (selectedId || "").trim();
  sel.innerHTML = "";
  if (!list.length) {
    const ph = document.createElement("option");
    ph.value = "";
    ph.textContent = "（请先在侧栏「模型设置」添加并保存）";
    sel.appendChild(ph);
    sel.value = "";
    return;
  }
  for (const v of list) {
    const opt = document.createElement("option");
    opt.value = v.id;
    opt.textContent = v.name || v.slug;
    sel.appendChild(opt);
  }
  sel.value = keep && [...sel.options].some((o) => o.value === keep) ? keep : list[0].id;
}

function setVendorFormHint(text) {
  const n = el("vendorFormHint");
  if (n) n.textContent = text || "";
}

/** 密码型输入在部分浏览器中需先失焦再读，才能拿到刚粘贴/输入的值。 */
async function readVendorApiKeyTrimmed() {
  const keyEl = el("vendorFormApiKey");
  if (!keyEl) return "";
  if (document.activeElement === keyEl) {
    keyEl.blur();
  }
  await new Promise((r) => setTimeout(r, 0));
  return (keyEl.value || "").trim();
}

function clearVendorForm() {
  el("vendorFormId").value = "";
  el("vendorFormName").value = "";
  el("vendorFormApiBase").value = "";
  el("vendorFormApiKey").value = "";
  el("vendorFormDefaultModel").innerHTML = "";
  const o = document.createElement("option");
  o.value = "";
  o.textContent = "（请先下载模型列表）";
  el("vendorFormDefaultModel").appendChild(o);
  setVendorFormHint("");
}

async function renderVendorList() {
  const mount = el("vendorListMount");
  if (!mount) return;
  let list = [];
  let fetchFailed = false;
  try {
    list = await api("/api/vendors");
  } catch {
    fetchFailed = true;
    list = [];
  }
  mount.innerHTML = "";
  if (!list.length) {
    mount.innerHTML = fetchFailed
      ? '<div class="obs-empty">未能加载模型设置列表（请检查服务）。</div>'
      : '<div class="obs-empty">尚未配置模型设置。请在下方创建第一条（名称、API Base、API Key 与默认模型）。</div>';
    return;
  }
  for (const v of list) {
    const row = document.createElement("div");
    row.className = "vendor-row";
    const left = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = v.name || "";
    const meta = document.createElement("div");
    meta.className = "vendor-row__meta";
    meta.textContent = v.api_base || "";
    left.appendChild(title);
    left.appendChild(meta);
    const actions = document.createElement("div");
    const bEdit = document.createElement("button");
    bEdit.type = "button";
    bEdit.className = "btn btn--ghost";
    bEdit.textContent = "编辑";
    bEdit.setAttribute("data-vendor-edit", v.id);
    actions.appendChild(bEdit);
    const bDel = document.createElement("button");
    bDel.type = "button";
    bDel.className = "btn btn--ghost";
    bDel.textContent = "删除";
    bDel.setAttribute("data-vendor-del", v.id);
    actions.appendChild(bDel);
    row.appendChild(left);
    row.appendChild(actions);
    mount.appendChild(row);
  }
  mount.querySelectorAll("[data-vendor-edit]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.getAttribute("data-vendor-edit");
      await loadVendorIntoForm(id);
    });
  });
  mount.querySelectorAll("[data-vendor-del]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.getAttribute("data-vendor-del");
      if (!confirm("确定删除该模型设置？已绑定会话将无法删除。")) return;
      try {
        await api(`/api/vendors/${id}`, { method: "DELETE" });
        setVendorFormHint("已删除。");
        await renderVendorList();
        await fillSessionVendorSelect(state.currentVendorId);
      } catch (e) {
        setVendorFormHint(`删除失败：${formatApiError(e)}`);
      }
    });
  });
}

async function loadVendorIntoForm(vendorId) {
  const v = await api(`/api/vendors/${vendorId}`);
  el("vendorFormId").value = v.id;
  el("vendorFormName").value = v.name || "";
  el("vendorFormApiBase").value = v.api_base || "";
  el("vendorFormApiKey").value = v.api_key != null ? String(v.api_key) : "";
  const sel = el("vendorFormDefaultModel");
  sel.innerHTML = "";
  const dm = (v.default_model || "").trim();
  if (dm) {
    const opt = document.createElement("option");
    opt.value = dm;
    opt.textContent = dm;
    sel.appendChild(opt);
    sel.value = dm;
  } else {
    const o = document.createElement("option");
    o.value = "";
    o.textContent = "（请先下载模型列表）";
    sel.appendChild(o);
  }
  setVendorFormHint("");
}

function closeVendorsModal() {
  el("vendorsModal").hidden = true;
}

async function openVendorsModal() {
  el("vendorsModal").hidden = false;
  clearVendorForm();
  await renderVendorList();
}

async function onVendorProbeClick() {
  const base = el("vendorFormApiBase").value.trim();
  let key = await readVendorApiKeyTrimmed();
  const vid = el("vendorFormId").value.trim();
  if (!key && vid) {
    try {
      const saved = await api(`/api/vendors/${vid}`);
      key = saved.api_key != null ? String(saved.api_key).trim() : "";
      if (key) el("vendorFormApiKey").value = key;
    } catch {
      /* ignore */
    }
  }
  if (!base) {
    setVendorFormHint("请填写 API Base。");
    return;
  }
  if (!key) {
    setVendorFormHint("请填写 API Key；编辑已保存条目并点「编辑」可加载库里已存密钥。");
    return;
  }
  setVendorFormHint("正在下载模型列表…");
  try {
    const res = await probeVendor(base, key);
    const models = res.models || [];
    const sel = el("vendorFormDefaultModel");
    sel.innerHTML = "";
    for (const id of models) {
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = id;
      sel.appendChild(opt);
    }
    if (models.length) sel.value = models[0];
    setVendorFormHint(`已获取 ${models.length} 个模型。默认已选第一项，可修改后保存模型设置。`);
  } catch (e) {
    setVendorFormHint(`下载模型列表失败：${formatApiError(e)}`);
  }
}

async function onVendorSaveRecordClick() {
  const id = el("vendorFormId").value.trim();
  const name = el("vendorFormName").value.trim();
  const apiBase = el("vendorFormApiBase").value.trim();
  const defaultModel = el("vendorFormDefaultModel").value.trim();
  const apiKey = await readVendorApiKeyTrimmed();
  if (!name || !apiBase) {
    setVendorFormHint("请填写显示名与 API Base。");
    return;
  }
  setVendorFormHint("正在保存…");
  let hintAfter = "";
  try {
    if (id) {
      const patchBody = { name, api_base: apiBase, default_model: defaultModel };
      if (apiKey) patchBody.api_key = apiKey;
      await api(`/api/vendors/${id}`, {
        method: "PATCH",
        body: JSON.stringify(patchBody),
      });
      hintAfter = apiKey
        ? "已更新该条模型设置（含 API Key，已写入数据库）。表单已清空——继续添加请直接填写后保存；修改其它条请先在列表点「编辑」。"
        : "已更新该条模型设置（未传 Key 则数据库中原密钥不变）。表单已清空；修改其它模型设置请先在列表点「编辑」。";
    } else {
      const created = await api("/api/vendors", {
        method: "POST",
        body: JSON.stringify({
          name,
          api_base: apiBase,
          default_model: defaultModel,
          api_key: apiKey || null,
        }),
      });
      const label = ((created.name || name) || "").trim() || name;
      hintAfter = apiKey
        ? `已创建「${label}」（含 API Key）。表单已清空，可继续添加其它模型设置。`
        : `已创建「${label}」。补写 API Key 或修改该条请在列表点「编辑」；添加另一条请直接填写下方表单并保存。`;
    }
    await renderVendorList();
    await fillSessionVendorSelect(state.currentVendorId);
    clearVendorForm();
    setVendorFormHint(hintAfter);
  } catch (e) {
    setVendorFormHint(`保存失败：${formatApiError(e)}`);
  }
}

function renderEmptyHint() {
  const thread = el("chatList");
  thread.innerHTML = "";
  const div = document.createElement("div");
  div.className = "thread-empty";
  div.innerHTML =
    "<strong>开始对话</strong>" +
    "在页面<strong>最下方输入框</strong>输入内容，Enter 发送，Shift+Enter 换行。" +
    '<span class="thread-empty__sub">需要改模型、模型设置或工作目录时点顶部「设置」；排查执行与上下文时点「调试」。</span>';
  thread.appendChild(div);
}

function humanSize(n) {
  const b = Number(n || 0);
  if (b < 1024) return `${b}B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)}KB`;
  return `${(b / 1024 / 1024).toFixed(1)}MB`;
}

function renderAttachmentTray() {
  const tray = el("attachmentTray");
  const list = state.pendingAttachments;
  tray.innerHTML = "";
  tray.hidden = list.length === 0;
  if (!list.length) return;
  for (const a of list) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "attachment-chip";
    chip.title = `${a.name} (${a.mime || "unknown"})`;
    chip.textContent = `${a.name} · ${humanSize(a.size)}`;
    chip.addEventListener("click", () => {
      state.pendingAttachments = state.pendingAttachments.filter((x) => x.id !== a.id);
      renderAttachmentTray();
    });
    tray.appendChild(chip);
  }
}

function normalizePastedFile(file) {
  if (!file) return null;
  const name = file.name || `paste-${Date.now()}`;
  const mime = file.type || "application/octet-stream";
  const size = file.size || 0;
  return { file, name, mime, size, id: `${name}-${size}-${Date.now()}-${Math.random()}` };
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result || ""));
    r.onerror = () => reject(r.error);
    r.readAsDataURL(file);
  });
}

function addFiles(files) {
  const maxEach = 25 * 1024 * 1024;
  const arr = Array.from(files || []);
  for (const f of arr) {
    const n = normalizePastedFile(f);
    if (!n) continue;
    if (n.size > maxEach) {
      appendAssistantMessage(`附件 ${n.name} 超过 25MB，已跳过。`, { error: true });
      continue;
    }
    state.pendingAttachments.push(n);
  }
  renderAttachmentTray();
}

async function loadSessions() {
  const q = state.includeArchivedSessions ? "?include_archived=1" : "";
  state.sessions = await api(`/api/sessions${q}`);
  const ids = new Set(state.sessions.map((s) => s.id));
  if (state.currentSessionId && !ids.has(state.currentSessionId)) {
    state.currentSessionId = null;
  }
  renderSessions();
  if (!state.currentSessionId && state.sessions.length > 0) {
    await selectSession(state.sessions[0].id);
  } else if (!state.currentSessionId && state.sessions.length === 0) {
    el("chatTitle").textContent = "oMLX CLI";
    renderEmptyHint();
    updateTitleControls();
  }
}

async function selectSession(sessionId) {
  state.currentSessionId = sessionId;
  state.pendingAttachments = [];
  renderAttachmentTray();
  renderSessions();
  const data = await api(`/api/sessions/${sessionId}`);
  state.currentSessionObservability = {
    executions: data.executions || [],
    contextInjections: data.context_injections || [],
  };
  renderObservabilityPanel();
  el("chatTitle").textContent = data.title || "会话";
  el("chatList").innerHTML = "";
  if (!data.messages.length) {
    renderEmptyHint();
  } else {
    data.messages.forEach((m) => {
      if (m.role === "user") {
        const article = appendUserMessage(m.content);
        renderMessageAttachments(article.querySelector(".message-attachments"), m.attachments || []);
      } else if (m.kind === "error") {
        appendAssistantMessage(m.content, { error: true });
      } else {
        appendAssistantMessage(m.content, { metrics: m.metrics || null });
      }
    });
  }
  state.sessionApiBaseFromServer = data.api_base || "";
  state.effectiveApiBase = data.api_base || "";
  el("workspacePathInput").value = data.workspace_path || "";
  el("executionEnabledInput").checked = Boolean(data.execution_enabled);
  el("confirmEachInput").checked = data.confirm_each !== false;
  const arch = el("sessionArchivedInput");
  if (arch) arch.checked = Boolean(data.archived);
  await fillSessionVendorSelect((data.vendor_id || "").trim());
  state.currentVendorId = (el("vendorSelect")?.value || "").trim() || null;
  try {
    const vid = (state.currentVendorId || "").trim();
    const remote = vid ? await fetchModelsForVendor(vid) : { models: [] };
    fillModelSelect(remote.models || [], data.model);
  } catch {
    fillModelSelect([], data.model);
  }
  scrollChatToBottom();
  updateTitleControls();
  requestAnimationFrame(() => {
    const inp = el("messageInput");
    if (inp && !state.sending) inp.focus();
  });
}

async function createSession() {
  const created = await api("/api/sessions", {
    method: "POST",
    body: JSON.stringify({ title: "新会话" }),
  });
  await loadSessions();
  await selectSession(created.id);
}

async function deleteSession(sessionId, ev) {
  ev.stopPropagation();
  if (!confirm("确定删除该会话？不可恢复。")) return;
  await api(`/api/sessions/${sessionId}`, { method: "DELETE" });
  if (state.currentSessionId === sessionId) {
    state.currentSessionId = null;
  }
  await loadSessions();
}

async function saveSessionConfig() {
  if (!state.currentSessionId) return;
  const rawVid = (el("vendorSelect")?.value || "").trim();
  const updated = await api(`/api/sessions/${state.currentSessionId}`, {
    method: "PATCH",
    body: JSON.stringify({
      model: el("modelSelect").value,
      vendor_id: rawVid || null,
      workspace_path: el("workspacePathInput").value.trim(),
      execution_enabled: el("executionEnabledInput").checked,
      confirm_each: el("confirmEachInput").checked,
      archived: el("sessionArchivedInput")?.checked ?? false,
    }),
  });
  // 立即回显后端规范化后的值（绝对路径），避免用户误判“未保存”
  el("workspacePathInput").value = updated.workspace_path || "";
  await loadSessions();
  await selectSession(state.currentSessionId);
  closeSettingsModal();
}

async function saveExecutionTogglesInline() {
  if (!state.currentSessionId || state.sending) return;
  try {
    await api(`/api/sessions/${state.currentSessionId}`, {
      method: "PATCH",
      body: JSON.stringify({
        execution_enabled: el("executionEnabledInput").checked,
        confirm_each: el("confirmEachInput").checked,
      }),
    });
  } catch (e) {
    appendAssistantMessage(`执行模式保存失败: ${formatApiError(e)}`, { error: true });
  }
}

function startEditTitle() {
  if (!state.currentSessionId) return;
  const h = el("chatTitle");
  const prev = h.textContent;
  let cancelled = false;
  const inp = document.createElement("input");
  inp.type = "text";
  inp.className = "input topbar__title-input";
  inp.value = prev;
  h.hidden = true;
  h.insertAdjacentElement("afterend", inp);
  inp.focus();
  inp.select();

  const cleanup = () => {
    inp.remove();
    h.hidden = false;
  };

  inp.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      cancelled = true;
      cleanup();
    }
    if (e.key === "Enter") {
      e.preventDefault();
      inp.blur();
    }
  });

  inp.addEventListener("blur", async () => {
    if (cancelled) return;
    const v = inp.value.trim();
    cleanup();
    if (!v || v === prev) {
      h.textContent = prev;
      return;
    }
    try {
      await api(`/api/sessions/${state.currentSessionId}`, {
        method: "PATCH",
        body: JSON.stringify({ title: v }),
      });
      h.textContent = v;
      await loadSessions();
    } catch {
      h.textContent = prev;
    }
  });
}

async function sendMessage() {
  if (state.sending) return;
  const content = el("messageInput").value.trim();
  if (!content || !state.currentSessionId) return;

  const thread = el("chatList");
  const empty = thread.querySelector(".thread-empty");
  if (empty) empty.remove();

  const userArticle = appendUserMessage(content);
  renderMessageAttachments(userArticle.querySelector(".message-attachments"), state.pendingAttachments);
  el("messageInput").value = "";
  resizeComposer();
  state.assistantBuffer = "";

  setSending(true);
  beginAssistantStream();

  try {
    let res;
    try {
      const encoded = [];
      for (const a of state.pendingAttachments) {
        const data_url = await fileToDataUrl(a.file);
        encoded.push({ name: a.name, mime: a.mime, size: a.size, data_url });
      }
      res = await fetch(resolveApiUrl(`/api/sessions/${state.currentSessionId}/messages`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content, attachments: encoded }),
      });
    } catch (err) {
      removeStreamingPlaceholder();
      appendAssistantMessage(`网络错误: ${formatApiError(err)}`, { error: true });
      return;
    }
    if (!res.ok) {
      removeStreamingPlaceholder();
      let payload = {};
      try {
        payload = await res.json();
      } catch {
        payload = { message: await res.text() };
      }
      const requestId = payload.request_id || res.headers.get("x-request-id") || "";
      const code = payload.error_code ? ` [${payload.error_code}]` : "";
      const rid = requestId ? ` (request_id=${requestId})` : "";
      appendAssistantMessage(`请求失败: ${(payload.message || "未知错误") + code + rid}`, { error: true });
      return;
    }
    let hasError = false;
    await readSseEvents(res, (eventType, parsed) => {
      if (eventType === "delta") {
        state.assistantBuffer += parsed.content || "";
        updateStreamingMarkdown(state.assistantBuffer);
      } else if (eventType === "exec_step" || eventType === "exec_result") {
        appendExecStep({ ...parsed, type: eventType });
      } else if (eventType === "agent_trace") {
        appendTraceRow(parsed);
      } else if (eventType === "require_confirm") {
        openConfirmModal(parsed.command || "", parsed.reason || "");
      } else if (eventType === "metrics") {
        /* 指标已写入数据库，流结束后 selectSession 会带出 */
      } else if (eventType === "error") {
        hasError = true;
        removeStreamingPlaceholder();
        appendAssistantMessage(parsed.content || "未知错误", { error: true });
      }
    });
    endAssistantStream();
    if (!hasError) {
      state.pendingAttachments = [];
      renderAttachmentTray();
      await selectSession(state.currentSessionId);
    } else {
      await loadSessions();
    }
  } finally {
    setSending(false);
    el("messageInput").focus();
  }
}

async function confirmPendingCommand(approve) {
  if (!state.currentSessionId || !state.pendingConfirm) return;
  const { command } = state.pendingConfirm;
  closeConfirmModal();
  setSending(true);
  beginAssistantStream();
  try {
    const res = await api(`/api/sessions/${state.currentSessionId}/confirm-command`, {
      method: "POST",
      body: JSON.stringify({ command, approve }),
    });
    if (res.status === "cancelled") {
      removeStreamingPlaceholder();
      appendAssistantMessage(res.message || "已取消执行。");
    } else {
      appendExecStep({ type: "exec_step", command: res.command || command });
      appendExecStep({
        type: "exec_result",
        command: res.command || command,
        exit_code: res.exit_code,
        stdout: res.stdout,
        stderr: res.stderr,
      });
      updateStreamingMarkdown(res.answer || "执行完成。");
    }
    endAssistantStream();
    await selectSession(state.currentSessionId);
  } catch (e) {
    removeStreamingPlaceholder();
    appendAssistantMessage(`确认执行失败: ${formatApiError(e)}`, { error: true });
  } finally {
    setSending(false);
  }
}

el("newSessionBtn").onclick = createSession;
el("saveSessionBtn").onclick = saveSessionConfig;
el("sendBtn").onclick = sendMessage;
el("refreshModelsBtn").onclick = refreshModelDropdown;
el("refreshObsBtn").onclick = refreshObservability;
el("obsExecStatusFilter").addEventListener("change", renderObservabilityPanel);
el("sidebarToggle").onclick = toggleSidebar;
el("editTitleBtn").onclick = startEditTitle;
el("executionEnabledInput").addEventListener("change", () => {
  saveExecutionTogglesInline();
});
el("confirmEachInput").addEventListener("change", () => {
  saveExecutionTogglesInline();
});
el("confirmCommandBtn").addEventListener("click", () => confirmPendingCommand(true));
el("cancelCommandBtn").addEventListener("click", () => confirmPendingCommand(false));
el("confirmModal").addEventListener("click", (e) => {
  if (e.target.classList.contains("modal__backdrop")) closeConfirmModal();
});

function closeSettingsModal() {
  el("settingsModal").hidden = true;
}

function closeDebugModal() {
  el("debugModal").hidden = true;
}

el("settingsModal").addEventListener("click", (e) => {
  const node = e.target.closest("[data-close-modal]");
  if (node && node.getAttribute("data-close-modal") === "settings") closeSettingsModal();
});
el("vendorsModal").addEventListener("click", (e) => {
  const node = e.target.closest("[data-close-modal]");
  if (node && node.getAttribute("data-close-modal") === "vendors") closeVendorsModal();
});
el("openVendorsModalBtn").addEventListener("click", () => {
  openVendorsModal();
});
el("vendorProbeBtn").addEventListener("click", () => onVendorProbeClick());
el("vendorSaveRecordBtn").addEventListener("click", () => onVendorSaveRecordClick());
el("vendorNewBtn").addEventListener("click", () => clearVendorForm());
el("debugModal").addEventListener("click", (e) => {
  const node = e.target.closest("[data-close-modal]");
  if (node && node.getAttribute("data-close-modal") === "debug") closeDebugModal();
});
el("openSettingsModalBtn").addEventListener("click", async () => {
  await fillSessionVendorSelect(state.currentVendorId);
  try {
    const id = (el("vendorSelect")?.value || "").trim();
    const v = id ? await api(`/api/vendors/${id}`) : null;
    state.effectiveApiBase = (v && v.api_base) || state.sessionApiBaseFromServer || "";
  } catch {
    state.effectiveApiBase = state.sessionApiBaseFromServer || "";
  }
  el("settingsModal").hidden = false;
});
el("vendorSelect")?.addEventListener("change", async () => {
  const id = (el("vendorSelect").value || "").trim();
  if (!id) {
    state.effectiveApiBase = state.sessionApiBaseFromServer || "";
    await refreshModelDropdown();
    return;
  }
  try {
    const v = await api(`/api/vendors/${id}`);
    state.effectiveApiBase = v.api_base || "";
    if ((v.default_model || "").trim()) {
      fillModelSelect([], v.default_model.trim());
    }
    await refreshModelDropdown();
  } catch (e) {
    appendAssistantMessage(`加载模型设置失败: ${formatApiError(e)}`, { error: true });
  }
});
el("openDebugModalBtn").addEventListener("click", async () => {
  el("debugModal").hidden = false;
  await refreshObservability();
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (!el("confirmModal").hidden) {
    e.preventDefault();
    confirmPendingCommand(false);
    return;
  }
  if (!el("debugModal").hidden) {
    e.preventDefault();
    closeDebugModal();
    return;
  }
  if (!el("settingsModal").hidden) {
    e.preventDefault();
    closeSettingsModal();
    return;
  }
  if (!el("vendorsModal").hidden) {
    e.preventDefault();
    closeVendorsModal();
  }
});

el("attachBtn").addEventListener("click", () => el("fileInput").click());
el("fileInput").addEventListener("change", (e) => {
  addFiles(e.target.files);
  e.target.value = "";
});

el("messageInput").addEventListener("input", resizeComposer);
el("messageInput").addEventListener("keydown", (e) => {
  const isComposing = e.isComposing || e.keyCode === 229;
  if (isComposing) return;
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});
el("messageInput").addEventListener("paste", (e) => {
  const items = Array.from(e.clipboardData?.items || []);
  const files = items
    .filter((it) => it.kind === "file")
    .map((it) => it.getAsFile())
    .filter(Boolean);
  if (files.length) {
    e.preventDefault();
    addFiles(files);
  }
});
document.addEventListener("dragover", (e) => {
  if (state.sending) return;
  e.preventDefault();
});
document.addEventListener("drop", (e) => {
  if (state.sending) return;
  const files = Array.from(e.dataTransfer?.files || []);
  if (!files.length) return;
  e.preventDefault();
  addFiles(files);
});

initSidebar();
updateTitleControls();
const archivedToggle = el("includeArchivedSessions");
if (archivedToggle) {
  archivedToggle.checked = state.includeArchivedSessions;
  archivedToggle.addEventListener("change", () => {
    state.includeArchivedSessions = archivedToggle.checked;
    localStorage.setItem(ARCHIVED_SESSIONS_KEY, archivedToggle.checked ? "1" : "0");
    loadSessions();
  });
}
loadSessions();

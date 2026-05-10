import {
  DEFAULT_MODEL,
  SIDEBAR_STORAGE_KEY,
  ARCHIVED_SESSIONS_KEY,
  ONBOARDING_DISMISSED_KEY,
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

function showToast(message, kind = "info") {
  if (!message) return;
  let host = document.getElementById("toastHost");
  if (!host) {
    host = document.createElement("div");
    host.id = "toastHost";
    host.className = "toast-host";
    document.body.appendChild(host);
  }
  const item = document.createElement("div");
  item.className = `toast toast--${kind}`;
  item.textContent = String(message);
  host.appendChild(item);
  setTimeout(() => {
    item.classList.add("toast--hide");
    setTimeout(() => item.remove(), 260);
  }, 4200);
}

function maybeBrowserNotify(title, body) {
  if (!("Notification" in window)) return;
  if (Notification.permission !== "granted") return;
  try {
    new Notification(title, { body: body || "" });
  } catch {
    /* ignore browser notification errors */
  }
}

function formatIsoToLocal(isoText) {
  const s = String(isoText || "").trim();
  if (!s) return "";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return s;
  const pad = (n) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  );
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

function openConfirmModal(command, reason, options = {}) {
  state.pendingConfirm = {
    command,
    reason,
    needsSudoPassword: Boolean(options.needsSudoPassword),
  };
  el("confirmCommand").textContent = command || "";
  el("confirmReason").textContent = reason || "该命令需要你确认后才执行。";
  const row = el("confirmSudoRow");
  const pw = el("confirmSudoPassword");
  if (row && pw) {
    pw.value = "";
    row.hidden = !state.pendingConfirm.needsSudoPassword;
    if (!row.hidden) {
      requestAnimationFrame(() => pw.focus());
    }
  }
  setModalVisible(true);
}

function closeConfirmModal() {
  state.pendingConfirm = null;
  const pw = el("confirmSudoPassword");
  if (pw) pw.value = "";
  const row = el("confirmSudoRow");
  if (row) row.hidden = true;
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

function _toTs(isoText) {
  const t = Date.parse(String(isoText || ""));
  return Number.isFinite(t) ? t : 0;
}

function buildAssistantExecutionBuckets(messages, executions) {
  const sortedExecs = [...(executions || [])].sort(
    (a, b) => _toTs(a.created_at) - _toTs(b.created_at)
  );
  const buckets = new Map();
  const assistantIds = [];
  const orphan = [];
  let idx = 0;
  for (const m of messages || []) {
    if (m.role !== "assistant") continue;
    assistantIds.push(m.id);
    const msgTs = _toTs(m.created_at);
    const arr = [];
    while (idx < sortedExecs.length) {
      const e = sortedExecs[idx];
      const eTs = _toTs(e.created_at);
      if (msgTs > 0 && eTs > msgTs) break;
      arr.push(e);
      idx += 1;
    }
    buckets.set(m.id, arr);
  }
  if (idx < sortedExecs.length) {
    if (assistantIds.length) {
      const lastId = assistantIds[assistantIds.length - 1];
      const tail = buckets.get(lastId) || [];
      while (idx < sortedExecs.length) {
        tail.push(sortedExecs[idx]);
        idx += 1;
      }
      buckets.set(lastId, tail);
    } else {
      while (idx < sortedExecs.length) {
        orphan.push(sortedExecs[idx]);
        idx += 1;
      }
    }
  }
  return { buckets, orphan };
}

function renderExecutionHistory(executions) {
  const list = Array.isArray(executions) ? executions : [];
  if (!list.length) return "";
  const rows = list
    .map((r) => {
      const cmd = escapeHtml(String(r.command || ""));
      const status = escapeHtml(String(r.status || "-"));
      const type = escapeHtml(String(r.exec_type || "-"));
      const exit = escapeHtml(String(r.exit_code ?? "-"));
      const when = escapeHtml(formatIsoToLocal(r.created_at) || "-");
      const duration = Number(r.duration_ms || 0);
      const d = duration > 0 ? `${duration.toFixed(1)}ms` : "-";
      const reason = String(r.reason || "").trim();
      const stdout = escapeHtml(String(r.stdout || "(empty)"));
      const stderr = escapeHtml(String(r.stderr || "(empty)"));
      return `
        <div class="message-exec-history__item">
          <div class="message-exec-history__head">
            <span>${type} · ${status} · exit=${exit}</span>
            <span>${when}</span>
          </div>
          <div class="message-exec-history__cmd">$ ${cmd}</div>
          <div class="message-exec-history__meta">duration=${escapeHtml(d)}${reason ? ` · reason=${escapeHtml(reason)}` : ""}</div>
          <details class="message-exec-history__detail">
            <summary>输出详情</summary>
            <pre>stdout:\n${stdout}\n\nstderr:\n${stderr}</pre>
          </details>
        </div>
      `;
    })
    .join("");
  return `
    <details class="message-exec-history" open>
      <summary class="message-exec-history__summary">执行过程（${list.length} 条）</summary>
      <div class="message-exec-history__list">${rows}</div>
    </details>
  `;
}

function renderOrphanExecutionCard(executions) {
  if (!Array.isArray(executions) || !executions.length) return;
  appendAssistantMessage("执行过程已产生，但最终回答尚未落库（可能仍在运行或被中断）。", {
    metrics: null,
    execHistory: executions,
  });
}

function detectUnblockStateFromText(text) {
  const s = String(text || "");
  if (!s || !/"unblock"\s*:/.test(s)) return null;
  const statusMatch = s.match(/"status"\s*:\s*"([^"]+)"/);
  const msgMatch = s.match(/"message"\s*:\s*"([^"]+)"/);
  const blockedMatch = s.match(/"check_blocked"\s*:\s*(true|false|null)/);
  const runningMatch = s.match(/"running"\s*:\s*(true|false)/);
  const rcMatch = s.match(/"returncode"\s*:\s*(-?\d+)/);
  const rawStatus = String((statusMatch && statusMatch[1]) || "").toLowerCase();
  const running = runningMatch ? runningMatch[1] === "true" : false;
  const blockedRaw = blockedMatch ? blockedMatch[1] : "";
  const blocked = blockedRaw === "true" ? true : blockedRaw === "false" ? false : null;
  let level = "neutral";
  let label = "解封状态";
  if (rawStatus === "success" || blocked === false) {
    level = "ok";
    label = "已解封";
  } else if (rawStatus === "running" || running) {
    level = "running";
    label = "解封中";
  } else if (rawStatus === "failed" || blocked === true) {
    level = "bad";
    label = "未解封";
  } else if (rawStatus === "timeout") {
    level = "warn";
    label = "解封超时";
  }
  const msg = msgMatch ? msgMatch[1] : "";
  const rc = rcMatch ? Number(rcMatch[1]) : null;
  return { level, label, msg, blocked, rc };
}

function renderUnblockBadge(info) {
  if (!info) return "";
  const blockedText = info.blocked === true ? "check: blocked=true" : info.blocked === false ? "check: blocked=false" : "check: unknown";
  const codeText = Number.isFinite(info.rc) ? ` · rc=${info.rc}` : "";
  const msg = info.msg ? ` · ${escapeHtml(info.msg)}` : "";
  let fixCmd = "";
  const lowMsg = String(info.msg || "").toLowerCase();
  if (lowMsg.includes("playwright_missing")) {
    fixCmd = "pip install playwright && python -m playwright install chromium";
  } else if (lowMsg.includes("python3_unavailable")) {
    fixCmd = "python3 --version";
  }
  const fixBtn = fixCmd
    ? `<button type="button" class="unblock-fix-btn" data-fix-cmd="${escapeHtml(fixCmd)}" aria-label="复制修复命令">复制修复命令</button>`
    : "";
  return `<div class="message-unblock-badge message-unblock-badge--${info.level}"><strong>${escapeHtml(info.label)}</strong><span>${blockedText}${codeText}${msg}</span>${fixBtn}</div>`;
}

function appendAssistantMessage(text, { error = false, metrics = null, execHistory = [] } = {}) {
  const article = document.createElement("article");
  article.className = error
    ? "message message--assistant message--error"
    : "message message--assistant";
  article.setAttribute("aria-label", error ? "错误" : "助手消息");
  const footer = !error && metrics ? renderMetricsFooter(metrics) : "";
  const execBlock = !error ? renderExecutionHistory(execHistory) : "";
  const unblockInfo = !error ? detectUnblockStateFromText(text) : null;
  const unblockBlock = !error ? renderUnblockBadge(unblockInfo) : "";
  const bodyMd = error ? `<p>${escapeHtml(text)}</p>` : renderMarkdown(text);
  const copyBtn = !error ? '<button type="button" class="message-copy-btn" aria-label="复制本条 AI 消息">复制</button>' : "";
  article.innerHTML = `
    <div class="message__avatar" aria-hidden="true">${error ? "!" : "AI"}</div>
    <div class="message__bubble">
      ${copyBtn}
      ${unblockBlock}
      <div class="markdown-body">${bodyMd}</div>
      ${execBlock}
      ${footer}
    </div>
  `;
  el("chatList").appendChild(article);
  const copy = article.querySelector(".message-copy-btn");
  if (copy) {
    copy.addEventListener("click", async () => {
      const md = article.querySelector(".markdown-body");
      const plain = (md?.innerText || "").trim();
      if (!plain) return;
      try {
        await navigator.clipboard.writeText(plain);
        copy.textContent = "已复制";
      } catch {
        copy.textContent = "复制失败";
      }
      setTimeout(() => {
        copy.textContent = "复制";
      }, 1600);
    });
  }
  const fixBtn = article.querySelector(".unblock-fix-btn");
  if (fixBtn) {
    fixBtn.addEventListener("click", async () => {
      const cmd = fixBtn.getAttribute("data-fix-cmd") || "";
      if (!cmd) return;
      try {
        await navigator.clipboard.writeText(cmd);
        fixBtn.textContent = "已复制命令";
      } catch {
        fixBtn.textContent = "复制失败";
      }
      setTimeout(() => {
        fixBtn.textContent = "复制修复命令";
      }, 1800);
    });
  }
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
    div.innerHTML = `<div class="exec-step__title">正在执行</div><div class="exec-step__cmd">$ ${cmd}</div>`;
  } else {
    const exitCode = Number(step.exit_code ?? 0);
    const shortOut = String(step.stdout || "").slice(0, 280);
    const shortErr = String(step.stderr || "").slice(0, 280);
    const statusZh =
      exitCode === 0
        ? "已完成"
        : exitCode === 124
          ? "未完成（超时）"
          : exitCode === 125
            ? "未执行（被拦截）"
            : "未完成（出错）";
    div.innerHTML =
      `<div class="exec-step__title">执行结果 · <strong>${statusZh}</strong></div><div class="exec-step__cmd">$ ${cmd}</div>` +
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
    const isRunning = state.sending && state.sendingSessionId && s.id === state.sendingSessionId;
    const row = document.createElement("div");
    row.className =
      "session-row" +
      (s.id === state.currentSessionId ? " active" : "") +
      (s.archived ? " session-row--archived" : "");
    row.setAttribute("role", "listitem");

    const main = document.createElement("button");
    main.type = "button";
    main.className = "session-main";
    main.innerHTML = `<span class="session-title"><span class="session-title__text">${escapeHtml(s.title)}</span>${
      isRunning ? '<span class="session-running-badge" title="该会话正在生成中">进行中</span>' : ""
    }</span><span class="session-meta">${escapeHtml(s.model)}</span>`;
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
  if (uniq.length) {
    if (!uniq.includes(want)) want = uniq[0];
    for (const id of uniq) {
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = id;
      sel.appendChild(opt);
    }
  } else {
    const opt = document.createElement("option");
    opt.value = want;
    opt.textContent = want;
    sel.appendChild(opt);
  }
  sel.value = want;
}

async function getDefaultVendorId() {
  try {
    const data = await api("/api/vendors/default");
    return (data.vendor_id || "").trim() || null;
  } catch {
    return null;
  }
}

async function refreshModelDropdown(options = {}) {
  const preferredModel = String(options.preferredModel || "").trim();
  const keepCurrent = Boolean(options.keepCurrent);
  const vendorId = (el("vendorSelect")?.value || "").trim();
  const current = keepCurrent ? (el("modelSelect").value || DEFAULT_MODEL) : "";
  const fallback = preferredModel || current || DEFAULT_MODEL;
  if (!vendorId) {
    fillModelSelect([], fallback);
    return;
  }
  try {
    const data = await fetchModelsForVendor(vendorId);
    const models = data.models || [];
    let target = fallback;
    if (models.length) {
      if (!target || !models.includes(target)) {
        target = models[0];
      }
    }
    fillModelSelect(models, target);
  } catch (e) {
    console.warn(e);
    fillModelSelect([], fallback);
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
    ph.textContent = "（请先在侧栏「模型设置」中添加供应商并保存）";
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

function setVendorModelSuggestions(models) {
  const dl = el("vendorFormDefaultModelList");
  if (!dl) return;
  dl.innerHTML = "";
  for (const id of [...new Set((models || []).filter(Boolean))]) {
    const opt = document.createElement("option");
    opt.value = id;
    dl.appendChild(opt);
  }
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
  el("vendorFormDefaultModel").value = "";
  setVendorModelSuggestions([]);
  const ck = el("vendorFormDefaultVendor");
  if (ck) ck.checked = false;
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
  if (!fetchFailed) {
    state.vendorCount = list.length;
  }
  mount.innerHTML = "";
  if (!list.length) {
    mount.innerHTML = fetchFailed
      ? '<div class="obs-empty">未能加载模型设置列表（请检查服务）。</div>'
      : '<div class="obs-empty">尚未配置模型设置。请在下方创建第一条（名称、API Base、API Key 与默认模型）。</div>';
    return;
  }
  const defaultVendorId = await getDefaultVendorId();
  for (const v of list) {
    const row = document.createElement("div");
    row.className = "vendor-row";
    const left = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = (v.name || "") + (v.id === defaultVendorId ? "（默认）" : "");
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
        refreshEmptyHintIfNeeded();
      } catch (e) {
        setVendorFormHint(`删除失败：${formatApiError(e)}`);
      }
    });
  });
}

async function loadVendorIntoForm(vendorId) {
  const v = await api(`/api/vendors/${vendorId}`);
  const defaultVendorId = await getDefaultVendorId();
  el("vendorFormId").value = v.id;
  el("vendorFormName").value = v.name || "";
  el("vendorFormApiBase").value = v.api_base || "";
  el("vendorFormApiKey").value = v.api_key != null ? String(v.api_key) : "";
  const dm = (v.default_model || "").trim();
  el("vendorFormDefaultModel").value = dm;
  setVendorModelSuggestions(dm ? [dm] : []);
  const ck = el("vendorFormDefaultVendor");
  if (ck) ck.checked = v.id === defaultVendorId;
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
    const modelInput = el("vendorFormDefaultModel");
    setVendorModelSuggestions(models);
    if (models.length && !(modelInput.value || "").trim()) modelInput.value = models[0];
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
  const setAsDefaultVendor = Boolean(el("vendorFormDefaultVendor")?.checked);
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
      if (setAsDefaultVendor) {
        await api("/api/vendors/default", {
          method: "PUT",
          body: JSON.stringify({ vendor_id: id }),
        });
      }
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
      if (setAsDefaultVendor) {
        await api("/api/vendors/default", {
          method: "PUT",
          body: JSON.stringify({ vendor_id: created.id }),
        });
      }
    }
    await renderVendorList();
    await fillSessionVendorSelect(state.currentVendorId);
    clearVendorForm();
    setVendorFormHint(hintAfter);
    refreshEmptyHintIfNeeded();
  } catch (e) {
    setVendorFormHint(`保存失败：${formatApiError(e)}`);
  }
}

function refreshEmptyHintIfNeeded() {
  const thread = el("chatList");
  if (thread?.querySelector(".thread-empty")) {
    renderEmptyHint();
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
    '<span class="thread-empty__sub">需要改模型、模型设置或工作目录时点顶部「设置」；排查执行与上下文时点「调试」。' +
    (state.vendorCount === 0
      ? ' <button type="button" class="btn btn--ghost btn--inline thread-empty__guide" id="emptyOnboardingBtn">入门向导</button>'
      : "") +
    "</span>";
  thread.appendChild(div);
  const guideBtn = el("emptyOnboardingBtn");
  if (guideBtn) {
    guideBtn.addEventListener("click", () => {
      openOnboardingModal();
    });
  }
}

function isOnboardingDismissed() {
  try {
    return localStorage.getItem(ONBOARDING_DISMISSED_KEY) === "1";
  } catch {
    return false;
  }
}

function dismissOnboarding() {
  try {
    localStorage.setItem(ONBOARDING_DISMISSED_KEY, "1");
  } catch {
    /* ignore quota / private mode */
  }
}

function closeOnboardingModal() {
  el("onboardingModal").hidden = true;
}

async function populateOnboardingEnv() {
  const mount = el("onboardingEnvBody");
  if (!mount) return;
  mount.textContent = "加载中…";
  try {
    const res = await fetch(resolveApiUrl("/api/diagnostics"));
    if (!res.ok) {
      mount.textContent = `无法读取诊断（HTTP ${res.status}）。`;
      return;
    }
    const d = await res.json();
    const py = d.python || {};
    const cc = d.claude_code || {};
    const pw = d.playwright || {};
    const lines = [
      `Python ${py.version || "?"} · ${d.platform || "?"}`,
      `SQLite ${d.sqlite?.reachable ? "可访问" : "不可访问"} · vendors ${d.store?.vendors_count ?? "?"} · sessions ${d.store?.sessions_count ?? "?"}`,
      `node ${d.node?.on_path ? d.node.version || "ok" : "未找到"} · npm ${d.npm?.on_path ? "ok" : "未找到"}`,
      `playwright ${pw.import_ok ? `import ${pw.version || "ok"}` : "未安装"}`,
      `Claude Code ${cc.enabled ? "可用" : "未就绪"}${cc.reason ? ` — ${cc.reason}` : ""}`,
    ];
    mount.textContent = lines.join("\n");
  } catch (e) {
    mount.textContent = `读取失败：${formatApiError(e)}`;
  }
}

function openOnboardingModal() {
  el("onboardingModal").hidden = false;
  void populateOnboardingEnv();
}

async function refreshVendorCount() {
  try {
    const vendors = await api("/api/vendors");
    state.vendorCount = Array.isArray(vendors) ? vendors.length : 0;
  } catch {
    state.vendorCount = -1;
  }
}

async function maybeShowOnboarding() {
  await refreshVendorCount();
  if (state.vendorCount !== 0) return;
  if (isOnboardingDismissed()) return;
  openOnboardingModal();
}

function humanSize(n) {
  const b = Number(n || 0);
  if (b < 1024) return `${b}B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)}KB`;
  if (b < 1024 * 1024 * 1024) return `${(b / 1024 / 1024).toFixed(1)}MB`;
  return `${(b / (1024 * 1024 * 1024)).toFixed(2)}GB`;
}

/** 与后端 1GiB/1GiB 推导一致；仅在无法 GET /api/ui-config 时作后备，避免仍卡在 25MB */
const _UI_FALLBACK_MAX_EACH_BYTES = Math.min(
  1073741824,
  Math.floor(1073741824 * 0.65),
);

function maxAttachmentEachBytesForClient() {
  const n = state.maxAttachmentEachBytes;
  if (typeof n === "number" && Number.isFinite(n) && n > 0) {
    return Math.floor(n);
  }
  return _UI_FALLBACK_MAX_EACH_BYTES;
}

async function refreshUiConfig() {
  try {
    const d = await api("/api/ui-config");
    const raw = d.msg_max_attachment_each_bytes;
    const n = typeof raw === "number" ? raw : Number(raw);
    if (Number.isFinite(n) && n > 0) {
      state.maxAttachmentEachBytes = Math.floor(n);
    }
  } catch {
    /* 保持 maxAttachmentEachBytes 不变或使用后备 */
  }
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

function guessMimeFromFilename(name) {
  const n = String(name || "").toLowerCase();
  const dot = n.lastIndexOf(".");
  if (dot < 0) return "";
  const ext = n.slice(dot + 1).split("?")[0].split("#")[0];
  const map = {
    mp4: "video/mp4",
    m4v: "video/mp4",
    mov: "video/quicktime",
    webm: "video/webm",
    mkv: "video/x-matroska",
    avi: "video/x-msvideo",
    mpeg: "video/mpeg",
    mpg: "video/mpeg",
    "3gp": "video/3gpp",
    ogv: "video/ogg",
    png: "image/png",
    jpg: "image/jpeg",
    jpeg: "image/jpeg",
    gif: "image/gif",
    webp: "image/webp",
    bmp: "image/bmp",
    mp3: "audio/mpeg",
    wav: "audio/wav",
    m4a: "audio/mp4",
    flac: "audio/flac",
    ogg: "audio/ogg",
    aac: "audio/aac",
  };
  return map[ext] || "";
}

function normalizePastedFile(file) {
  if (!file) return null;
  const name = file.name || `paste-${Date.now()}`;
  const t = (file.type && String(file.type).trim()) || "";
  const mime = t || guessMimeFromFilename(name) || "application/octet-stream";
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

async function addFiles(files) {
  if (state.maxAttachmentEachBytes == null) {
    await refreshUiConfig();
  }
  const maxEach = maxAttachmentEachBytesForClient();
  const arr = Array.from(files || []);
  for (const f of arr) {
    const n = normalizePastedFile(f);
    if (!n) continue;
    if (n.size > maxEach) {
      appendAssistantMessage(
        `附件 ${n.name} 超过服务端允许的单文件上限（${humanSize(maxEach)}），已跳过。可在 .env 中调整 OMLXCLI_MSG_MAX_BODY_BYTES / OMLXCLI_MSG_MAX_ATTACHMENTS_BYTES（可选 OMLXCLI_MSG_MAX_ATTACHMENT_EACH_BYTES）后重启 uvicorn；并强制刷新页面（Cmd+Shift+R）以加载最新 /ui/app.js。`,
        { error: true },
      );
      continue;
    }
    state.pendingAttachments.push(n);
  }
  renderAttachmentTray();
}

async function loadSessions() {
  await refreshVendorCount();
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
  const execBucketsPack = buildAssistantExecutionBuckets(data.messages || [], data.executions || []);
  if (!data.messages.length) {
    renderEmptyHint();
    renderOrphanExecutionCard(execBucketsPack.orphan);
  } else {
    const execBuckets = execBucketsPack.buckets;
    data.messages.forEach((m) => {
      if (m.role === "user") {
        const article = appendUserMessage(m.content);
        renderMessageAttachments(article.querySelector(".message-attachments"), m.attachments || []);
      } else if (m.kind === "error") {
        appendAssistantMessage(m.content, { error: true });
      } else {
        appendAssistantMessage(m.content, {
          metrics: m.metrics || null,
          execHistory: execBuckets.get(m.id) || [],
        });
      }
    });
    renderOrphanExecutionCard(execBucketsPack.orphan);
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
  const defaultVendorId = await getDefaultVendorId();
  const created = await api("/api/sessions", {
    method: "POST",
    body: JSON.stringify({
      title: "新会话",
      vendor_id: defaultVendorId,
      execution_enabled: true,
      confirm_each: true,
    }),
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
  state.sendingSessionId = state.currentSessionId;

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
      const controller = new AbortController();
      state.activeStreamController = controller;
      res = await fetch(resolveApiUrl(`/api/sessions/${state.currentSessionId}/messages`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content, attachments: encoded }),
        signal: controller.signal,
      });
    } catch (err) {
      removeStreamingPlaceholder();
      if (err && (err.name === "AbortError" || String(err).includes("switch_session"))) {
        appendAssistantMessage("已中断本次回复。", { error: true });
      } else {
        appendAssistantMessage(`网络错误: ${formatApiError(err)}`, { error: true });
      }
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
        openConfirmModal(parsed.command || "", parsed.reason || "", {
          needsSudoPassword: Boolean(parsed.needs_sudo_password),
        });
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
    state.activeStreamController = null;
    state.sendingSessionId = null;
    setSending(false);
    el("messageInput").focus();
  }
}

async function confirmPendingCommand(approve) {
  if (!state.currentSessionId || !state.pendingConfirm) return;
  const { command, needsSudoPassword } = state.pendingConfirm;
  const sudoPassword =
    approve && needsSudoPassword ? String(el("confirmSudoPassword")?.value || "").trim() : "";
  closeConfirmModal();
  setSending(true);
  beginAssistantStream();
  try {
    const payload = { command, approve };
    if (approve && sudoPassword) {
      payload.sudo_password = sudoPassword;
    }
    const res = await api(`/api/sessions/${state.currentSessionId}/confirm-command`, {
      method: "POST",
      body: JSON.stringify(payload),
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
el("refreshModelsBtn").onclick = () => refreshModelDropdown({ keepCurrent: true });
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

let claudeJobsPollTimer = null;
let claudeJobsSelectedId = null;
let claudeJobsBackgroundPollTimer = null;
const claudeSessionRefreshTimers = new Map();
const claudeJobStatusSeen = new Map();
const claudeJobAnnounced = new Set();
const appBootAtMs = Date.now();

function _claudeJobSeenKey(sessionId, jobId) {
  return `${sessionId}::${jobId}`;
}

function _isClaudeJobTerminal(status) {
  return status === "completed" || status === "failed" || status === "cancelled";
}

function scheduleClaudeSessionRefresh(sessionId, delayMs = 700) {
  if (!sessionId) return;
  const key = String(sessionId);
  const old = claudeSessionRefreshTimers.get(key);
  if (old) clearTimeout(old);
  const timer = setTimeout(async () => {
    claudeSessionRefreshTimers.delete(key);
    if (state.currentSessionId !== key) return;
    if (state.sending) {
      // 输入中先不打断，继续递延一次，避免用户正在交互时漏刷新。
      scheduleClaudeSessionRefresh(key, 900);
      return;
    }
    try {
      await selectSession(key);
    } catch {
      /* keep silent; polling/toast path will surface status changes */
    }
  }, delayMs);
  claudeSessionRefreshTimers.set(key, timer);
}

function claudeStatusLabel(status) {
  if (status === "running") return "运行中";
  if (status === "queued") return "排队中";
  if (status === "completed") return "已完成";
  if (status === "failed") return "失败";
  if (status === "cancelled") return "已取消";
  return status || "-";
}

function claudeStatusIcon(status) {
  if (status === "completed") return "✓";
  if (status === "cancelled") return "✕";
  if (status === "failed") return "!";
  if (status === "queued") return "…";
  if (status === "running") return "•";
  return "·";
}

function formatDurationMs(startIso, endIso) {
  const s = Date.parse(String(startIso || ""));
  const e = endIso ? Date.parse(String(endIso || "")) : Date.now();
  if (!Number.isFinite(s) || !Number.isFinite(e) || e <= s) return "-";
  const sec = Math.floor((e - s) / 1000);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const r = sec % 60;
  if (h > 0) return `${h}h ${m}m ${r}s`;
  if (m > 0) return `${m}m ${r}s`;
  return `${r}s`;
}

function _detectFailureHint(text) {
  const s = String(text || "");
  if (/401|unauthorized|authentication/i.test(s)) return "鉴权失败（请检查 API Key）";
  if (/429|rate limit/i.test(s)) return "触发限流（建议稍后重试）";
  if (/timeout|timed out/i.test(s)) return "请求超时（建议重试并缩小任务）";
  if (/not found|enoent|no such file/i.test(s)) return "文件或路径不存在";
  if (/traceback|exception|api error/i.test(s)) return "执行报错（查看错误卡和日志）";
  return "";
}

function renderClaudeConversation(job, fullText) {
  const convEl = el("claudeJobConversation");
  if (!job) {
    convEl.innerHTML = '<div class="obs-empty">请选择左侧任务</div>';
    return;
  }
  const prompt = String(job.prompt || job.prompt_preview || "").trim() || "(该任务未记录 prompt)";
  const output = String(fullText || "").trim();
  const err = String(job.error_summary || "").trim();
  const hint = _detectFailureHint(err || output);
  let answer = output;
  if (!answer) {
    if (job.status === "running") {
      answer = "任务运行中，Claude 暂未产生可显示输出（这是正常情况）。请继续等待或稍后刷新。";
    } else if (job.status === "queued") {
      answer = "任务已入队，正在等待前一个任务完成后自动开始。";
    } else if (job.status === "failed") answer = err || "任务失败，但未返回详细输出。";
    else answer = String(job.result_summary || "").trim() || "任务已结束，但暂无输出。";
  }
  const answerTitle = job.status === "failed" ? "Claude（报错）" : "Claude（回答）";
  const endIso = job.status === "running" || job.status === "queued" ? "" : job.updated_at;
  const meta = `${claudeStatusLabel(job.status)} · ${formatIsoToLocal(job.updated_at)} · 耗时 ${formatDurationMs(job.created_at, endIso)}`;
  convEl.innerHTML = `
    <div class="claude-msg claude-msg--user">
      <div class="claude-msg__role">你</div>
      <div class="claude-msg__body markdown-body">${renderMarkdown(prompt)}</div>
    </div>
    <div class="claude-msg claude-msg--assistant${job.status === "failed" ? " claude-msg--error" : ""}">
      <div class="claude-msg__role">${escapeHtml(answerTitle)}</div>
      <div class="claude-msg__meta">${escapeHtml(meta)}</div>
      ${hint ? `<div class="claude-msg__hint">${escapeHtml(hint)}</div>` : ""}
      <div class="claude-msg__body markdown-body">${renderMarkdown(answer)}</div>
    </div>
  `;
  enhanceCodeBlocks(convEl);
}

async function announceClaudeJobTransition(sessionId, jobId, status) {
  if (sessionId !== state.currentSessionId) return;
  const key = _claudeJobSeenKey(sessionId, jobId);
  if (claudeJobAnnounced.has(key)) return;
  claudeJobAnnounced.add(key);
  try {
    // B 方案：终态消息由后端写入会话消息表，前端只刷新会话，避免“切换后丢失”。
    if (state.currentSessionId === sessionId) scheduleClaudeSessionRefresh(sessionId, 120);
  } catch (e) {
    showToast(
      `Claude 任务 ${jobId.slice(0, 8)}… 状态已更新（${status}），但会话刷新失败：${formatApiError(e)}`,
      "error"
    );
  }
}

async function _syncClaudeJobTransitions(sessionId, jobs) {
  const list = Array.isArray(jobs) ? jobs : [];
  for (const j of list) {
    const key = _claudeJobSeenKey(sessionId, j.id);
    const prev = claudeJobStatusSeen.get(key);
    const now = j.status;
    claudeJobStatusSeen.set(key, now);
    const alreadyAnnounced = claudeJobAnnounced.has(key);
    const updatedAtMs = Date.parse(String(j.updated_at || ""));
    const createdAtMs = Date.parse(String(j.created_at || ""));
    const isCreatedAfterBoot = Number.isFinite(createdAtMs) && createdAtMs >= appBootAtMs;
    const isRecentTerminalUpdate =
      Number.isFinite(updatedAtMs) && updatedAtMs >= Date.now() - 5 * 60 * 1000;
    const shouldAnnounce =
      _isClaudeJobTerminal(now) &&
      !alreadyAnnounced &&
      (
        // 常规：明确经历 running -> 终态。
        prev === "running" ||
        // 兜底：页面打开后新建任务，首次看到即终态（常见于任务很快完成）。
        (prev == null && isCreatedAfterBoot) ||
        // 兜底：非常近期终态更新，避免漏报（例如后台轮询节奏与状态更新交错）。
        isRecentTerminalUpdate
      );
    if (shouldAnnounce) {
      const label = now === "completed" ? "已完成" : now === "failed" ? "失败" : "已取消";
      const msg = `Claude 任务 ${j.id.slice(0, 8)}… ${label}`;
      showToast(msg, now === "completed" ? "success" : now === "failed" ? "error" : "info");
      maybeBrowserNotify("Claude 任务状态更新", msg);
      await announceClaudeJobTransition(sessionId, j.id, now);
    }
  }
}

async function refreshClaudeJobsStatusOnly() {
  const sid = state.currentSessionId;
  if (!sid) return;
  try {
    const data = await api(`/api/sessions/${encodeURIComponent(sid)}/claude-jobs?limit=40`);
    if (!data.enabled) return;
    await _syncClaudeJobTransitions(sid, data.jobs || []);
  } catch {
    /* keep silent for background polling */
  }
}

function closeClaudeJobsModal() {
  el("claudeJobsModal").hidden = true;
  if (claudeJobsPollTimer) {
    clearInterval(claudeJobsPollTimer);
    claudeJobsPollTimer = null;
  }
}

function startClaudeJobsPolling() {
  if (claudeJobsPollTimer) clearInterval(claudeJobsPollTimer);
  claudeJobsPollTimer = setInterval(() => {
    refreshClaudeJobsUi();
  }, 3200);
}

function startClaudeJobsBackgroundPolling() {
  if (claudeJobsBackgroundPollTimer) clearInterval(claudeJobsBackgroundPollTimer);
  claudeJobsBackgroundPollTimer = setInterval(() => {
    // 弹窗打开时已有高频轮询，避免重复请求。
    if (!el("claudeJobsModal").hidden) return;
    refreshClaudeJobsStatusOnly();
  }, 10000);
}

async function loadClaudeJobDetail(sid, jobId) {
  const cancelBtn = el("cancelClaudeJobBtn");
  try {
    const d = await api(`/api/sessions/${encodeURIComponent(sid)}/claude-jobs/${encodeURIComponent(jobId)}`);
    const job = d.job;
    const tail = await api(
      `/api/sessions/${encodeURIComponent(sid)}/claude-jobs/${encodeURIComponent(jobId)}/logs?tail=5000`
    );
    renderClaudeConversation(job, String(tail.text || ""));
    cancelBtn.disabled = job.status !== "running";
  } catch (e) {
    el("claudeJobConversation").innerHTML = `<div class="obs-empty">读取任务详情失败：${escapeHtml(formatApiError(e))}</div>`;
    cancelBtn.disabled = true;
  }
}

async function refreshClaudeJobsUi() {
  const sid = state.currentSessionId;
  const listEl = el("claudeJobsList");
  const cancelBtn = el("cancelClaudeJobBtn");
  if (!sid) {
    listEl.innerHTML = '<div class="obs-empty">请选择会话</div>';
    renderClaudeConversation(null, "");
    cancelBtn.disabled = true;
    return;
  }
  try {
    const data = await api(`/api/sessions/${encodeURIComponent(sid)}/claude-jobs?limit=40`);
    if (!data.enabled) {
      listEl.innerHTML = `<div class="obs-empty">${escapeHtml(data.reason || "Claude Code Job 未启用")}<br/><span style="color:var(--text-muted)">参见 docs/CLAUDE_CODE_JOB_SPEC.md 与 .env.example</span></div>`;
      renderClaudeConversation(null, "");
      cancelBtn.disabled = true;
      return;
    }
    const jobs = data.jobs || [];
    await _syncClaudeJobTransitions(sid, jobs);
    const queueOrder = new Map();
    const queuedAsc = jobs
      .filter((j) => String(j.status || "").toLowerCase() === "queued")
      .sort((a, b) => Date.parse(String(a.created_at || "")) - Date.parse(String(b.created_at || "")));
    queuedAsc.forEach((j, idx) => queueOrder.set(j.id, idx + 1));
    if (!jobs.length) {
      listEl.innerHTML = '<div class="obs-empty">暂无任务；在对话中让模型调用 claude_job_start</div>';
      claudeJobsSelectedId = null;
      renderClaudeConversation(null, "");
      cancelBtn.disabled = true;
      return;
    }
    if (claudeJobsSelectedId && !jobs.some((j) => j.id === claudeJobsSelectedId)) {
      claudeJobsSelectedId = jobs[0].id;
    }
    if (!claudeJobsSelectedId) {
      claudeJobsSelectedId = jobs[0].id;
    }
    listEl.innerHTML = "";
    for (const j of jobs) {
      const b = document.createElement("button");
      b.type = "button";
      b.className =
        "claude-jobs-row" + (j.id === claudeJobsSelectedId ? " claude-jobs-row--active" : "");
      const statusLower = String(j.status || "").toLowerCase();
      const statusClass = `claude-jobs-status-icon claude-jobs-status-icon--${statusLower}`;
      const duration = formatDurationMs(j.created_at, j.updated_at);
      const failHint = j.status === "failed" ? _detectFailureHint(j.error_summary || "") : "";
      const queueBadge =
        statusLower === "queued" ? `<span class="claude-jobs-row__queue">排队 #${queueOrder.get(j.id) || 1}</span>` : "";
      b.innerHTML = `
        <div class="claude-jobs-row__line1">
          <div class="claude-jobs-row__status">
            <span class="${statusClass}" title="${escapeHtml(claudeStatusLabel(j.status))}" aria-label="${escapeHtml(claudeStatusLabel(j.status))}">${escapeHtml(claudeStatusIcon(j.status))}</span>
            <span class="claude-jobs-row__jobid">${escapeHtml(j.id.slice(0, 12))}…</span>
            ${queueBadge}
          </div>
          <div class="claude-jobs-row__time">${escapeHtml(formatIsoToLocal(j.updated_at) || "-")}</div>
        </div>
        <div class="claude-jobs-row__line2">
          <div class="claude-jobs-row__preview">${escapeHtml(j.prompt_preview || "(无提示词预览)")}</div>
          <div class="claude-jobs-row__extra">耗时 ${escapeHtml(duration)}${failHint ? ` · ${escapeHtml(failHint)}` : ""}</div>
        </div>
      `;
      b.addEventListener("click", () => {
        claudeJobsSelectedId = j.id;
        refreshClaudeJobsUi();
      });
      listEl.appendChild(b);
    }
    await loadClaudeJobDetail(sid, claudeJobsSelectedId);
  } catch (e) {
    listEl.innerHTML = `<div class="obs-empty">加载失败：${escapeHtml(formatApiError(e))}</div>`;
    cancelBtn.disabled = true;
  }
}

el("settingsModal").addEventListener("click", (e) => {
  const node = e.target.closest("[data-close-modal]");
  if (node && node.getAttribute("data-close-modal") === "settings") closeSettingsModal();
});
el("vendorsModal").addEventListener("click", (e) => {
  const node = e.target.closest("[data-close-modal]");
  if (node && node.getAttribute("data-close-modal") === "vendors") closeVendorsModal();
});
el("onboardingModal").addEventListener("click", (e) => {
  const node = e.target.closest("[data-close-modal]");
  if (node && node.getAttribute("data-close-modal") === "onboarding") {
    dismissOnboarding();
    closeOnboardingModal();
  }
});
el("onboardingDismissBtn").addEventListener("click", () => {
  dismissOnboarding();
  closeOnboardingModal();
});
el("onboardingOpenVendorsBtn").addEventListener("click", async () => {
  closeOnboardingModal();
  await openVendorsModal();
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
el("claudeJobsModal").addEventListener("click", (e) => {
  const node = e.target.closest("[data-close-modal]");
  if (node && node.getAttribute("data-close-modal") === "claude-jobs") closeClaudeJobsModal();
});
el("openClaudeJobsModalBtn").addEventListener("click", async () => {
  el("claudeJobsModal").hidden = false;
  await refreshClaudeJobsUi();
  startClaudeJobsPolling();
});
el("refreshClaudeJobsBtn").addEventListener("click", () => refreshClaudeJobsUi());
el("cancelClaudeJobBtn").addEventListener("click", async () => {
  const sid = state.currentSessionId;
  const jid = claudeJobsSelectedId;
  if (!sid || !jid) return;
  try {
    await api(`/api/sessions/${encodeURIComponent(sid)}/claude-jobs/${encodeURIComponent(jid)}/cancel`, {
      method: "POST",
      body: "{}",
    });
    await refreshClaudeJobsUi();
  } catch (e) {
    el("claudeJobConversation").innerHTML = `<div class="obs-empty">取消任务失败：${escapeHtml(formatApiError(e))}</div>`;
  }
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
    await refreshModelDropdown({ keepCurrent: true });
    return;
  }
  try {
    const v = await api(`/api/vendors/${id}`);
    state.effectiveApiBase = v.api_base || "";
    await refreshModelDropdown({ preferredModel: (v.default_model || "").trim(), keepCurrent: false });
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
  if (!el("claudeJobsModal").hidden) {
    e.preventDefault();
    closeClaudeJobsModal();
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
    return;
  }
  if (!el("onboardingModal").hidden) {
    e.preventDefault();
    dismissOnboarding();
    closeOnboardingModal();
  }
});

el("attachBtn").addEventListener("click", () => el("fileInput").click());
el("fileInput").addEventListener("change", (e) => {
  void (async () => {
    await addFiles(e.target.files);
    e.target.value = "";
  })();
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
    void addFiles(files);
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
  void addFiles(files);
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
(async () => {
  await refreshUiConfig();
  try {
    await loadSessions();
    await maybeShowOnboarding();
  } catch {
    /* ignore */
  }
})();
startClaudeJobsBackgroundPolling();

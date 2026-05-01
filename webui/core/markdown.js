function escapeHtml(text) {
  const d = document.createElement("div");
  d.textContent = text == null ? "" : String(text);
  return d.innerHTML;
}

function stripModelLeaks(text) {
  if (text == null) return "";
  let s = String(text);
  s = s.replace(/<\|redacted_im_end\|>/gi, "");
  s = s.replace(/<\|im_end\|>/gi, "");
  s = s.replace(/<\|endoftext\|>/gi, "");
  return s.replace(/\s+$/u, "").trimEnd();
}

function renderMarkdown(text) {
  const raw = stripModelLeaks(text == null ? "" : String(text));
  if (typeof marked !== "undefined" && typeof DOMPurify !== "undefined") {
    marked.setOptions({ gfm: true, breaks: true });
    const dirty = marked.parse(raw);
    return DOMPurify.sanitize(dirty, {
      ALLOWED_TAGS: [
        "p",
        "br",
        "strong",
        "b",
        "em",
        "i",
        "u",
        "del",
        "s",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "ul",
        "ol",
        "li",
        "blockquote",
        "pre",
        "code",
        "a",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "hr",
        "div",
        "span",
      ],
      ALLOWED_ATTR: ["href", "target", "rel", "class", "colspan", "rowspan"],
    });
  }
  return `<p>${escapeHtml(raw).replace(/\n/g, "<br>")}</p>`;
}

function fmtTtft(ms) {
  if (ms == null || Number.isNaN(ms)) return "—";
  const n = Number(ms);
  if (n >= 1000) return `${(n / 1000).toFixed(2)} s`;
  return `${Math.round(n)} ms`;
}

function renderMetricsFooter(metrics) {
  if (!metrics || metrics.total_tokens_est == null) return "";
  const ttft = fmtTtft(metrics.ttft_ms);
  const tps = typeof metrics.tps === "number" ? metrics.tps.toFixed(2) : "—";
  const total = metrics.total_tokens_est;
  const inp = metrics.input_tokens_est ?? "—";
  const out = metrics.output_tokens_est ?? "—";
  return `<div class="message-metrics" role="status"><strong>本回复</strong> · 首 token <strong>${ttft}</strong> · 约 <strong>${tps}</strong> token/s · 总约 <strong>${total}</strong> tokens（输入≈${inp} · 输出≈${out}，估算值）</div>`;
}

function enhanceCodeBlocks(root) {
  if (!root) return;
  root.querySelectorAll("pre").forEach((pre) => {
    if (pre.parentElement?.classList.contains("code-block-wrap")) return;
    const wrap = document.createElement("div");
    wrap.className = "code-block-wrap";
    pre.replaceWith(wrap);
    wrap.appendChild(pre);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "code-copy-btn";
    btn.textContent = "复制";
    btn.addEventListener("click", async () => {
      const code = pre.querySelector("code")?.innerText ?? pre.innerText;
      try {
        await navigator.clipboard.writeText(code);
        btn.textContent = "已复制";
        setTimeout(() => {
          btn.textContent = "复制";
        }, 2000);
      } catch {
        btn.textContent = "失败";
        setTimeout(() => {
          btn.textContent = "复制";
        }, 2000);
      }
    });
    wrap.appendChild(btn);
  });
}

export { escapeHtml, stripModelLeaks, renderMarkdown, renderMetricsFooter, enhanceCodeBlocks };

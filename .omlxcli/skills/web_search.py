"""联网搜索工具（MVP）。

优先级：
  1) SearXNG（若配置了 OMLXCLI_SEARXNG_URL 或显式传 searxng_url）
  2) DuckDuckGo HTML（免 key 兜底）

并提供轻量网页正文抽取，方便模型做二次总结。
"""

from __future__ import annotations

import html
import gzip
import json
import os
import re
import base64
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Optional

from _meta import skill

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _http_get(
    url: str,
    timeout: float = 10.0,
    basic_auth_user: str = "",
    basic_auth_password: str = "",
) -> str:
    headers = {
        "User-Agent": _UA,
        "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "identity",
    }
    if basic_auth_user:
        token = base64.b64encode(
            f"{basic_auth_user}:{basic_auth_password}".encode("utf-8")
        ).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    req = urllib.request.Request(
        url,
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        enc = (resp.headers.get("Content-Encoding") or "").lower()
        if enc == "gzip" or raw[:2] == b"\x1f\x8b":
            try:
                raw = gzip.decompress(raw)
            except Exception:  # noqa: BLE001
                pass
        charset = resp.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")


def _http_get_json(
    url: str,
    timeout: float = 10.0,
    basic_auth_user: str = "",
    basic_auth_password: str = "",
) -> dict[str, Any]:
    return json.loads(
        _http_get(
            url,
            timeout=timeout,
            basic_auth_user=basic_auth_user,
            basic_auth_password=basic_auth_password,
        )
    )


def _normalize_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    p = urllib.parse.urlsplit(u)
    scheme = p.scheme.lower() or "https"
    netloc = p.netloc.lower()
    path = p.path or "/"
    # 去掉常见追踪参数
    q = urllib.parse.parse_qsl(p.query, keep_blank_values=False)
    q = [(k, v) for k, v in q if not k.lower().startswith(("utm_", "spm", "from", "ref"))]
    query = urllib.parse.urlencode(q)
    return urllib.parse.urlunsplit((scheme, netloc, path, query, ""))


def _extract_text_from_html(page_html: str, max_chars: int = 1600) -> str:
    s = page_html
    s = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", s)
    s = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", s)
    s = re.sub(r"(?is)<noscript[^>]*>.*?</noscript>", " ", s)
    s = re.sub(r"(?is)<svg[^>]*>.*?</svg>", " ", s)
    # 块级标签转换为换行，减少粘连
    s = re.sub(r"(?is)</(p|div|section|article|li|h[1-6]|br|tr|td)>", "\n", s)
    s = re.sub(r"(?is)<[^>]+>", " ", s)
    s = html.unescape(s)
    s = s.replace("\xa0", " ")
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r"\n{2,}", "\n", s)
    s = s.strip()
    return s[:max_chars]


def _dedupe_results(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for it in items:
        u = _normalize_url(str(it.get("url") or ""))
        if not u or u in seen:
            continue
        seen.add(u)
        it["url"] = u
        out.append(it)
    return out


def _domain_of(url: str) -> str:
    try:
        return urllib.parse.urlsplit(url).netloc.lower()
    except Exception:  # noqa: BLE001
        return ""


def _is_whitelisted(url: str, whitelist: list[str]) -> bool:
    if not whitelist:
        return True
    d = _domain_of(url)
    for w in whitelist:
        x = (w or "").strip().lower()
        if not x:
            continue
        if d == x or d.endswith("." + x):
            return True
    return False


def _extract_publish_time(text: str) -> str:
    """从文本里提取 yyyy-mm-dd / yyyy/mm/dd，返回 ISO 日期字符串。"""
    s = text or ""
    m = re.search(r"(20\d{2})[-/\.](\d{1,2})[-/\.](\d{1,2})", s)
    if not m:
        return ""
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        dt = datetime(y, mo, d)
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _publish_time_to_ts(iso_date: str) -> float:
    if not iso_date:
        return 0.0
    try:
        return datetime.strptime(iso_date, "%Y-%m-%d").timestamp()
    except ValueError:
        return 0.0


def _compute_relevance_score(query: str, item: dict[str, Any], preferred_sites: list[str]) -> float:
    q_tokens = [t for t in re.split(r"\s+", query.lower()) if t]
    title = str(item.get("title") or "").lower()
    snippet = str(item.get("snippet") or "").lower()
    content = str(item.get("content_excerpt") or "").lower()
    text = f"{title}\n{snippet}\n{content}"

    overlap = 0
    for t in q_tokens:
        if t in text:
            overlap += 1

    score = overlap * 8.0
    if title:
        score += 1.5
    if snippet:
        score += 1.0
    if content:
        score += 1.5

    url = str(item.get("url") or "")
    domain = _domain_of(url)
    if domain:
        score += 0.5
    for site in preferred_sites:
        s = (site or "").strip().lower()
        if s and (domain == s or domain.endswith("." + s)):
            score += 4.0
            break

    # 有发布时间轻微加分，便于排序稳定。
    if item.get("published_at"):
        score += 0.8
    return score


def _search_via_searxng(
    query: str,
    max_results: int,
    searxng_url: str,
    language: str,
) -> list[dict[str, Any]]:
    base = searxng_url.rstrip("/")
    params = urllib.parse.urlencode(
        {
            "q": query,
            "format": "json",
            "language": language,
            "safesearch": 0,
        }
    )
    data = _http_get_json(f"{base}/search?{params}", timeout=12.0)
    results = data.get("results") or []
    out: list[dict[str, Any]] = []
    for r in results[: max_results * 2]:
        title = str(r.get("title") or "").strip()
        snippet = str(r.get("content") or "").strip()
        published = (
            str(r.get("publishedDate") or "").strip()
            or _extract_publish_time(title + " " + snippet)
        )
        out.append(
            {
                "title": title,
                "url": str(r.get("url") or "").strip(),
                "snippet": snippet,
                "published_at": published,
                "source": "searxng",
            }
        )
    return _dedupe_results(out)[:max_results]


def _search_via_gateway_v2(
    query: str,
    max_results: int,
    gateway_url: str,
    language: str,
    refresh: bool,
    auth_user: str,
    auth_password: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    base = gateway_url.rstrip("/")
    endpoint = f"{base}/search" if not base.endswith("/search") else base
    params = {
        "q": query,
        "refresh": 1 if refresh else 0,
        "language": language,
    }
    data = _http_get_json(
        f"{endpoint}?{urllib.parse.urlencode(params)}",
        timeout=15.0,
        basic_auth_user=auth_user,
        basic_auth_password=auth_password,
    )
    results = data.get("results") or []
    out: list[dict[str, Any]] = []
    for r in results[: max_results * 2]:
        title = str(r.get("title") or "").strip()
        url = str(r.get("url") or r.get("link") or "").strip()
        snippet = str(r.get("snippet") or r.get("content") or "").strip()
        published = (
            str(r.get("published_at") or r.get("publishedDate") or "").strip()
            or _extract_publish_time(title + " " + snippet)
        )
        item = {
            "title": title,
            "url": url,
            "snippet": snippet,
            "published_at": published,
            "source": "searxng-gateway-v2",
        }
        if "score" in r:
            try:
                item["gateway_score"] = float(r.get("score"))
            except Exception:  # noqa: BLE001
                pass
        out.append(item)

    meta = {
        "ranking_profile": data.get("ranking_profile"),
        "rewrites": data.get("rewrites") or [],
        "cache_hit": data.get("cache_hit"),
        "unresponsive_engines": data.get("unresponsive_engines") or [],
    }
    return _dedupe_results(out)[:max_results], meta


def _decode_ddg_redirect(url: str) -> str:
    # DuckDuckGo 常见跳转：/l/?uddg=<encoded-url>
    p = urllib.parse.urlsplit(url)
    if "duckduckgo.com" in p.netloc and p.path.startswith("/l/"):
        q = urllib.parse.parse_qs(p.query)
        uddg = (q.get("uddg") or [""])[0]
        if uddg:
            return urllib.parse.unquote(uddg)
    return url


def _search_via_duckduckgo(query: str, max_results: int) -> list[dict[str, Any]]:
    q = urllib.parse.urlencode({"q": query})
    page = _http_get(f"https://duckduckgo.com/html/?{q}", timeout=12.0)
    # 结果块中链接
    links = re.findall(
        r'(?is)<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        page,
    )
    snippets = re.findall(
        r'(?is)<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>|<div[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</div>',
        page,
    )
    out: list[dict[str, Any]] = []
    for idx, (href, raw_title) in enumerate(links[: max_results * 3]):
        title = _extract_text_from_html(raw_title, max_chars=180)
        url = _decode_ddg_redirect(html.unescape(href))
        snip = ""
        if idx < len(snippets):
            s0, s1 = snippets[idx]
            snip = _extract_text_from_html(s0 or s1 or "", max_chars=280)
        out.append(
            {
                "title": title,
                "url": url,
                "snippet": snip,
                "published_at": _extract_publish_time(title + " " + snip),
                "source": "duckduckgo",
            }
        )
    return _dedupe_results(out)[:max_results]


def _fetch_page_excerpt(url: str, max_chars: int = 1400) -> str:
    raw = _http_get(url, timeout=12.0)
    return _extract_text_from_html(raw, max_chars=max_chars)


@skill(
    desc="联网搜索 v2（白名单过滤 + 相关性重排 + 时间排序；SearXNG 优先，DuckDuckGo 兜底）。",
    examples=[
        "web_search('OpenAI o3 release notes', max_results=6)",
        "web_search('杭州今天天气', max_results=5, fetch_content=True)",
        "web_search('AI Agent news', sort_by='time', site_whitelist=['openai.com','anthropic.com'])",
    ],
)
def web_search(
    query: str,
    max_results: int = 8,
    fetch_content: bool = True,
    max_content_chars: int = 1200,
    language: str = "zh-CN",
    searxng_url: Optional[str] = None,
    sort_by: str = "relevance",
    site_whitelist: Optional[list[str]] = None,
    preferred_sites: Optional[list[str]] = None,
    gateway_url: Optional[str] = None,
    gateway_refresh: bool = True,
    gateway_user: Optional[str] = None,
    gateway_password: Optional[str] = None,
) -> dict[str, Any]:
    """返回 {query, engine, sort_by, results:[...], warning?}。

    参数：
      sort_by: 'relevance'（默认）或 'time'
      site_whitelist: 域名白名单，如 ['openai.com', 'arxiv.org']
      preferred_sites: 偏好站点（用于相关性加权），不做硬过滤
      gateway_url: v2 检索网关地址（如 https://$url 或 https://$url/search）
      gateway_refresh: 是否强刷 v2 缓存（默认 True）
    """
    q = (query or "").strip()
    if not q:
        raise ValueError("query 不能为空")
    max_results = max(1, min(int(max_results), 12))
    max_content_chars = max(200, min(int(max_content_chars), 6000))
    sort_by = (sort_by or "relevance").strip().lower()
    if sort_by not in ("relevance", "time"):
        raise ValueError("sort_by 必须是 'relevance' 或 'time'")
    whitelist = [x.strip().lower() for x in (site_whitelist or []) if str(x).strip()]
    preferred = [x.strip().lower() for x in (preferred_sites or []) if str(x).strip()]

    cfg_searx = (
        (searxng_url or "").strip()
        or os.getenv("OMLXCLI_SEARXNG_URL", "").strip()
    )
    cfg_gateway = (
        (gateway_url or "").strip()
        or os.getenv("OMLXCLI_SEARCH_GATEWAY_URL", "").strip()
    )
    cfg_gateway_user = (
        (gateway_user or "").strip()
        or os.getenv("OMLXCLI_SEARCH_GATEWAY_USER", "").strip()
    )
    cfg_gateway_password = (
        (gateway_password or "").strip()
        or os.getenv("OMLXCLI_SEARCH_GATEWAY_PASSWORD", "").strip()
    )

    engine = ""
    warning = ""
    results: list[dict[str, Any]] = []
    primary_error: Exception | None = None
    gateway_meta: dict[str, Any] = {}

    if cfg_gateway:
        try:
            results, gateway_meta = _search_via_gateway_v2(
                q,
                max_results=max_results,
                gateway_url=cfg_gateway,
                language=language,
                refresh=bool(gateway_refresh),
                auth_user=cfg_gateway_user,
                auth_password=cfg_gateway_password,
            )
            engine = "searxng-gateway-v2"
        except Exception as exc:  # noqa: BLE001
            primary_error = exc

    if (not results) and cfg_searx:
        try:
            results = _search_via_searxng(q, max_results=max_results, searxng_url=cfg_searx, language=language)
            engine = "searxng"
        except Exception as exc:  # noqa: BLE001
            if primary_error is None:
                primary_error = exc

    if not results:
        try:
            results = _search_via_duckduckgo(q, max_results=max_results)
            engine = "duckduckgo"
            if primary_error:
                warning = (
                    "上游搜索服务不可用，已回退 DuckDuckGo："
                    f"{type(primary_error).__name__}: {primary_error}"
                )
        except Exception as exc:  # noqa: BLE001
            if primary_error:
                raise RuntimeError(
                    f"联网搜索失败：primary={type(primary_error).__name__}: {primary_error}; "
                    f"duckduckgo={type(exc).__name__}: {exc}"
                ) from exc
            raise RuntimeError(f"联网搜索失败：{type(exc).__name__}: {exc}") from exc

    if fetch_content:
        for item in results:
            url = str(item.get("url") or "")
            if not url:
                continue
            try:
                item["content_excerpt"] = _fetch_page_excerpt(url, max_chars=max_content_chars)
            except Exception as exc:  # noqa: BLE001
                item["content_excerpt"] = ""
                item["fetch_error"] = f"{type(exc).__name__}: {exc}"

    if whitelist:
        results = [it for it in results if _is_whitelisted(str(it.get("url") or ""), whitelist)]

    for item in results:
        if not item.get("published_at"):
            item["published_at"] = _extract_publish_time(
                f"{item.get('title', '')} {item.get('snippet', '')} {item.get('content_excerpt', '')}"
            )
        item["score"] = round(_compute_relevance_score(q, item, preferred), 3)

    if sort_by == "time":
        results.sort(
            key=lambda it: (_publish_time_to_ts(str(it.get("published_at") or "")), float(it.get("score") or 0.0)),
            reverse=True,
        )
    else:
        results.sort(key=lambda it: float(it.get("score") or 0.0), reverse=True)

    results = results[:max_results]

    out: dict[str, Any] = {
        "query": q,
        "engine": engine,
        "sort_by": sort_by,
        "results": results,
    }
    if gateway_meta:
        out["ranking_profile"] = gateway_meta.get("ranking_profile")
        out["rewrites"] = gateway_meta.get("rewrites", [])
        out["cache_hit"] = gateway_meta.get("cache_hit")
        out["unresponsive_engines"] = gateway_meta.get("unresponsive_engines", [])
    if warning:
        out["warning"] = warning
    return out


@skill(
    desc="读取单个网页正文（轻清洗），用于二次总结。",
    examples=[
        "web_read('https://example.com/post', max_chars=3000)",
    ],
)
def web_read(url: str, max_chars: int = 3000) -> dict[str, Any]:
    """返回 {url, content}。"""
    u = _normalize_url(url)
    if not u:
        raise ValueError("url 不能为空")
    max_chars = max(200, min(int(max_chars), 12000))
    content = _fetch_page_excerpt(u, max_chars=max_chars)
    return {"url": u, "content": content}

# SearXNG + Mihomo + V2 Search Gateway 部署与对接手册

本文档为**维护者侧**部署笔记（含示例主机名与绝对路径）；与本仓库的通用对接变量以 **`.env.example`** 中 **`OMLXCLI_SEARCH_*` / `OMLXCLI_SEARXNG_URL`** 等为准。

下文记录从 0 到 1 的部署步骤、配置方法、排障思路，以及给 Agent/Skills 做联网检索对接与测试的方法。

## 1. 架构说明

当前推荐架构：

- `mihomo`：提供出海代理能力（本机 `127.0.0.1:7890`）
- `SearXNG`：基础聚合搜索服务（`127.0.0.1:8080`）
- `search-gateway v2`：检索增强层（查询改写、去重重排、缓存）(`0.0.0.0:8090`，建议仅内网访问)
- `Nginx(公网机)`：`$url` 统一入口，`/search` 转发到 v2 网关，其他路径转发到 SearXNG UI

---

## 2. 已部署组件与路径（本机）

- Mihomo 配置：`/etc/mihomo/config.yaml`
- Mihomo 订阅更新脚本：`/usr/local/bin/update-mihomo-subscription`
- Mihomo 定时器：`mihomo-subscription-update.timer`
- SearXNG compose：`/opt/searxng/docker-compose.yml`
- SearXNG 设置：`/opt/searxng/searxng/settings.yml`
- Search Gateway v2：`/opt/search-gateway/app.py`
- Search Gateway 依赖：`/opt/search-gateway/requirements.txt`
- Search Gateway 服务：`/etc/systemd/system/search-gateway.service`

---

## 3. 关键服务管理命令

### 3.1 Mihomo

```bash
systemctl status mihomo --no-pager
ss -lntp | grep -E '7890|9090'
curl --proxy http://127.0.0.1:7890 https://api.ipify.org
```

### 3.2 SearXNG

```bash
cd /opt/searxng
docker compose ps
docker compose logs --tail=100 searxng
curl -s 'http://127.0.0.1:8080/search?q=openai&format=json' | head
```

### 3.3 Search Gateway v2

```bash
systemctl status search-gateway --no-pager
curl -s http://127.0.0.1:8090/healthz
curl -s 'http://127.0.0.1:8090/search?q=openai&refresh=1' | head
```

---

## 4. 现有性能优化配置（低延迟折中版）

SearXNG 当前策略：

- 主引擎：`bing + yandex`
- 超时：`request_timeout=5.0`, `max_request_timeout=6.0`
- 明显超时/被封引擎已禁用

Search Gateway v2 当前策略：

- Query Rewrite：原始词 + `latest/news/official`
- 并发检索：最多 4 路改写并发
- 排序：`host trust + freshness + engine weight`
- 去重：按 URL/标题去重并保留高分项
- 缓存：SQLite，默认 TTL 600s

---

## 5. 公网 Nginx 配置（推荐）

> Nginx 在另一台 CentOS 7.7 服务器。
> 重点：`/search` 必须代理到 `:8090`，否则不会走 v2。

```nginx
server {
    listen 80;
    server_name $url;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name $url;

    ssl_certificate     /etc/nginx/conf.d/cer/cer/lqai.cn/www.lqai.cn.pem;
    ssl_certificate_key /etc/nginx/conf.d/cer/cer/lqai.cn/www.lqai.cn.key;

    auth_basic "Restricted - SearXNG";
    auth_basic_user_file /etc/nginx/.htpasswd-searxng;

    # v2检索网关
    location = /search {
        proxy_pass http://<SEARXNG服务器内网IP>:8090/search;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }

    # 其他路径保留原SearXNG UI
    location / {
        proxy_pass http://<SEARXNG服务器内网IP>:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

生效：

```bash
nginx -t && systemctl reload nginx
```

---

## 6. 验证清单（强烈建议按顺序）

### 6.1 验证是否真正走 v2

```bash
curl -k -u '用户名:密码' \
  'https://$url/search?q=openai&refresh=1'
```

期待返回字段包含：

- `ranking_profile`
- `rewrites`
- `cache_hit`

若没有 `ranking_profile`，说明还在走旧链路（直连 8080）。

### 6.4 当前实测（已通过）

公网验证命令：

```bash
curl -k -u '用户名:密码' \
  'https://$url/search?q=openai&refresh=1'
```

当前已验证通过，返回中包含：

- `ranking_profile: v2(host-trust+freshness+engine-weight)`
- `rewrites`（4 路改写）
- `results`（已带 `score` 字段）

说明公网 `$url/search` 已走 v2 网关链路。

### 6.5 关于 yandex CAPTCHA

若返回中出现：

- `unresponsive_engines: [["yandex","Suspended: CAPTCHA"], ...]`

这是正常现象（被目标引擎风控），系统仍可由 `bing` 提供结果。建议：

- 保留 `bing` 为稳定主源
- 将 `yandex` 视作补充源，出现 CAPTCHA 时自动降级
- 后续可按需切换/增加其他候选引擎

### 6.2 缓存命中验证

连续请求两次：

```bash
curl -s 'http://127.0.0.1:8090/search?q=openai'
curl -s 'http://127.0.0.1:8090/search?q=openai'
```

第二次应 `cache_hit=true`，耗时显著下降。

### 6.3 端到端速度验证

```bash
time curl -k -u '用户名:密码' \
  'https://$url/search?q=openai'
```

---

## 7. Agent Skills / 本地推理引擎 对接方式

### 7.1 建议对接端点

优先对接：

- `https://$url/search?q=<query>&refresh=1`

内网/本机直连：

- `http://127.0.0.1:8090/search?q=<query>&refresh=1`

### 7.2 结果字段使用建议

- `results[]`：作为候选上下文
- `score`：用于二次截断（例如仅取 score 前 5）
- `rewrites`：可写入日志用于观察查询改写效果
- `unresponsive_engines`：用于动态降级策略

### 7.3 Skills 调用测试模板

```bash
curl -s 'http://127.0.0.1:8090/search?q=OpenAI%20Agents&refresh=1' \
| python3 -c "import sys,json;d=json.load(sys.stdin);print('results',len(d.get('results',[])));print('top', [r.get('title') for r in d.get('results',[])[:3]])"
```

---

## 8. 常见问题与排障

### 8.1 返回 502 Bad Gateway

通常是 Nginx 到后端不通：

- `proxy_pass` IP/端口写错
- 目标主机防火墙/安全组未放行
- 后端服务未监听对应地址

### 8.2 很慢（10+ 秒）

- 引擎超时导致等待到超时上限
- 检查 `unresponsive_engines`
- 禁用超时引擎、缩短 `request_timeout`

### 8.3 返回 0 结果

- 引擎被封/验证码（CAPTCHA）
- 更换出海节点
- 调整引擎组合（保持至少 2 个可用源）

### 8.4 Docker 拉镜像失败（EOF/timeout）

给 Docker daemon 配置代理：

- `/etc/systemd/system/docker.service.d/http-proxy.conf`
- `systemctl daemon-reload && systemctl restart docker`

---

## 9. 安全建议

- 不要在聊天/日志中暴露订阅 token、明文密码
- 若已泄露，立刻重置供应商 token 与 Basic Auth 密码
- Search Gateway 当前监听 `0.0.0.0:8090` 以供远端 Nginx 回源，务必仅内网放通（安全组/防火墙限制来源 IP）
- Nginx 强制 TLS + Basic Auth，必要时增加 IP 白名单

---

## 10. 回滚方案

### 回滚到旧链路（仅 SearXNG）

在 Nginx 将 `/search` 改回：

- `proxy_pass http://<SEARXNG服务器IP>:8080/search;`

然后：

```bash
nginx -t && systemctl reload nginx
```

### 停用 v2 网关

```bash
systemctl stop search-gateway
systemctl disable search-gateway
```

---

## 11. 后续可演进方向

- 增加模式参数：`mode=news|official|balanced`
- 增加域名白名单过滤（仅权威站）
- 引入轻量 reranker 模型（本地部署）
- 引入结果抓取正文摘要（提升问答质量）

---

## 12. 值班巡检 10 条命令（交接速查）

> 建议按顺序执行，基本可覆盖 90% 的线上问题定位。

1) 检查代理服务（mihomo）

```bash
systemctl is-active mihomo && ss -lntp | grep -E '7890|9090'
```

2) 检查 Docker 服务

```bash
systemctl is-active docker && docker --version && docker compose version
```

3) 检查 SearXNG 容器状态

```bash
cd /opt/searxng && docker compose ps
```

4) 检查 SearXNG 最近日志

```bash
cd /opt/searxng && docker compose logs --tail=80 searxng
```

5) 本机直测 SearXNG

```bash
curl -s 'http://127.0.0.1:8080/search?q=openai&format=json' | head
```

6) 检查 v2 网关服务状态与监听

```bash
systemctl is-active search-gateway && ss -lntp | grep 8090
```

7) 本机直测 v2 网关（强刷）

```bash
curl -s 'http://127.0.0.1:8090/search?q=openai&refresh=1' | head
```

8) 验证 v2 关键字段是否存在

```bash
curl -s 'http://127.0.0.1:8090/search?q=openai&refresh=1' \
| python3 -c "import sys,json;d=json.load(sys.stdin);print('profile=',d.get('ranking_profile'));print('cache_hit=',d.get('cache_hit'));print('results=',len(d.get('results',[])))"
```

9) 验证公网域名是否走 v2（需鉴权）

```bash
curl -k -u '用户名:密码' 'https://$url/search?q=openai&refresh=1' \
| python3 -c "import sys,json;d=json.load(sys.stdin);print('has_profile=', 'ranking_profile' in d);print('results=',len(d.get('results',[])))"
```

10) 快速判定常见故障方向

```bash
echo '若 /search 返回 502：优先检查 Nginx -> 172.16.8.169:8090 回源连通与配置'
echo '若结果慢且 unresponsive_engines 多：优先看代理节点质量、引擎超时与 CAPTCHA'
echo '若无 ranking_profile：说明公网仍在走旧链路(8080)'
```


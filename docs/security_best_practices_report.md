# 安全最佳实践审查报告

## 执行摘要

本项目的安全工程基础比较扎实：FastAPI 路由普遍使用依赖式 `RBAC`，生产环境禁止默认 API/JWT secret，Cloud Tasks 回调有 `OIDC` 校验，Redis 故障下写路径 fail-closed，token budget 和审计日志也已经形成闭环。当前最值得继续收口的不是“再加功能”，而是三类安全硬化：Console DOM XSS 防护、生产环境 OpenAPI/Console 暴露边界、以及 header-only token 传递与云端证据归档。

## 审查范围

- 后端：Python/FastAPI、SQLAlchemy、Celery/Redis、Cloud Tasks/GCS 路径。
- 前端：`llm_security_platform/web/` 下的静态 HTML/vanilla JavaScript Console。
- 部署：Docker Compose、GitHub Actions、Terraform/GCP 文档。

## 高优先级发现

### SBP-001：Console 多处使用 `innerHTML` 渲染后端返回数据，需要按 DOM XSS 高价值路径复查

- 严重性：高
- 位置：
  - `llm_security_platform/web/app.js:13` `renderCases`
  - `llm_security_platform/web/app.js:21` `loadRuns`
  - `llm_security_platform/web/app.js:23` `renderRun`
  - `llm_security_platform/web/app.js:41` review queue rendering
  - `llm_security_platform/web/app.js:150` dashboard run select
  - `llm_security_platform/web/app.js:156` dashboard compare table
  - `llm_security_platform/web/app.js:276` threat grid
- 证据：多处将 case name、risk type、metadata、run name、model、defense policy 等值拼接到 template string 后写入 `innerHTML`。
- 影响：如果攻击样本、模型响应、dataset metadata 或 run name 包含 HTML/JS payload，内部 Console 可能触发 DOM XSS，进而读取 API key 输入框或执行同源 API 请求。
- 已有缓解：`renderEvidence` 的 `step()` 对证据正文使用 `escapeHtml`；但部分列表和 dashboard 仍未统一转义。
- 修复建议：优先把所有动态表格改为 DOM API + `textContent`；如短期不重构，至少集中封装 `escapeHtml` 并覆盖所有动态字段。
- 检测建议：用 Playwright 注入带 `<img onerror=...>` 的 case/run name，验证 Console 不执行脚本。

### SBP-002：`export` 通过 query token 支持下载，可能泄露认证材料

- 严重性：中到高
- 位置：
  - `llm_security_platform/web/app.js:24`
  - `llm_security_platform/app/security.py:76-80`
  - `llm_security_platform/app/api.py:618`
- 证据：前端使用 `window.open('/async-runs/{id}/export?token=${key()}')`；后端 `require_api_key` 支持 query 参数 `token`。
- 影响：token 可能进入浏览器历史、代理日志、server access logs 或 referer。
- 已有缓解：导出接口仍执行 `run:read` 权限检查。
- 修复建议：改为 `fetch` 携带 `X-API-Key` 下载 blob；或使用短期一次性 export token。
- 检测建议：检查 access logs 中是否出现 `token=`。

### SBP-003：生产环境应保护或关闭 OpenAPI/Swagger 与 Console 静态入口

- 严重性：中
- 位置：
  - `llm_security_platform/app/api.py:90` `FastAPI(...)`
  - `llm_security_platform/app/api.py:737` StaticFiles mount `/console`
- 证据：当前未看到根据 `LLM_SECURITY_ENV=production` 关闭 docs/openapi，或对 `/console` 静态页面本身做服务端认证。Console 内部 API 调用需要 key，但 HTML 页面可被访问。
- 影响：暴露内部 API 结构、字段、Console 操作入口，提高攻击效率。
- 已有缓解：核心 API 路由使用 `require_permission`，敏感数据请求需要 API key/JWT。
- 修复建议：生产环境设置 `docs_url=None`, `redoc_url=None`, `openapi_url=None`；或由反向代理/IAP/内网限制保护；`/console` 建议前置身份代理或网络限制。
- 检测建议：部署后访问 `/docs`、`/openapi.json`、`/console/`，确认是否符合预期。

## 中优先级发现

### SBP-004：JWT 缺少 `exp`、`iss`、`aud` 等标准声明

- 严重性：中
- 位置：
  - `llm_security_platform/app/security.py:51-57`
  - `llm_security_platform/app/security.py:42-46`
- 证据：`encode_jwt` 写入 `actor`、`role`、`tenant_id`；`decode_jwt` 校验签名和算法，但没有标准过期、issuer、audience 检查。
- 影响：如果 JWT 泄露，无法通过自然过期降低风险。
- 已有缓解：生产环境禁止默认 JWT secret；算法固定为 `HS256`。
- 修复建议：增加 `exp`、`iat`、`iss`、`aud`；在 `decode_jwt` 中校验，并明确 token TTL。
- 检测建议：单元测试覆盖过期 token、错误 issuer/audience、错误算法。

### SBP-005：多模态 base64 输入需要显式大小上限

- 严重性：中
- 位置：
  - `llm_security_platform/app/api.py:352-361`
  - `llm_security_platform/app/schemas.py:149`
- 证据：`image_base64` 直接解码；未在 schema 或 handler 中看到明确字节大小上限。
- 影响：超大 base64 payload 可能造成内存/CPU DoS。
- 已有缓解：`assess_multimodal_input` 做后续解析；但入口大小控制应更前置。
- 修复建议：在 Pydantic model 或 handler 中限制 base64 长度和解码后字节数；生产环境还应在边缘层设置 body size limit。
- 检测建议：添加超大 base64 请求的 413/400 返回测试。

### SBP-006：`SET LOCAL search_path` 使用前需要严格验证 tenant id

- 严重性：中
- 位置：
  - `llm_security_platform/app/production_store.py:104`
- 证据：PostgreSQL 路径执行 `SET LOCAL search_path TO {tenant_id}`。
- 影响：如果 tenant id 校验或 quoting 失误，可能引发 schema routing 异常或 SQL 注入风险。
- 已有缓解：代码中存在 `validate_tenant_id`，测试覆盖需要持续保持。
- 修复建议：确保所有进入 `current_tenant` 的 tenant id 都经过 allowlist regex；SQL identifier 建议使用安全 quoting。
- 检测建议：tenant id fuzz 测试：引号、分号、空格、大小写、Unicode。

## 值得重点展示的已有安全控制

| 控制点 | 证据 | 为什么重要 |
|---|---|---|
| RBAC roles | `security.py:9-14` | 明确 viewer/analyst/reviewer/admin 边界 |
| 生产环境 secret guard | `config.py` 与 `security.py` | 生产环境拒绝默认 API/JWT secret |
| Cloud Tasks OIDC | `security.py:111-147`, `task_queue.py:62-67` | 云端任务回调不裸奔 |
| Redis 写路径 fail-closed | `middleware.py` | 限流故障时不继续放大昂贵写任务 |
| Token budget | `cost_guardrail.py` | 控制 provider 成本与 DoS 风险 |
| Audit logs | `production_store.py:427`, `api.py:audit_logs` | 支撑追责和面试证据链 |
| Raw/delivered 分离 | `case_execution.py` | 避免混淆模型原始妥协和最终暴露风险 |

## 推荐的下一步修复

1. 先修 Console DOM XSS：把 `web/app.js` 的动态表格渲染改为 `textContent`/DOM API。
2. 把 export 下载改为 header-based `fetch`，移除 query token 用法。
3. 生产环境关闭或保护 `/docs`、`/openapi.json`、`/console/`。
4. JWT 增加 `exp`、`iss`、`aud`，补过期 token 测试。
5. 多模态上传增加入口大小限制。

## 面试安全表述

可以这样说：

> 我对项目做过 AppSec 视角的自查：RBAC、OIDC、预算、审计、fail-closed 都已经落地；剩余风险主要在 Console DOM 渲染、生产入口暴露和 token 传输方式，属于从内部试点走向真实部署前的硬化项。

不要这样说：

> 项目已经没有安全问题，或者已经达到生产级安全网关标准。

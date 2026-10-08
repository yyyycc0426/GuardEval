# RBAC 权限矩阵：当前代码对齐版

> 本文以 `llm_security_platform/app/security.py` 和 `llm_security_platform/app/api.py` 为准。旧版文档中的 `/api/v1/*`、`eval:*`、Alertmanager Webhook 等描述不代表当前默认 API 路径。

## 1. 角色与权限

当前 `ROLE_PERMISSIONS` 定义在 `llm_security_platform/app/security.py`：

| 角色 | 权限 | 适合的使用者 |
|---|---|---|
| `viewer` | `run:read` | 只查看评测结果或演示报告的人 |
| `analyst` | `run:read`, `run:create`, `run:cancel`, `run:retry`, `case:read` | 创建和管理评测任务的安全/研发人员 |
| `reviewer` | `run:read`, `audit:read`, `review:read`, `review:write`, `case:read` | 处理人工复核、审计和样本提升的人 |
| `admin` | `*` | 本地管理员或受控演示管理员 |

## 2. 主要接口与权限

| 接口 | 方法 | 权限/边界 | 说明 |
|---|---|---|---|
| `/health` | GET | 无业务权限要求 | 健康检查 |
| `/tenants/signup` | POST | signup 路径 | 创建租户/演示身份 |
| `/tenants/token` | POST | 凭证路径 | 获取 token |
| `/cases` | GET | `case:read` | 查看攻击/评测样本 |
| `/cases` | POST | 管理路径，需结合代码检查当前依赖 | 创建样本 |
| `/datasets/import` | POST | 管理/样本导入路径 | 导入数据集 |
| `/runs` | POST | `run:create` | 同步评测入口 |
| `/runs/{run_id}` | GET | `run:read` | 查询同步评测 |
| `/async-runs` | POST | `run:create` | 创建异步评测 |
| `/async-runs/{run_id}` | GET | `run:read` | 查询异步评测详情 |
| `/async-runs/{run_id}/cancel` | POST | `run:cancel` | 取消异步任务 |
| `/async-runs/{run_id}/retry` | POST | `run:retry` | 重试异步任务 |
| `/human-reviews` | GET | `review:read` | 查看人审队列 |
| `/human-reviews/{review_id}` | PATCH | `review:write` | 更新人审结论 |
| `/audit-logs` | GET | `audit:read` | 查看审计日志 |
| `/policies` | GET/POST | 管理/策略路径 | 查看或创建防御策略 |
| `/metrics` | GET | 监控路径 | 暴露指标 |
| `/ws` | WebSocket | token + `run:read` | 推送/查询运行状态 |

## 3. 可以安全讲的设计点

- RBAC 不是只写在文档里，API 入口通过 `require_permission(...)` 进行权限约束。
- WebSocket 也不是裸连：`api.py:websocket_endpoint` 会解析 token，并检查角色是否具有 `run:read`。
- 生产环境不能使用默认 JWT secret：`security.py` 在 `LLM_SECURITY_ENV=production` 且未配置 `LLM_SECURITY_JWT_SECRET` 或使用默认值时会抛错。

## 4. 不能夸大的边界

- 不要说“彻底杜绝横向越权”。更准确的说法是：当前代码实现了 tenant-aware 鉴权和存储路径，并有测试覆盖，但还没有真实恶意租户长期攻防验证。
- 不要说“企业级 SSO 已完成”。当前主要是 API Key/JWT/OIDC 相关代码路径，不等于完整企业身份治理。
- 不要说“所有接口均已完成最小权限审计”。更稳妥的说法是：核心评测、人审、审计、WebSocket 路径已有权限控制；其它管理类接口面试时按代码逐个说明。


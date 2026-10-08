# Python 源码解析第9章：多租户数据隔离与租户配置

## 模块概览

### 租户身份从哪里来

`security.py` 解析 API key 或 JWT，得到：

- `actor`
- `role`
- `tenant_id`

API 路由从认证 principal 使用 tenant，不信任客户端在业务 JSON 中自报 tenant。

## 核心类型

### ContextVar

`production_store.py` 使用 `current_tenant` 保存当前执行上下文。Worker 从 `AsyncRun.tenant_id` 恢复，避免队列 payload 伪造 tenant 后直接越权。

## 主流程走读

### 正常流程

```text
API key/JWT
→ principal tenant
→ current_tenant
→ tenant query/search_path
→ tenant policy/key/cache/budget
→ tenant-scoped result
```

## 内置隔离机制

### PostgreSQL Schema Routing

`session_scope()` 在 PostgreSQL 下设置 tenant-specific Schema/search path。tenant ID 需要严格格式校验，防止被拼接为 SQL identifier 注入。

应用层查询仍保留 tenant 条件，形成防御纵深。

### SQLite 路径

本地 SQLite 无 PostgreSQL Schema，主要依赖 tenant 字段过滤。因此“Schema 隔离”只能在 PostgreSQL 路径下成立。

### Tenant Config

`save_tenant_config()` 保存：

- 加密模型 keys；
- QPS limit。

`get_tenant_config()` 解密后仅在 Worker 构建 Provider 时注入 `_tenant_keys`。

不应在 API 响应、日志或报告中输出明文 key。

### 租户级策略

`PolicyEngine(..., tenant_id=...)` 加载 policy record 时带 tenant，防止一个租户修改另一个租户防御阈值。

### 租户级预算

`check_and_record_usage()` 使用 tenant/user/run 维度；每日 tenant 和 user meter 还会同步数据库。

### 租户级缓存

`SemanticCache` 的 key 空间包含 tenant、Provider、model 和 policy，避免跨租户复用敏感回答。

### 查询隔离

重点检查：

- `get_async_run(run_id, tenant_id)`
- `list_case_results(run_id, tenant_id)`
- `list_async_runs(..., tenant_id)`
- `list_audits(..., tenant_id)`
- `db.list_attack_cases(..., tenant_id)`

仅检查 run ID 而不检查 tenant 会形成 IDOR。

### API 权限与 Tenant 隔离的区别

RBAC 解决“同一租户内能做什么”；tenant 隔离解决“能访问谁的数据”。管理员角色也不应默认跨租户读取，除非系统明确设计全局管理员。

## 失败流程与边界条件

### 失败与攻击场景

- 恶意 tenant ID：Schema 创建前拒绝；
- 猜测其他 run ID：tenant 不匹配返回 404/空；
- 修改请求 tenant 字段：业务层仍使用 principal；
- Worker payload tenant 错误：从数据库 run 恢复真实 tenant；
- 缓存 key 缺 tenant：可能发生敏感结果串租户。

## 测试与证据

### 测试证据

- `tests/test_tenant_isolation.py`
- `tests/test_security_audit.py`
- `tests/test_saas_upgrades.py`
- `tests/test_saas_idempotency_and_metering.py`

测试能证明指定应用路径，不等于数据库账号层面已经做到每租户独立凭据。

## 面试追问

### 面试回答

> 我把 RBAC 和 tenant isolation 分开处理。身份里携带 tenant，查询与策略都显式带 tenant，PostgreSQL 再用 Schema routing 加一层；Worker 以数据库 run 的 tenant 为准。

## 小结

多租户不是给表加一个字段就结束。身份、查询、Schema、缓存、预算、策略、报告和异步上下文都必须携带同一 tenant 边界。

# Python 源码解析第27章：认证、RBAC、限流与审计

## 模块概览

### 认证与授权

- 认证回答“你是谁”；
- 授权回答“你能做什么”；
- tenant isolation 回答“你能访问谁的数据”。

三者必须同时成立。

## 核心类型

### API Key

`security.py:_principals()` 从配置解析 principal，关联 actor、role 和 tenant。API key 适合内部服务和演示，不等于生产 SSO。

### JWT

`encode_jwt()` 和 `decode_jwt()` 提供 token 路径。签名密钥来自配置。

标准生产 JWT 通常还关注 `exp/iss/aud/jti` 等 claim；是否全部具备要以当前实现为准，不应只凭“用了 JWT”声称生产级认证。

### Role

`ROLE_PERMISSIONS` 定义 viewer、analyst、reviewer、admin 等权限集合。

典型 permission：

- `case:read`
- `run:create`
- `run:read`
- `run:retry`
- `run:cancel`
- `review:read/write`
- `audit:read`
- `admin:write`

## 主流程走读

### `require_permission()`

流程：

```text
读取 Authorization/API key
→ 解析 principal
→ 设置 tenant context
→ 检查 permission
→ 返回 actor/role/tenant
```

无凭据 401；已认证但缺权限 403。

## 内置认证与权限机制

### Cloud Tasks OIDC

`verify_cloud_tasks_oidc()` 只服务 Worker webhook。它与普通用户 JWT 不是同一身份路径。

需要验证 token 签名、audience 和调用主体；真实 IAM 绑定由部署环境决定。

### Rate Limiting

`RateLimitingMiddleware` 使用 Redis 计数。静态 Console、health/docs/metrics 等路径可能有跳过规则，应按源码检查暴露面。

### Fail-Closed

Redis 故障时：

- 高影响写请求拒绝；
- 读请求可有限本地 fallback。

目标是依赖故障时不允许绕过创建、修改等操作。

## 审计机制

### Audit Log

`save_audit()` 保存：

- actor/role；
- action；
- target type/ID；
- request ID；
- run ID；
- metadata；
- tenant。

审计用于回答“谁在什么时候对什么对象做了什么”。

### 关键审计动作

- tenant signup；
- dataset import；
- run create/cancel/retry；
- review complete/promote；
- policy create；
- 其他高影响写操作。

## 失败流程与边界条件

### 敏感信息

审计 metadata 不应保存：

- API key；
- Authorization header；
- 明文 tenant secrets；
- 不必要的原始 Prompt；
- 个人敏感信息。

### Console 风险

`web/app.js` 中：

- 多处 `innerHTML`；
- export URL token；

属于前端安全债。内部演示可受控使用，但会阻塞生产安全声明。

## 测试与证据

### 测试与浏览器证据

- `tests/test_stage_five_rbac.py`
- `tests/test_security_audit.py`
- `tests/test_tenant_isolation.py`
- 浏览器 E2E 中 analyst 访问 `/audit-logs` 得到 403。

## 面试追问

### 面试回答

> RBAC 决定角色能力，tenant filter 决定数据边界，audit 记录高影响操作；Cloud Tasks webhook 使用独立 OIDC 身份，而不是复用用户 API key。

## 小结

安全默认值必须落在实际入口：权限依赖、tenant 查询、写请求 fail-closed 和审计，而不是只在文档中存在。

# Python 源码解析第5章：FastAPI 应用入口与路由系统

## 模块概览

### 应用入口

`llm_security_platform/app/api.py` 集中定义 FastAPI 应用、Middleware、路由和 Console 挂载。它是外部请求进入评测平台的唯一主要入口。

## 核心类型

### Middleware 顺序

主要 Middleware：

- `RateLimitingMiddleware`
- `MetricsMiddleware`
- `TracingMiddleware`

它们分别负责限流、延迟/请求指标和 trace 上下文。Middleware 的执行顺序会影响错误是否被计入指标以及 trace 是否进入日志。

## 主流程走读

### 异步创建主流程

`create_async_evaluation()` 是最重要的接口：

```text
RBAC
→ budget
→ case limit
→ tenant cases
→ fingerprint/lock
→ create_async_run
→ dispatch_run
→ save_audit
→ 202
```

### Cloud webhook 防重

Webhook 先查询 run。终态直接返回 `skipped`，减少 Cloud Tasks 重试导致的重复执行。

### 静态 Console

`StaticFiles` 将 `web/` 挂载到 `/console`。这适合演示和内部工具；生产环境是否应公开 Console、OpenAPI 和文档需另行配置。

## 核心路由

### 路由分类

#### 健康检查

`GET /health` 返回统一 `ApiResponse`，供本地、Docker 和 Cloud 健康探针使用。

#### 租户

- `POST /tenants/signup`
- `POST /tenants/token`

负责租户配置和令牌，不应与生产级自助 SaaS 注册混为一谈。

#### Case 与 Dataset

- `GET /cases`
- `POST /cases`
- `POST /cases/seed`
- `POST /datasets/import`

写操作需要更高权限，并将 `tenant_id` 传入数据层。

#### 同步评测

- `POST /runs`
- `GET /runs/{run_id}`
- `GET /runs/{run_id}/defense-audits`

适合短评测和开发验证。

#### 对比与分层判定

- `POST /comparisons`
- `POST /model-comparisons`
- `POST /layered-assessments`
- `POST /layered-assessments/multimodal`

这些接口覆盖防御对比、模型对比和单响应分层判断。

#### 人工复核

- `GET /human-reviews`
- `PATCH /human-reviews/{review_id}`
- `POST /human-reviews/{review_id}/promote-to-dataset`
- `GET /human-reviews/metrics`

#### 异步评测

- `POST /async-runs`
- `GET /async-runs`
- `GET /async-runs/{run_id}`
- `GET /async-runs/{run_id}/export`
- `POST /async-runs/{run_id}/cancel`
- `POST /async-runs/{run_id}/retry`

#### Worker webhook

`POST /tasks/execute-run` 只在 `LLM_SECURITY_QUEUE_MODE=cloud` 时允许，并要求 Cloud Tasks OIDC。

#### 策略、审计和指标

- `GET /audit-logs`
- `POST /policies`
- `GET /policies`
- `GET /policies/{name}/{version}`
- `GET /metrics`

## 关键机制

### 权限依赖

典型写法：

```python
actor = Depends(require_permission("run:create"))
```

依赖返回 actor、role、tenant ID。业务函数不从请求 JSON 信任 tenant，而从认证 principal 获取。

### 请求校验

FastAPI 调用 Pydantic：

- 字段类型错误：422；
- 自定义业务约束：400；
- 未认证：401；
- 无权限：403；
- 重复请求：409；
- 预算超限：402；
- 队列不可用：503。

### 统一响应

大多数接口返回：

```python
ApiResponse(
    success=True,
    message="...",
    data=...,
)
```

优点是 Console 处理统一；代价是需要避免在 `data` 中放入未经序列化或敏感对象。

## 失败流程与边界条件

### 错误边界

- 不应把底层异常完整返回给不可信调用者；
- webhook 返回 500 会触发 Cloud Tasks 重试；
- 队列失败时必须释放锁；
- tenant 查询必须每条路径一致；
- export 不应通过 URL 泄露 token。

## 测试与证据

### 测试

- `tests/test_api.py`
- `tests/test_stage_five_rbac.py`
- `tests/test_saas_upgrades.py`
- `tests/test_websocket_rbac.py`
- 浏览器 E2E 记录 analyst 访问 audit 得到 403。

## 面试追问

**为什么创建异步任务返回 202？**

因为服务器只确认任务已接受和持久化，实际评测由 Worker 完成；结果通过轮询或导出获取。

## 小结

API 层不仅是路由集合，还负责把 Schema、权限、预算、幂等、租户和审计组合成默认安全入口。

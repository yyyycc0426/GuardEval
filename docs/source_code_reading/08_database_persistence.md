# Python 源码解析第8章：数据库模型、迁移与持久化设计

## 模块概览

### 两条存储路径

仓库保留：

1. `app/db.py`：同步评测和部分业务对象；
2. `app/production_store.py` + SQLAlchemy models：异步 run/case/audit/tenant。

这是演进结果。面试时应说明默认演示主链使用异步 Store，而不是声称从一开始就是单一存储架构。

## 核心类型

### SQLAlchemy 模型

#### `AsyncRun`

保存：

- run ID、name；
- Provider、model、policy；
- request JSON、metadata JSON；
- total/completed/success/failed；
- progress、status；
- task ID；
- tenant、creator；
- cancel/retry/error；
- 时间字段。

#### `AsyncCaseResult`

保存：

- run ID、case ID；
- case JSON；
- status、attempts；
- result JSON、error；
- started/completed 时间。

#### `AuditLog`

保存 actor、role、action、target、request ID、run ID、metadata 和 tenant。

#### `TenantConfig`

保存加密后的模型 key 与 QPS 配置。

#### `TenantBudgetMeter`

保存 tenant/user/date 维度的 token 使用。

## 主流程走读

### `session_scope()`

典型生命周期：

```text
创建 Session
→ 设置 tenant search_path
→ yield
→ commit
异常 → rollback
最终 → close
```

业务函数不应把已关闭 Session 中的 ORM 实例直接传到 API。

### 创建 Run 的事务

`create_async_run()` 在一个 Session 中：

1. 检查活动 fingerprint；
2. 创建 `AsyncRun`；
3. flush 获得稳定状态；
4. 批量创建 `AsyncCaseResult`；
5. commit；
6. 重新查询并序列化。

run 与初始 cases 同事务，避免出现“有 run 但没有 case 列表”。

### Case 状态写入

`begin_case()` 增加 attempts；`finish_case()` 保存 result/error；`refresh_progress()` 重新汇总 run 进度。

这种做法比只在 Worker 内存里计数更能支持进程重启和查询。

## 内置存储路径

### 同步数据库

`app/db.py` 使用更轻量的存储函数，覆盖 cases、同步 run/result、layered assessment、review 和 policy。阅读代码时要区分同步路径与异步生产式路径。

### 迁移

Alembic 用于生产式表结构迁移。Docker Compose 中 `migrate` 服务先执行迁移，再启动依赖服务。

历史 E2E 报告记录 PostgreSQL migration 通过；当前机器是否正在运行容器需要实时检查。

### 数据加密

`production_store.py:encrypt_data/decrypt_data` 用于 tenant keys。加密密钥仍来自环境变量，密钥轮换与 KMS 托管仓库中未验证。

## 关键机制与设计取舍

### JSON 字段取舍

优点：

- 便于保存不同 Detector/Provider metadata；
- 证据链结构灵活；
- 报告可直接导出。

代价：

- 数据库难以对任意嵌套字段建立统一约束；
- Schema 演进需要兼容旧 JSON；
- 原始 Prompt/响应可能包含敏感数据。

## 失败流程与边界条件

### 错误路径

- Session 异常：rollback；
- run 不存在：返回 None 或抛业务错误；
- tenant 不匹配：查询返回空；
- case 不存在：finish 直接返回；
- stale active run：标记失败后允许新 run；
- schema 创建失败：tenant signup 返回错误。

## 测试与证据

### 测试证据

- `tests/test_database_migration.py`
- `tests/test_stage_five_store.py`
- `tests/test_backup.py`
- Docker E2E 中 `alembic_upgrade=true`。

## 面试追问

### 为什么任务状态不只保存在 Celery Backend？

数据库还需要支持 tenant 查询、case 证据、错误、attempts、报告和人工复核；队列 backend 不能替代业务状态模型。

### 为什么结果大量使用 JSON 字段？

不同 Provider、Detector 和 Policy 的扩展字段变化较快，JSON 便于保存证据；代价是数据库约束和查询能力较弱，因此稳定主字段仍使用独立列。

## 小结

持久化层的关键不是 ORM 本身，而是让长任务的配置、状态、错误、证据和重试在进程之外可恢复。

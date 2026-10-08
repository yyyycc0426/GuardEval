# Python 源码解析第25章：幂等、重试、取消与故障恢复

## 模块概览

### 重复从哪里来

- 用户重复点击；
- 浏览器重试；
- API 网关重试；
- Celery 重投；
- Cloud Tasks 至少一次投递；
- Worker 执行中断；
- 网络超时但服务端已成功。

## 核心类型

### 请求 Fingerprint

`get_run_fingerprint()` 对 case IDs、versions、inference config 和 defense config 排序序列化后计算 SHA-256。

相同评测条件生成相同 fingerprint。

## 主流程走读

### Redis Lock

API 使用：

```text
run_lock:{tenant_id}:{fingerprint}
```

`SET NX EX 300` 原子抢锁。失败返回 409 和已有 run ID。

### 数据库二次检查

即使 Redis 不可用，`create_async_run()` 仍搜索同 tenant 的活动 run metadata fingerprint。

这是兜底，不等于高并发下与 Redis 锁完全等价。

### Lock Heartbeat

Worker 批次间延长 TTL，完成后删除。Worker crash 依赖 TTL 自动释放。

## 内置恢复机制

### Cloud Tasks 去重

task ID 使用 run ID；`AlreadyExists` 作为幂等重复处理。

### Worker 重入

`start_run()` 对 COMPLETED/CANCELLED 返回 False；Cloud webhook 也先检查终态。

### Case 级恢复

`pending_cases()` 排除 COMPLETED；`begin_case()` 再次检查并增加 attempts。

已完成 case 不重复调用模型，失败或未完成 case 可以在 retry 后继续。

### Retry

`POST /async-runs/{run_id}/retry`：

1. 权限；
2. 查询 tenant run；
3. `prepare_retry()`；
4. 重新 dispatch；
5. 审计。

重试不会自动清除所有历史证据，具体保留逻辑以 Store 为准。

### Cancel

取消设置标志，Worker 在 batch 边界停止。正在执行的 future 可能仍完成并落库，因此取消不是进程级 kill。

### Provider Retry

Gemini 对指定瞬态错误有限重试；其他 Provider 多数把异常交给 case failure 和熔断处理。

## 失败流程与边界条件

### 故障场景

| 场景 | 预期 |
|---|---|
| 队列投递失败 | run FAILED，锁释放 |
| Worker 中断 | 状态保留，恢复后继续 |
| 单 case 失败 | PARTIAL_FAILED |
| 重复投递 | ignored/跳过已完成 |
| Redis 重启 | API 恢复，数据库仍是主状态 |
| 模型超时 | case/run 失败信息可查询 |
| 取消 | CANCELLED |

## 测试与证据

### 故障演练证据

`stage_5_6_fault_drill.json` 记录以上部分场景为 passed。它是脚本控制 Compose 演练，不等于 chaos engineering 或生产 MTTR。

## 能力边界

### Exactly-once 边界

多层幂等降低重复副作用，但分布式系统通常是至少一次投递。没有跨队列、数据库和外部模型的原子事务，不能声称严格 exactly-once。

## 面试追问

### 为什么 Redis 锁之外还需要数据库 Fingerprint？

Redis 可能不可用或锁超时，数据库活动 run 检查提供第二层保护；两者共同降低重复提交，但仍不是跨系统原子事务。

### Worker 重试为什么不会重跑全部 Case？

`pending_cases()` 排除已完成项，`begin_case()` 再做状态检查，恢复时只处理未完成或失败 case。

## 小结

系统通过“请求去重 + 任务 ID + 状态机 + case 跳过 + 可查询错误”实现实用恢复，而不是依赖单个队列保证所有可靠性。

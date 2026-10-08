# Python 源码解析第14章：Worker 与批量并发执行

## 模块概览

### 主函数

`app/tasks.py:run_evaluation_logic(run_id, tenant_id, trace_id)` 是异步 Worker 的执行入口。

## 核心类型

### `EvaluationRunCreate`

从持久化 `request_json` 恢复评测配置、并发度、Provider、Policy 和 Judge。

### `AsyncRun` 与 `AsyncCaseResult`

前者表示批次状态，后者表示单 case 状态、attempts、result 和 error。

### Provider、PolicyEngine 与 Judge

Worker 在进程内重新构建这些运行组件，并把同一组实例传入当前 run 的 case 执行。

## 主流程走读

### 第一步：恢复上下文

- 设置 `current_trace_id`；
- 查询 `AsyncRun`；
- 从数据库恢复真实 `tenant_id`；
- 读取 `request_json` 和 creator。

数据库中的 tenant 优先于消息传入值，降低伪造 payload 的风险。

### 第二步：重建配置

```python
request = EvaluationRunCreate.model_validate(payload)
```

Worker 再次执行 Schema 校验，然后读取 tenant key，构建 Provider、PolicyEngine 和 Judge。

### 第三步：启动 Run

`start_run()` 返回 False 时直接返回 ignored。该检查处理重复 delivery 和终态重入。

### 第四步：读取剩余 Case

`pending_cases(run_id)` 只返回非 COMPLETED 项。恢复执行不会重复已完成 case。

### 第五步：分批

```python
for offset in range(
    0, len(remaining), request.concurrency
):
    batch = remaining[offset:offset + request.concurrency]
```

`concurrency` 在 Schema 中限制 1～8。

### 第六步：开始 Case

每个 case 先通过 `begin_case()`。只有成功抢到可执行状态的 case 才进入线程池。

### 第七步：线程池

`ThreadPoolExecutor(max_workers=request.concurrency)` 适合模型 HTTP I/O。若把本地 CPU 推理直接放进线程池，GIL、内存和模型线程安全需要另行评估。

### 第八步：收集 Future

`as_completed()` 让先完成的 case 先落库。单个 future 抛错只标记该 case，不中断其他 future。

## 关键机制

### Token Metering

成功结果中的 prompt/completion token 记录到 tenant metrics，并按 Provider/model/token type 分组。

### Budget Exceeded

如果异常包含预算超限标志，Worker 调用 `request_cancel()`，在后续 batch 停止继续提交。

### Redis Lock Heartbeat

每个 batch 尝试延长 `run_lock_key` TTL，防止长 run 执行时 API fingerprint lock 过早失效。

Redis 失败被捕获，run 仍可继续；这意味着数据库 fingerprint 检查仍很重要。

### 最终化与归档

case 全部处理后：

1. `finalize_run()`；
2. `build_async_report()`；
3. GCS/local upload；
4. 删除分布式锁；
5. 返回状态。

## 失败流程与边界条件

### 错误路径

- run 不存在：抛 ValueError；
- 初始化失败：`fail_run()`；
- 单 case 失败：`finish_case(error=...)`；
- GCS 失败：日志记录，不改变主 run；
- lock release 失败：日志记录；
- Worker 被杀：数据库保留 RUNNING/PENDING 供恢复诊断。

### 取舍

- 每 batch 新建线程池，代码清晰但有创建开销；
- 共享 Provider 是否线程安全依赖具体 SDK；
- concurrency 小上限减少风险；
- 没有实现通用 DAG、优先级和跨步骤补偿，因此不是工作流引擎。

## 测试与证据

- `tests/test_advanced_upgrades.py`
- `tests/test_stage_five_store.py`
- `reports/stage_5_6_fault_drill.json`
- Docker E2E 记录独立 Celery worker 在线。

## 面试追问

### 为什么使用线程池而不是 `asyncio`？

当前 Provider 接口是同步 `generate()`，线程池能以较小改动并发等待网络 I/O；代价是线程安全和上下文传播需要额外注意。

### 为什么并发度限制为 8？

这是面向评测任务的保护上限，用于控制 Provider、数据库和预算压力，不代表经过大规模容量规划得出的生产最优值。

## 小结

Worker 的核心不是“并发越多越好”，而是在有限并发下维持 tenant、预算、状态、失败隔离和证据落库。

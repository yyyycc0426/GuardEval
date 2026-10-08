# Python 源码解析第12章：Celery 与 Cloud Tasks 任务分发

## 模块概览

### 为什么需要异步队列

一次 run 可能包含几十到上百个 case，每个 case 还会访问模型、缓存和数据库。API 如果同步等待：

- 请求容易超时；
- 无法可靠查询进度；
- 进程重启会丢失内存状态；
- API 实例和 Worker 无法独立扩缩。

因此 `/async-runs` 只负责接受、持久化和分发。

## 核心类型

### 抽象接口

```python
class BaseTaskQueue(ABC):
    def enqueue(
        self, run_id, tenant_id="default", trace_id=None
    ) -> str:
        ...
```

队列只接收轻量 ID，不发送 Provider client、完整 case 或密钥。

## 主流程走读

### Worker Webhook

`POST /tasks/execute-run`：

1. 非 cloud mode 返回 403；
2. 校验 OIDC；
3. 检查 `run_id`；
4. 查询 run；
5. 终态返回 skipped；
6. 非终态执行 `run_evaluation_logic()`。

### Trace 传播

API 创建 trace ID，经 task payload 传入 Worker，再进入日志 ContextVar。这样可以将创建请求、队列和 case 日志关联。

## 内置任务队列

### Celery 路径

`CeleryTaskQueue.enqueue()`：

```text
execute_evaluation_run.delay(run_id, tenant_id, trace_id)
→ broker
→ Celery worker
→ run_evaluation_logic()
```

Celery 返回 task ID，`set_task_id()` 写入 `AsyncRun.celery_task_id`。

默认 `LLM_SECURITY_QUEUE_MODE=local` 实际选择 Celery，并不代表进程内直接执行。

### Cloud Tasks 路径

`CloudTasksTaskQueue.enqueue()` 读取：

- `GOOGLE_CLOUD_PROJECT`
- `GOOGLE_CLOUD_LOCATION`
- `LLM_SECURITY_CLOUD_TASKS_QUEUE`
- `LLM_SECURITY_WORKER_SERVICE_URL`
- `LLM_SECURITY_TASKS_SERVICE_ACCOUNT`

构造：

```text
POST {worker_service_url}/tasks/execute-run
```

body 包含 `run_id/tenant_id/trace_id`。

## 关键机制

### OIDC

配置 service account 后，task 附带：

- `service_account_email`
- `audience=service_url`

API 端 `verify_cloud_tasks_oidc()` 负责校验。IAM 是否正确配置仍需要真实云环境证据。

### Task ID 幂等

Cloud task name 使用 `run_id`：

```text
projects/.../queues/.../tasks/{run_id}
```

重复创建触发 `AlreadyExists` 时，代码返回原 task name。这降低重复投递，但不等于整个业务 exactly-once。

## 失败流程与边界条件

### 错误路径

| 错误 | 行为 |
|---|---|
| 缺 project/service URL | enqueue 抛错 |
| Cloud create_task 失败 | 日志 + 上抛 |
| API enqueue 失败 | run 标记失败，返回 503 |
| OIDC 无效 | webhook 拒绝 |
| 重复 task | 返回已有 task name |
| webhook 500 | Cloud Tasks 可按队列策略重试 |

### 选型取舍

Celery 适合 Compose 和传统 Worker；Cloud Tasks 适合 Serverless HTTP Push、无常驻 pull Worker。两条路径共享 run 状态机，但运维模型不同。

## 测试与证据

### 证据

- `tests/test_task_queue.py` 验证选择、payload、OIDC 和 AlreadyExists，Cloud client 被 Mock；
- `stage_5_5_docker_e2e.json` 记录 Celery worker ping；
- Cloud Run/Tasks 真实最新运行状态需单独云日志，仓库中未由单测证明。

## 面试追问

### 为什么队列消息只发送 `run_id`？

完整配置和 case 已先持久化；Worker 可按 `run_id` 恢复，避免序列化 SDK Client、密钥和大消息体。

### Celery 与 Cloud Tasks 的核心差异是什么？

Celery Worker 主动从 broker 拉取，Cloud Tasks 向 HTTP Worker 推送；两者复用同一 run 状态机，但鉴权、重试和运维模型不同。

## 小结

队列抽象让 API 只依赖“可分发 run ID”。可靠性最终仍依赖数据库状态、幂等检查和部署环境。

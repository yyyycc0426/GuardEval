# Python 源码解析总览：LLM/RAG 安全评测平台主链路

> 这篇文档带你读 `proj4` 的核心源码：从用户创建安全评测任务，到异步执行、模型调用、防御策略、Judge 判定、人审、审计、报告和指标生成。它不是升级计划，也不是营销 README，而是一份面试前用来“按源码讲项目”的复习文档。

## 模块概览

LLM 安全评测主链路集中在这些文件里：

| 文件 | 职责 |
|---|---|
| `llm_security_platform/app/api.py` | FastAPI 入口，定义 case、run、async-run、人审、审计、metrics、console 等接口 |
| `llm_security_platform/app/schemas.py` | 请求、响应、检测结果、防御决策、报告等 Pydantic 类型 |
| `llm_security_platform/app/tasks.py` | 异步 Worker 主逻辑，执行 run 和 case |
| `llm_security_platform/app/case_execution.py` | 单个 case 的执行闭环：防御 -> 模型 -> 检测/Judge -> 结果 |
| `llm_security_platform/app/production_store.py` | 异步 run、case result、audit log、tenant config 的持久化 |
| `llm_security_platform/app/task_queue.py` | Celery 与 Cloud Tasks 的调度抽象 |
| `llm_security_platform/app/providers.py` | Mock、Ollama、OpenAI-compatible、Gemini/Vertex 等模型 Provider 适配 |
| `llm_security_platform/app/judge.py` | `LLMJudge` 与 `RuleBackedJudge` |
| `llm_security_platform/app/layered_detection.py` | 规则、语义、Judge、人审的分层判定 |
| `llm_security_platform/policies/policy_engine.py` | input/RAG/output 防御策略编排 |
| `llm_security_platform/policies/input_defense.py` | 输入层防御 |
| `llm_security_platform/policies/rag_defense.py` | RAG 上下文与间接注入防御 |
| `llm_security_platform/policies/output_defense.py` | 输出层脱敏、重写、拦截 |
| `llm_security_platform/app/security.py` | API key、JWT、RBAC、Cloud Tasks OIDC |
| `llm_security_platform/app/middleware.py` | Redis 限流，写路径 fail-closed |
| `llm_security_platform/app/cost_guardrail.py` | run/user/tenant 三层 token budget |
| `llm_security_platform/app/metrics.py` | Prometheus 风格指标导出 |
| `llm_security_platform/web/app.js` | 静态 Console，创建 run、查看报告、查看 case 证据链 |

风格上，这个项目不是把每个概念拆成几十个小文件，而是按“业务闭环”组织：API 管入口，Worker 管执行，Store 管状态，Policy/Provider/Judge 管评测逻辑。

## 核心类型

#### `AttackCaseCreate` 与攻击样本

位置：`llm_security_platform/app/schemas.py`

攻击样本是评测系统的输入。它描述“测什么风险、用什么 prompt、期待什么安全行为”。

典型字段包括：

- `case_id`
- `name`
- `risk_type`
- `prompt`
- `system_prompt`
- `success_indicators`
- `metadata`

对应数据文件：

- `llm_security_platform/data/attack_cases_v2.json`
- `llm_security_platform/data/dataset_manifest.json`

面试时可以这样说：

> 这个项目不是随便写几个 prompt 做 demo，而是把攻击样本、风险类型、成功判定、数据集版本和报告指标串成了可复现评测链路。

#### `EvaluationRunCreate` 与评测请求

位置：`llm_security_platform/app/schemas.py`

`EvaluationRunCreate` 是用户创建一次评测 run 时传入的请求结构。它把“评测谁、用什么模型、开哪些防御、跑哪些 case、并发多少、Judge 用什么”统一起来。

核心字段：

- `name`
- `provider`
- `model`
- `defense_policy`
- `case_ids`
- `concurrency`
- `judge_provider`
- `inference_config`
- `defense_config`
- `versions`

这类结构的价值是：一次评测 run 不只是一条 prompt，而是一组可追踪的实验配置。

#### `DetectorResult`、`DefenseDecision` 与判定结果

位置：

- `llm_security_platform/app/schemas.py`
- `llm_security_platform/policies/base.py`
- `llm_security_platform/policies/policy_engine.py`

`DetectorResult` 表示检测器或 Judge 的判定结果，`DefenseDecision` 表示某一层防御对输入、RAG 或输出做了什么处理。

项目里的防御动作不是简单的 yes/no，而是类似：

- `allow`
- `block`
- `sanitize`
- `rewrite`
- `redact`
- `review`

这使得报告能解释“为什么被拦截、为什么被改写、为什么需要人审”，而不是只给一个黑盒分数。

#### `EvaluationReport` 与报告指标

位置：`llm_security_platform/app/schemas.py`

`EvaluationReport` 是面试里最值得讲的类型之一。它把安全评测结果拆成多维指标：

- `attack_success_rate`
- `raw_model_compromise_rate`
- `delivered_attack_success_rate`
- `false_positive_rate`
- `normal_task_success_rate`
- `p50_latency_ms`
- `p95_latency_ms`
- `total_tokens`
- `estimated_total_cost`
- `review_rate`
- `by_risk_type`
- `by_language`
- `by_attack_method`

最重要的是这两个指标：

| 指标 | 含义 |
|---|---|
| `raw_model_compromise_rate` | 原始模型是否被诱导输出了危险内容 |
| `delivered_attack_success_rate` | 危险内容是否越过防御层，最终交付给用户 |

这两个指标的分离，是项目的核心亮点。

面试时可以这样说：

> 我没有把“模型被诱导”和“用户真的看到危险输出”混在一起，而是拆成 raw compromise 和 delivered ASR。这样能评估防御层到底有没有在模型失守后兜住风险。

#### `ApiResponse` 与统一 API 外壳

位置：`llm_security_platform/app/schemas.py`

API 返回统一包装为：

```python
class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Any = None
```

这样 Console 和测试代码可以统一读取 `success/message/data`，减少前端和 API 的格式分歧。

## 核心数据模型与状态机制

### 两层数据模型

#### 内层：统一评测结构

内层是面向后端逻辑的结构：

```text
AttackCase
EvaluationRunCreate
DefenseDecision
DetectorResult
JudgeDecision
EvaluationResult
EvaluationReport
```

它们解决的是“系统内部怎么理解一次评测”。

#### 外层：API 响应与报告格式

外层是面向前端、接口调用者和报告消费者的结构：

```text
ApiResponse
  ├── success
  ├── message
  └── data
        ├── run
        ├── report
        └── cases
```

这种两层模型的好处是：

- 内部逻辑可以持续演进
- 外部 API 格式保持稳定
- Console 只需要关心统一的 `data`
- 面试时容易解释“存储结构”和“展示结构”分离

### 状态事件模型

这个项目没有做真正的 SSE token streaming，但有清晰的“异步状态事件模型”。面试时不要把它说成流式输出系统，而要说成异步评测状态机。

#### run 状态

常见状态：

- `PENDING`
- `RUNNING`
- `COMPLETED`
- `FAILED`
- `PARTIAL_FAILED`
- `CANCELLED`

这些状态由 `production_store.py` 维护，`tasks.py` 在执行完成后调用 `finalize_run` 统一收口。

#### case 状态

每个 case 独立执行，有自己的状态、尝试次数、结果和错误信息。

这带来的好处是：

- 单 case 失败不会吞掉整个 run
- 可以 retry 未完成或失败 case
- 报告能展示失败比例
- 人审可以定位到具体 case

#### 失败、取消、重试

对应接口：

- `POST /async-runs/{run_id}/cancel`
- `POST /async-runs/{run_id}/retry`

对应测试：

- `llm_security_platform/tests/test_stage_five_store.py`
- `llm_security_platform/tests/test_saas_idempotency_and_metering.py`
- `llm_security_platform/reports/stage_5_6_fault_drill.json`

面试时可以这样说：

> 我没有让异步任务只存在 worker 内存里，而是把 run/case 状态持久化。失败、取消、重试和部分失败都有显式状态，这样前端和报告都能看到系统真实进展。

## 主流程走读

#### 第一步：用户创建异步评测任务

入口：

- `POST /async-runs`
- 函数：`api.py:create_async_evaluation`

用户在 Console 或 API 中提交：

```json
{
  "name": "Security Eval",
  "provider": "mock",
  "model": "mock-vulnerable-model",
  "defense_policy": "baseline",
  "case_ids": [],
  "concurrency": 4,
  "judge_provider": "mock"
}
```

源码逻辑可以概括为：

```python
@app.post("/async-runs", response_model=ApiResponse, status_code=202)
def create_async_evaluation(
    request: EvaluationRunCreate,
    http_request: Request,
    actor=Depends(require_permission("run:create")),
):
    ...
```

这里有两个关键点：

1. `require_permission("run:create")` 说明创建 run 需要权限。
2. 创建 run 不是同步执行模型，而是先落库，再交给队列/Worker。

#### 第二步：构建 run 元数据与幂等锁

位置：`api.py:create_async_evaluation`

创建 run 前，系统会做几件事：

- 检查 token budget
- 限制单次 case 数量
- 根据 `case_ids` 取攻击样本
- 计算 run fingerprint
- 使用 Redis lock 防止重复提交
- 写入 `dataset_version`、`policy_version`、`code_commit_hash`、`model_config`

核心概念：

```python
fingerprint = get_run_fingerprint(request, request.case_ids)
lock_key = f"run_lock:{actor['tenant_id']}:{fingerprint}"
```

这说明项目不是“点一次跑一次”的简单脚本，而是考虑了重复提交、幂等、实验版本和可追溯性。

面试时可以这样说：

> 对批量评测来说，重复提交会浪费模型调用成本，所以我给 run 加了 fingerprint 和 Redis lock；即使队列提交失败，也会把 run 标记失败并释放锁。

#### 第三步：任务入队

位置：

- `api.py:create_async_evaluation`
- `app/task_queue.py`
- `app/async_jobs.py`

创建 run 后，API 调用：

```python
task_id = dispatch_run(
    run["run_id"],
    tenant_id=actor["tenant_id"],
    trace_id=current_trace_id.get()
)
```

`task_queue.py` 把调度方式抽象成两类：

- 本地/Docker：Celery + Redis
- 云端：Google Cloud Tasks + Cloud Run webhook

这是一种“同一业务语义，不同运行环境”的设计。

面试时不要说：

> 我已经完成了生产级云原生平台。

应该说：

> 项目设计了本地 Celery/Redis 和云端 Cloud Tasks 两条执行路径。仓库里能验证代码路径和 smoke 脚本，但长期云端运行需要额外日志证据。

#### 第四步：Worker 执行 case

入口：

- `tasks.py:run_evaluation_logic`
- Celery task：`execute_evaluation_run`

Worker 的主流程：

1. 根据 `run_id` 读取 run 请求
2. 设置 `tenant_id`
3. 构建 Provider
4. 构建 `PolicyEngine`
5. 构建 Judge
6. 拉取 pending cases
7. 按 `concurrency` 分批执行
8. 单 case 成功则 `finish_case`
9. 单 case 失败则记录 error
10. 最后 `finalize_run`
11. 生成报告并上传 GCS 或写入 fallback

核心片段：

```python
def run_evaluation_logic(run_id, tenant_id="default", trace_id=None):
    ...
    request = EvaluationRunCreate.model_validate(payload)
    provider = build_provider(request.provider, request.model, request.inference_config)
    policy_engine = PolicyEngine(request.defense_policy, versions=request.versions, tenant_id=tenant_id)
    ...
```

并发执行片段：

```python
with ThreadPoolExecutor(max_workers=request.concurrency) as executor:
    futures = {
        executor.submit(
            execute_case,
            item["case"],
            provider,
            policy_engine,
            judge,
            run_id=run_id,
            tenant_id=tenant_id,
            user_id=created_by
        ): item
        for item in runnable
    }
```

这里的工程取舍是：模型调用属于 I/O 型长任务，使用线程池能提高批量评测吞吐；数据库状态更新仍通过 store 层处理。

#### 第五步：防御、模型调用与 Judge 判定

位置：

- `case_execution.py:execute_case`
- `policy_engine.py:PolicyEngine`
- `providers.py:build_provider`
- `judge.py:RuleBackedJudge`
- `judge.py:LLMJudge`
- `layered_detection.py:assess_response`

单个 case 的实际顺序可以理解成：

```text
攻击样本
  -> input defense
  -> RAG defense
  -> Provider.generate()
  -> output defense
  -> rule detector
  -> semantic detector
  -> Judge
  -> human review 标记
  -> final outcome
```

重点是：Provider 只负责生成，防御和判定不混在 Provider 里。

这使得同一组攻击样本可以换不同模型、不同防御策略、不同 Judge 进行对比。

#### 第六步：结果落库与报告生成

位置：

- `production_store.py:create_async_run`
- `production_store.py:finish_case`
- `production_store.py:finalize_run`
- `production_store.py:build_async_report`

创建 run 时，会先写入 `AsyncRun`，再为每个 case 创建 `AsyncCaseResult`。

执行过程中，每个 case 都有独立状态。这样单条 case 失败不会让整个 run 静默消失。

run 结束时：

```python
def finalize_run(run_id):
    ...
    if run.cancel_requested:
        run.status = "CANCELLED"
    elif run.failed_cases == 0:
        run.status = "COMPLETED"
    elif run.success_cases == 0:
        run.status = "FAILED"
    else:
        run.status = "PARTIAL_FAILED"
```

这个状态设计非常适合面试讲“可靠性”：

- 全部成功：`COMPLETED`
- 全部失败：`FAILED`
- 部分失败：`PARTIAL_FAILED`
- 用户取消：`CANCELLED`

#### 第七步：Console 查询与证据链展示

位置：

- `api.py:async_run_detail`
- `api.py:export_async_run`
- `web/app.js`

查询接口：

```python
@app.get("/async-runs/{run_id}", response_model=ApiResponse)
def async_run_detail(run_id: str, _actor=Depends(require_permission("run:read"))):
    ...
```

返回内容包括：

- `run`
- `report`
- `cases`

Console 再把 case 的 evidence chain 展示出来：

```text
原始攻击输入
  -> 输入检测结果
  -> 防御动作
  -> 实际模型输入
  -> 原始模型响应
  -> 规则检测结论
  -> 语义检测结论
  -> Judge 结论
  -> 人工复核结论
  -> 最终 Outcome
  -> 审计日志
```

浏览器 E2E 证据：

- `reports/browser_e2e_console_report.json`
- `output/playwright/console_initial.png`
- `output/playwright/console_analyst_cases.png`
- `output/playwright/console_overview_after_run.png`
- `output/playwright/console_current_after_run.png`

其中一次验证结果：

- `status`: `COMPLETED`
- `total_cases`: `113`
- `completed_cases`: `113`
- `failed_cases`: `0`

## 内置安全评测能力

### RAG 泄露检测

RAG 泄露在这个项目里不是“知识库问答”，而是安全评测场景。

相关文件：

- `llm_security_platform/app/rag_context.py`
- `llm_security_platform/policies/rag_defense.py`
- `llm_security_platform/data/attack_cases_v2.json`
- `llm_security_platform/docs/success_criteria.md`

主线是：

```text
恶意 prompt / 间接注入样本
  -> 构造 RAG context
  -> RAG defense 加边界、过滤或标记
  -> 模型生成 raw response
  -> output defense 检查是否泄露
  -> detector / Judge 判断是否攻击成功
```

这里最重要的不是“用了向量数据库”，而是“能不能测出 RAG 应用是否把不该交付的上下文泄露给用户”。

安全表述：

> 项目覆盖 RAG 泄露评测和防御策略对比，但不是完整企业知识库 RAG 问答系统，也不证明覆盖全部 RAG 攻击方式。

### 防御策略对比

相关文件：

- `llm_security_platform/policies/input_defense.py`
- `llm_security_platform/policies/rag_defense.py`
- `llm_security_platform/policies/output_defense.py`
- `llm_security_platform/policies/policy_engine.py`
- `llm_security_platform/reports/stage_four_defense_ablation.json`

策略组合：

- `none`
- `input_defense`
- `rag_defense`
- `output_defense`
- `input_defense+rag_defense`
- `input_defense+output_defense`
- `rag_defense+output_defense`
- `input_defense+rag_defense+output_defense`

这类 ablation 的价值是：不是只说“加了防御”，而是能比较每一层防御对 ASR、FPR、正常任务成功率、延迟和 token 成本的影响。

面试时可以这样说：

> 我把防御拆成 input、RAG、output 三层，然后做策略组合对比。这样能看出到底是哪一层在降低 delivered ASR，哪一层可能带来误杀。

## 安全、成本与可观测性

### RBAC、租户与审计

#### RBAC

位置：`llm_security_platform/app/security.py`

核心角色：

```python
ROLE_PERMISSIONS = {
    "viewer": {"run:read"},
    "analyst": {"run:read", "run:create", "run:cancel", "run:retry", "case:read"},
    "reviewer": {"run:read", "audit:read", "review:read", "review:write", "case:read"},
    "admin": {"*"},
}
```

含义：

- `viewer`：只能看 run
- `analyst`：能创建、取消、重试 run
- `reviewer`：能看审计和处理人审
- `admin`：全权限

浏览器验证里，`analyst-key` 查询 run 详情成功，但访问 `/audit-logs` 返回 403，说明 RBAC 边界生效。

证据文件：

- `reports/browser_e2e_console_report.json`

#### 租户隔离

位置：`production_store.py:session_scope`

系统通过 `current_tenant` 保存当前租户上下文，并在查询时带 `tenant_id` 过滤。PostgreSQL 路径还使用 `SET LOCAL search_path` 做 schema routing。

面试安全表述：

> 当前租户隔离适合内部试点和工程演示，不应说成完整 SaaS 合规或物理级隔离。

#### 审计日志

位置：

- `production_store.py:save_audit`
- `api.py:audit_logs`

审计日志记录谁对哪个 run 做了什么操作，支撑安全追责和面试证据链。

### 成本、指标与可观测性

#### token budget

位置：`llm_security_platform/app/cost_guardrail.py`

预算分三层：

- run 级
- user 级
- tenant 级

为什么需要：

> LLM 安全评测是批量调用模型的任务，如果没有预算和限流，一个错误配置或重复提交就可能造成成本失控。

#### Prometheus 指标

位置：`llm_security_platform/app/metrics.py`

导出指标包括：

- `raw_model_compromise_rate`
- `delivered_attack_success_rate`
- `false_positive_rate`
- token usage
- human review metrics

接口：

- `GET /metrics`

注意：`/metrics` 需要权限，不能当成匿名公开监控入口来讲。

## 部署与证据边界

### Docker、Cloud Tasks 与部署边界

#### Docker Compose

证据：

- `llm_security_platform/docker-compose.yml`
- `llm_security_platform/reports/stage_5_5_docker_e2e.json`
- `docs/interview_evidence_package.md`

可以讲：

> 项目提供 Docker Compose 路径，用于本地启动 PostgreSQL、Redis、API、worker、Prometheus/Grafana 等组件。

#### Cloud Tasks

证据：

- `llm_security_platform/app/task_queue.py`
- `api.py:execute_run_task`
- `security.py:verify_cloud_tasks_oidc`
- `docs/cloud_e2e_smoke_test.md`
- `docs/cloud_release_runbook.md`

Cloud Tasks webhook 不是裸奔的。`execute_run_task` 里会检查：

```python
queue_mode = os.environ.get("LLM_SECURITY_QUEUE_MODE", "local").lower()
if queue_mode != "cloud":
    raise HTTPException(status_code=403, ...)

verify_cloud_tasks_oidc(authorization)
```

边界：

> 仓库能证明 Cloud Tasks 路径有代码、OIDC 校验、runbook 和 smoke 脚本；不能证明长期云端生产稳定运行。

## 失败流程与边界条件

### 错误分类

面试中可以把错误分成几类讲：

| 类型 | 例子 | 项目中的处理 |
|---|---|---|
| 鉴权错误 | 缺少 API key、权限不足 | 401/403，`require_permission` |
| 参数错误 | case 为空、case 数超限 | 400 |
| 重复提交 | 相同 fingerprint 的 run 正在执行 | 409 |
| 队列错误 | Celery/Cloud Tasks 不可用 | run 标记失败，返回 503 |
| 单 case 执行失败 | 模型超时、Provider 报错 | case 标记 failed，run 可进入 `PARTIAL_FAILED` |
| 成本超限 | token budget exceeded | 取消剩余任务或拒绝创建 |
| Redis 故障 | 限流系统不可用 | 写路径 fail-closed，读路径 fallback |

## 面试追问

### 面试追问点

#### 1. 为什么不是同步 HTTP 直接跑？

因为批量安全评测包含大量模型调用，可能耗时、失败、超限或需要取消。同步 HTTP 会导致请求超时、状态不可见、无法恢复。异步 run 能让 API 快速返回 `run_id`，Worker 后台执行，用户通过 `/async-runs/{run_id}` 查询状态。

#### 2. 为什么要区分 raw ASR 和 delivered ASR？

raw ASR 反映模型本身是否被诱导；delivered ASR 反映最终危险内容是否穿过防御交付给用户。安全平台真正关心的是二者差异：模型可能失守，但输出层仍可能兜住风险。

#### 3. Judge 为什么不能全信？

Judge 本身也是模型或规则系统，会误判。项目引入 human review、confidence、evidence chain，是为了避免把 Judge 结论包装成绝对真相。

#### 4. RAG 防御是不是能防住所有间接注入？

不能。RAG defense 可以降低已知场景下的泄露风险，比如边界隔离、敏感字段过滤、输出检查，但不能保证覆盖所有未知攻击。

#### 5. 为什么需要 token budget？

LLM 评测任务天然可能烧 token。预算控制可以限制单 run、单 user、单 tenant 的最大消耗，避免重复提交或异常任务造成成本失控。

#### 6. Cloud Tasks 路径是否生产可用？

代码上有 Cloud Tasks push、OIDC 校验、runbook 和 smoke 脚本；但如果没有最新 Cloud Logging、GCS 对象、Cloud Run revision 等证据，就只能说“具备云端部署路径”，不能说“长期生产稳定运行”。

## 小结

这个项目的主线不是“我会调 LLM API”，而是：

```text
攻击样本
  -> 异步评测任务
  -> 模型 Provider
  -> 防御策略
  -> 检测/Judge
  -> 人审/审计
  -> 指标报告
  -> Console 展示
```

最值得展示的能力是：

- LLM/RAG 安全评测闭环
- 异步任务与失败状态建模
- raw/delivered 安全指标分离
- 防御策略 ablation
- RBAC、审计、租户、预算
- 测试、E2E、报告证据链

最需要克制的边界是：

- 不是生产级安全网关
- 不是通用 Agent Runtime
- 不是完整企业知识库 RAG 系统
- 不承诺 100% 防御
- 不宣称真实 ROI 或长期云端稳定性

一句面试收尾：

> 这个项目本质上是把 LLM/RAG 安全评测从“人工试 prompt”工程化成“可复现、可审计、可比较、可部署”的后端系统。它当前适合作为内部试点级评测平台展示，而不是包装成生产级安全产品。

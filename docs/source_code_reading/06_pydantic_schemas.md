# Python 源码解析第6章：Pydantic Schema 与统一数据协议

## 模块概览

`app/schemas.py` 定义系统跨层传递的数据契约。它的作用不是“写几个请求类”，而是限制评测配置、统一检测结果，并让 API 文档与运行时校验一致。

## 核心类型

### 基础枚举

```python
RiskType = Literal[
    "prompt_injection", "jailbreak",
    "rag_data_leakage", "benign",
]
DefenseAction = Literal[
    "allow", "block", "sanitize",
    "rewrite", "redact", "review",
]
```

`Literal` 在进入业务层前拒绝未知值，避免任意字符串改变分支。

### `AttackCaseCreate`

核心字段：

- `case_id`：稳定标识；
- `name`：展示名称；
- `risk_type`：风险类别；
- `prompt`、`system_prompt`；
- `success_indicators`；
- `safe_response_indicators`；
- `metadata`。

`case_id` 有长度边界，`prompt` 不允许为空。复杂 metadata 仍需要数据集校验补充语义约束。

### `EvaluationRunCreate`

它是一次评测的配置总表：

- `provider`
- `model`
- `defense_policy`
- `case_ids`
- `versions`
- `inference_config`
- `defense_config`
- `judge_provider`
- `concurrency`

`concurrency` 被限制在 1～8，避免客户端直接请求极端线程数。

`inference_config` 使用 alias `model_config`，兼容外部字段名，同时通过 `populate_by_name=True` 支持内部名称。

### Provider Schema 边界

当前 run Schema 允许 `mock`、`ollama`、`openai_compatible`；`providers.py` 工厂还实现 `vertexai` 和 `gemini`。因此后两者属于代码适配存在，但并非当前默认 run API Schema 已开放的同等级能力。

### 检测结果类型

#### `DetectorResult`

统一规则、语义和 Judge finding：

- detector/version；
- input/response scope；
- risk type；
- risk score；
- confidence；
- evidence；
- decision；
- metadata。

#### `DetectorDecision`

面向最终 case 结果：

- 输入和输出信号；
- `attack_success`；
- `outcome_label`；
- `business_completed`。

两个类型的职责不同：前者是检测器协议，后者是面向业务报告的汇总判定。

### `JudgeDecision`

继承 `DetectorResult` 并设置：

```python
model_config = ConfigDict(extra="forbid")
```

额外要求：

- `attack_success`
- `outcome`
- `evidence_quotes`
- `reason`
- `needs_human_review`

禁止额外字段能更快暴露 LLM JSON 输出漂移。

### `LayeredAssessment`

保存：

- input rule finding；
- response rule finding；
- semantic finding；
- Judge decision；
- conflicts；
- review reasons；
- final outcome。

它不是简单覆盖 Judge，而是把多层证据并列保存。

### `DefenseDecision`

重要字段：

- policy name/version；
- enabled；
- action/risk level；
- reason/evidence；
- before/after；
- latency；
- audit ID；
- metadata。

`before/after` 让策略改写可追溯，但也意味着存储层必须注意敏感原文访问权限。

### `EvaluationResult` 与 `EvaluationReport`

`EvaluationResult` 表示单 case；`EvaluationReport` 表示 run 聚合。报告同时包含攻击、安全、可用性、性能和成本指标。

### `ApiResponse`

统一 `success/message/data`，便于 Console 和脚本消费。HTTP 状态码仍必须表达协议语义，不能只依赖 `success`。

## 主流程走读

### 正常与失败路径

- 类型或范围错误：Pydantic 422；
- 不支持的 Provider：在 Schema 或工厂被拒绝；
- Judge 返回额外字段：结构校验失败；
- risk score 超出 0～1：字段校验失败；
- metadata 内部内容：需要业务代码继续验证。

## 测试与证据

### 测试证据

- `tests/test_detector_protocol.py`
- `tests/test_api.py`
- `tests/test_dataset.py`
- `tests/test_model_comparison.py`

## 面试追问

### 面试回答

> Schema 层的价值是把“评测配置”和“安全判定结果”变成稳定协议。Provider、Judge、Policy 和报告可以独立演进，但跨层字段由 Pydantic 约束。

## 小结

Schema 是平台的语言边界。它减少非法配置，但不能替代 tenant 授权、数据集语义验证和敏感字段访问控制。

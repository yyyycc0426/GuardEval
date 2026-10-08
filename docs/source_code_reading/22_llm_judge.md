# Python 源码解析第22章：LLM Judge 与结构化裁判

## 模块概览

### Judge 的职责

Judge 判断某个响应是否满足攻击成功条件。它与被测 Provider 分离，避免生成模型直接决定自己的安全性。

## 核心类型

### `JudgeDecision`

关键字段：

- `attack_success`
- `outcome`
- `confidence`
- `evidence_quotes`
- `reason`
- `needs_human_review`
- `raw_response`

`extra="forbid"` 防止 LLM 任意增加字段。

## 主流程走读

### Prompt 构造

`judge.py:build_judge_prompt(case, model_response)` 将：

- case 风险类型；
- 成功标准；
- 模型响应；
- 输出 Schema；

组织成裁判请求。

### 不可信边界

被测响应可能包含“忽略裁判指令”等文本，因此应作为不可信 evidence 包装，而不是拼接到 Judge system instruction 中。

`tests/test_judge.py` 检查 Prompt builder 没有把证据合并进系统指令。

## 内置 Judge

### `LLMJudge`

调用独立 Provider，获取文本后：

1. `_extract_json()`；
2. 解析 JSON；
3. 构造 `JudgeDecision`；
4. 校验证据和 outcome；
5. 必要时标记 review。

### `RuleBackedJudge`

使用确定性规则生成同一协议，适合：

- 单元测试；
- Mock E2E；
- 无外部模型环境；
- 基线对比。

它不具备真正的复杂语义推理能力。

## 关键机制

### Evidence Quotes

如果判定攻击成功却没有具体引用，系统不能把它当高置信真值。测试要求这类结果进入复核。

## 失败流程与边界条件

### JSON 提取风险

LLM 可能返回：

- Markdown code fence；
- JSON 前后解释；
- 非法引号；
- 缺字段；
- 额外字段；
- 与 evidence 不一致的结论。

解析失败应被记录，不能默认判安全。

### Judge Provider

run 配置：

- `disabled`
- `mock`
- `ollama`
- `openai_compatible`

被测模型和 Judge 使用同模型时可能有相关偏差；独立 Judge 也不等于客观真值。

### 成本与延迟

LLM Judge 会为每个 case 增加调用、token 和延迟。可以通过规则预筛、人审抽样或批处理降低成本，但当前实现的具体策略以代码为准。

### Judge 与人工

Judge-human agreement 只对已经复核的样本有效，不能外推到全部数据。

## 测试与证据

### 测试

- `tests/test_judge.py`
- `tests/test_detector_protocol.py`
- `reports/stage_three_judge_benchmark.json`

## 面试追问

### 面试回答

> Judge 输出必须结构化、带 evidence quotes。无证据的成功判定不会被直接接受，而会进入人工复核；因此我把 Judge 当一层检测器，不当绝对真值。

## 小结

LLM Judge 提升语义覆盖，但引入模型偏差、成本和 Prompt Injection 风险。结构化协议、证据引用和人审是其可信度边界。

# Python 源码解析第1章：初识 LLM/RAG 安全评测平台

> 本章先回答“谁用、为什么用、输入输出是什么、如何衡量有效”。项目应定位为内部、可复现的 LLM/RAG 安全评测与防御对比平台，不是生产流量网关，也不承诺消除越狱。

## 模块概览

| 关注点 | 仓库证据 |
|---|---|
| 项目入口 | `README.md` |
| 成功标准 | `llm_security_platform/docs/success_criteria.md` |
| 攻击范围 | `llm_security_platform/docs/threat_model.md` |
| 主 API | `llm_security_platform/app/api.py` |
| 执行链 | `app/tasks.py:run_evaluation_logic`、`app/case_execution.py:execute_case` |
| 证据索引 | `docs/interview_evidence_package.md` |

### 一句话定位

> 面向 AI 平台、安全测试和模型应用研发人员，对 LLM/RAG 应用批量执行 Prompt Injection、Jailbreak、RAG 泄露等攻击用例，对比防御前后的风险、误拦、延迟与成本，并保留可审计证据链。

这句话包含四个必要元素：

- 谁用：AI 平台、安全测试、LLM 应用研发人员；
- 为什么用：发现模型应用在受控攻击集上的暴露面；
- 怎么用：创建评测 run，批量执行攻击 case 和防御策略；
- 如何判断有效：比较 raw compromise、Delivered ASR、误报、正常任务成功率、失败率、延迟和成本。

## 核心输入与输出

### 系统输入

一次评测的主要输入由 `EvaluationRunCreate` 描述：

- `provider` 与 `model`；
- `case_ids`；
- `defense_policy`；
- `judge_provider`；
- `concurrency`；
- `inference_config`；
- `versions`。

攻击样本由 `AttackCaseCreate` 描述，包含风险类型、Prompt、System Prompt、攻击成功指示器和元数据。

### 系统输出

输出不是一段聊天文本，而是：

- run 状态与进度；
- 每个 case 的原始响应和交付响应；
- 输入、响应、Judge 判定；
- 防御决策与审计 ID；
- 人工复核标记；
- token、成本和延迟；
- 汇总报告和导出 JSON。

## 主流程走读

### 没有系统时

人工红队通常面临：

1. 攻击 Prompt 分散，难以版本化；
2. 每个模型和策略的执行条件不一致；
3. 只保存“看起来被攻破”的截图；
4. 失败样本、良性误拦和成本没有统一统计；
5. 无法追溯 Provider、模型配置、数据集和代码版本。

### 使用系统后

```text
选择数据集和模型
→ 创建评测 run
→ 异步执行 case
→ 输入/RAG/输出防御
→ Detector 与 Judge 判定
→ 必要时人工复核
→ 结果持久化
→ 查询、对比、导出报告
```

平台改进的是评测的可复现性、结构化和审计性，不等于已经证明真实业务 ROI。

## 指标与证据

### 成功标准

需要同时观察攻击面和业务可用性：

| 指标 | 含义 |
|---|---|
| `raw_model_compromise_rate` | 原始模型响应被判为失陷的比例 |
| `delivered_attack_success_rate` | 最终交付响应仍不安全的比例 |
| `false_positive_rate` | 良性请求被错误拦截的比例 |
| `normal_task_success_rate` | 良性请求完成预期任务的比例 |
| `failure_rate` | 执行失败 case 占比 |
| `p95_latency_ms` | 长尾延迟 |
| `estimated_total_cost` | 估算模型调用成本 |
| `review_rate` | 进入人工复核的比例 |

零 Delivered ASR 如果伴随大量误拦，不能视为好防御。

### 证据等级

- 代码存在：说明设计和实现可读；
- 自动化测试：说明被测试行为在测试条件下通过；
- Mock run：说明流程可重复，不代表真实模型安全效果；
- 浏览器 E2E：说明 UI 到异步报告链路在记录环境中跑通；
- Docker E2E：说明独立 API/Worker/PostgreSQL/Redis 边界在产物记录中跑通；
- 真实模型 benchmark：只能说明指定模型、数据集和配置；
- 真实用户效果：仓库中未验证。

## 失败流程与边界条件

### 项目明确不做什么

- 不作为生产请求的实时安全代理；
- 不保证拦截全部越狱或提示注入；
- 不替代人工红队和业务风险判断；
- 不证明所有外部模型都已真实运行；
- 不声称 Cloud Run/Cloud Tasks 已长期稳定运营；
- 不属于 Agent Runtime、MCP 或多 Agent 框架；
- 不具备真实客户、付费转化或 ROI 证据。

## 面试追问

### 面试表达

可以说：

> 我重点解决的不是“再写一个聊天接口”，而是把攻击样本、模型调用、防御策略、Judge、人审和报告串成可复现的评测闭环。

避免说：

> 这是企业级生产安全平台，能够防住所有越狱。

## 小结

这个项目最有价值的身份是“LLM 应用安全评测与 AgentOps/LLMOps 后端工程项目”。后续章节会分别展开 API、数据集、Provider、异步 Worker、防御、Judge、可靠性和证据边界。

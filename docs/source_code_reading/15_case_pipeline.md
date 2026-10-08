# Python 源码解析第15章：单个 Case 的安全执行流水线

## 模块概览

### 入口

```python
execute_case(
    case,
    provider,
    policy_engine,
    judge=None,
    run_id=None,
    tenant_id="default",
    user_id="system",
)
```

它是项目最重要的业务函数。

## 核心类型

### 构建上下文

`DefenseContext` 保存：

- case；
- system prompt；
- user prompt；
- retrieved documents；
- response text。

RAG 文档通过 `retrieved_documents_for_case()` 获取。

## 主流程走读

### 模型前防御

`policy_engine.before_model()`：

- input defense；
- RAG defense；
- baseline hardening；
- block/rewrite/review；
- 生成 `DefenseDecision`。

若 blocked，不调用 Provider，直接返回配置化拦截响应。

### 预算预占

有 run ID 时：

1. 检查当前预算；
2. 预占每 case token；
3. 模型返回后以实际 token 对账；
4. 异常时 `finally` 释放未使用量。

## 内置执行组件

### Semantic Cache

缓存 key 包含 tenant、Provider、model、policy 和 Prompt。命中后复用 `ModelCallResult` 并标记 `semantic_cache_hit`。

安全评测使用缓存可能影响真实延迟和独立调用统计，因此报告解读需说明缓存条件。

### Circuit Breaker

调用前检查 model breaker。OPEN 时快速失败，不继续压垮 Provider。

`build_provider()` 还会套 Provider wrapper breaker，属于两层保护；面试时应说明这是当前实现而非通用最佳实践。

### Provider 调用

```python
call = provider.generate(
    defense.system_prompt,
    defense.user_prompt,
)
```

原始文本保存为 `raw_response_text`。

### 模型后防御

`policy_engine.after_model()` 可能：

- redact secret；
- rewrite attack marker；
- 标记 review；
- 生成额外审计决策。

最终文本保存为 `response_text`。

### 双重检测

```text
raw_detector = 检查模型原始响应
detector = 检查最终交付响应
```

这支持分别计算 raw compromise 和 Delivered ASR。

### Judge

- `judge=False`：禁用；
- 显式 Judge：使用配置对象；
- `None`：回退 `RuleBackedJudge`。

Judge通常查看原始响应，避免输出防御把攻击证据抹掉。

## 关键机制

### Evidence Chain

返回结构包含：

- input detection；
- defense decisions；
- effective model input；
- raw model response；
- rule detection；
- semantic status；
- Judge result；
- human review slot；
- final outcome。

## 失败流程与边界条件

### Blocked 路径

不调用模型，token/cost 为 0，仍执行最终检测并保存防御决策。

### Failed 路径

当前函数对 CircuitBreaker open 做明确 failed 响应；其他 Provider 异常可能上抛到 Worker，由 Worker 标记 case FAILED。

失败不能计为安全回答。

### 安全与隐私边界

保存 raw Prompt、有效 Prompt 和原始响应有审计价值，也增加敏感数据存储风险。访问控制和保留策略必须与部署环境配套。

## 测试与证据

### 测试

- `tests/test_evaluator.py`
- `tests/test_defense_policies.py`
- `tests/test_cost_guardrail.py`
- `tests/test_qdrant_cache.py`

## 面试追问

### 面试回答

> 单 case 不是简单调用模型。我先执行输入/RAG 防御，再做预算和缓存检查，调用 Provider 后执行输出防御，最后同时判定原始响应和交付响应，并保存证据链。

## 小结

`execute_case()` 把安全性、成本、可靠性和可审计性放在同一条确定性流水线中，是整个项目最值得熟练讲解的函数。

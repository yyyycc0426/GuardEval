# Python 源码解析第26章：语义缓存、熔断器与成本护栏

## 模块概览

### 为什么放在同一章

三者都控制模型调用资源：

- Cache 减少重复调用；
- Circuit Breaker 阻止持续访问故障 Provider；
- Budget 防止 run/user/tenant 无限消耗 token。

它们优化的目标不同，不能互相替代。

## 核心类型

### Semantic Cache

`app/semantic_cache.py:SemanticCache` 以：

- tenant；
- Provider；
- model；
- defense policy；
- system/user Prompt；

构造隔离空间。

### Embedder

`get_embedder()` 获取向量模型；Qdrant 或 Mock client 保存向量与结果。测试环境可使用 MockQdrantClient。

## 主流程走读

### Cache Lookup

命中后返回 `ModelCallResult`，并在 metadata 标记 `semantic_cache_hit=True`。

### Cache Store

模型成功返回后保存。失败、空响应或不稳定结果不应被当作正常缓存，具体行为以实现和测试为准。

## 内置资源保护

### Circuit Breaker

`CircuitBreaker` 维护：

- failure count；
- failure threshold；
- opened time；
- recovery timeout。

### 状态

```text
CLOSED：允许请求
→ 连续失败
OPEN：快速拒绝
→ recovery timeout
HALF-OPEN式试探/恢复
→ 成功后关闭
```

具体类是否显式命名 HALF_OPEN 以源码为准。

### 两层熔断

- `CircuitBreakerProviderWrapper` 按 Provider/model；
- `case_execution.py` 的 `model_breaker` 按模型调用路径。

双层能快速保护，但也增加状态理解复杂度，不能笼统称为统一熔断平台。

## 成本控制机制

### Cost Guardrail

`check_and_record_usage(tenant_id, user_id, run_id, tokens_count)` 检查：

- run budget；
- user daily budget；
- tenant daily budget。

### Token 预占

调用前预占 `PRE_ALLOCATED_TOKENS`，避免多个并发 case 同时看到剩余预算后全部发出请求。

调用后：

```text
actual - preallocated
```

做增量对账；异常时在 finally 释放。

### Redis 与数据库

Redis 提供快速计数；tenant/user daily 使用还可从数据库加载并同步。Redis 故障下的精确一致性取决于 fallback 实现，不能声称强事务预算。

### Budget Exceeded

抛出 `BudgetExceededError`，API 可返回 402；Worker case 捕获到预算超限后请求取消 run。

### 估算成本

Provider 根据 token 和配置费率计算 `estimated_cost`。它不含缓存、免费额度、动态价格、网络或基础设施成本。

## 失败流程与边界条件

### 安全风险

- 跨 tenant key 冲突；
- defense policy 变化但 key 未变化；
- 相似 Prompt 语义不同；
- 缓存中包含敏感响应；
- benchmark 延迟被缓存污染；
- Provider/model 升级后旧结果过期。

## 测试与证据

### 测试

- `tests/test_qdrant_cache.py`
- `tests/test_cost_guardrail.py`
- `tests/test_saas_idempotency_and_metering.py`
- `tests/test_advanced_upgrades.py`

## 面试追问

### 面试回答

> 我在并发调用前做 token 预占，结束后按实际 usage 对账；重复 Prompt 可走 tenant/policy 隔离的语义缓存，连续 Provider 故障由熔断器快速失败。

## 小结

资源保护必须同时考虑正确性：缓存不能串租户，熔断失败不能计作安全，预算超限不能留下永久预占。

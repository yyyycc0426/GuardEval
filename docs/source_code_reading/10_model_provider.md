# Python 源码解析第10章：模型 Provider 抽象与适配器

## 模块概览

### 核心接口

`app/providers.py` 定义：

```python
class ModelProvider(ABC):
    @abstractmethod
    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> ModelCallResult:
        ...
```

上层 `execute_case()` 不直接依赖具体 SDK。

## 核心类型

### `ModelCallResult`

统一返回：

- `response_text`
- `token_usage`
- `estimated_cost`
- `provider_metadata`

这样报告、预算和缓存不需要了解 OpenAI、Ollama 或 Gemini 的原始响应对象。

## 主流程走读

### Provider 工厂

`build_provider()`：

1. 复制 model config；
2. 移除 `_tenant_keys`；
3. 选择实现；
4. 注入 base URL/API key；
5. 包装 `CircuitBreakerProviderWrapper`。

显式分支便于审计；新增 Provider 需要同步修改工厂、Schema、配置和测试。

## 内置 Provider

### `MockProvider`

用途：

- 可重复演示；
- 指定攻击 marker；
- 模拟 timeout；
- 模拟单 case failure；
- 生成稳定 token usage。

它证明评测流程，不证明真实模型的越狱表现。

### `OllamaProvider`

调用：

```text
POST {base_url}/api/chat
```

使用非流式响应，传入 system/user messages、temperature、top_p、seed、num_predict 和 timeout。空文本或 HTTP 异常转换成 `ModelProviderError`。

### `OpenAICompatibleProvider`

使用 OpenAI SDK 的 `chat.completions.create()`，支持自定义 base URL。根据模型名选择通用 OpenAI-compatible 或 SiliconFlow 配置。

成本由输入/输出每百万 token 单价估算，不等于账单结算。

### `GeminiProvider`

支持 Developer API key 和 Vertex mode。对部分 `429/5xx/UNAVAILABLE` 做有上限退避；2.5 模型可关闭 thinking budget，避免短分类任务只产生隐藏推理而无文本。

### `VertexAIProvider`

直接使用 Vertex SDK 和 ADC。实现存在，但当前 `EvaluationRunCreate` 默认 Schema 未开放 `vertexai` 选择值，因此证据等级低于默认 API Provider。

## 关键机制

### Token 归一化

不同 SDK 的 usage 字段被转换为：

```python
{
    "prompt_tokens": ...,
    "completion_tokens": ...,
    "total_tokens": ...,
}
```

某些 Provider 无法提供 usage 时可能为 0，不能把 0 误解为没有成本。

### Provider Metadata

可包含：

- response ID；
- latency；
- finish reason；
- SDK duration；
- cache hit；
- circuit breaker fallback。

这些字段是辅助证据，不保证各 Provider 完全一致。

## 失败流程与边界条件

### 异常策略

- 配置缺 key：初始化失败；
- 网络或 SDK 异常：`ModelProviderError`；
- 空响应：失败；
- Gemini 瞬态错误：有限重试；
- 连续失败：熔断；
- 单 case 失败：由 Worker 隔离。

### 选型取舍

| 方案 | 优点 | 代价 |
|---|---|---|
| 自定义接口 | 轻量、可控 | 功能少于 LangChain |
| OpenAI-compatible | 覆盖多服务 | 供应商扩展字段不统一 |
| Mock | 可重复 | 不代表真实模型 |
| Ollama | 本地隐私 | 依赖本地模型和硬件 |

## 测试与证据

### 测试证据

- `tests/test_evaluator.py`
- `tests/test_ollama_config.py`
- `tests/test_real_model_ablation.py`
- `reports/stage_4_5_real_model_ablation.json`

真实模型报告必须同时说明 model、dataset、policy、Judge 和运行日期。

## 面试追问

### 为什么不用 LangChain 的统一模型接口？

当前调用面较小，自定义 `ModelProvider` 更轻量，也能明确控制 token、成本、异常和 metadata；代价是需要自行维护 Provider 适配。

### Mock Provider 能证明什么？

它能证明评测链路、状态、指标和失败处理可重复，不能证明真实模型的安全效果。

## 小结

Provider 层的核心价值是把供应商差异压缩到统一调用和结果协议，同时保留 token、成本和元数据用于评测。

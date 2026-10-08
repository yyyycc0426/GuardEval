# Python 源码解析第2章：Prompt Injection、Jailbreak 与 RAG 泄露

## 模块概览

### 本章目标

理解项目到底在测什么，以及为什么“模型拒答”“模型原始失陷”“最终交付安全”是三个不同概念。

## 核心类型

### 核心风险类型

`app/schemas.py` 将主风险类型限制为：

```python
RiskType = Literal[
    "prompt_injection",
    "jailbreak",
    "rag_data_leakage",
    "benign",
]
```

`benign` 不是攻击，而是误报和业务可用性的对照组。

## 主流程走读

### 攻击是否成功

项目 outcome 包含：

- `safe_answer`
- `refuse`
- `partial_leak`
- `full_leak`
- `tool_abuse`
- `unclear`

判定需要结合：

- 成功指示器；
- 明确拒答；
- 规则 finding；
- Judge evidence；
- 必要时人工标签。

## 内置攻击类型

### Prompt Injection

提示注入是攻击者通过输入改变模型原有指令层级或目标。项目中常见信号包括：

- “ignore previous instructions”；
- 请求展示 System Prompt；
- 伪造 developer/system 指令；
- 编码、Unicode、同形字符混淆；
- 在 RAG 文档中嵌入命令。

检测入口：

- `app/detectors.py:detect_input_risk`
- `app/detectors.py:rule_detect_input`
- `policies/input_defense.py:InputDefense.apply`

### Jailbreak

Jailbreak 更强调绕过模型原有安全约束，例如角色扮演、developer mode 或渐进诱导。它可以借助提示注入实现，但二者不完全相同。

项目用 `success_indicators`、拒答识别和 Judge 共同判断是否成功，而不是只看是否出现某个敏感词。

### System Prompt 泄露

攻击目标是让模型复述内部指令。项目同时保存：

- 输入攻击信号；
- 原始模型响应；
- 输出防御后的响应；
- evidence quotes；
- 最终 outcome。

如果原始响应泄露，但输出防御已脱敏：

```text
raw compromise = true
delivered attack success = false
```

这不能说明模型本身安全，只说明最后一道防线降低了用户暴露。

### RAG 数据泄露

RAG 风险包括：

1. 检索到无权限文档；
2. 文档包含恶意指令；
3. 模型复述秘密或 Canary；
4. 检索内容与用户权限不一致；
5. 输出防御没有清理敏感字段。

相关实现：

- `app/rag_context.py`
- `policies/rag_defense.py`
- `policies/output_defense.py`
- `tests/test_rag_benchmark_v3.py`

### 间接提示注入

直接注入来自用户 Prompt；间接注入来自被检索网页、文件或知识库记录。`RAGDefense` 将文档视为不可信数据，过滤 denied document，并移除文档内命令。

这是一种启发式缓解，不是形式化隔离。模型仍可能被未覆盖的自然语言模式诱导。

### 编码与混淆攻击

Mock Provider 和检测器包含 Unicode 规范化、同形字符和编码标志处理，用于构造可重复测试。此类测试证明规则覆盖了指定变体，不证明覆盖所有编码攻击。

### 多轮渐进攻击

`app/crescendo.py:CrescendoOrchestrator` 表示自适应多轮攻击轨道。它属于扩展评测能力，不是默认 `/async-runs` 主流程中的每个 case 都会自动执行的通用 Agent Loop。

## 失败流程与边界条件

### 失败样本如何计算

Provider 调用失败不应默认为“防御成功”。报告需要单独显示 `failure_rate`，否则可以通过让所有请求报错制造虚假的零 ASR。

### 为什么不存在绝对防御

- 自然语言攻击空间开放；
- 外部模型版本会变化；
- Judge 也会误判；
- RAG 数据源和权限系统可能变化；
- 规则和 benchmark 只能覆盖已知分布；
- 输出脱敏会损害正常任务。

## 测试与证据

### 测试证据

| 测试 | 能证明什么 |
|---|---|
| `tests/test_detectors.py` | 指定规则和结果协议 |
| `tests/test_defense_policies.py` | 指定输入/RAG/输出防御行为 |
| `tests/test_crescendo.py` | 自适应攻击编排逻辑 |
| `tests/test_rag_benchmark_v3.py` | 指定 RAG 数据集上的评测行为 |

## 面试追问

**问：为什么不能只看攻击成功率？**

答：必须同时看原始模型妥协、最终交付攻击成功、良性误拦、正常任务成功和执行失败。单一 ASR 容易掩盖全拦截或全失败。

## 小结

项目测的是“模型应用在指定攻击集和防御配置下的风险表现”，不是给模型发一个 Prompt 后凭感觉判断安全。

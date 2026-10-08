# Python 源码解析第16章：PolicyEngine 防御策略编排

## 模块概览

### 核心抽象

`policies/base.py` 定义：

- `DefenseContext`
- `DefensePolicy`

每个策略实现 `apply(context) -> DefenseDecision`。

### 为什么需要编排器

输入、RAG 和输出防御的运行阶段不同。如果调用方任意改变顺序，可能在模型调用后才清理输入，或者在模型调用前尝试清理不存在的输出。

### 固定顺序

```python
POLICY_ORDER = (
    "input_defense",
    "rag_defense",
    "output_defense",
)
```

`parse_policy_bundle()` 支持 `+` 或 `,`，拒绝未知策略，并按固定顺序重新排列。

### Bundle

典型配置：

```text
none
baseline
input_defense+rag_defense+output_defense
```

`none` 表示不启用防御，但仍会执行检测和报告。

### Policy 加载

`_load_policy(name, version)`：

1. 按 tenant/name/version 查询数据库；
2. 读取 policy config；
3. 显式构造 Input/RAG/Output Policy；
4. 未找到数据库记录时使用代码默认配置。

显式分支便于审计，但不是动态插件系统。

## 核心类型

### `DefenseExecution`

在策略间传递：

- system prompt；
- user prompt；
- response text；
- blocked；
- review required；
- decisions。

## 主流程走读

### `before_model()`

依次执行 input 和 RAG：

- append decision；
- 应用 system prompt suffix；
- 用 `after` 更新 user prompt；
- block 后停止；
- review 标记累积。

若有文档但未启用 RAG defense，仍用 `render_untrusted_documents()` 拼接原始上下文。

### `after_model()`

只执行 output defense：

- 读取 `context.response_text`；
- 应用 redact/rewrite；
- 标记 review；
- 必要时追加 `human_review_router` 决策。

## 内置防御策略

### Baseline

`_baseline()` 使用规则风险分数、阈值和 hardened suffix。它是兼容旧版比较的基线，不与三层策略完全等价。

## 关键机制

### 策略审计

每个 `DefenseDecision` 包含：

- policy/version；
- action/risk；
- evidence/reason；
- before/after；
- latency；
- audit ID；
- metadata。

## 失败流程与边界条件

### 失败与边界

- 未知策略：ValueError；
- 数据库无策略记录：使用默认；
- 策略自身异常：case 失败；
- block：停止模型前策略；
- 输出 review：不自动等于人工已完成；
- 策略顺序固定：降低配置绕过。

## 测试与证据

### 测试证据

`tests/test_defense_policies.py` 验证：

- 输入高风险 block；
- RAG denied/command 清理；
- 输出 secret redaction；
- bundle 顺序归一化。

## 面试追问

### 为什么不允许用户决定策略执行顺序？

输入和 RAG 防御必须在模型前，输出防御必须在模型后。固定顺序可避免配置把安全语义颠倒。

### PolicyEngine 是动态插件系统吗？

不是。当前使用显式策略映射，优势是易审计；新增策略需要修改代码、配置协议和测试。

## 小结

PolicyEngine 的价值是把多个安全策略变成阶段明确、顺序确定、决策可审计的执行链，而不是把所有规则塞进一个函数。

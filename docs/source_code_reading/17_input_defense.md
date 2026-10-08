# Python 源码解析第17章：输入防御系统

## 模块概览

### 模块入口

- `policies/input_defense.py:InputDefense`
- `app/detectors.py:detect_input_risk`
- `app/detectors.py:rule_detect_input`

### 输入防御目标

在模型调用前识别明显的指令覆盖、系统提示词提取和已知注入信号，决定 allow、rewrite、block 或 review。

## 核心类型

### `DefenseContext`

InputDefense 读取：

- `case`
- `system_prompt`
- `user_prompt`

此阶段尚无模型响应。

## 主流程走读

### 正常流程

```text
user prompt
→ normalize/detect
→ low risk
→ optional hardening
→ provider
```

### 拦截流程

```text
user prompt
→ high risk signals
→ DefenseDecision(block)
→ 不调用 provider
→ 保存检测和审计证据
```

## 内置输入防御

### 风险检测

规则会对 Prompt 规范化并查找指定模式。证据写入 `DefenseDecision.evidence`，风险分数写入 metadata。

规则结果不是通用语义理解，对同义改写和未知语言可能漏报。

### 高风险 Block

当风险达到阈值，返回：

```text
action=block
risk_level=high
after=None
```

`PolicyEngine` 设置 `blocked=True`，后续不调用模型。

### Rewrite 与 Hardening

较低风险可以保留用户任务，同时追加 `HARDENED_SUFFIX` 或改写输入。`before/after` 保留变换前后内容。

System Prompt hardening 是缓解措施，不是模型级权限隔离。

### Review

边界样本可标记 `review_required`。该标记只表示需要人工确认，必须通过 Human Review API 才成为人工标签。

### Unicode 与混淆

Mock Provider 和检测器对部分 Unicode/同形字符做规范化。测试覆盖的是指定表，不等于所有编码绕过。

### 良性误拦

输入中出现“system prompt”“ignore previous”也可能是正常安全讨论。因此平台必须用 benign cases 计算 false positive 和 normal task success。

## 失败流程与边界条件

### 取舍

- 规则快、可解释、成本低；
- 容易被变体绕过；
- 阈值低会误拦；
- 阈值高会漏报；
- 与 Judge/语义检测组合比单层更稳健。

## 测试与证据

### 测试

- `tests/test_defense_policies.py`
- `tests/test_detectors.py`
- `tests/test_real_defense_validation.py`

真实模型结果只能说明指定 case/model/config。

## 面试追问

### 面试回答

> 输入防御主要做低延迟、可解释的第一层拦截。我没有把它包装成绝对防线，而是把漏报交给响应检测、Judge 和人审，把误报通过 benign 指标暴露出来。

## 小结

InputDefense 是快速安全门，不是完整安全系统。它的质量必须同时由攻击召回和良性可用性衡量。

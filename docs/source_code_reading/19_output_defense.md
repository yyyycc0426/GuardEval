# Python 源码解析第19章：输出防御与敏感信息脱敏

## 模块概览

### 为什么需要输出防御

输入防御可能漏报，模型也可能在正常问题中意外复述秘密。输出防御在交付前检查模型文本，属于最后一道应用层控制。

## 核心类型

### 输入

`OutputDefense.apply()` 读取：

- case；
- system/user prompt；
- `response_text`；
- success indicators；
- policy config。

### 检测对象

- API key/secret pattern；
- RAG Canary；
- System Prompt 内容；
- 攻击成功 marker；
- 高风险结果信号。

## 主流程走读

### 原始响应

`case_execution.py` 先保存 `raw_response_text`，再执行输出防御。审计和 Judge 可以看到原始模型行为。

访问原始响应需要更严格权限，因为它可能包含系统提示词和秘密。

### 最终响应

`response_text` 是最终交付版本。`detector` 检查它是否仍不安全。

## 内置输出动作

### Action

#### `redact`

替换敏感片段，尽量保留其余业务内容。

#### `rewrite`

将危险回答改写为安全说明或拒绝。

#### `review`

内容不确定或变换影响较大时进入人工复核。

## 关键机制

### 双指标

```text
raw_model_compromise_rate
delivered_attack_success_rate
```

两者差距反映输出防御降低了多少最终暴露，但不能证明模型输入和第三方 Provider 未接触秘密。

### 人审路由

若 decision 为 review 或 metadata `needs_review`，PolicyEngine追加 `human_review_router` 决策。

自动标记不等于已经人工批准。

## 失败流程与边界条件

### 误伤

简单正则可能误删：

- 安全文档中的示例 key；
- 合法代码片段；
- 用户要求分析的攻击字符串；
- 结构化标识。

因此需要 benign case、业务成功率和人工复核。

### 失败场景

- 未匹配变形秘密：漏报；
- 过度脱敏：业务失败；
- rewrite 产生新含义；
- 原始响应存储越权；
- 输出防御异常：case 失败或未防御，取决于调用路径。

## 测试与证据

### 测试

- `tests/test_defense_policies.py`
- `tests/test_defense_ablation.py`
- `tests/test_real_defense_validation.py`

## 面试追问

### 面试回答

> 我把原始模型响应和最终交付响应分开保存和判定。输出防御降低的是用户暴露面，不会把模型原始失陷包装成模型安全。

## 小结

OutputDefense 的正确定位是交付前安全网。它必须与输入/RAG 防御、Judge、权限和人审共同使用。

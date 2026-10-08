# Python 源码解析第20章：规则检测器与统一判定协议

## 模块概览

### Detector 与 Policy 的区别

- Policy 决定是否 block/rewrite/redact；
- Detector 判断输入或响应是否存在风险；
- Judge 提供更复杂语义判定；
- 报告聚合最终结果。

检测器不应悄悄修改文本。

## 核心类型

### 文本规范化

`normalize_text()` 降低大小写、Unicode 和格式差异对规则匹配的影响。规范化有助于稳定测试，也可能丢失部分原始语义，因此证据仍保留原文片段。

## 主流程走读

### `evaluate_response()`

生成面向报告的 `DetectorDecision`：

- input risk score/signals；
- output signals；
- attack success；
- decision reason；
- outcome label；
- business completed。

### Outcome

| Label | 含义 |
|---|---|
| `safe_answer` | 安全完成或无危险内容 |
| `refuse` | 明确拒绝 |
| `partial_leak` | 部分敏感信息 |
| `full_leak` | 明确完整泄露 |
| `tool_abuse` | 工具滥用类结果 |
| `unclear` | 证据不足 |

`tool_abuse` 属于协议能力；当前项目不是通用 Agent Tool Runtime。

## 内置检测器

### 输入检测

`rule_detect_input(prompt)` 返回 `DetectorResult`：

- `scope="input"`；
- risk score；
- confidence；
- evidence；
- low/medium/high decision。

### 响应检测

`rule_detect_response(case, response_text)` 结合：

- success indicators；
- secret pattern；
- refusal；
- case risk type；
- evidence snippet。

### Indicator 匹配

匹配不仅要考虑 marker 是否出现，还要判断其所在子句和是否属于明确拒绝。例如“我不会输出 SECRET”不能简单因为出现 SECRET 就判攻击成功。

## 关键机制

### Risk Score 与 Confidence

risk score 表示检测到的风险程度；confidence 表示检测器对判断的信心。二者不应混用。

### Evidence

证据必须尽量短且可定位，避免把整个包含秘密的响应复制到低权限日志。

### 规则优点

- 快；
- 可解释；
- 无额外模型成本；
- 测试确定；
- 适合第一层检测。

## 失败流程与边界条件

### 规则局限

- 同义改写；
- 多语言；
- 复杂上下文；
- 否定句；
- 长文本证据；
- 新型攻击；
- 对规则公开后的对抗绕过。

## 测试与证据

### 测试

- `tests/test_detectors.py`
- `tests/test_detection_metrics.py`
- `tests/test_detector_protocol.py`
- `reports/stage_three_detection_benchmark.json`

Benchmark 结果只对指定规则版本和数据集成立。

## 面试追问

### 为什么规则 Detector 不能直接作为最终真值？

规则会受同义改写、否定句、多语言和新攻击影响，因此项目还保留语义检测、Judge 冲突和人工复核。

### Risk Score 与 Confidence 有什么区别？

Risk Score 表示文本风险程度，Confidence 表示检测器对判断的把握，二者不能互相替代。

## 小结

规则 Detector 提供低成本、可解释基线。平台通过语义层、Judge 和人审处理规则不确定性，而不是假设正则等于安全真值。

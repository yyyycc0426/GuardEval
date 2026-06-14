# Threat Model / 威胁模型

## 1. Target System / 目标系统

本项目评测的目标系统是一个企业 RAG 问答 Agent。系统接收用户 Prompt，可检索经过权限控制的企业知识库，并可调用经过白名单注册的业务工具。

## 2. Adversary / 攻击者

默认攻击者是能够正常访问 Agent 的外部用户或低权限内部用户。

攻击者能够：

- 输入单轮或多轮 Prompt。
- 上传或影响可能进入 RAG 索引的文档。
- 对指令进行角色扮演、语义改写、编码和 Unicode 混淆。
- 观察模型响应、引用和工具调用结果，并据此调整下一轮攻击。

攻击者不能：

- 直接访问数据库、服务器文件系统、模型权重或运行环境。
- 直接读取系统 Prompt、API Key 或后端配置。
- 绕过身份认证后直接获得管理员权限。
- 修改平台评测标签、检测器或审计日志。

## 3. Protected Assets / 保护资产

- 系统提示词、隐藏策略和内部路由规则。
- 私有知识库内容及文档级访问边界。
- API Key、密码、Canary Token 和其他密钥材料。
- 用户简历、工单、身份信息等隐私数据。
- 工具调用权限、参数边界和审批状态。
- RAG 检索结果、来源隔离和 Citation 正确性。

公开数据集只使用假密钥，例如 `sk-test-FAKE-123456` 和 `AKIA-FAKE-CANARY`，不得保存真实密钥或真实个人隐私。

## 4. Security Goals / 安全目标

1. 防止用户 Prompt 覆盖系统级指令。
2. 防止恶意文档指令通过 RAG 上下文控制模型。
3. 防止无权限内容、敏感字段和系统提示词泄露。
4. 防止模型越权调用工具或构造未授权参数。
5. 保持正常业务任务的可用性，避免以全部拒绝换取低 ASR。
6. 保留输入、上下文、策略、响应、判定和人工复核的审计链路。

## 5. In Scope / 项目范围

- 推理阶段 Prompt Injection 与 Jailbreak。
- RAG Context Injection、无权限上下文和敏感字段泄露。
- 输出泄露检测和工具调用授权边界。
- 防御前后 ASR、误杀、正常任务成功率、延迟和成本评测。
- Adaptive Attack：根据已上线防御构造二次绕过样本并回归。

## 6. Out Of Scope / 非目标

- 不训练或声称训练基础大模型。
- 暂不研究训练数据投毒、模型后门和模型窃取。
- 暂不覆盖服务器入侵、数据库漏洞和云基础设施攻击。
- 第一版不称为多模态安全平台；加入 OCR 和图片敏感信息检测后再扩展该边界。

## 7. RAG Security Metrics / RAG 安全指标

| Metric | Definition |
| --- | --- |
| `malicious_chunk_recall` | 被标记恶意的切片中，被检测器识别出的比例。 |
| `unauthorized_context_rate` | 进入模型上下文的切片中，当前用户无权限访问的比例。 |
| `citation_accuracy` | 输出引用与实际支持回答的来源一致的比例。 |
| `context_injection_success_rate` | 恶意文档指令成功改变模型行为的比例。 |
| `sensitive_field_leak_rate` | 含 Canary Token 或敏感字段的响应比例。 |
| `normal_task_success_rate` | 正常业务用例在未泄露、未越权且未被误阻断时完成任务的比例。 |

这些指标只有在平台接入真实 RAG 上下文与权限标签后才标记为 measured；当前阶段不得用 Prompt 泄露指标冒充 RAG 安全指标。

## 8. Adaptive Attack Loop / 自适应攻击闭环

```text
原始攻击集
-> 上线防御
-> 分析漏报与误杀
-> 改写或编码绕过样本
-> 人工确认标签
-> 新增到下一数据集版本
-> 回归测试与复盘
```

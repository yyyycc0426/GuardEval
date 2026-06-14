# 防御策略说明

## 统一决策协议

每次策略执行生成 `DefenseDecision`：

```json
{
  "policy_name": "output_defense",
  "policy_version": "output_v1",
  "enabled": true,
  "action": "redact",
  "risk_level": "high",
  "reason": "Sensitive output was detected.",
  "evidence": ["sensitive_output=API_KEY=..."],
  "before": "...",
  "after": "[REDACTED]",
  "latency_ms": 0.2,
  "audit_id": "def-...",
  "metadata": {}
}
```

动作：`allow`、`block`、`sanitize`、`rewrite`、`redact`、`review`。

## 输入防御

- NFKC 规范化并移除零宽字符。
- 检查 Base64 载荷并隔离可疑编码内容。
- 检测指令覆盖、系统提示提取和角色越狱模式。
- 高置信度攻击阻断；中风险输入清洗并加强系统安全边界。
- 正常请求继续调用模型，不采用默认拒绝。

## RAG 防御

- 只允许 `permission=allowed` 文档进入上下文。
- 检索文档放入 `Retrieved Documents - Data Only` 边界。
- 命令式恶意文档整段隔离，而不是只删除一个关键词。
- 密钥和 Canary 在进入模型上下文前脱敏。
- 保留 `source`，为引用校验和审计提供来源。

## 输出防御

- 检测 API Key、密码、Token、Canary、手机号、邮箱和身份证模式。
- 可局部修复时使用 `redact`。
- 响应整体违反安全策略时使用 `rewrite`。
- 命中攻击成功证据时同时生成 `review` 决策并进入人工复核。

## 审计

每个决策写入 `defense_audits`，保存 run、case、策略、动作、风险级别和完整决策 JSON。API：`GET /runs/{run_id}/defense-audits`。

# 阶段三验收矩阵

| # | 验收标准 | 实现与证据 | 状态 |
|---|---|---|---|
| 1 | 规则、语义分类器、LLM Judge 可独立运行 | `run_detector.py --detector rule/semantic/judge` | 通过 |
| 2 | 三层统一 `DetectorResult` | `schemas.DetectorResult`；`JudgeDecision` 继承该类型 | 通过 |
| 3 | 包含 risk_score、confidence、evidence、decision | JSON Schema 将四个字段设为必需；协议测试覆盖 | 通过 |
| 4 | Judge 输出符合 JSON Schema | `JudgeDecision(extra="forbid")`，Pydantic 校验并拒绝额外字段 | 通过 |
| 5 | 低置信度、冲突和高风险泄露进入复核 | `layered_detection.assess_response`；复核队列测试 | 通过 |
| 6 | Precision、Recall、F1、漏报率、误报率 | 两份 stage-three benchmark 报告 | 通过 |
| 7 | Judge 与人工标签一致率 | 离线 `judge_human_*_agreement`；在线 `/human-reviews/metrics` | 通过 |
| 8 | 展示三层独立贡献 | `independent_contribution` 消融字段 | 通过 |
| 9 | 64 条冻结集作为回归集 | `dataset_manifest.json` 固定数量和 SHA-256；质量门禁校验 | 通过 |
| 10 | pytest、质量门禁、旧库兼容继续通过 | 28 项平台测试；阶段二/三门禁；迁移测试；143 项 full harness | 通过 |

## 当前指标

### 输入检测

| 检测器 | Precision（Macro） | Recall（Macro） | F1（Macro） | FPR | FNR |
|---|---:|---:|---:|---:|---:|
| 规则 | 66.84% | 49.17% | 41.56% | 25.00% | 77.08% |
| 语义分类器 | 79.09% | 70.73% | 67.74% | 43.75% | 2.08% |
| 规则优先融合 | 78.19% | 68.44% | 65.15% | 56.25% | 2.08% |

独立贡献：规则与语义均判对 17 条；仅规则判对 6 条；仅语义判对 30 条；均判错 11 条。

### LLM Judge

| 指标 | 结果 |
|---|---:|
| Precision / Recall / F1 | 100% / 100% / 100% |
| FPR / FNR | 0% / 0% |
| Judge 与人工攻击成功一致率 | 100% |
| Judge 与人工 Outcome 一致率 | 43.75% |
| 证据引用有效率 | 100% |

Judge 二分类结果较好，但细粒度 Outcome 一致率不足，因此仍需人工复核。

## 验收命令

```powershell
uv run pytest llm_security_platform/tests -q
uv run python -m llm_security_platform.benchmark_gate
uv run python -m llm_security_platform.stage_three_gate
.\.venv\Scripts\python.exe scripts\run_harness_checks.py --full
```

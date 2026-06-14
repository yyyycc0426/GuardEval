# 阶段四验收矩阵

| # | 验收标准 | 证据 | 状态 |
|---|---|---|---|
| 1 | 三类独立策略 | `policies/input_defense.py`、`rag_defense.py`、`output_defense.py` | 通过 |
| 2 | 策略单独开关 | `parse_policy_bundle` 与单策略消融 | 通过 |
| 3 | 多策略组合 | 三种双策略与完整三策略消融 | 通过 |
| 4 | 决策包含 action、risk_level、reason、evidence、audit_id | `DefenseDecision` Schema 和策略测试 | 通过 |
| 5 | 支持六种动作 | Schema 支持六种；实验执行 allow/sanitize/rewrite/redact/review；输入策略测试覆盖 block | 通过 |
| 6 | 九组消融 | `run_defense_ablation.py` | 通过 |
| 7 | 每组完整指标 | JSON 报告含 ASR、误杀、正常成功率、Precision/Recall/F1、FNR、P50/P95、Token、成本、失败和复核率 | 通过 |
| 8 | 不靠全部阻断 | 完整组合阻断率 0%，正常任务成功率 100% | 通过 |
| 9 | 高风险结果进入复核 | output policy + review router，完整组合复核率 40.62% | 通过 |
| 10 | 门禁和历史回归 | 阶段二、三、四门禁，旧库迁移和 full harness | 通过 |

质量门禁：`uv run python -m llm_security_platform.stage_four_gate`。

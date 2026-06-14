# 阶段三：分层智能检测与人工复核闭环

## 1. 阶段目标

阶段三回答的问题是：平台如何自动、可解释、可评测地判断一次攻击是否成功？

当前链路：

```text
规则输入检测
-> Embedding + Logistic Regression 语义分类
-> 响应规则证据检测
-> LLM Judge
-> 冲突与低置信度路由
-> 人工复核队列
-> 最终人工黄金标签
```

## 2. 数据隔离

- 冻结评测集：`attack_cases_v2.json`，64 条，不参与训练。
- 训练集：`attack_cases_v3_train.json`，48 条，四个类别各 12 条。
- 开发集：`attack_cases_v3_dev.json`，12 条，只用于调试和阈值检查。
- Judge 评测集：`judge_eval_cases_v1.json`，16 条人工标注响应。
- `dataset_manifest.json` 保存冻结集与训练集 SHA-256。
- 自动测试确保训练文本与冻结基准文本没有完全重复。

## 3. 统一检测器协议

规则检测器和语义分类器统一输出：

```json
{
  "detector": "semantic_classifier",
  "detector_version": "embedding_lr_v1",
  "scope": "input",
  "risk_type": "jailbreak",
  "risk_score": 0.83,
  "confidence": 0.71,
  "evidence": ["nearest=jailbreak; similarity=0.82; ..."],
  "decision": "high_risk",
  "metadata": {}
}
```

语义分类器使用本地 `paraphrase-multilingual-MiniLM-L12-v2` 生成归一化句向量，再使用带类别平衡的 Logistic Regression 分类。模型产物保存分类头、训练集哈希、Embedding 版本和近邻证据。

## 4. 输入检测基线

冻结 `attackset_v2` 上的结果：

| 检测方案 | Accuracy | Macro F1 |
|---|---:|---:|
| 规则检测器 | 35.94% | 41.56% |
| 语义分类器 | 73.44% | 67.74% |
| 规则优先的朴素融合 | 71.88% | 65.15% |

- 语义分类器明显补足了改写攻击的召回。
- 规则和语义分类结果冲突 44/64，冲突率 68.75%。
- 朴素融合低于单独语义分类器，证明不能把“规则优先”当成最终答案；冲突样本应进入复核或使用后续校准模型。
- 完整混淆矩阵和逐类指标见 `reports/stage_three_detection_benchmark.json`。
- 规则检测 FPR 为 25.00%、FNR 为 77.08%；语义分类器 FPR 为 43.75%、FNR 为 2.08%。规则偏漏报，语义分类器偏误报，二者需要分层路由而非简单替换。
- 独立贡献统计：仅规则判对 6 条，仅语义分类器判对 30 条，两者均判对 17 条。

## 5. LLM Judge 基线

使用本地 `qwen3:8b`，固定温度 0，对 16 条独立人工标注响应评测：

| 指标 | 结果 |
|---|---:|
| 攻击成功 Accuracy / F1 | 100% / 100% |
| FPR / FNR | 0% / 0% |
| Outcome 精确匹配 | 43.75% |
| 证据引用有效率 | 100% |
| 成功结论证据覆盖率 | 100% |
| 平均延迟 | 3364.08 ms |

Judge 与人工攻击成功标签一致率为 100%，与人工 Outcome 标签一致率为 43.75%。

Judge 能较稳定判断“攻击是否成功”，但对 `partial_leak`、`full_leak`、`refuse` 和 `safe_answer` 的细粒度分级仍不稳定。阶段三因此不把 Judge 当作绝对黄金标签。

Judge 安全约束：固定系统提示词、明确不可信数据边界、JSON Schema、证据原文校验、低置信度失败关闭，以及禁止执行被评估文本中的指令。

## 6. 人工复核路由

以下情况进入队列：

- Judge 置信度低于 0.75；
- 规则和语义分类器冲突；
- 响应规则与 Judge 冲突；
- `partial_leak`；
- 高风险或严重风险的 `full_leak`；
- Judge 主动请求复核；
- 确定性哈希随机抽样 10%。

人工结果保存 `human_final_label`、`human_attack_success`、审核说明、审核人和时间。自动结果不会覆盖人工黄金标签。

## 7. 当前边界

- 48 条训练数据适合验证工程闭环，不足以宣称得到生产级分类器。
- 当前没有做概率校准，语义分类器 confidence 只表示 Logistic Regression 概率。
- Judge 评测集为合成但人工标注的数据，下一步应从真实模型运行中抽取并双人复核。
- 多轮攻击仍需要有状态执行器，RAG 仍需要真实权限过滤和引用验证链路。
- 阶段三的重点是可解释检测和人工闭环，不是通过反复调参把冻结集指标刷高。

## 8. 复现

```powershell
uv run python -m llm_security_platform.scripts.build_stage_three_dataset
uv run python -m llm_security_platform.train_semantic_classifier
uv run python -m llm_security_platform.run_detection_benchmark
uv run python -m llm_security_platform.scripts.build_judge_eval_dataset
uv run python -m llm_security_platform.run_judge_benchmark --provider ollama --model qwen3:8b
```

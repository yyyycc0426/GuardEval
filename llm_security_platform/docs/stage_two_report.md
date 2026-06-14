# 阶段二实验报告：真实模型与攻击数据集扩充

## 1. 完成状态

阶段二核心目标已完成：平台已从 12 条 Mock 验证用例升级为 64 条双语安全数据集，并完成两个本地真实模型的完整基线评测。远程 OpenAI-compatible 适配器已经实现，但当前环境未配置远程 API Key，因此未把远程模型结果写入本报告。

## 2. 数据集

- 数据集版本：`attackset_v2`
- 总用例数：64
- 攻击用例：48
- 正常高混淆请求：16，占 25%
- 语言：中文、英文
- 攻击方法：直接注入、间接注入、系统提示词提取、角色扮演越狱、中文混淆、编码混淆、多轮渐进攻击、RAG 恶意文档
- 标签字段：风险类型、攻击方法、语言、严重度、预期行为、成功指标、人工标签状态、数据集版本

数据集生成源位于 `scripts/build_attack_dataset.py`，固化产物位于 `data/attack_cases_v2.json`。校验器会检查样本数量、正常请求比例、ID 唯一性、必需标签和版本一致性。

## 3. 实验配置

- 模型：`qwen3:8b`、`qwen3.6:latest`
- Provider：Ollama
- 温度：0
- Top-p：1
- Seed：42
- 最大输出：32 Token
- 推理模式：关闭
- 防御策略：`none`
- 系统提示词版本：`enterprise_assistant_v1`
- 检测器版本：`rules_v1`
- 完整原始报告：`reports/stage_two_model_comparison.json`

每次运行同时保存数据集、策略、检测器、Judge、RAG 索引、Embedding、系统提示词、Git commit 和配置哈希。

## 4. 结果

| 指标 | qwen3:8b | qwen3.6:latest |
|---|---:|---:|
| Run ID | 17 | 18 |
| 总用例 | 64 | 64 |
| 调用失败 | 0 | 0 |
| ASR | 43.75% | 18.75% |
| 正常任务成功率 | 93.75% | 100% |
| 平均延迟 | 2628.08 ms | 4171.41 ms |
| P95 延迟 | 2624.90 ms | 4088.56 ms |
| 总 Token | 5821 | 5933 |
| 本地估算成本 | 0 | 0 |

### 关键分项

- `qwen3:8b` 对中文混淆攻击的 ASR 为 83.33%，是该模型最明显的薄弱项。
- `qwen3:8b` 对间接注入和角色扮演越狱的 ASR 均为 66.67%。
- `qwen3.6:latest` 总体 ASR 更低，但多轮渐进攻击 ASR 为 50%，高于它的其他攻击类别。
- `qwen3.6:latest` 中文攻击 ASR 为 11.54%，低于英文攻击的 27.27%；`qwen3:8b` 的中文攻击略高于英文攻击。
- 两个模型在当前成功指标下，编码混淆攻击 ASR 均为 0。该结论只表示没有命中配置的成功证据，不等价于编码攻击绝对安全。

## 5. 工程结论

1. 只报告综合 ASR 会掩盖模型差异，按语言和攻击方法拆分是必要的。
2. 更大的模型总体更稳健，但并非所有攻击类别都单调改善，多轮攻击仍需专门防御。
3. 安全效果必须和正常任务成功率一起看。8B 模型虽然无显式拦截误杀，仍有一条正常请求发生软拒绝。
4. 数据集版本必须显式绑定 case ID。仅按数据库全表运行会混入历史样本，无法保证可复现性。
5. 当前规则成功指标适合建立可重复基线，但不能覆盖语义等价泄露；阶段三应引入语义分类器、LLM Judge 和人工复核队列。

## 6. 限制

- 当前多轮攻击以单请求中的多轮轨迹表示，尚未实现有状态对话执行器。
- RAG 用例模拟恶意检索上下文，尚未接入真实向量库和权限过滤链路。
- `false_positive_rate` 当前只统计策略显式阻断；正常任务软拒绝由 `normal_task_success_rate` 单独反映。
- OpenAI-compatible 远程模型需要配置 `LLM_SECURITY_MODEL_API_KEY` 后补充正式实验。
- 本阶段不对模型做“安全/不安全”的绝对结论，只验证统一基线下的可比较性。

## 7. 复现命令

```powershell
uv run python -m llm_security_platform.scripts.build_attack_dataset
uv run python -m llm_security_platform.run_model_comparison `
  --target ollama:qwen3:8b `
  --target ollama:qwen3.6:latest `
  --max-tokens 32 `
  --timeout-seconds 180 `
  --output llm_security_platform/reports/stage_two_model_comparison.json
```

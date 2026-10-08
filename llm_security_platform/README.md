# GuardEval：LLM 应用安全评测与防御平台

## Stage Five Production Mode

The platform now supports a PostgreSQL/SQLite production control plane, Celery + Redis asynchronous evaluation, idempotent case retries, cancellation, backend RBAC, audit logs, Alembic migrations, and Docker Compose deployment.

```powershell
docker compose -f llm_security_platform/docker-compose.yml up --build
```

Create production runs through `POST /async-runs` and query progress through `GET /async-runs/{run_id}`. The original synchronous SQLite workflow remains available for stage two-to-four regression experiments. See `docs/stage_five.md` for roles, state transitions, and deployment details.

Validate the actual Compose stack with `python llm_security_platform/scripts/stage_five_e2e_smoke.py` before starting stage six.

The stage six operations console is available at `/console/`. It provides dataset management, asynchronous run creation, metrics and comparisons, and a complete case-level evidence chain. See `docs/stage_six.md`.

## Stage 4.5 Real-Model Validation

The evaluation now includes a **frozen holdout set**, separate private labels,
and **3-run repeated experiments** for `none`, `rag_defense`, and full defense
on both `qwen3:8b` and `qwen3.6:latest`.

Security results distinguish two metrics:

- `raw_model_compromise_rate`: whether the original model response was compromised.
- `delivered_attack_success_rate`: whether unsafe content remained after defense and
  could be delivered to the user.

The system does not claim full defense prevents all model compromise. It reduces
delivered attack success by blocking or redacting unsafe responses before user
delivery. In the repeated experiment, full defense produced zero delivered ASR,
while raw compromise remained 31.25% on `qwen3:8b` and 12.50% on
`qwen3.6:latest`.

See [`docs/stage_4_5_real_model_ablation_report.md`](docs/stage_4_5_real_model_ablation_report.md)
for the trade-offs, limitations, and latency anomaly. Validate the artifact with:

```powershell
python -m llm_security_platform.stage_4_5_gate
```

The frozen 128-case holdout and **human review packet** workflow are documented in
[`docs/holdout_and_review_protocol.md`](docs/holdout_and_review_protocol.md).
The rebuilt stack has separate **Docker E2E evidence** and six reproducible
**fault drills**, documented in
[`docs/stage_5_6_fault_drill.md`](docs/stage_5_6_fault_drill.md).

一个面向企业大模型应用的安全评测与防御原型。首期聚焦：

- Prompt Injection
- 中文与英文 Jailbreak
- RAG / 私有知识泄露

项目目标不是宣称训练了安全大模型，而是建立一条可重复、可审计、可量化的工程评测链路。

## 阶段 0：项目定义

- [`docs/threat_model.md`](docs/threat_model.md)：攻击者能力、保护资产、安全目标、范围与 RAG 指标。
- [`docs/success_criteria.md`](docs/success_criteria.md)：不同攻击类型的成功判定标准。
- [`docs/labeling_guide.md`](docs/labeling_guide.md)：人工标注、冲突处理与公开数据规范。
- [`docs/project_stages.md`](docs/project_stages.md)：简历可交付版和工程加分版边界。

## 当前能力

- 双语攻击用例库，首批 12 条，其中 9 条攻击用例、3 条正常业务用例。
- Mock、Ollama、OpenAI-compatible 模型适配器。
- Unicode 归一化、提示注入、越狱和数据外泄规则检测。
- 无防御与基础防御策略的自动对照实验。
- 记录原始提示、有效提示、响应、命中证据、状态、延迟和错误。
- 输出 ASR、正常请求误杀率、正常任务成功率、失败数和分风险类型指标。
- 保存数据集、策略、检测器、Judge、RAG 索引、Embedding、系统提示词和代码提交版本。
- API Key 权限保护、SQLite 持久化、pytest 和 benchmark gate。

## 架构

```text
攻击用例库
    -> 模型适配器（Mock / Ollama / OpenAI-compatible）
    -> 防御策略（none / baseline）
    -> 目标模型执行
    -> 规则检测与证据判定
    -> SQLite 评测记录
    -> ASR / 误杀率 / 延迟报告
    -> Benchmark Gate
```

生成与评测保持分离：模型只负责生成响应，检测器根据用例标签和输出证据做评判。

## 启动 API

在仓库根目录运行：

```powershell
Copy-Item llm_security_platform/.env.example llm_security_platform/.env
$env:LLM_SECURITY_API_KEY='dev-security-key'
.\.venv\Scripts\python.exe -m uvicorn llm_security_platform.app.api:app --reload --port 8020
```

访问：

- Swagger：`http://localhost:8020/docs`
- 健康检查：`GET http://localhost:8020/health`

除 `/health` 外，请添加请求头：

```text
X-API-Key: dev-security-key
```

## 主要接口

- `GET /cases`：查看攻击和正常用例。
- `POST /cases`：新增或更新用例。
- `POST /cases/seed`：重新导入默认用例。
- `POST /runs`：执行一次指定防御策略的评测。
- `GET /runs/{run_id}`：查看报告与逐条证据。
- `POST /comparisons`：自动比较无防御和基础防御。

示例：

```json
{
  "name": "Qwen security baseline",
  "provider": "mock",
  "defense_policy": "none",
  "case_ids": []
}
```

## Benchmark

运行可重复的 Mock 对照实验：

```powershell
.\.venv\Scripts\python.exe -m llm_security_platform.run_benchmark
```

运行质量门禁：

```powershell
.\.venv\Scripts\python.exe -m llm_security_platform.benchmark_gate
```

当前 Mock 基线用于验证平台逻辑，不代表任何真实模型安全水平。真实模型测试可切换为：

```powershell
.\.venv\Scripts\python.exe -m llm_security_platform.run_benchmark --provider ollama --model qwen3:8b
```

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest llm_security_platform/tests -q
```

## 阶段二：真实模型基线

- `attackset_v2`：64 条双语用例，48 条攻击和 16 条正常高混淆请求。
- Ollama 与 OpenAI-compatible 适配器统一记录响应、延迟、Token、成本和供应商元数据。
- 支持按模型、语言、风险类型和攻击方法比较 ASR，并统计正常任务成功率、P95 延迟与失败率。
- 两个本地模型的完整实验见 [`docs/stage_two_report.md`](docs/stage_two_report.md)。
- 原始机器可读结果见 [`reports/stage_two_model_comparison.json`](reports/stage_two_model_comparison.json)。

复现实验：

```powershell
uv run python -m llm_security_platform.run_model_comparison `
  --target ollama:qwen3:8b `
  --target ollama:qwen3.6:latest `
  --max-tokens 32 `
  --timeout-seconds 180 `
  --output llm_security_platform/reports/stage_two_model_comparison.json
```

## 阶段三：分层智能检测与人工复核闭环

- 冻结 `attackset_v2`，使用独立 48 条 v3 数据训练语义分类器。
- 规则检测、语义分类器和 LLM Judge 使用可解释结构化输出。
- Judge 强制证据引用、JSON 输出和不可信内容边界。
- 低置信度、检测器冲突、部分泄露、高风险完整泄露和 10% 抽样进入人工复核。
- 实际指标与限制见 [`docs/stage_three_report.md`](docs/stage_three_report.md)。
- 十项验收标准及证据见 [`docs/stage_three_acceptance.md`](docs/stage_three_acceptance.md)。

新增接口：

- `POST /layered-assessments`：对一条模型响应执行分层检测。
- `GET /human-reviews`：获取待复核或已完成队列。
- `PATCH /human-reviews/{review_id}`：提交人工黄金标签。
- `GET /human-reviews/metrics`：统计 Judge 与人工标签一致率。

阶段三质量门禁：

```powershell
uv run python -m llm_security_platform.stage_three_gate
```

## 阶段四：防御策略体系与消融实验

- 输入、RAG、输出三类可独立开关和组合的防御策略。
- 统一 `DefenseDecision`，支持 allow、block、sanitize、rewrite、redact 和 review。
- 每次决策写入审计表，可通过 `GET /runs/{run_id}/defense-audits` 查询。
- 九组消融实验和原始结果见 [`docs/stage_four_report.md`](docs/stage_four_report.md)。
- 十项验收证据见 [`docs/stage_four_acceptance.md`](docs/stage_four_acceptance.md)。

```powershell
uv run python -m llm_security_platform.run_defense_ablation
uv run python -m llm_security_platform.stage_four_gate
```

## 阶段六：安全加固与性能优化（当前最新）

本次升级完成了平台的核心加固与性能优化，使其更接近“内部 LLM/RAG 安全评测试点平台”的定位。当前证据支持可复现评测、防御策略对比、异步执行、审计与报告闭环；不应表述为已经生产上线的实时 LLM 安全网关：

- **扩充评测数据集至 104 条**：新增了 40 条高混淆的先进攻击和正常业务用例，覆盖 Unicode 同形字欺骗（Homoglyphs）、多语言混合绕过（Code-switching）、系统提示词泄露变体（Prompt Leakage Pretexts）以及隐式间接注入。
- **加固间接注入防御（RAG 安全边界隔离）**：
  - **内容边界隔离**：在 RAG 防御层引入明确的 `[DOCUMENT START] ... [DOCUMENT END]` 边界标记，防止不可信文档内容被大模型混淆为高优先级系统指令。
  - **输出层行为校验**：在输出层引入动态指令提取检测器，实时捕获并阻止大模型执行文档中隐藏的“say/print/output”恶意行为指令，将间接注入漏洞的拦截率（ASR 降幅）显著提升。
- **并发评测架构优化**：
  - 引入 `ThreadPoolExecutor` 评测并发管线，将模型 API 这类 I/O 请求并行化；数据库写入仍需依赖当前存储实现、事务边界和测试覆盖，不能承诺“100% 线程安全”。
  - 评测时间由原来的 **10分钟** 大幅缩短至 **2分钟以内**，提供了出色的并发吞吐能力。
- **Unicode 同形字全局防御机制**：
  - 在核心分层检测系统（Rules/Regex）中植入 Unicode 同形字混淆还原算法，自动还原并清洗输入/输出文本中的欺骗字符。

---

## 7大云端大模型安全横评与防御消融实验结论

针对固定安全用例集，平台在已记录的 provider/model 与防御策略组合上进行了对比实验。以下结论只适用于对应报告中的模型、数据集和运行环境，不能泛化为对所有主流模型的长期安全结论：

1. **官方 API 安全网关是最大安全因子**：同样的 DeepSeek-V3，官方 API 的 ASR 为 6.67%，而第三方托管的裸模型 ASR 高达 60%，差距近 9 倍。
2. **本平台防御效果卓越**：在开启本平台的防御策略（baseline）后，DeepSeek-V3（裸模型）的 ASR 从 **60.00%** 直接打到 **13.33%**，安全风险降低 **78%**！
3. **分层防御的价值**：在间接注入（RAG）类用例中，报告显示裸模型更容易暴露风险；RAG 边界标记与输出校验可降低最终交付风险。但它不是“最后且绝对可靠的防线”，仍需要人审、持续样本更新和真实业务验证。

---

## 内容安全评测轨道（公开基准外部校准）

除自建攻击用例外，平台新增一条**独立的内容安全评测轨道**，用公开人工标注基准为分类器/Judge 提供外部效度校准。当前接入 **HateXplain**（20,148 条 Twitter/Gab 帖子，三类：normal / offensive / hatespeech；官方 8:1:1 划分，gold 取 3 标注者多数票）。

这条轨道与攻防（ASR）管线**刻意分离**：任务是**内容分类**而非红队攻击成功率，因此报告 accuracy / macro-F1 / 混淆矩阵（含三分类与 toxic/non-toxic 二分类两个视角），不是 ASR。详见 [`docs/content_safety_track.md`](docs/content_safety_track.md)。

```powershell
# 离线确定性基线（TF-IDF + LogisticRegression，零 API 成本，默认）
python -m llm_security_platform.run_content_safety_benchmark
# 多数类下限（健全性参照）
python -m llm_security_platform.run_content_safety_benchmark --classifier majority
# 可选：用目标模型做分类器（mock / ollama / openai_compatible，建议配 --limit 抽样）
python -m llm_security_platform.run_content_safety_benchmark --classifier llm --provider mock --limit 200
# 质量门禁（基线需超过多数类下限并达到 macro-F1 阈值）
python -m llm_security_platform.content_safety_gate
```

当前离线基线在 1,924 条 test 上的结果（仅代表该基线与该数据集，不代表任何真实模型安全水平）：三分类 accuracy ≈ 0.67、macro-F1 ≈ 0.66，多数类下限 macro-F1 ≈ 0.19。`offensive` 与 `hatespeech` 边界模糊（offensive F1 ≈ 0.52）是该数据集已知难点。

**LoRA 微调判定器（可选，需 CUDA 环境，依赖见 `requirements-ft.txt`）**：用 LoRA 微调 Qwen3-1.7B 做三分类（仅训练 0.37% 参数，单卡约 15 分钟），在与 LLM Judge 相同的 300 条分层样本上 macro-F1 0.685（qwen3:8b 零样本 0.495），正常内容误判率由 70% 降到 18%，代价是有害召回由 0.99 降到 0.815。同一 adapter 换成 4-bit NF4 推理，峰值显存 -51%，完整 test 集 macro-F1 基本不变（0.686 → 0.688），但单条时延增加约 9%–14%。细节与取舍见 [`docs/content_safety_track.md`](docs/content_safety_track.md)。

```powershell
python -m llm_security_platform.run_lora_safety_judge
```

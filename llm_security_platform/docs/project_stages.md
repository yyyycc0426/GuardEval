# Delivery Scope / 项目交付范围

## Resume Deliverable Version / 简历可交付版

必须完成：

1. 阶段 0：威胁模型、成功标准、标注规范与版本追踪。
2. 阶段 1：可运行安全评测基线。
3. 阶段 2（已完成）：两个本地真实模型、64 条双语用例、数据集版本管理和多维模型对比报告。
4. 阶段 3（基础闭环已完成）：规则、语义分类器、LLM Judge、冲突路由和人工复核队列。
5. 阶段 4（已完成）：输入、RAG、输出防御策略，决策审计、九组消融实验和防全拦截质量门禁。
4. 阶段 3：规则、语义分类器、LLM Judge 与人工复核。
5. 阶段 4：至少三种可独立开关的防御策略和消融实验。
6. 基础管理页面：创建任务、查看指标和检查失败案例。

## Bonus Engineering Version / 工程加分版

- PostgreSQL 与 Alembic。
- Celery 与 Redis。
- 完整 RBAC、审计日志和人工审核队列。
- Prometheus、Grafana、Docker Compose。
- OCR 图片输入和图片敏感信息检测。

核心实验优先于基础设施。真实模型结果、可靠标签和防御权衡未完成前，不以环境组件数量作为项目完成度。

## Content-Safety Track / 内容安全评测轨道（已完成）

独立于阶段 0–6 攻防主线的一条**内容分类评测轨道**，用公开真人标注基准为判定器做外部效度校准。

- 数据：HateXplain（20,148 条，normal/offensive/hatespeech，多数票 gold，官方 8:1:1 划分，sha256 锁定）。
- 分类器对照：TF-IDF 离线基线、本地 qwen3:8b、云端 gemini-2.5-flash（Vertex AI + ADC）。
- 指标：accuracy / macro-F1 / 混淆矩阵（三分类 + toxic 二分类），失败调用单独计数并排除；外加 token 级 rationale 解释性评测（模型证据词 vs 真人标注）。
- 发现：本地与云端 LLM 一致过度拦截（有害召回 ~98–99%，正常召回 0.30–0.47）。
- 入口：`run_content_safety_benchmark.py`、`run_rationale_benchmark.py`、`content_safety_gate.py`；详见 [`content_safety_track.md`](content_safety_track.md)。

与攻防管线刻意分离：任务是内容分类、指标不是 ASR；它给平台原有的自建攻击样本提供了公开数据的外部效度。

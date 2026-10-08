# LLM/RAG 安全评测平台 Python 源码解析

这是一套基于当前仓库代码、测试和运行产物编写的中文源码学习材料。目标是让你能够从项目定位讲到 API、数据、异步任务、防御、Judge、人审、可靠性、安全、部署和证据边界。

技术名、函数名、接口路径和配置项保留英文。每章均区分代码存在、自动化测试、Mock、真实模型、容器/云运行与真实业务效果，不把项目包装成生产安全网关。

## 统一章内结构

每章都按同一条阅读路径组织，左侧目录可以直接展开到具体类型、步骤和实现：

```text
模块概览
→ 核心类型
→ 主流程走读
→ 内置实现（Provider、Queue、Policy、Detector、路由或页面模块）
→ 关键机制
→ 失败流程与边界条件
→ 测试与证据
→ 面试追问
→ 小结
```

不适合“内置工具”表述的章节会换成准确名称，例如“内置 Provider”“核心路由”“内置防御策略”“内置检测器”“核心数据表与 Store 方法”，不会把项目误写成 Agent Tool Calling 框架。

## 总览

- [00：LLM/RAG 安全评测平台主链路总览](00_overview.md)

## 第一部分：认识项目与安全问题

1. [初识 LLM/RAG 安全评测平台](01_project_positioning.md)
2. [Prompt Injection、Jailbreak 与 RAG 泄露](02_security_threats.md)
3. [威胁模型与安全边界](03_threat_model.md)
4. [总体架构与端到端数据流](04_architecture_data_flow.md)

## 第二部分：API、Schema 与数据基础

5. [FastAPI 应用入口与路由系统](05_fastapi_routes.md)
6. [Pydantic Schema 与统一数据协议](06_pydantic_schemas.md)
7. [攻击数据集、标签与版本管理](07_dataset_labels_versions.md)
8. [数据库模型、迁移与持久化设计](08_database_persistence.md)
9. [多租户数据隔离与租户配置](09_multitenancy.md)

## 第三部分：Provider、队列与执行引擎

10. [模型 Provider 抽象与适配器](10_model_provider.md)
11. [组件选择、任务分发与评测执行框架](11_component_selection_execution.md)
12. [Celery 与 Cloud Tasks 任务分发](12_task_queues.md)
13. [异步 Run 状态机](13_async_state_machine.md)
14. [Worker 与批量并发执行](14_worker_concurrency.md)
15. [单个 Case 的安全执行流水线](15_case_pipeline.md)

## 第四部分：防御、检测与判定

16. [PolicyEngine 防御策略编排](16_policy_engine.md)
17. [输入防御系统](17_input_defense.md)
18. [RAG 上下文与间接提示注入防御](18_rag_defense.md)
19. [输出防御与敏感信息脱敏](19_output_defense.md)
20. [规则检测器与统一判定协议](20_rule_detectors.md)
21. [语义分类与分层检测](21_semantic_layered_detection.md)
22. [LLM Judge 与结构化裁判](22_llm_judge.md)
23. [人工复核与数据回流闭环](23_human_review_loop.md)

## 第五部分：评测、可靠性与安全工程

24. [模型对比、防御消融与指标体系](24_metrics_ablation.md)
25. [幂等、重试、取消与故障恢复](25_idempotency_recovery.md)
26. [语义缓存、熔断器与成本护栏](26_cache_circuit_cost.md)
27. [认证、RBAC、限流与审计](27_auth_rbac_audit.md)
28. [Trace、日志、指标与报告生成](28_observability_reports.md)

## 第六部分：展示、部署与证据

29. [Web Console 与前后端业务闭环](29_web_console.md)
30. [配置、Docker、Cloud 部署与最终证据包](30_deployment_evidence.md)

## 推荐学习顺序

### 第一次理解项目

```text
00 → 01 → 02 → 04 → 05 → 11 → 15 → 24 → 30
```

### 准备后端工程面试

```text
05 → 06 → 08 → 09 → 10 → 12 → 13 → 14 → 25 → 28
```

### 准备 LLM/RAG 安全面试

```text
02 → 03 → 16 → 17 → 18 → 19 → 20 → 21 → 22 → 23 → 24
```

### 准备项目演示

```text
01 → 04 → 29 → 30
```

## 每章统一检查问题

读完一章后应能回答：

1. 这个模块解决什么问题？
2. 核心文件、类和函数在哪里？
3. 输入和输出是什么？
4. 正常调用链如何执行？
5. 失败时状态如何保存？
6. 为什么采用当前方案？
7. 替代方案和代价是什么？
8. 哪些行为有自动化测试？
9. 哪些结论只有 Mock 或历史产物？
10. 面试时哪些话不能夸大？

## 相关材料

- [项目证据包](../interview_evidence_package.md)
- [总文档导航](../INDEX.md)
- [面试学习包](../interview_mastery/README.md)

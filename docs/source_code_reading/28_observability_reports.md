# Python 源码解析第28章：Trace、日志、指标与报告生成

## 模块概览

### 可观测性目标

平台需要回答：

- 哪个请求创建了 run；
- 任务在哪个 Worker 执行；
- 哪个 case 失败；
- Provider/model 是什么；
- 延迟和 token 多少；
- 防御做了什么；
- 报告由哪版代码和数据产生。

## 核心类型

### Trace ID

`TracingMiddleware` 读取或生成 trace ID，写入 ContextVar 和响应 Header。

队列 payload 携带 trace ID，Worker 恢复后日志可以跨 API/队列关联。

### JSON 日志

`tracing.py:JSONFormatter` 结构化：

- timestamp；
- level；
- logger；
- message；
- trace ID；
- 可选上下文。

结构化日志便于检索；如果 message 本身包含 Prompt/secret，格式化并不能自动脱敏。

## 主流程走读

### API Metrics

`MetricsMiddleware` 记录请求数量和延迟。异常请求也应按状态码分类，否则指标会偏乐观。

## 内置指标与报告

### `MetricsStore`

维护：

- tenant token；
- Provider/model；
- token type；
- 其他运行指标。

`generate_prometheus_exposition()` 输出 Prometheus 文本。

### `/metrics`

接口需要 `audit:read`。这减少公开暴露租户、模型和成本标签的风险。

## 关键机制

### Provenance

`provenance.py` 记录：

- git commit；
- dataset version；
- policy version；
- inference config；
- defense config；
- run config hash。

这让结果能回答“用哪版代码、哪版数据、什么配置跑的”。

### Case Evidence

单 case 保存：

- original/effective prompt；
- raw/delivered response；
- detector；
- defense decisions；
- Judge；
- token/cost；
- evidence chain。

### Run Report

`build_async_report()` 聚合：

- total/completed/failed；
- ASR/raw compromise；
- normal task success/false positive；
- p50/p95；
- token/cost。

同步 `build_report()` 还包含更完整分组和防御指标。

### 百分位

异步报告对排序延迟计算 p50/p95。小样本百分位离散，不能过度解释。

### 导出

`GET /async-runs/{run_id}/export` 返回 run、report、cases 等 JSON。导出仍需要 tenant 和 `run:read`。

### GCS Store

Worker完成后尝试上传：

```text
reports/{tenant_id}/{run_id}_report.json
```

失败记录日志，并由本地 fallback 保留有限产物。数据库是主状态。

## 失败流程与边界条件

### 错误和边界

- GCS 失败不应把已完成 run 改成模型失败；
- metrics 内存状态不等于持久监控；
- Prometheus/Grafana Compose 存在不等于已配置告警 SLA；
- trace ID 不是安全凭证；
- raw evidence 需要访问控制和保留策略。

## 测试与证据

### 证据

- `tests/test_metrics.py`
- `docs/interview_evidence_package.md`
- `reports/browser_e2e_console_report.json`
- `llm_security_platform/reports/`。

## 面试追问

### Trace ID 和 Audit Log 有什么区别？

Trace ID 用于关联一次技术调用链；Audit Log 记录谁对什么业务对象执行了什么高影响操作，二者目的和保留要求不同。

### 为什么报告要记录代码和数据版本？

模型安全指标高度依赖 case set、Policy、Judge 和代码版本；没有 provenance 的百分比难以复现和比较。

## 小结

可观测性不是多打印几行日志，而是把请求、任务、case、模型、配置、决策和报告用稳定 ID 串起来。

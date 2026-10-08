# Python 源码解析第24章：模型对比、防御消融与指标体系

## 模块概览

### 为什么做对比

单个 run 的 ASR 没有参照。平台支持：

- 同模型无防御 vs 有防御；
- 不同模型同数据集；
- 不同 policy version；
- raw response vs delivered response。

## 核心类型

### 攻击指标

#### Raw Model Compromise Rate

```text
原始响应被判攻击成功的攻击 case
/
有有效结果的攻击 case
```

#### Delivered ASR

```text
最终交付响应仍被判攻击成功的攻击 case
/
有有效结果的攻击 case
```

#### Failure Rate

执行失败必须单列，不能从分母中静默消失。

### 良性指标

#### False Positive Rate

良性 case 被 block 或实质降级的比例。

#### Normal Task Success Rate

良性 case 完成预期任务的比例。

二者防止用全拒绝换取低 ASR。

### 防御分类指标

- precision；
- recall；
- F1；
- false negative rate；
- action counts；
- review rate。

需要明确正类定义、分母、人工标签来源。

## 主流程走读

### 同步报告

`app/evaluator.py:build_report()` 从结果计算完整 `EvaluationReport`。

### 异步报告

`production_store.py:build_async_report()` 聚合异步 case，字段较精简。两条路径指标集合不完全一致，读报告时要先确认来源。

## 内置评测方式

### 防御消融

`compare_policies()` 运行无防御和有防御配置，计算 ASR reduction。严谨比较要求：

- 同一 dataset version；
- 同一 Provider/model；
- 同一 inference config；
- 同一 Judge；
- 同一失败处理；
- 最好重复运行。

### 模型对比

`compare_models()` 接收多个 `ModelTarget`。比较的是“模型 + 配置 + Provider 路径”，不只是模型名称。

## 关键机制

### 性能与成本

- average latency；
- p50/p95；
- total tokens；
- estimated total cost。

缓存命中、Mock Provider 和并发设置会改变这些指标，不能跨环境直接比较。

### 分组

报告可按：

- risk type；
- language；
- attack method；

查看整体平均值掩盖的局部弱点。

## 失败流程与边界条件

### 不能证明什么

- 不能由一次 0 ASR 推断所有攻击安全；
- 不能把受控数据集指标当真实业务事故率；
- 不能把成本估算当正式账单；
- 不能把 Judge label 当人工真值；
- 不能忽略失败 case。

## 测试与证据

### 证据产物

- `stage_four_defense_ablation.json`
- `stage_4_5_real_model_ablation.json`
- `stage_two_model_comparison.json`
- `stage_three_detection_benchmark.json`

Mock、真实本地模型、云模型产物必须分级。

## 面试追问

### 面试回答

> 我最关注 raw compromise 和 Delivered ASR 的差异，同时用 benign false positive、normal task success 和 failure rate 防止“全部拒绝”或“全部失败”制造好看数字。

## 小结

指标必须绑定数据集、模型、配置、Judge 和失败处理。平台价值是让对比条件和证据可追踪，而不只是输出一个百分比。

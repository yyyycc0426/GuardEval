# Python 源码解析第7章：攻击数据集、标签与版本管理

## 模块概览

主要入口：

- `app/dataset.py:load_dataset`
- `app/dataset.py:validate_dataset`
- `app/seed.py:seed_cases`
- `app/api.py:import_dataset`
- `data/attack_cases_v2.json`
- `data/dataset_manifest.json`

### 为什么数据集比 Prompt 列表更重要

可复现评测至少需要：

- 稳定 case ID；
- 风险类型；
- 攻击方法；
- 成功与安全指示器；
- 良性对照；
- 语言和严重度；
- 数据集版本；
- holdout 规则。

如果只保留零散 Prompt，防御前后比较会因样本变化失去意义。

## 核心类型

### 样本结构

典型 case：

```json
{
  "case_id": "atk-001",
  "risk_type": "prompt_injection",
  "prompt": "...",
  "success_indicators": ["..."],
  "metadata": {
    "attack_method": "direct_injection",
    "severity": "high",
    "language": "en"
  }
}
```

`success_indicators` 是规则判定证据之一，不是唯一真值。

## 主流程走读

### 数据加载

`load_dataset(path)` 读取 JSON；`validate_dataset()` 检查 case 数量、字段和良性比例。API 导入还用 `DatasetImport` 限制最大 case 数。

## 内置数据组成

### 良性样本

`risk_type="benign"` 用于计算：

- false positive rate；
- normal task success rate；
- 防御是否过度拒答。

没有良性样本的零 ASR 可能只是“全部拦截”。

### Dataset Manifest

Manifest 应记录：

- dataset version；
- case 数量；
- 风险类型分布；
- 语言/方法分布；
- 生成或来源说明；
- hash 或版本标识。

仓库中存在 manifest，但真实第三方数据授权和长期治理需要单独核对。

### Seed 流程

`seed_cases()` 将默认数据集写入 tenant 范围。它适合本地演示和测试初始化，不等于生产数据同步服务。

### 导入流程

```text
POST /datasets/import
→ admin:write
→ DatasetImport 校验
→ dataset version
→ 保存每个 case
→ 审计记录
```

重复 case 的更新/覆盖语义要以 `db.save_attack_case()` 当前实现为准，不能假设拥有完整数据版本回滚。

### Holdout

`docs/holdout_and_review_protocol.md` 规定冻结 holdout 的目标：避免用同一批样本不断调规则，再把结果当泛化能力。

安全表述：

> 在指定冻结 holdout 和配置下得到某项指标。

不安全表述：

> 平台对未知攻击也保持同样效果。

### 标签来源

标签可能来自：

- case 定义；
- 规则 Detector；
- LLM Judge；
- 人工复核；
- 内容安全公开数据集标签。

这些来源的可信度不同，报告必须说明最终标签由谁确定。

## 失败流程与边界条件

### 数据污染风险

- 测试样本进入训练或规则调优；
- success indicator 直接出现在防御规则；
- Mock Provider 按已知 marker 返回；
- 人审结果回流后未重新划分 holdout；
- 不同 dataset version 混合比较。

## 测试与证据

### 测试证据

- `tests/test_dataset.py`
- `tests/test_stage_three_dataset.py`
- `tests/test_holdout_dataset.py`
- `tests/test_data_loopback.py`

## 面试追问

### 面试回答

> 我把 case ID、risk type、attack method、success indicator、benign 对照和 dataset version 都保存下来。这样报告能按风险和方法分组，也能解释结果来自哪一版数据。

## 小结

数据集决定 benchmark 的上限。代码跑通不代表评测可信；只有样本边界、版本、标签和失败处理清楚，指标才可解释。

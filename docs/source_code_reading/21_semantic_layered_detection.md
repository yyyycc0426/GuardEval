# Python 源码解析第21章：语义分类与分层检测

## 模块概览

### 为什么要分层

规则检测快但覆盖有限，LLM Judge 灵活但有成本和不稳定性。分层检测把：

- 输入规则；
- 响应规则；
- 语义分类；
- LLM Judge；
- 人工复核；

组合成不同成本和可信度的证据。

## 核心类型

### 语义分类器

`app/semantic_classifier.py` 包含：

- `SentenceTransformerEmbedder`
- `SemanticArtifact`
- `SemanticRiskClassifier`

它将文本映射到向量或分类空间，输出风险 finding。

### Artifact

语义模型需要明确：

- 模型路径；
- 训练/校准数据；
- label；
- 阈值；
- 版本；
- 加载失败行为。

仅存在类定义不代表生产环境已加载真实语义模型。

## 主流程走读

### 分层入口

`app/layered_detection.py:assess_response` 接收：

- case；
- model response；
- Judge；
- optional semantic classifier；
- sample rate；
- tenant。

### 执行顺序

```text
input rule
→ response rule
→ optional semantic
→ Judge
→ conflict detection
→ review routing
→ final assessment
```

## 内置分层机制

### Spot Check

`_sample_for_review()` 对部分非高风险结果抽样，让系统能发现低风险路径中的系统性漏报。

抽样率只能控制复核量，不能保证统计代表性，除非有明确采样设计。

### 最终字段

`LayeredAssessment` 保存：

- rule findings；
- semantic finding；
- Judge；
- conflicts；
- review reasons；
- final attack success；
- final outcome。

### 未配置语义模型

`case_execution.py` 的 evidence chain 可记录：

```text
semantic_detection=None
semantic_status=not_configured
```

这比伪造一个低风险结果更诚实。

### 错误路径

- 模型文件不存在；
- Embedding 依赖不可用；
- 输出维度不一致；
- classifier 未校准；
- tenant artifact 混用；
- 多层结果冲突。

## 失败流程与边界条件

### 冲突

典型冲突：

- 规则认为安全，Judge 认为攻击成功；
- 规则命中 marker，但 Judge 认为是拒答引用；
- 语义模型高风险，规则没有 evidence；
- Judge 高置信但没有 evidence quotes。

冲突本身是人审理由，不应简单用后一个结果覆盖前一个。

## 测试与证据

### 测试

- `tests/test_semantic_classifier.py`
- `tests/test_advanced_upgrades.py`
- `tests/test_finalize_real_model_review.py`

## 面试追问

### 面试回答

> 我没有把 Judge 当唯一真值。系统保留规则、语义和 Judge 的独立 finding，发生冲突或低置信时进入人审。

## 小结

分层检测的价值是显式暴露不同检测器之间的不确定性，而不是隐藏差异后给出一个看似确定的分数。

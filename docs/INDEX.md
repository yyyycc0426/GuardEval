# 📖 文档阅读指南（从这里开始）

> 新增源码解析系列：[`source_code_reading/README.md`](source_code_reading/README.md)  
> 目前包含 `00` 总览和 `01—30` 章完整源码学习材料，覆盖项目定位、威胁模型、FastAPI、Schema、数据集、数据库、多租户、Provider、异步任务、防御、检测、Judge、人审、可靠性、安全、可观测性、Console、Docker/Cloud 与证据边界。

> 文档看着多,其实只有**两摊**:
> - **🟦 项目文档** — 给别人看、给自己复习用(在 `docs/` 和 `llm_security_platform/docs/`)
> - **🟥 面试材料** — 只给自己用,一套放在 `docs/interview_mastery/`(已 gitignore,不公开)
>
> **不用记几十个文件。看下面的"按场景阅读路径",对号入座,只读那 2–4 个就够。**

---

## 🚦 按场景:你现在想干嘛?

### 场景 1｜10 分钟快速回忆"项目是什么"（最常用）
按顺序读 3 个:
1. [`../README.md`](../README.md) — 一句话定位 + 架构图 + 截图 + 结果表
2. [`interview_mastery/01_project_big_picture.md`](interview_mastery/01_project_big_picture.md) — 用户/痛点/闭环/边界
3. [`../llm_security_platform/docs/content_safety_track.md`](../llm_security_platform/docs/content_safety_track.md) — 最新亮点(内容安全轨道)

### 场景 2｜准备面试（重点看 interview_mastery,见下方专门的阅读顺序）
→ 跳到本文 **「📂 interview_mastery 文件夹怎么读」**。

### 场景 3｜面试官要抠技术细节,我去翻底牌
按需查这几个(不用通读):
- [`../llm_security_platform/docs/threat_model.md`](../llm_security_platform/docs/threat_model.md) — 攻击者/资产/范围
- [`../llm_security_platform/docs/success_criteria.md`](../llm_security_platform/docs/success_criteria.md) — 攻击成功怎么判
- [`../llm_security_platform/docs/defense_policy.md`](../llm_security_platform/docs/defense_policy.md) — 三层防御
- [`advanced_architectural_deep_dive.md`](advanced_architectural_deep_dive.md) — 架构深挖

### 场景 4｜招聘方/别人第一次看我的仓库
只需 [`../README.md`](../README.md)(里面会指回这份 INDEX)。其余文档他们按需点。

---

## 📂 interview_mastery 文件夹怎么读（19 个文件,排好序了）

> 别从头到尾 01→18 硬啃。按下面 4 步走,**标 ⭐ 的先读,标"查"的当字典、标"跳"的不用看**。

**第 1 步 · 把项目讲清楚(基础,先读)**
- ⭐ `01_project_big_picture.md` — 项目全景
- ⭐ `02_architecture_map.md` — 架构地图(含内容安全平行轨道)
- `04_main_flows_step_by_step.md` — 主流程拆解
- `03_code_walkthrough.md` / `05_technical_deep_dive.md` — 查(要讲代码时再看)

**第 2 步 · 形成你的"开口讲法"**
- ⭐ `17_mock_interview_content_safety.md` — **最重要**:开场 30 秒/2 分钟口播稿 + 多轮追问模拟
- `06_interview_story.md` — 项目故事线

**第 3 步 · 刷问答(临考重点)**
- ⭐ `13_interview_battlefield_guide.md` — 实战临场话术
- ⭐ `15_extreme_interview_deep_dive_bank.md` — 高压深挖题库
- `07_interview_qa.md` — 高频问答
- `14_deep_dive_interview_strategy.md` — 查(很长,409 行,当字典查,别通读)
- `11_technical_deep_dive_supplement.md` / `12_advanced_engineering_hidden_gems.md` — 查(想加技术亮点时翻)

**第 4 步 · 简历 & 收尾**
- ⭐ `18_resume_bullets_proj4.md` — 简历条目,直接抄
- `16_prototype_vs_production_comparison.md` — 防过度承诺(被问"离生产多远"时)
- `08_self_check_quiz.md` — 考前自测

> 一句话:**面试前主要读 `01 02 17 13 15 18` 这 6 个,其余按需查。**

---

## 🗂️ 其余文档:知道在哪即可,不用通读

### 🟦 技术核心(`llm_security_platform/docs/`)
`content_safety_track.md`(新亮点)· `threat_model.md` · `defense_policy.md` · `success_criteria.md` · `project_stages.md` · `labeling_guide.md` · `holdout_and_review_protocol.md`

### 🟦 开发证据 / 阶段报告(查证据用,不用天天看)
`stage_two/three/four/five/six_report.md` · `*_acceptance.md` · `stage_4_5_real_model_ablation_report.md` · `stage_5_6_fault_drill.md` · `security_redteam_report.md` · `stage_six_demo_script.md`

### 🟦 运维 / 安全 / 架构(根 `docs/`)
`advanced_architectural_deep_dive.md` · `agent_fallback_policy.md` · `proj4-threat-model.md` · `security_best_practices_report.md` · `rbac_matrix.md` · `cloud_release_runbook.md` · `cloud_e2e_smoke_test.md` · `specs/email_alert_notification_spec.md`

---

**记住一件事:迷路了就回到这份 `docs/INDEX.md`。**

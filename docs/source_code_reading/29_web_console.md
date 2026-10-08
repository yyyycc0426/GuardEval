# Python 源码解析第29章：Web Console 与前后端业务闭环

## 模块概览

### Console 定位

`llm_security_platform/web/` 是静态内部操作台，用于演示和查看评测证据。它不是完整商业 SaaS 前端。

## 核心类型

### 文件

- `index.html`：页面结构；
- `styles.css`：布局与状态样式；
- `app.js`：API 调用、状态和 DOM 更新。

## 主流程走读

### 连接

用户输入 API base/key，Console 调用 `/health` 和 `/cases` 验证连接。

错误 key 应得到认证失败；浏览器证据记录了先失败、后使用 analyst key 成功。

### 加载 Cases

`GET /cases` 返回 tenant 可见攻击样本，Console 展示数量和选择状态。

### 创建 Run

Console 构造 `EvaluationRunCreate`：

- name；
- Provider/model；
- defense policy；
- case IDs；
- concurrency；
- inference config。

调用 `POST /async-runs` 后保存 run ID。

### 轮询

通过：

```text
GET /async-runs/{run_id}
```

周期性更新：

- status；
- progress；
- completed/failed；
- report；
- cases。

## 内置页面模块

### 结果展示

重点字段：

- risk type；
- status；
- raw/delivered response；
- attack success；
- defense decisions；
- review required；
- token/cost；
- latency。

### 报告导出

Console调用 export 接口下载 JSON。认证信息应放 Header，不应长期放 URL query。

### RBAC 展示

analyst 可创建和查看 run，但访问 `/audit-logs` 得到 403。该负向行为是权限证据，不是 UI 故障。

## 失败流程与边界条件

### 已知 UX 问题

重复提交 409 的 detail 对象显示为 `[object Object]`，属于前端错误格式处理问题。

### 安全问题

#### `innerHTML`

若把服务端或模型文本直接拼入 DOM，可能形成 XSS。必须确认转义路径；当前代码存在多处 `innerHTML`，不能声称生产前端已完成安全加固。

#### URL Token

export query token 可能进入浏览历史、代理和日志。内部演示应避免真实高权限凭据。

### 取舍

静态 Console：

- 部署简单；
- 易展示证据；
- 不需要前端构建链；
- 状态管理、组件复用和安全编码保障较弱。

## 测试与证据

### 浏览器 E2E

`reports/browser_e2e_console_report.json` 记录：

- Chromium headless；
- 113 cases loaded；
- mock baseline async run；
- 113/113 completed；
- failed cases 0；
- analyst audit 403；
- 截图路径。

这是 Mock Provider 的业务链 E2E，不是 113 次真实模型调用。

### 截图

- `output/playwright/console_initial.png`
- `console_analyst_cases.png`
- `console_overview_after_run.png`
- `console_current_after_run.png`

## 面试追问

### 为什么采用静态 Console？

它能以较低复杂度展示创建 run、轮询和证据链，适合内部试点；代价是组件化、状态管理和前端安全保障弱于完整 React/Vue 工程。

### 浏览器 E2E 能证明真实模型效果吗？

不能。本次浏览器产物使用 Mock Provider，证明前端到异步报告闭环和 RBAC 负向行为，不证明真实模型安全率。

## 小结

Console 证明了用户可以完成“加载 case—创建 run—轮询—查看报告”的闭环。它是证据展示层，而不是项目安全能力的唯一来源。

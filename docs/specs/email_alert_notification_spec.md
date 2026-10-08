# 工程规范：邮件报警通知功能设计

## 一、 建设目标 (Objective)
本功能旨在当平台在评测过程中检测到**大模型被攻破（Model Compromise）**或**租户 Token 预算耗尽（Budget Depletion）**时，自动向租户管理员发送异步电子邮件报警通知。这将帮助企业安全团队和运维团队缩短对越狱泄漏和拒绝钱包服务（DoW）财务风险的响应时间（MTTR）。

### 核心业务场景
1. **大模型失守报警**：当评测引擎发现某条测试用例的判定结果为 `attack_success = True` 且风险类型达到预设的高危评级时，系统自动发送报警邮件。
2. **预算耗尽预警**：当租户的每日已用 Token 数达到配置限额（例如日配额的 90%）或者单次任务预分配申请因超限被拦截时，自动通知管理员进行扩容。
3. **后台异步分发**：邮件发送过程由 Celery 异步队列在后台独立消费，绝对不会阻塞核心评测 Harness 线程或 FastAPI 的 HTTP 响应。

---

## 二、 技术栈选型 (Tech Stack)
* **核心语言与框架**：Python 3.12, FastAPI, Celery 5.4.
* **邮件协议底层库**：Python 标准库 **`smtplib` 与 `email.mime`**。
  * *选型考量*：遵循“依赖纪律”，不引入如 SendGrid, Resend 等重量级第三方 SDK，保持系统轻量，规避许可证风险与外部依赖安全漏洞。
* **模板引擎**：标准 Python 字符串模板（`string.Template`），防范模板注入（SSTI）安全漏洞。

---

## 三、 运行与测试命令 (Commands)
* **运行邮件功能测试套件**：
  ```bash
  .venv\Scripts\pytest llm_security_platform/tests/test_email_alerts.py
  ```
* **手动测试发送命令（CLI 工具）**：
  ```bash
  .venv\Scripts\python -m llm_security_platform.scripts.send_test_email --to admin@example.com
  ```

---

## 四、 存储库目录变更 (Project Structure)

本功能将修改和创建以下代码文件：

```
llm_security_platform/
├── app/
│   ├── config.py                 # [修改] 新增 SMTP 相关的配置项与默认值
│   ├── tasks.py                  # [修改] 新增 send_alert_email_task 异步 Celery 任务
│   ├── notifications.py          # [新建] 封装 SMTP 客户端发送逻辑与 HTML 模板拼接
│   └── cost_guardrail.py         # [修改] 预算超限时触发异步邮件调度
├── tests/
│   └── test_email_alerts.py      # [新建] 针对邮件逻辑、异常捕获与 mock 连接的单元测试
└── scripts/
    └── send_test_email.py        # [新建] 用于系统初次部署测试的命令行发送工具
```

---

## 五、 代码设计规范 (Code Style)

采用类型安全、职责清晰的面向对象风格，并对网络 I/O 设置硬性超时控制：

```python
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging

logger = logging.getLogger("llm_security_platform.notifications")

def send_smtp_email(to_address: str, subject: str, html_content: str, config: dict) -> bool:
    """
    使用内置 smtplib 发送带超时硬卡点的 HTML 报警邮件
    """
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config["SMTP_FROM"]
    msg["To"] = to_address
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        # 设置 10 秒硬性超时，防止内网防火墙导致线程挂起
        with smtplib.SMTP(config["SMTP_HOST"], config["SMTP_PORT"], timeout=10) as server:
            if config.get("SMTP_USE_TLS"):
                server.starttls()
            if config.get("SMTP_USER") and config.get("SMTP_PASSWORD"):
                server.login(config["SMTP_USER"], config["SMTP_PASSWORD"])
            server.sendmail(config["SMTP_FROM"], [to_address], msg.as_string())
        logger.info(f"成功向 {to_address} 发送了安全审计报警邮件。")
        return True
    except Exception as exc:
        # 安全脱敏：异常日志中绝对不打印 SMTP_PASSWORD 凭证
        logger.error(f"向 {to_address} 发送 SMTP 邮件失败: {exc}")
        return False
```

---

## 六、 测试策略 (Testing Strategy)

1. **测试框架**：`pytest`
2. **Mock 隔离机制**：使用 `unittest.mock.patch("smtplib.SMTP")` 拦截所有真实的外部网络连接，重点验证邮件标题、收件人列表以及 HTML 内容中是否渲染了正确的 `run_id` 和风险状态。
3. **关键覆盖用例**：
   * 验证 `execute_run` 发现 `attack_success=True` 时是否正确调用了 `send_alert_email_task.delay()`。
   * 验证在数据库级别触发 `BudgetExceededError` 时是否触发了预警邮件任务。
   * 验证当 SMTP 服务器宕机时，Celery 任务能妥善捕获错误并写入错误日志，不导致主业务流程挂起。

---

## 七、 实施边界与纪律 (Boundaries)

* **必须做 (Always do)**：
  - 所有邮件发送请求必须通过 Celery 以 **`.delay()` 异步非阻塞** 形式派发。
  - 在所有日志中对密码信息做强脱敏过滤，禁止将其输出至系统控制台或审计日志。
  - 对用户配置的通知邮箱地址执行严格的格式正则校验。
* **请示后做 (Ask first)**：
  - 在租户配置数据库表中添加新的邮件通知订阅名单关系字段。
  - 更改全局 `config.py` 加载优先级引入新的复杂配置依赖项。
* **禁止做 (Never do)**：
  - 严禁在同步 API 请求线程中直接建立 SMTP 连接，防止超时导致用户请求挂起。
  - 严禁将明文 SMTP 账号密码硬编码在任何代码中。

---

## 八、 验收与成功指标 (Success Criteria)
1. **越狱报警验证**：运行包含越狱用例且不带防御策略的评测（ASR == 1.0），验证 Celery 任务日志中显示 `send_alert_email_task` 被成功触发并完成 Mock 发送。
2. **限额报警验证**：触发租户 Token 日限额扣减越权时，API 返回 402 错误的同时，验证邮件发送队列新增了一条 Budget Depletion 的预警任务。
3. **回归测试通过**：新增的测试套件 [test_email_alerts.py](file:///d:/AI_Projects/proj4/llm_security_platform/tests/test_email_alerts.py) 100% 通过，且系统原有的 135 个测试用例无任何退化。

---

## 九、 待澄清的开放性问题 (Open Questions)
* **报警轰炸频控**：如果在高并发评测下，一个 Run 中有 50 条测试用例被判定为越狱成功，系统是否会连续发送 50 封邮件导致邮件轰炸？我们是否应当引入基于 Redis 的租户级频控机制（例如：同一个租户或同一评测 Run 在 5 分钟内最多只发送 1 封邮件，后续报警合并发送）？

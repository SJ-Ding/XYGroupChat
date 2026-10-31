# 江苏省人民医院 / 南京鼓楼医院模拟器

包含两家医院的官网式模拟页面、按院隔离的号源/预约数据和 Playwright 浏览器执行器。医院名称与地址来自高德公开数据；医生、号源、费用、预约和病历均为虚构演示数据。模拟器由小艺主服务同源托管。

## 启动

在项目根目录运行：

```powershell
.\start.ps1
```

打开：

- 小艺聊天：`http://localhost:8000/?user=child`
- 模拟医院：`http://localhost:8000/hospital/`

也可以在聊天中说“打开模拟医院”，小艺会调用 `hospital_simulator` 工具。预约任务使用本机 Chrome 或 Edge 显示操作过程；如系统没有浏览器，可运行：

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```

## 聊天工具

`hospital_simulator` 支持查询与挂号动作：

| 动作 | 用途 |
| --- | --- |
| `open` | 打开模拟医院首页 |
| `nearby` | 根据家庭地址查询附近医院 |
| `query` | 只查询号源，不启动浏览器 |
| `book` | 启动自动预约任务并走到提交前的核对页 |
| `status` | 查看当前用户最近任务的真实状态 |
| `approve` | 仅由任务卡片“确认并继续”触发最终提交 |
| `cancel` | 用户明确要求时终止任务 |

`book` 走到核对页后会发送预约卡片。家人点击“确认并继续”才会提交；锁号后仍在本人收银台完成模拟支付。`approve` 不开放给聊天模型自行调用。两家医院分别使用 `/hospital/apps/h-jsph/` 和 `/hospital/apps/h-glyy/`，API 为 `/api/hospital/apps/{hospital_id}/`。

## 单独调试执行器

主服务启动后，可绕过聊天直接验证浏览器执行器：

```powershell
.\.venv\Scripts\python.exe hospital\run_web_task.py "预约骨科上午" --no-llm
```

`run_web_task.py` 只操作本机模拟页面；支付必须由本人完成。

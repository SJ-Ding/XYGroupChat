# 市第一人民医院模拟器

该目录由原 `D:\WorkSpace\hospital_backend` 迁移而来，包含虚构医院网页、预约数据与 Playwright 浏览器执行器。模拟器由小艺主服务同源托管，不再需要单独启动 Node 端口。

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

`hospital_simulator` 提供五种动作：

| 动作 | 用途 |
| --- | --- |
| `open` | 打开模拟医院首页 |
| `book` | 启动自动预约任务并走到提交前的核对页 |
| `status` | 查看当前用户最近任务的真实状态 |
| `approve` | 仅由任务卡片“确认并继续”触发最终提交 |
| `cancel` | 用户明确要求时终止任务 |

`book` 走到核对页后会发送预约卡片。家人点击“确认并继续”才会提交；也可以直接在浏览器中操作。`approve` 不开放给聊天模型自行调用。所有动作只访问本机 `localhost`/`127.0.0.1`，预约数据为虚构演示数据。

## 单独调试执行器

主服务启动后，可绕过聊天直接验证浏览器执行器：

```powershell
.\.venv\Scripts\python.exe hospital\run_web_task.py "预约骨科上午" --no-llm
```

`run_web_task.py` 不自动授权超过 50 元的费用；需要人工修改状态或通过聊天明确授权。

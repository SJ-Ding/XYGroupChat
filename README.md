# 小忆 · 家庭群聊与记忆 Agent

Python FastAPI + SQLite + React/TypeScript 的本地单进程 MVP。爸爸、妈妈、小宇通过 URL 指定身份进入同一家庭群，无需登录或密码。小忆可以看图、检索和沉淀家庭记忆、管理待办与群内提醒。

## 快速启动（Windows）

需要 Python **3.10+（推荐 3.12）**、Node.js **20.19+ 或 22+**、npm。

```powershell
git clone git@github.com:SJ-Ding/XYGroupChat.git
cd XYGroupChat
.\start.ps1
# 或双击 start.cmd
```

直接打开对应链接：

- 爸爸：http://localhost:8000/?user=dad
- 妈妈：http://localhost:8000/?user=mom
- 子女：http://localhost:8000/?user=child

没有 `user` 参数时默认进入子女身份，并将 URL 补为 `?user=child`。同一浏览器的不同标签页可使用不同身份；身份不保存在 Cookie 或本地存储中。群成员面板提供切换链接。非法身份会显示成员选择，不会静默切换。

脚本安装依赖、构建前端、初始化数据库并启动服务。首次安装需要联网。若 PowerShell 限制执行脚本，可直接使用 `start.cmd`。

需要演示聊天与记忆时运行 `start.ps1 -Demo`，或手动 `python -m backend.demo`（需使用项目虚拟环境）。演示记录均带有 **【演示】** 标记，不会触发后台记忆提取。默认不添加虚构的家庭事实。

局域网使用 `start.ps1 -Bind 0.0.0.0`，其他设备访问电脑的局域网 IP 和 8000 端口。手机与电脑需在同一网络。默认只监听本机；此版本不包含公网注册、HTTPS 网关或多进程部署。

## 模型配置

服务端启动时读取根目录 `.env`，模板见 `.env.example`。首次启动会复制模板，请在本地填写自己的 Key 后重启。`.env` 在 `.gitignore` 中，前端不会接收它，仓库不包含 API Key。

```dotenv
DEEPSEEK_API_KEY=在本地填写
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
DATA_DIR=data
```

变更模型配置后重启。界面中的 Agent 名称、系统提示词、自主介入开关、观察窗口即时保存到数据库。REST、图片和 WebSocket 请求都显式携带同一 `user` 参数。此演示模式的身份由 URL 自行选择，访问者可切换为任意家庭成员。

模型适配器采用官方 OpenAI 兼容 Chat Completions 格式，支持图片块、JSON 判断和工具调用。实际可用模型及额度取决于账号。模型失败不会阻止家人聊天；设置页显示失败原因并可重试。

## 使用流程

### 查看 Agent 运行状态

点击左侧（手机端底部）的 **Agent**，或直接打开 `http://localhost:8000/?user=child&view=agent`。此页面每 2 秒自动刷新，展示调度器心跳、模型配置状态、当前执行阶段、排队/失败/已完成任务、自主观察窗口与候选回复、决策日志、已加载 Skill、最近工具执行和待发送提醒。

失败任务可在页面中重试，来源消息可跳回聊天查看；右上角仍可打开 Agent 设置。状态请求中断时会保留上次数据并提示，不会将旧数据误标为实时状态。模型密钥只显示“是否配置”，不做额外联网探测，也不返回密钥值。

1. 在三个标签页或设备分别打开 `?user=dad`、`?user=mom`、`?user=child`。
2. 群聊支持文字、最多四张图片、Enter 发送、Shift+Enter 换行、历史分页、断线补取和在线状态。
3. 输入 `@小忆 ` 后提问即可立即进入回复流程；附件和近期图片可用于看图。修改 Agent 名称后请使用新名称。
4. 普通消息在后台进行需求识别和稳定记忆提取。偏好和明确的长期约定可自动入库；一次性安排不会自动变成长期记忆。
5. 明确需求无人回应时立即准备候选回复，**从最后一条相关消息起等待30秒后才发送**。相关回应取消候选，需求变更重新计时，无关消息不重置；每个需求只自主跟进一次，全天启用。
6. 可明确要求：`@小忆 记住爸爸喜欢喝茶`、`@小忆 添加待办：爸爸周六买菜`、`@小忆 一分钟后提醒我们检查晚餐准备`。推测出的计划不会自动执行写入技能。
7. 家庭记忆侧栏支持检索、编辑、删除、修订记录及来源聊天定位。人工更正优先；删除后相同来源的自动提取会被抑制。

后台分析与生成需要模型网络请求；30秒是最早允许自主发送的时间，模型较慢时会继续等待。若较新消息分析失败，为避免发送过期候选，会暂停该群的自主跟进，直到重试成功。重启时恢复数据库中的任务并核验状态；运行服务才能触发定时提醒。

## 开发与测试

```powershell
# 后端（项目根目录）
.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
# 前端开发，另开终端
cd frontend
npm ci
npm run dev
# 构建前端
npm run build
# 后端测试，项目根目录
.venv\Scripts\python.exe -m pytest -q
```

Vite 在 5173 端口代理 `/api` 与 `/ws` 至 8000；生产构建由 FastAPI 同源托管。API 文档为 `/docs`。

## 结构与数据

- `backend/db.py`：SQLAlchemy 模型、SQLite WAL、版本化初始化迁移、账号和家庭群种子。
- `backend/app.py`：URL 身份解析、群成员范围、图片、REST API 与 WebSocket。
- `backend/agent.py`：群级串行分析、候选预生成、持久任务与唯一发送键、历史摘要。
- `backend/memory.py`：中文单字/双字 FTS5 检索、人工更正、修订与来源抑制。
- `backend/skills.py`：可信 Skill 注册与执行协议；扩展说明见 `skills/family/SKILL.md`。
- `frontend/src`：响应式聊天界面、记忆、待办、设置与成员切换。
- `tests`：隔离临时数据库及模拟模型；不消耗真实模型额度。

`data/family.db` 保存账号会话、群关系、消息、记忆和版本化应用记录，`data/uploads` 保存受群权限保护的图片。SQLite FTS5 是本地索引，无需 Redis、向量库或 Embedding 服务。迁移版本记录在 `schema_migrations`；后续表结构变更需增加显式迁移。备份请停止服务后复制整个 `data` 目录。

实际数据库与图片路径以 `.env` 的 `DATA_DIR` 为准。聊天记录、记忆数据库和上传图片均保留在本地，不随源码发布。

每条人类消息与分析任务同事务写入；消息先持久化再广播。客户端和 Agent 使用唯一键去重。群内生成配置按任务保存快照；设置修改会取消旧的待发候选。工具幂等结果与业务键共同处理重试。初版必须单进程运行，不要增加 `uvicorn --workers`。

本次验收与视觉对照记录见 [docs/QA.md](docs/QA.md)，包括 20 项自动化测试、三身份浏览器流程、真实 DeepSeek 记忆与看图调用，以及 30 秒自主跟进的实测结果。

家庭聊天和检索出的记忆会发送给配置的模型服务。此版提供群内共同记忆，不提供成员私密记忆、消息撤回、任意脚本 Skill、语音视频、外部日历或系统推送。

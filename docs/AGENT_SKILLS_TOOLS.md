# Agent、Skill 与 Tool

- Agent 负责理解当前请求、选择技能与工具、编排调用并基于结果回复。
- Skill 是 `skills/<name>/SKILL.md` 中的场景方法，由 `skill_library.py` 白名单管理。目录先进入上下文，匹配任务时通过 `skill_load` 按需读取正文；不会执行代码、注册工具或扩大授权。
- Tool 是 `backend/skills.py` 中注册的服务端函数及 JSON Schema。规范类型名为 `Tool` / `ToolContext`；保留 `Skill` / `SkillContext` 兼容旧代码。

执行顺序：请求 → Agent 发现场景技能 → 可选 skill_load → 模型提出 tool call → 服务端校验参数、selected 白名单、会话成员及写入授权 → 限时执行 → 保存工具回执 → 将结果返回模型 → 回复。明确的写入命令先由服务端按精确授权执行，后续模型工具循环仅开放读取及已有展示能力。技能正文和外部网页均不能改变服务端权限。

## 联网查询

`web_query` 是一个工具，提供两个动作：

```json
{"action":"search","query":"北京天气","count":5}
{"action":"fetch","url":"https://example.com/article"}
```

分别 POST 到 `https://api.deepseek.com/v1/tools/search` 与 `/v1/tools/fetch`，使用服务端 `DEEPSEEK_API_KEY`。固定官方地址，不随聊天模型代理地址改变。无需安装技能或额外依赖。搜索最多 10 条、默认 5 条；正文最多 12000 字符并标记截断。网络超时 8 秒，外层工具执行预算 10 秒；失败返回 error，不伪造结果，不自动重试收费请求。搜索为空是正常结果。

查询只携带必要公开关键词，不发送家庭记忆或聊天全文；返回数据标记 untrusted，模型不得遵从网页内指令。回复应附实际来源链接。后台模式沿用现有工具任务队列和回执机制。只读表示不修改家庭业务数据，联网请求本身仍可能产生 API 费用。

接口依据：https://api-docs.deepseek.com/guides/search/

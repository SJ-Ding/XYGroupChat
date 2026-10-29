# 家庭技能包

这些说明帮助开发者理解能力，不会作为脚本执行。技能只有在服务端 Python 注册后才可使用。

| 名称 | 使用时机 | 是否写入 |
|---|---|---|
| memory_search | 询问家人偏好、约定和过往事实时，先检索家庭记忆 | 否 |
| remember | 用户明确要求“记住……” | 是 |
| family_tasks | 列出待办；用户明确要求时创建或完成 | 创建/完成时写入 |
| group_reminder | 用户明确要求在未来时间提醒 | 是 |

提醒时间为 Unix 秒时间戳；使用群内发送，不发邮件或系统推送。自主跟进只能使用只读技能。

## 添加一个 Skill

在 `backend/skills.py` 或由它显式导入的可信模块中注册：

```python
from backend.skills import Skill, register, schema

async def family_greeting(context, arguments):
    return {"greeting": "祝家人们今天顺利！"}

register(Skill(
    name="family_greeting",
    description="生成一条家庭问候。",
    schema=schema({}),
    execute=family_greeting,
    writes=False,
))
```

执行上下文提供群 ID、发起成员 ID、源消息 ID、稳定运行 ID 和写入授权标记。执行器会验证 JSON Schema、成员资格、10 秒超时和运行级幂等缓存；每轮最多 6 个工具调用、最多 4 轮。

有副作用的自定义技能还必须用 `context.run_id` 与参数生成稳定业务键，以抵御进程在“已执行但缓存尚未保存”之间中断。不可注册任意 shell、文件执行或不受限网络访问工具。

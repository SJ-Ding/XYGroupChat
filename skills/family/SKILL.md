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

执行上下文提供会话 ID、发起成员 ID、源消息 ID、稳定运行 ID、已加载能力和精确动作授权列表。执行器会验证 JSON Schema、成员资格、工具及参数的授权、10 秒超时和运行级幂等缓存；每轮最多 6 个工具调用、最多 4 轮。个人空间使用服务端绑定的独立会话 ID，只能本人访问，不能读取到群上下文。

`Skill.instructions` 是可信服务端注册的操作步骤，按任务加载；`Skill.version` 标识版本。聊天任务的写入必须精确匹配 `context.grants` 中的工具名与完整参数，模型不能用 `allow_writes` 扩大授权。`grants=None` 仅保留给受信任的旧内部调用；新增代码必须传入明确列表，无授权时传空列表。

复杂目标通过任务规划或步骤表单先生成待审核任务，审核后执行。周期提醒、用药提醒和主题订阅通过“个人与提醒”管理；不使用一次性群提醒技能猜测周期或药物安排。模块说明见 `docs/HARNESS.md`。

有副作用的自定义技能还必须用 `context.run_id` 与参数生成稳定业务键，以抵御进程在“已执行但缓存尚未保存”之间中断。不可注册任意 shell、文件执行或不受限网络访问工具。

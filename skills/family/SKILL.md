# 家庭技能包

这些说明帮助开发者理解能力，不会作为脚本执行。技能只有在服务端 Python 注册后才可使用。

| 名称 | 使用时机 | 是否写入 |
|---|---|---|
| memory_search | 询问家人偏好、约定和过往事实时，先检索家庭记忆 | 否 |
| skill_load | 按目录名称加载当前需要的家庭场景操作说明 | 否 |
| remember | 用户明确要求“记住……” | 是 |
| family_tasks | 列出待办；用户明确要求时创建或完成 | 创建/完成时写入 |
| group_reminder | 用户明确要求在未来时间提醒 | 是 |

提醒时间为 Unix 秒时间戳；使用群内发送，不发邮件或系统推送。自主跟进只能使用只读技能。

## 渐进式场景技能

系统身份与规则、工具定义及工具操作约束常驻；场景技能在初始提示词中只提供名称和简短 description。模型匹配任务后调用 `skill_load({"name":"family-meals"})`，工具结果返回该技能正文，供当前生成过程使用。下一个请求重新从目录开始，不把此前正文加入聊天历史或家庭记忆。

可信目录定义于 `backend/skill_library.py`，正文位于对应 `skills/<name>/SKILL.md`。当前提供餐食采购、家务分工、家庭出行、学习辅导、日常照护、家庭预算、家庭沟通和居家安全八个技能。比如“半小时做一家三口的晚餐”加载 `family-meals`，“周末怎么分家务”加载 `family-chores`。普通闲聊不必加载；跨场景任务只加载实际需要的条目。

加载器只接受服务端目录中的名称，不接受路径、用户上传文件或任意代码；正文上限 6000 字符，受现有工具超时、成员权限、调用轮数和上下文预算控制。加载本身不修改 grants、可用工具或写入权限，建议清单不等于创建待办或设置提醒。工具结果中出现 error 时不能声称技能加载成功。

新增场景时，在可信目录添加名称与简短描述，在同名目录编写带 name/description 前置信息的 SKILL.md，再验证目录可发现、正文可加载且不会预先进入提示词。业务工具仍通过下述服务端注册流程添加，Markdown 不作为程序执行。

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

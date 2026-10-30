# 对话卡片接入

消息响应新增 `cards`（旧消息为空数组）。群聊前端通过 `/api/groups/{gid}/agent-tasks` 和 `/cards` 恢复任务与卡片状态，WebSocket `card_update` 携带 `id` 和 `version`。已有消息中的卡片也会更新，不能只用消息游标同步。

Agent 使用 `send_card(title, description?, items?)` 发送信息卡片，不生成业务按钮或执行授权。任务执行器自动创建和更新进度卡。信息项使用 `{label, value}`，金额是展示字符串，业务适配器负责提供实际业务结果。

可信 Python skill 可调用：

```python
from backend.skills import human_input
from backend.cards import update_progress

async def service(ctx, args):
    await update_progress(ctx.group_id, ctx.task_key, '已完成信息准备，等待审核')
    receipt = await human_input(ctx, 'review-v1', {
        'title': '请核对服务信息',
        'items': [{'label': '服务', 'value': '业务实际返回的信息'}],
        'fields': [{'key': 'contact', 'label': '联系人', 'required': True}],
        # 可选：amount，以及可信业务服务提供的 HTTPS links
    })
    contact = receipt['values']['contact']
    # 继续处理，receipt 同时记录 user_id 和 at。
```

`human_input` 首次调用会持久化请求并抛出 `HumanIntervention` 释放执行器；用户提交后，该步骤重入，同一个 request_key 返回持久化结果。不要捕获这个暂停异常。检查点前的外部副作用必须使用业务幂等键或单独拆分为已持久化的步骤，避免重入时重复办理。每个新的审核阶段使用新 request_key。

字段支持 text、number、select；select 需要 options。links 使用 `{label, url}`，仅允许 HTTPS。外链点击只记审计，不代表支付成功；业务适配器应以支付回执恢复后续流程。`request_intervention` 提供事务内底层接口，`human_input` 是建议使用的执行器接口。

操作接口：`POST /api/groups/{gid}/cards/{card_id}/actions`，提交 `action`、`version`、`request_id`，以及可选 `values` / `link_index`。服务端校验版本与当前允许动作，重复请求返回原实体最新状态，冲突返回 409，字段校验返回 422。卡片响应的 `actions` 是前端可显示的动作列表。群内成员可协作处理；个人命名空间不通过群接口暴露。

任务取消不会撤销已完成的外部动作。未知复杂类型的缺失参数通过现有任务管理入口补充；基础必填字段可以直接在卡片填写，随后单独审核授权。

"""Safe, durable execution summaries. Never persist model reasoning or raw data here."""
import asyncio
import time
import uuid
import logging
from contextvars import ContextVar

from .db import DB, Record, Message, get, put
from sqlalchemy import func, or_

reused_result = ContextVar("chain_reused", default=False)

LABELS = {'memory_search': '查询相关记忆', 'family_tasks': '处理家庭待办', 'skill_load': '加载场景技能', 'web_query': '联网查询', 'amap_mcp': '查询地点与路线', 'send_card': '准备结果卡片', 'hospital_simulator': '办理就医服务', 'medical_profile': '查询健康档案', 'remember': '保存记忆', 'group_reminder': '设置提醒'}

def tool_title(name, args):
    title = LABELS.get(name, '执行工具操作')
    actions = {
        'family_tasks': {'list':'查询家庭待办', 'create':'创建家庭待办', 'complete':'完成家庭待办'},
        'hospital_simulator': {'query':'查询就医号源', 'book':'办理预约挂号', 'status':'查询预约进度', 'cancel':'取消预约', 'confirm':'确认预约信息'},
        'amap_mcp': {'search':'查询地点', 'route':'查询路线'},
    }
    if isinstance(args, dict):
        action = args.get('action')
        if isinstance(action, str):
            title = actions.get(name, {}).get(action, title)
        if name == 'skill_load':
            from .skill_library import CATALOG
            if isinstance(args.get('name'), str) and args['name'] in CATALOG:
                title += '：' + args['name']
    return f'{title}（{name}）'


async def notify(gid, source):
    from .app import broadcast
    # Notifications contain no context or summaries and are safe for existing group sockets.
    try:
        await broadcast(gid, {'type': 'chain_update', 'source': source})
    except Exception:
        logging.getLogger(__name__).exception('执行链路通知失败')

async def start(gid, source, run, kind, title):
    key = str(uuid.uuid4())
    with DB() as db:
        task = get(db, 'run', gid, run) if run else None
        attempt = (task.data.get('attempt', 0) if task else 0) + 1
        put(db, 'chain', gid, key, dict(source=source, run_id=run or 'analysis', kind=kind,
            title=title, attempt=attempt, status='running', started=time.time(), ended=None, summary=''))
        db.commit()
    await notify(gid, source)
    return key

async def finish(gid, key, status='succeeded', summary='已完成'):
    with DB() as db:
        row = get(db, 'chain', gid, key)
        value = row.data
        value.update(status=status, ended=time.time(), summary=summary)
        row.set(value)
        db.commit()
    await notify(gid, value['source'])

async def model_call(agent, gid, source, run, phase, messages, **kwargs):
    key = await start(gid, source, run, 'model', '理解请求' if phase == 'analysis' else '整理回复')
    try:
        answer = await agent.call(gid, messages, **kwargs)
    except BaseException as exc:
        await finish(gid, key, 'cancelled' if isinstance(exc, asyncio.CancelledError) else 'failed', '调用已取消' if isinstance(exc, asyncio.CancelledError) else '模型调用失败')
        raise
    await finish(gid, key, summary='已确定下一步操作' if answer.get('tool_calls') else '已完成本轮处理')
    return answer

def query(gid, ids):
    with DB() as db:
        valid = {m.id for m in db.query(Message).filter(Message.group_id == gid, Message.id.in_(ids), Message.user_id != 0)}
        result = {str(i): {'steps': [], 'tasks': []} for i in valid}
        if not valid:
            return result
        rows = db.query(Record).filter_by(group_id=gid).filter(Record.kind.in_(['chain', 'run', 'trace']), or_(func.json_extract(Record.payload, '$.source').in_(valid), func.json_extract(Record.payload, '$.source_id').in_(valid))).order_by(Record.id).all()
        runs = {r.key:r.data for r in rows if r.kind == 'run'}
        def root(key):
            seen = set()
            while key in runs and runs[key].get('parent_run') and key not in seen:
                seen.add(key)
                key = runs[key]['parent_run']
            return key
        for row in rows:
            d = row.data
            source = d.get('source') if row.kind in ('chain', 'trace') else d.get('source_id')
            if source not in valid:
                continue
            target = result[str(source)]
            if row.kind == 'chain':
                target['steps'].append(dict(id=row.key, sequence=row.id, attempt=d.get('attempt', 1), task_id=root(d['run_id']), **{k:d.get(k) for k in ('run_id','kind','title','status','started','ended','summary')}))
            elif row.kind == 'run':
                target['tasks'].append(dict(id=row.key, status=d.get('status'), reply_status=d.get('reply_status')))
        # Older traces prove a model call occurred, but cannot reconstruct tool steps.
        for source, target in result.items():
            if target['steps']:
                continue
            for row in rows:
                d = row.data
                if row.kind == 'trace' and d.get('source') == int(source):
                    target['steps'].append(dict(id='history:'+row.key, sequence=row.id, attempt=1,
                        run_id=d.get('run_id'), kind='model', title='理解请求' if d.get('phase') == 'analysis' else '整理回复',
                        status={'done':'succeeded'}.get(d.get('status'), d.get('status', 'failed')),
                        started=None, ended=None, summary='历史调用；详细过程未记录'))
        return result

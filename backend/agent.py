import asyncio
import base64
import copy
import json
import logging
import time
import uuid
from collections import defaultdict
from .db import DB, DATA, Message, User, Record, get, put, records
from .memory import search, save_memory
from .model import Model
from .skills import SkillContext, tools, execute

class Agent:
    def __init__(self, broadcast, model=None, now=time.time):
        self.broadcast = broadcast
        self.model = model or Model()
        self.now = now
        self.locks = defaultdict(asyncio.Lock)
        self.running = set()
        self.pending = set()
        self.stopped = False
        self.executions = {}
        self.started_at = None
        self.last_tick = None
        self.scheduler_error = None

    def spawn(self, coro, key=None):
        if key and key in self.running:
            coro.close()
            return
        if key:
            self.running.add(key)
        task = asyncio.create_task(coro)
        self.pending.add(task)
        def done(t):
            self.pending.discard(t)
            if key:
                self.running.discard(key)
            if not t.cancelled():
                t.exception()
        task.add_done_callback(done)

    async def close(self):
        self.stopped = True
        for t in list(self.pending):
            t.cancel()
        await asyncio.gather(*list(self.pending), return_exceptions=True)

    def log(self, db, gid, reason, source=None):
        put(db, 'log', gid, str(uuid.uuid4()), {'reason': reason, 'source': source, 'at': self.now()})

    async def send(self, gid, content, key):
        with DB() as db:
            old = db.query(Message).filter_by(group_id=gid, user_id=0, client_id=key).first()
            if old:
                return old.id
            m = Message(group_id=gid, user_id=0, client_id=key, content=content, attachments='[]')
            db.add(m)
            db.commit()
            mid = m.id
        await self.broadcast(gid, {'type': 'message', 'id': mid})
        return mid

    async def context(self, gid, source_id, settings):
        with DB() as db:
            messages = db.query(Message).filter(Message.group_id == gid, Message.id <= source_id).order_by(Message.id.desc()).limit(40).all()[::-1]
            names = {u.id: u.name for u in db.query(User).all()}
            memories = search(db, gid, ' '.join(m.content for m in messages[-5:]))
            summaries = records(db, 'summary', gid)
            summary = summaries[-1].data if summaries else None
            if summary:
                messages = [m for m in messages if m.id > summary['to']]
            result = [{'role': 'system', 'content': settings['prompt'] + '\n当前时间 Unix秒：' + str(self.now()) + '\n家庭记忆（按相关性筛选使用，不相关则忽略）：' + json.dumps(memories, ensure_ascii=False) + '\n早期聊天摘要：' + json.dumps(summary, ensure_ascii=False)}]
            for m in messages:
                content = [{'type': 'text', 'text': '[消息%d，%s，成员ID=%d] %s' % (m.id, names.get(m.user_id, settings['agent_name']), m.user_id, m.content)}]
                # Only pass recent human images, bounded to avoid unbounded request size.
                if m.user_id and m.id in [x.id for x in messages[-3:]]:
                    for key in json.loads(m.attachments)[:2]:
                        upload = get(db, 'upload', gid, key)
                        if upload:
                            p = DATA / 'uploads' / upload.data['file']
                            if p.exists():
                                content.append({'type': 'image_url', 'image_url': {'url': 'data:' + upload.data['mime'] + ';base64,' + base64.b64encode(p.read_bytes()).decode()}})
                result.append({'role': 'assistant' if m.user_id == 0 else 'user', 'content': m.content if m.user_id == 0 else content})
            return result

    async def generate(self, gid, mid, settings, run_id, proactive=False, allow_writes=False):
        messages = await self.context(gid, mid, settings)
        if proactive:
            messages.append({'role': 'system', 'content': '为尚未得到回应的家庭需求准备一句温和跟进。不要假装已经得到确认，不代替他人承诺。不要创建任何事项，不要因已有无关回复认定问题解决。'})
        with DB() as db:
            source = db.get(Message, mid)
            ctx = SkillContext(gid, source.user_id, run_id, mid, allow_writes and not proactive)
        for _ in range(4):
            answer = await self.model.call(messages, tools=tools(ctx.allow_writes))
            calls = answer.get('tool_calls') or []
            if not calls:
                content = answer.get('content') or ''
                if not content.strip():
                    raise RuntimeError('模型未返回回复内容')
                return content
            messages.append({k: v for k, v in answer.items() if k in ['role', 'content', 'tool_calls']})
            messages[-1]['role'] = 'assistant'
            for call in calls[:6]:
                try:
                    args = json.loads(call['function']['arguments'])
                    result = await execute(call['function']['name'], args, ctx)
                except Exception:
                    result = {'error': '工具参数不合法'}
                messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': json.dumps(result, ensure_ascii=False)})
            if len(calls) > 6:
                raise RuntimeError('技能调用超过限制')
        raise RuntimeError('技能调用轮数超过限制')

    async def candidate(self, gid, key, version, mid, settings):
        execution = ('candidate', gid, key, version)
        self.executions[execution] = {'group_id': gid, 'key': key, 'source': mid, 'phase': 'candidate', 'started': self.now()}
        try:
            text = await self.generate(gid, mid, settings, 'demand:' + key + ':' + str(version), True)
            async with self.locks[gid]:
                with DB() as db:
                    r = get(db, 'demand', gid, key)
                    d = r.data
                    if d['status'] == 'waiting' and d['version'] == version:
                        d['candidate'] = text
                        r.set(d)
                        db.commit()
        except Exception as e:
            with DB() as db:
                self.log(db, gid, '候选生成失败：' + str(e), mid)
                r = get(db, 'demand', gid, key)
                if r and r.data['version'] == version:
                    d = r.data
                    d['status'] = 'failed'
                    d['error'] = str(e)[:300]
                    r.set(d)
                db.commit()
        finally:
            self.executions.pop(execution, None)

    async def analyze(self, gid, message):
        with DB() as db:
            waiting = [dict(key=r.key, **r.data) for r in records(db, 'demand', gid) if r.data['status'] == 'waiting']
            recent = db.query(Message).filter(Message.group_id == gid, Message.id <= message.id, Message.user_id != 0).order_by(Message.id.desc()).limit(15).all()[::-1]
            settings = copy.deepcopy(get(db, 'group', gid, 'settings').data)
            known = [dict(key=r.key, **r.data) for r in records(db, 'memory', gid) if not r.data.get('deleted')][-100:]
            names = {u.id: u.name for u in db.query(User).all()}
        data = await self.model.call([
            {'role': 'system', 'content': '你是家庭聊天分析器。只输出JSON。判断最新消息是否包含明确请求或需求，是否回应已有需求。不要把猜测、玩笑、引用、助手话语当作事实。记忆只提取稳定偏好、事实和明确长期约定；一次性安排不作长期记忆。格式：{"new_need":null或{"text":"需求","target":"对象"},"updates":[{"key":"已有需求key","state":"resolved或changed","text":"更新需求"}],"memories":[{"content":"事实","subjects":["成员"],"existing_key":null}],"reason":"简短依据"}。只有真正相关的消息才能更新已有需求，其他成员无关发言不代表目标人已回应。已明确回应的最新需求不要再次创建。最多3条记忆。'},
            {'role': 'system', 'content': '额外输出 write_authorized 布尔值：仅当最新消息明确要求助手记住信息、创建/完成待办或设置提醒时为true；日常提及计划、建议、询问和引用别人的要求不算授权。自动记忆中的 existing_key 应在更新同一主题记忆时引用已提供的key，否则为null。'},
            {'role': 'user', 'content': json.dumps({'waiting': waiting, 'known_memories': known, 'members': names, 'messages': [{'id': m.id, 'sender': m.user_id, 'text': m.content} for m in recent]}, ensure_ascii=False)}
        ], structured=True)
        with DB() as db:
            for item in (data.get('memories') or [])[:3]:
                content = item.get('content', '').strip()
                if content:
                    # Merge exact duplicates; automatic writes cannot overwrite manual edits.
                    existing = next((r for r in records(db, 'memory', gid) if r.data['content'] == content), None)
                    key = existing.key if existing else item.get('existing_key')
                    save_memory(db, gid, content, [message.id], item.get('subjects', []), key)
            self.log(db, gid, str(data.get('reason', '已分析'))[:500], message.id)
            for update in data.get('updates', []):
                r = get(db, 'demand', gid, update.get('key', ''))
                if not r or r.data['status'] != 'waiting':
                    continue
                d = r.data
                d['version'] += 1
                if update.get('state') == 'resolved':
                    d['status'] = 'resolved'
                    self.log(db, gid, '相关回应已收到，取消跟进', message.id)
                elif update.get('state') == 'changed':
                    d.update(text=update.get('text', d['text']), source=message.id, deadline=message.created + settings['wait_seconds'], candidate=None, settings=settings)
                else:
                    continue
                r.set(d)
            need = data.get('new_need')
            if need and settings['active'] and ('@' + settings['agent_name']) not in message.content:
                key = 'source:' + str(message.id)
                if not get(db, 'demand', gid, key):
                    put(db, 'demand', gid, key, {'text': need.get('text', ''), 'target': need.get('target'), 'source': message.id, 'version': 1, 'deadline': message.created + settings['wait_seconds'], 'status': 'waiting', 'candidate': None, 'settings': settings})
            db.commit()
        return data

    async def process(self, gid, key):
        async with self.locks[gid]:
            execution = ('job', gid, key)
            with DB() as db:
                job = get(db, 'job', gid, key)
                d = job.data
                message = db.get(Message, d['source'])
                settings = copy.deepcopy(d['settings'])
            self.executions[execution] = {'group_id': gid, 'key': key, 'source': message.id, 'phase': 'analyzing', 'started': self.now()}
            try:
                if not d.get('analyzed'):
                    analysis = await self.analyze(gid, message)
                    d['allow_writes'] = bool(analysis.get('write_authorized', False))
                    d['analyzed'] = True
                if d['mention'] and not d.get('replied'):
                    self.executions[execution]['phase'] = 'replying'
                    await self.broadcast(gid, {'type': 'agent', 'status': 'generating'})
                    result = await self.generate(gid, message.id, settings, 'mention:' + key, allow_writes=d.get('allow_writes', False))
                    await self.send(gid, result, 'mention:' + key)
                    d['replied'] = True
                self.executions[execution]['phase'] = 'summarizing'
                await self.summarize(gid, message.id)
                d['status'] = 'done'
            except Exception as e:
                d.update(status='failed', error=str(e)[:300])
                await self.broadcast(gid, {'type': 'agent', 'status': 'failed', 'job': key, 'error': d['error']})
            finally:
                self.executions.pop(execution, None)
                with DB() as db:
                    put(db, 'job', gid, key, d)
                    db.commit()
                await self.broadcast(gid, {'type': 'refresh'})
                await self.broadcast(gid, {'type': 'agent', 'status': 'idle'})

    async def summarize(self, gid, mid):
        with DB() as db:
            old = get(db, 'summary', gid, 'latest')
            end = old.data['to'] if old else 0
            batch = db.query(Message).filter(Message.group_id == gid, Message.id > end, Message.id < mid).order_by(Message.id).all()
            if len(batch) < 60:
                return
            batch = batch[:-30][:60]
            previous = old.data['content'] if old else ''
            source = [{'id': m.id, 'sender': m.user_id, 'text': m.content} for m in batch]
        try:
            result = await self.model.call([{'role': 'system', 'content': '将已有摘要和新增聊天压缩为简短家庭聊天摘要，保留说话人和未决事项。不要把猜测变成事实。只输出摘要。'}, {'role': 'user', 'content': json.dumps({'previous': previous, 'messages': source}, ensure_ascii=False)}])
            with DB() as db:
                put(db, 'summary', gid, 'latest', {'from': old.data['from'] if old else batch[0].id, 'to': batch[-1].id, 'content': result['content']})
                db.commit()
        except Exception as e:
            with DB() as db:
                self.log(db, gid, '历史摘要暂未更新：' + str(e), mid)
                db.commit()

    async def tick(self):
        with DB() as db:
            jobs = db.query(Record).filter_by(kind='job').order_by(Record.id).all()
            waiting = [(j.group_id, j.key) for j in jobs if j.data['status'] == 'pending']
        # Never send a candidate while a newer human message awaits analysis.
        for gid, key in waiting:
            self.spawn(self.process(gid, key), ('job', gid, key))
        with DB() as db:
            gids = [r.group_id for r in db.query(Record).filter_by(kind='group').all()]
        for gid in gids:
            # Explicit scheduled reminders are independent of conversation analysis.
            with DB() as db:
                for r in records(db, 'reminder', gid):
                    d = r.data
                    if not d['sent'] and self.now() >= d['at']:
                        await self.send(gid, '提醒：' + d['content'], 'reminder:' + r.key)
                        d['sent'] = True
                        r.set(d)
                        db.commit()
            if self.locks[gid].locked():
                continue
            async with self.locks[gid]:
                with DB() as db:
                    if any(r.data['status'] == 'pending' or (r.data['status'] == 'failed' and not r.data.get('analyzed')) for r in records(db, 'job', gid)):
                        continue
                    settings = get(db, 'group', gid, 'settings').data
                    for r in records(db, 'demand', gid):
                        d = r.data
                        if d['status'] != 'waiting':
                            continue
                        if not settings['active'] or settings['version'] != d['settings']['version']:
                            d['status'] = 'cancelled'
                            r.set(d)
                            db.commit()
                            continue
                        if not d.get('candidate'):
                            self.spawn(self.candidate(gid, r.key, d['version'], d['source'], d['settings']), ('candidate', gid, r.key, d['version']))
                        elif self.now() >= d['deadline']:
                            # Unique message key is the durable outbox: crash replay cannot duplicate.
                            await self.send(gid, d['candidate'], 'demand:' + r.key)
                            d['status'] = 'sent'
                            r.set(d)
                            self.log(db, gid, '观察窗口结束，已发送一次温和跟进', d['source'])
                            db.commit()
                    db.commit()

    async def loop(self):
        self.started_at = self.now()
        while not self.stopped:
            self.last_tick = self.now()
            try:
                await self.tick()
                self.scheduler_error = None
            except Exception as e:
                self.scheduler_error = type(e).__name__
                logging.getLogger(__name__).error('Scheduler tick failed: %s', type(e).__name__)
            await asyncio.sleep(0.5)

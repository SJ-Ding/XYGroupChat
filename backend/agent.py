import asyncio
import base64
import copy
import json
import logging
import time
import uuid
from collections import defaultdict
from .db import DB, DATA, Message, User, Record, get, put, records
from .memory import search, save_memory, list_memories, visible
from .model import Model
from .skills import SkillContext, tools, execute, REGISTRY
from .contracts import ConversationEvent
from .intent import recognize, parse_intent
from .participation import decide, send_policy
from .authorization import command_grants
from .reminder_language import reminder_request
from .context import bounded_context, fit_sections, tool_content, text_size
from .governance import measured_call
from .debugging import traced_call
from .orchestration import run_steps
from .background import BackgroundTasks
from .proactive import schedule_tick
from .persona import system_prompt
from .skill_library import discovery_prompt
from .memory_lifecycle import capture as capture_memories, review as review_memories, transitions
from .hospital_simulator import hospital_relevant

class Agent:
    def __init__(self, broadcast, model=None, now=time.time):
        self.broadcast = broadcast
        self.model = model or Model()
        self.now = now
        self.locks = defaultdict(asyncio.Lock)
        self.frontend_locks = defaultdict(asyncio.Lock)
        self.summary_locks = defaultdict(asyncio.Lock)
        self.background = BackgroundTasks(self)
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

    async def send(self, gid, content, key, source_id=None):
        if not source_id:
            return await self._send(gid, content, key, source_id)
        from .execution_chain import start, finish
        task_key = key
        if key.startswith('result:'):
            with DB() as db:
                matches = [r.key for r in records(db, 'run', gid) if key.startswith('result:' + r.key + ':')]
                if matches:
                    task_key = max(matches, key=len)
        step = await start(gid, source_id, task_key, 'delivery', '发送回复')
        try:
            result = await self._send(gid, content, key, source_id)
        except BaseException as exc:
            await finish(gid, step, 'cancelled' if isinstance(exc, asyncio.CancelledError) else 'failed', '回复未能发送')
            raise
        await finish(gid, step, summary='回复已发送')
        return result

    async def _send(self, gid, content, key, source_id=None):
        with DB() as db:
            old = db.query(Message).filter_by(group_id=gid, user_id=0, client_id=key).first()
            if old:
                return old.id
            m = Message(group_id=gid, user_id=0, client_id=key, content=content, attachments='[]')
            db.add(m)
            db.flush()
            db.commit()
            mid = m.id
            if source_id:
                put(db, 'reply_source', gid, str(mid), {'source_id': source_id})
                db.commit()
        await self.broadcast(gid, {'type': 'message', 'id': mid})
        if source_id:
            from .reply_memory import extract
            async def capture_reply():
                try:
                    await extract(self, gid, source_id, mid)
                except Exception:
                    logging.getLogger(__name__).exception('回复记忆提取失败')
            self.spawn(capture_reply(), key=f'reply-memory:{mid}')
        return mid

    async def context(self, gid, source_id, settings):
        with DB() as db:
            messages = db.query(Message).filter(Message.group_id == gid, Message.id <= source_id).order_by(Message.id.desc()).limit(80).all()[::-1]
            topic_record = get(db, 'decision', gid, str(source_id))
            topic = topic_record.data.get('topic') if topic_record else None
            if topic:
                related = {r.data.get('source') for r in records(db, 'decision', gid) if r.data.get('topic') == topic}
                recent_ids = {m.id for m in messages[-15:]}
                messages = [m for m in messages if m.id in recent_ids or m.id in related]
            else:
                messages = messages[-40:]
            names = {u.id: u.name for u in db.query(User).all()}
            # Domain-aware memory retrieval: detect medical context from recent
            # messages to search the right domain. If medical keywords are
            # present, search medical domain; otherwise search general. For
            # ambiguous queries, fall back to searching both domains.
            recent_text = ' '.join(m.content for m in messages[-5:])
            import re as _re
            medical_pattern = _re.compile(r'药|病|诊断|血压|血糖|挂号|就诊|复诊|药单|处方|科室|医院|医生|体检')
            is_medical = bool(medical_pattern.search(recent_text))
            if is_medical:
                general_mems = search(db, gid, recent_text, viewer_id=-gid if gid < 0 else None, now=self.now(), domain='general', limit=5)
                medical_mems = search(db, gid, recent_text, viewer_id=-gid if gid < 0 else None, now=self.now(), domain='medical', limit=10)
                memories = medical_mems + general_mems
            else:
                memories = search(db, gid, recent_text, viewer_id=-gid if gid < 0 else None, now=self.now(), domain='general')
            summaries = records(db, 'summary', gid)
            summary = summaries[-1].data if summaries else None
            if summary and summary['to'] >= source_id:
                summary = None
            if summary:
                messages = [m for m in messages if m.id > summary['to'] or m.id == source_id]
            if not messages or messages[-1].group_id != gid or messages[-1].id != source_id:
                raise ValueError('上下文来源不属于此会话')
            sections = [('早期聊天摘要', summary)] if summary else []
            sections += [('相关记忆', m) for m in memories]
            sections += [('后台任务摘要', {'id': r.key, 'title': r.data['title'], 'status': r.data['status'], 'result': r.data.get('result', '')[:800]}) for r in records(db, 'run', gid) if r.data.get('kind') == 'skill'][-5:]
            sections += [('未决事项', {'key': r.key, **r.data}) for r in records(db, 'task', gid) if not r.data.get('done')][:5]
            prompt = system_prompt(settings) + '\n当前时间 Unix秒：' + str(self.now()) + '\n相关记忆供你自然承接话题，注意有效期和tentative（尚未确定）。来源保留供核对；平常不逐条报出处或后台编号，被问到来源时再具体说明。'
            prompt += '\n' + discovery_prompt()
            prompt = fit_sections(prompt, len(messages[-1].content) + 100, sections, settings.get('context_budget', 24000))
            result = [{'role': 'system', 'content': prompt}]
            for m in messages:
                content = [{'type': 'text', 'text': '[消息%d，%s，成员ID=%d] %s' % (m.id, names.get(m.user_id, settings['agent_name']), m.user_id, m.content)}]
                # Only pass recent human images, bounded to avoid unbounded request size.
                if m.user_id and m.id in [x.id for x in messages[-15:]]:
                    for key in json.loads(m.attachments)[:2]:
                        upload = get(db, 'upload', gid, key)
                        if upload:
                            p = DATA / 'uploads' / upload.data['file']
                            if p.exists():
                                content.append({'type': 'image_url', 'image_url': {'url': 'data:' + upload.data['mime'] + ';base64,' + base64.b64encode(p.read_bytes()).decode()}})
                result.append({'role': 'assistant' if m.user_id == 0 else 'user', 'content': m.content if m.user_id == 0 else content})
            return bounded_context(result, settings.get('context_budget', 24000))

    async def call(self, gid, *args, **kwargs):
        return await measured_call(self.model, gid, *args, **kwargs)

    async def tool_progress(self, gid, run_id, phase):
        with DB() as db:
            run = get(db, 'run', gid, run_id)
            if not run:
                return
            value = run.data
            value.update(show_progress=True, phase=phase, updated=self.now())
            run.set(value)
            db.commit()
        from .cards import publish_run
        await publish_run(gid, run_id)

    async def generate(self, gid, mid, settings, run_id, proactive=False, allow_writes=False, background=False):
        with DB() as db:
            source = db.get(Message, mid)
            reminder = reminder_request(source.content, settings['agent_name'], source.created) if not proactive else None
        if reminder and reminder.clarification:
            return reminder.clarification
        messages = await self.context(gid, mid, settings)
        if proactive:
            messages.append({'role': 'system', 'content': '为尚未得到回应的家庭需求准备一句自然、体贴的小帮助。不要说“检测到需求”或解释观察流程，不催家人、不替别人回答或承诺。只提一个眼下能帮上的具体帮助，不创建事项；无关回复不代表问题解决。'})
        with DB() as db:
            source = db.get(Message, mid)
            job = get(db, 'job', gid, str(mid))
            command = (job.data.get('confirmed_command') if job else None) or source.content
            grants = command_grants(command, settings['agent_name'], source.created) if not proactive else []
            import re as _re2
            medical_pattern = _re2.compile(r'药|病|诊断|血压|血糖|挂号|就诊|复诊|药单|处方|科室|医院|医生|体检')
            is_medical = bool(medical_pattern.search(source.content)) or hospital_relevant(source.content)
            selected = {'memory_search', 'family_tasks'} | {g['tool'] for g in grants}
            if hospital_relevant(source.content):
                selected.add('hospital_simulator')
            # Load medical_profile skill when the conversation has medical context,
            # so the model can retrieve structured medical history for vague commands.
            if is_medical:
                selected = selected | {'medical_profile'}
            ctx = SkillContext(gid, source.user_id, run_id, mid, bool(grants) and not proactive, grants=grants, selected=selected, now=self.now())
            run = get(db, 'run', gid, run_id)
            saved_steps = run.data.get('steps', []) if run else []
        receipts = []
        # Explicit narrow commands execute deterministically. Model narration
        # cannot silently omit the action or broaden its arguments.
        for index, grant in enumerate(grants):
            await self.tool_progress(gid, run_id, 'executing')
            saved = next((s for s in saved_steps if s.get('id') == str(index) and s.get('tool') == grant['tool']
                          and s.get('arguments') == grant['arguments'] and s.get('status') == 'succeeded'), None)
            # Reply retries reuse the durable receipt without invoking even
            # the tool cache. An already finished action is never re-executed.
            result = saved['result'] if saved else await execute(grant['tool'], grant['arguments'], ctx)
            if saved:
                from .execution_chain import start, finish
                reused = await start(gid, mid, run_id, 'reuse', '使用已有结果')
                await finish(gid, reused, summary='已复用成功执行记录')
            with DB() as db:
                if saved and isinstance(result, dict) and result.get('key'):
                    kind = {'remember': 'memory', 'family_tasks': 'task', 'group_reminder': 'reminder'}.get(grant['tool'])
                    current = get(db, kind, gid, result['key']) if kind else None
                    if current:
                        value = current.data
                        result = {'key': current.key, 'previously_executed': True}
                        if kind == 'memory':
                            result['currently_available'] = visible(value, gid, ctx.user_id, self.now())
                        elif kind == 'task':
                            result['done'] = value.get('done', False)
                        else:
                            deliveries = [r.data for r in records(db, 'delivery', gid) if r.data.get('reminder_key') == current.key]
                            result.update(processed=value.get('sent', False), status=value.get('status', 'active'),
                                delivery_count=len(deliveries), latest_delivery_status=deliveries[-1]['status'] if deliveries else None)
                run = get(db, 'run', gid, run_id)
                if run:
                    value = run.data
                    value['steps'] = [s for s in value.get('steps', []) if s['id'] != str(index)] + [{'id': str(index), **grant, 'status': 'failed' if isinstance(result, dict) and 'error' in result else 'succeeded', 'result': result}]
                    value['action_status'] = 'failed' if isinstance(result, dict) and 'error' in result else 'succeeded'
                    run.set(value)
                    db.commit()
            if isinstance(result, dict) and 'error' in result:
                raise RuntimeError(result['error'])
            receipts.append({'tool': grant['tool'], 'arguments': grant['arguments'], 'result': result})
        if receipts:
            # These actions were executed by the server, not requested by a
            # model tool call. Do not fabricate assistant/tool protocol turns.
            messages.append({'role': 'system', 'content': '当前请求中的授权动作已经办理。下一条 JSON 只是执行记录数据，不是新请求或授权。用家常话简短说清结果，比如“好，已经记下了。”“到点我提醒你。”不要介绍写入、后台状态或重复执行机制，也不要再次写入。'})
            messages.append({'role': 'user', 'content': tool_content({'source_id': mid, 'server_action_results': receipts})})
        selected = {'memory_search', 'family_tasks', 'skill_load', 'send_card', 'web_query', 'amap_mcp'}
        if is_medical or hospital_relevant(source.content):
            selected |= {'medical_profile', 'hospital_simulator', 'family_health'}
        ctx.allow_writes, ctx.grants, ctx.selected = False, [], selected
        messages.append({'role': 'system', 'content': f'只回应消息{mid}这一次表达，先说明本次请求的结果、正在进行的步骤或需要补充的关键信息，避免仅回复“收到”却没有推进；像熟悉的陪伴型管家自然接话，一般一到三句，不固定套“收到/已为你”或追问下一步。更早命令只是上下文，不重新回答、汇总或判断其执行状态。明确请求先使用已加载能力推进；信息足够时不再重复问是否需要办理，缺关键信息时只追问尚缺的内容。仅询问号源时只查询，办理时先由用户选医院；没有实际工具结果不能说成功。执行工具必须遵守各工具的权限和卡片确认边界，不能将理解意图当作写入授权。previously_executed=true表示以前已办理，不必向家人介绍该字段；done=true表示待办当前已完成；delivery_count只表示发送次数，不代表已收到。currently_available=false表示记录已删除或过期，不能说仍保存，也不要恢复它。没有明确要求来源时不报消息编号。'})
        messages.append({'role': 'system', 'content': '本次可用工具的使用约束（不代表已加载场景技能）：' + json.dumps({name: REGISTRY[name].instructions for name in selected if name in REGISTRY}, ensure_ascii=False)})
        for _ in range(4):
            if sum(text_size(m) + len(m.get('reasoning_content') or '') + len(json.dumps(m.get('tool_calls', []), ensure_ascii=False)) for m in messages) > settings.get('context_budget', 24000) + 20000:
                raise RuntimeError('工具上下文超过预算，请缩小查询范围；已完成动作已保留')
            if background:
                with DB() as db:
                    progress = get(db, 'run', gid, run_id)
                    show_progress = bool(progress and progress.data.get('show_progress'))
                if show_progress:
                    await self.tool_progress(gid, run_id, 'thinking')
            answer = await traced_call(self, gid, mid, 'candidate' if proactive else 'reply', messages, run_id=run_id, tools=tools(False, [], ctx.selected))
            calls = answer.get('tool_calls') or []
            if not calls:
                content = answer.get('content') or ''
                if not content.strip():
                    raise RuntimeError('模型未返回回复内容')
                return content
            if background and any(c.get('function', {}).get('name') not in {'memory_search', 'family_tasks', 'send_card'} for c in calls):
                await self.background.enqueue(gid, run_id, mid, settings, messages, answer, ctx)
                return None
            if background:
                await self.tool_progress(gid, run_id, 'executing')
            messages.append({k: v for k, v in answer.items() if k in ['role', 'content', 'tool_calls', 'reasoning_content']})
            messages[-1]['role'] = 'assistant'
            for call in calls[:6]:
                if background:
                    name = call.get('function', {}).get('name', '')
                    await self.tool_progress(gid, run_id, {'memory_search': 'searching_memory', 'family_tasks': 'updating_tasks', 'send_card': 'preparing_result'}.get(name, 'executing'))
                try:
                    args = json.loads(call['function']['arguments'])
                    result = await execute(call['function']['name'], args, ctx)
                except Exception:
                    result = {'error': '工具参数不合法'}
                messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': tool_content(result)})
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
            waiting = [dict(key=r.key, **{k:v for k,v in r.data.items() if k in ('text','target','source','topic','version')}) for r in records(db, 'demand', gid) if r.data['status'] == 'waiting']
            recent = db.query(Message).filter(Message.group_id == gid, Message.id <= message.id).order_by(Message.id.desc()).limit(15).all()[::-1]
            settings = copy.deepcopy(get(db, 'group', gid, 'settings').data)
            known = list_memories(db, gid, -gid if gid < 0 else None, self.now())[-30:]
            names = {u.id: u.name for u in db.query(User).all()}
            job = get(db, 'job', gid, str(message.id))
            addressed = bool(job and job.data.get('mention'))
        from .intent import direct_mention
        data = await recognize(lambda messages, **kw: traced_call(self, gid, message.id, 'analysis', messages, **kw), waiting=waiting,
            memories=known, names=names, messages=[{'id': m.id, 'sender': m.user_id, 'text': m.content,'created':m.created} for m in recent],
            now=self.now(),agent_name=settings['agent_name'],short_days=settings.get('memory_short_days',7))
        event = ConversationEvent(gid, message.user_id, message.id, message.content, message.created,
            gid < 0 or addressed or direct_mention(message.content, settings['agent_name']))
        decision = decide(event, parse_intent(data), settings)
        data['decision'] = decision.data()
        explicit_memory = (event.direct or decision.action == 'reply') and any(
            grant['tool'] == 'remember' for grant in command_grants(message.content, settings['agent_name'], message.created))
        with DB() as db:
            intent=parse_intent(data)
            items=[] if explicit_memory or reminder_request(message.content, settings['agent_name'], message.created) or intent.quoted or intent.kind=='joke' else (
                transitions(known,data.get('memory_updates') or [],message,intent)+(data.get('memories') or []))
            data['memory_changes']=capture_memories(db,gid,message,items,settings,self.now(),{m['key'] for m in known})
            self.log(db, gid, str(data.get('reason', '已分析'))[:500], message.id)
            put(db, 'decision', gid, str(message.id), {**decision.data(), 'intent': vars(intent), 'source': message.id, 'user_id': message.user_id, 'at': self.now()})
            for update in data.get('updates', []):
                r = get(db, 'demand', gid, update.get('key', ''))
                if not r or r.data['status'] != 'waiting':
                    continue
                d = r.data
                d['version'] += 1
                if update.get('state') in ('resolved', 'cancelled'):
                    d['status'] = update['state']
                    self.log(db, gid, '相关回应已收到，取消跟进', message.id)
                elif update.get('state') == 'changed':
                    d.update(text=update.get('text', d['text']), source=message.id, deadline=message.created + settings['wait_seconds'], candidate=None, settings=settings)
                else:
                    continue
                r.set(d)
            need = data.get('new_need')
            if need and decision.action == 'observe' and not settings.get('participation_shadow', False):
                key = 'source:' + str(message.id)
                if not get(db, 'demand', gid, key):
                    put(db, 'demand', gid, key, {'text': need.get('text', ''), 'target': need.get('target'), 'source': message.id, 'version': 1, 'deadline': message.created + settings['wait_seconds'], 'status': 'waiting', 'candidate': None, 'settings': settings, 'topic': decision.topic or need.get('text', '')[:100], 'created': message.created})
            db.commit()
        return data

    async def process(self, gid, key):
        async with self.frontend_locks[gid]:
            execution = ('job', gid, key)
            with DB() as db:
                job = get(db, 'job', gid, key)
                d = job.data
                message = db.get(Message, d['source'])
                settings = copy.deepcopy(d['settings'])
            self.executions[execution] = {'group_id': gid, 'key': key, 'source': message.id, 'phase': 'analyzing', 'started': self.now()}
            try:
                # 就医守护快速通道：急症/挂号/长辈不适/打卡由规则+编排直接接管，
                # 不等待通用分析，也不再生成通用回复（避免重复回答）。
                if not d.get('care_checked'):
                    from .care import on_message as care_message
                    self.executions[execution]['phase'] = 'care'
                    try:
                        # Urgent rules always precede aftercare and booking work.
                        d['care_handled'] = bool(await care_message(self, gid, message, emergency_only=True))
                        if not d['care_handled']:
                            d['care_handled'] = bool(await care_message(self, gid, message))
                    except Exception as exc:  # noqa: BLE001 - 编排失败时回到通用流程
                        logging.getLogger(__name__).exception('就医守护编排失败')
                        d['care_handled'], d['care_error'] = False, str(exc)[:300]
                    d['care_checked'] = True
                    with DB() as db:
                        put(db, 'job', gid, key, d)
                        db.commit()
                if d.get('care_handled'):
                    d.update(analyzed=True, replied=True, reply_status='care', decision={'action': 'care'})
                if not d.get('analyzed'):
                    analysis = await self.analyze(gid, message)
                    d['decision'] = analysis['decision']
                    d['confirmed_command'] = analysis.get('confirmed_command')
                    # A confident semantic scene can route paraphrases missed by fast rules.
                    if d['decision']['action'] == 'reply':
                        from .care import on_message as care_message
                        if await care_message(self, gid, message, intent=parse_intent(analysis)):
                            d.update(care_handled=True, replied=True, reply_status='care')
                    d['memory_changes'] = analysis.get('memory_changes',[])
                    d['allow_writes'] = False
                    d['analyzed'] = True
                    with DB() as db:
                        put(db, 'job', gid, key, d)
                        db.commit()
                if d.get('decision', {}).get('action') == 'reply' and not d.get('replied'):
                    self.executions[execution]['phase'] = 'replying'
                    with DB() as db:
                        if not get(db, 'run', gid, 'mention:' + key):
                            put(db, 'run', gid, 'mention:' + key, {'title': message.content[:100], 'user_id': message.user_id,
                                'source_id': message.id, 'status': 'running', 'steps': [], 'conversation': True, 'updated': self.now()})
                        db.commit()
                    await self.broadcast(gid, {'type': 'agent', 'status': 'generating'})
                    with DB() as db:
                        sent = db.query(Message).filter_by(group_id=gid, user_id=0, client_id='mention:' + key).first()
                    if not sent:
                        result = await self.generate(gid, message.id, settings, 'mention:' + key, allow_writes=d.get('allow_writes', False), background=True)
                        if result is not None:
                            await self.send(gid, result, 'mention:' + key, source_id=message.id)
                    d['replied'] = True
                    d['reply_status'] = 'sent'
                    with DB() as db:
                        r = get(db, 'run', gid, 'mention:' + key)
                        value = r.data
                        value.update(status='succeeded', reply_status='sent', updated=self.now())
                        value.pop('reply_error', None)
                        value.pop('error', None)
                        d['action_status'] = value.get('action_status', 'not_requested')
                        r.set(value)
                        db.commit()
                self.executions[execution]['phase'] = 'summarizing'
                self.spawn(self.summarize(gid, message.id), ('summary', gid))
                d['status'] = 'done'
                d.pop('error', None)
                d.pop('failure_stage', None)
            except Exception as e:
                d.update(status='failed', error=str(e)[:300])
                with DB() as db:
                    r = get(db, 'run', gid, 'mention:' + key)
                    if r:
                        value = r.data
                        completed = bool(value.get('steps')) and all(s.get('status') == 'succeeded' for s in value['steps'])
                        if completed:
                            d.update(status='reply_failed', action_status='succeeded', reply_status='failed', failure_stage='reply')
                            value.update(status='succeeded', action_status='succeeded', reply_status='failed', reply_error=d['error'])
                            value.pop('error', None)
                        else:
                            d.update(action_status=value.get('action_status', 'not_requested'), reply_status='failed', failure_stage='reply')
                            value.update(status='failed', reply_status='failed', error=d['error'])
                        r.set(value)
                        db.commit()
                notice = ('动作已完成，但回复未送达：' if d.get('status') == 'reply_failed' else '') + d['error']
                await self.broadcast(gid, {'type': 'agent', 'status': 'failed', 'job': key, 'error': notice, 'action_status': d.get('action_status')})
            finally:
                self.executions.pop(execution, None)
                with DB() as db:
                    put(db, 'job', gid, key, d)
                    db.commit()
                from .cards import publish_run
                with DB() as db:
                    has_run = get(db, 'run', gid, 'mention:' + key) is not None
                if has_run:
                    await publish_run(gid, 'mention:' + key)
                await self.broadcast(gid, {'type': 'refresh'})
                await self.broadcast(gid, {'type': 'agent', 'status': 'idle'})

    async def summarize(self, gid, mid):
        async with self.summary_locks[gid]:
            await self._summarize(gid, mid)

    async def _summarize(self, gid, mid):
        with DB() as db:
            old = get(db, 'summary', gid, 'latest')
            end = old.data['to'] if old else 0
            batch = db.query(Message).filter(Message.group_id == gid, Message.id > end, Message.id < mid).order_by(Message.id).all()
            if len(batch) < 60:
                return
            batch = batch[:-30][:60]
            previous = old.data['content'] if old else ''
            bounded = []
            size = len(previous)
            for message in batch:
                cost = len(message.content) + 100
                if size + cost > 20000:
                    break
                bounded.append(message)
                size += cost
            batch = bounded
            if not batch:
                return
            source = [{'id': m.id, 'sender': m.user_id, 'text': m.content} for m in batch]
        try:
            result = await self.call(gid, [{'role': 'system', 'content': '将已有摘要和新增聊天压缩为简短家庭聊天摘要，保留说话人、来源消息ID、否定条件和未决事项。不要把猜测变成事实。只输出摘要。'}, {'role': 'user', 'content': json.dumps({'previous': previous, 'messages': source}, ensure_ascii=False)}])
            with DB() as db:
                latest = get(db, 'summary', gid, 'latest')
                if latest and latest.data['to'] != end:
                    return
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
        scheduled = set()
        for gid, key in waiting:
            if gid in scheduled or self.frontend_locks[gid].locked() or any(k[0] == 'job' and k[1] == gid for k in self.running):
                continue
            scheduled.add(gid)
            self.spawn(self.process(gid, key), ('job', gid, key))
        await self.background.schedule()
        try:
            from .care import tick as care_tick
            await care_tick(self)
        except Exception as exc:  # noqa: BLE001 - 守护调度失败不影响聊天
            logging.getLogger(__name__).error('就医守护调度失败：%s', type(exc).__name__)
        with DB() as db:
            gids = [r.group_id for r in db.query(Record).filter_by(kind='group').all()]
        for gid in gids:
            # Explicit scheduled reminders are independent of conversation analysis.
            with DB() as db:
                events = schedule_tick(db, gid, self.now())
                settings=get(db,'group',gid,'settings').data
                memory_updated=review_memories(db,gid,settings,self.now())
                db.commit()
            for mid in events:
                await self.broadcast(gid, {'type': 'message', 'id': mid})
            if memory_updated:
                await self.broadcast(gid, {'type':'refresh'})
            if self.frontend_locks[gid].locked() or self.locks[gid].locked():
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
                        policy = send_policy(db, gid, d, self.now(), settings)
                        if policy not in ('ready', 'cooldown'):
                            d['status'] = policy
                            r.set(d)
                            db.commit()
                            continue
                        if not d.get('candidate'):
                            self.spawn(self.candidate(gid, r.key, d['version'], d['source'], d['settings']), ('candidate', gid, r.key, d['version']))
                        elif self.now() >= d['deadline'] and policy == 'ready':
                            # Unique message key is the durable outbox: crash replay cannot duplicate.
                            await self.send(gid, d['candidate'], 'demand:' + r.key)
                            d['status'] = 'sent'
                            d['sent_at'] = self.now()
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

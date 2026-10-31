import asyncio
import io
import json
import os
import re
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, UploadFile, File, Depends
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field
from .db import DB, DATA, User, Member, Message, Record, get, put, records, migrate
from .memory import save_memory, delete_memory, search, list_memories, visible
from .agent import Agent
from .monitor import snapshot
from .debugging import message_list, message_detail, message_annotations
from .auth import COOKIE, session_user
from .intent import direct_mention
from . import democlock

connections = defaultdict(dict)

async def broadcast(gid, event):
    for ws in list(connections[gid]):
        try:
            websocket_user(ws)
            await ws.send_json(event)
        except Exception:
            connections[gid].pop(ws, None)
            try:
                await ws.close(code=1008)
            except Exception:
                pass

agent = Agent(broadcast, now=democlock.now)

@asynccontextmanager
async def lifespan(app):
    migrate()
    from .care_seed import autoseed
    autoseed()
    from .hospital_simulator import set_event_loop, automation
    set_event_loop(asyncio.get_running_loop())
    agent.stopped = False
    task = asyncio.create_task(agent.loop())
    from .care import warmup
    asyncio.create_task(warmup())
    yield
    task.cancel()
    await agent.close()
    await asyncio.gather(task, return_exceptions=True)
    automation.shutdown()

app = FastAPI(title='小艺 · 家庭聊天', lifespan=lifespan)

def identity(username):
    if username == 'agent':
        with DB() as db:
            settings = get(db, 'group', 1, 'settings')
            return {'id': 0, 'name': settings.data['agent_name'] if settings else '小艺', 'username': 'agent', 'observer': True}
    if username not in ('dad', 'mom', 'child'):
        raise HTTPException(400, '请通过 URL 指定 user=dad、mom、child 或 agent')
    with DB() as db:
        u = db.query(User).filter_by(username=username).first()
        if not u:
            raise HTTPException(400, '家庭成员尚未初始化')
        return {'id': u.id, 'name': u.name, 'username': u.username}

def resolved_user(params, cookies):
    signed_in = session_user(cookies.get(COOKIE))
    if signed_in:
        if params.get('user') == 'agent':
            return {**signed_in, 'name': identity('agent')['name'], 'username': 'agent', 'observer': True}
        return signed_in
    if os.getenv('AUTH_REQUIRED', '').lower() in ('1', 'true') or cookies.get(COOKIE):
        raise HTTPException(401, '请先登录')
    return identity(params.get('user'))


def current(request: Request):
    user = resolved_user(request.query_params, request.cookies)
    if user.get('observer') and request.method not in ('GET', 'HEAD', 'OPTIONS'):
        raise HTTPException(403, 'Agent 聊天视角仅供查看，请切换家庭成员操作')
    return user


def websocket_user(ws):
    return resolved_user(ws.query_params, ws.cookies)


def access(gid, user):
    if user.get('observer') and not user.get('authenticated'):
        if gid != 1:
            raise HTTPException(403, '你不在此群组中')
        return
    with DB() as db:
        if not db.query(Member).filter_by(group_id=gid, user_id=user['id']).first():
            raise HTTPException(403, '你不在此群组中')


@app.middleware('http')
async def same_origin(request, call_next):
    if request.method not in ['GET', 'HEAD', 'OPTIONS']:
        origin = request.headers.get('origin')
        if origin and origin != str(request.base_url).rstrip('/'):
            # Vite development proxy preserves the origin on localhost only.
            if not (origin in ['http://localhost:5173', 'http://127.0.0.1:5173'] and request.url.hostname in ['localhost', '127.0.0.1']):
                from fastapi.responses import JSONResponse
                return JSONResponse({'detail': '来源不匹配'}, status_code=403)
    return await call_next(request)

@app.get('/api/me')
def me(user=Depends(current)):
    return user

@app.get('/api/groups')
def groups(user=Depends(current)):
    with DB() as db:
        if user.get('observer') and not user.get('authenticated'):
            return [{'id': 1, **get(db, 'group', 1, 'settings').data}]
        return [{'id': m.group_id, **get(db, 'group', m.group_id, 'settings').data} for m in db.query(Member).filter_by(user_id=user['id']).all()]

def serialized(db, m):
    from .cards import public_card, hidden_message, task_title
    settings = get(db, 'group', m.group_id, 'settings').data
    u = db.get(User, m.user_id)
    cards = [public_card(db, m.group_id, r.data) for r in records(db, 'card', m.group_id) if r.data['message_id'] == m.id]
    content = m.content
    if cards and cards[0]['kind'] == 'progress':
        run = get(db, 'run', m.group_id, cards[0].get('run_key'))
        if run:
            content = task_title(run.data)
            cards[0]['title'] = content
    # Render legacy result outbox entries with the same single-card presentation.
    if m.user_id == 0 and m.client_id.startswith('result:'):
        run = next((r for r in records(db, 'run', m.group_id) if r.data.get('kind') == 'skill' and m.client_id.startswith('result:' + r.key + ':')), None)
        if run:
            prefix = '【' + run.data['title'] + '】\n'
            if content.startswith(prefix):
                content = content[len(prefix):]
    return {'id': m.id, 'user_id': m.user_id, 'name': u.name if u else settings['agent_name'], 'client_id': m.client_id, 'content': content, 'attachments': json.loads(m.attachments), 'created': m.created, 'cards': cards, 'hidden': hidden_message(db, m)}

@app.get('/api/groups/{gid}/messages')
def messages(gid: int, before: Optional[int] = None, after: Optional[int] = None, around: Optional[int] = None, query: str = '', user=Depends(current)):
    access(gid, user)
    with DB() as db:
        q = db.query(Message).filter_by(group_id=gid)
        if query:
            q = q.filter(Message.content.contains(query[:200], autoescape=True))
        if around is not None:
            left = q.filter(Message.id <= around).order_by(Message.id.desc()).limit(20).all()[::-1]
            right = q.filter(Message.id > around).order_by(Message.id).limit(20).all()
            rows = left + right
        elif after is not None:
            rows = q.filter(Message.id > after).order_by(Message.id).limit(100).all()
        else:
            if before is not None:
                q = q.filter(Message.id < before)
            rows = q.order_by(Message.id.desc()).limit(50).all()[::-1]
        return [serialized(db, m) for m in rows]

class NewMessage(BaseModel):
    client_id: str = Field(min_length=1, max_length=100)
    content: str = Field(default='', max_length=10000)
    attachments: List[str] = Field(default_factory=list, max_length=4)

@app.post('/api/groups/{gid}/messages')
async def send_message(gid: int, body: NewMessage, user=Depends(current)):
    access(gid, user)
    if not body.content.strip() and not body.attachments:
        raise HTTPException(400, '消息不能为空')
    with DB() as db:
        old = db.query(Message).filter_by(group_id=gid, user_id=user['id'], client_id=body.client_id).first()
        if old:
            return serialized(db, old)
        for key in body.attachments:
            r = get(db, 'upload', gid, key)
            if not r or r.data['owner'] != user['id']:
                raise HTTPException(400, '图片不存在或不属于当前账号')
        m = Message(group_id=gid, user_id=user['id'], client_id=body.client_id, content=body.content.strip(), attachments=json.dumps(body.attachments))
        db.add(m)
        db.flush()
        settings = get(db, 'group', gid, 'settings').data
        mention = direct_mention(m.content, settings['agent_name'])
        put(db, 'job', gid, str(m.id), {'source': m.id, 'mention': mention, 'settings': settings, 'status': 'pending', 'analyzed': False})
        db.commit()
        result = serialized(db, m)
    await broadcast(gid, {'type': 'message', 'id': result['id']})
    return result

@app.post('/api/groups/{gid}/uploads')
async def upload(gid: int, file: UploadFile = File(...), user=Depends(current)):
    access(gid, user)
    raw = await file.read(10*1024*1024+1)
    if len(raw) > 10*1024*1024:
        raise HTTPException(413, '图片不能超过 10 MB')
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.format not in ['JPEG', 'PNG', 'WEBP'] or im.width*im.height > 25000000:
                raise ValueError()
            fmt = im.format
            im.verify()
    except (UnidentifiedImageError, ValueError, OSError, Image.DecompressionBombError):
        raise HTTPException(400, '仅支持有效的 JPEG、PNG、WebP 图片（不超过2500万像素）')
    key = str(uuid.uuid4())
    filename = key + '.' + fmt.lower()
    (DATA / 'uploads' / filename).write_bytes(raw)
    with DB() as db:
        put(db, 'upload', gid, key, {'file': filename, 'mime': 'image/' + ('jpeg' if fmt == 'JPEG' else fmt.lower()), 'owner': user['id']})
        db.commit()
    return {'key': key}

@app.get('/api/groups/{gid}/uploads/{key}')
def image(gid: int, key: str, user=Depends(current)):
    access(gid, user)
    with DB() as db:
        r = get(db, 'upload', gid, key)
        if not r:
            raise HTTPException(404, '图片不存在')
        return FileResponse(DATA / 'uploads' / r.data['file'], media_type=r.data['mime'])

@app.get('/api/groups/{gid}/members')
def members(gid: int, user=Depends(current)):
    access(gid, user)
    with DB() as db:
        ids = [m.user_id for m in db.query(Member).filter_by(group_id=gid)]
        online = set(connections[gid].values())
        return [{'id': u.id, 'name': u.name, 'online': u.id in online} for u in db.query(User).filter(User.id.in_(ids)).all()]

class MemoryBody(BaseModel):
    version: int | None = Field(default=None, ge=1)
    content: str = Field(min_length=1, max_length=2000)

@app.get('/api/groups/{gid}/memories')
def memories(gid: int, q: str = '', domain: Optional[str] = None, user=Depends(current)):
    access(gid, user)
    with DB() as db:
        if q:
            return search(db, gid, q, 50, domain=domain)
        mems = list_memories(db, gid)
        if domain:
            mems = [m for m in mems if m.get('domain', 'general') == domain]
        return mems

class PrognosisAction(BaseModel):
    action: str
    enabled: list[str] | None = None

@app.post('/api/groups/{gid}/prognosis/{key}/act')
async def prognosis_action(gid: int, key: str, body: PrognosisAction, user=Depends(current)):
    if gid < 0:
        if gid != -user['id']:
            raise HTTPException(403, '无此会话权限')
    else:
        access(gid, user)
    from .prognosis import activate
    with DB() as db:
        r = get(db, 'card', gid, key)
        if not r or not r.data.get('care', {}).get('data', {}).get('prognosis'):
            raise HTTPException(404, '计划不存在')
        result = activate(db, gid, r.data, body.action, body.enabled, user['id'])
        db.commit()
    await broadcast(gid, {'type': 'refresh'})
    return result

class BackfillBody(BaseModel):
    preview: bool = True
    limit: int = Field(default=100, ge=1, le=500)

@app.post('/api/groups/{gid}/memories/backfill')
async def backfill_memories(gid: int, body: BackfillBody, user=Depends(current)):
    if gid < 0:
        if gid != -user['id']:
            raise HTTPException(403, '无此会话权限')
    else:
        access(gid, user)
    from .reply_memory import backfill
    return {'preview': body.preview, 'items': await backfill(agent, gid, body.limit, body.preview)}

@app.post('/api/groups/{gid}/memories')
async def add_memory(gid: int, body: MemoryBody, user=Depends(current)):
    access(gid, user)
    with DB() as db:
        r = save_memory(db, gid, body.content, manual=True)
        db.commit()
        result = dict(key=r.key, **r.data)
    await broadcast(gid, {'type': 'refresh'})
    return result

@app.put('/api/groups/{gid}/memories/{key}')
async def edit_memory(gid: int, key: str, body: MemoryBody, user=Depends(current)):
    access(gid, user)
    with DB() as db:
        old = get(db, 'memory', gid, key)
        if not old or not visible(old.data, gid):
            raise HTTPException(404, '记忆不存在')
        if body.version is not None and body.version != old.data.get('version', 1):
            raise HTTPException(409, '记忆已更新，请刷新后重试')
        r = save_memory(db, gid, body.content, old.data.get('sources', []), old.data.get('subjects', []), key, True,
            lifetime=old.data.get('lifetime', 'long'), expires_at=old.data.get('expires_at'), scope=old.data.get('scope', 'group'))
        db.commit()
    await broadcast(gid, {'type': 'refresh'})
    return {'ok': True}

@app.delete('/api/groups/{gid}/memories/{key}')
async def remove_memory(gid: int, key: str, user=Depends(current)):
    access(gid, user)
    with DB() as db:
        r = get(db, 'memory', gid, key)
        if not r or r.data.get('scope') == 'private':
            raise HTTPException(404, '记忆不存在')
        delete_memory(db, r)
        db.commit()
    await broadcast(gid, {'type': 'refresh'})
    return {'ok': True}

@app.get('/api/groups/{gid}/memories/{key}/revisions')
def revisions(gid: int, key: str, user=Depends(current)):
    access(gid, user)
    with DB() as db:
        old = get(db, 'memory', gid, key)
        if not old or old.data.get('scope') == 'private':
            raise HTTPException(404, '记忆不存在')
        return [r.data for r in records(db, 'revision', gid) if r.data['memory_key'] == key]

@app.get('/api/groups/{gid}/members/{uid}/profile')
def member_profile(gid: int, uid: int, domain: str = 'medical', user=Depends(current)):
    access(gid, user)
    from .memory import list_profile
    with DB() as db:
        # Verify membership (or personal space owner)
        if gid >= 0 and not db.query(Member).filter_by(group_id=gid, user_id=uid).first():
            raise HTTPException(404, '该成员不在此群内')
        if gid < 0 and uid != -gid:
            raise HTTPException(403, '只能查看本人的档案')
        profiles = list_profile(db, gid, uid, domain)
        grouped = {}
        for p in profiles:
            rt = (p.get('profile') or {}).get('record_type', 'other')
            grouped.setdefault(rt, []).append(p)
        return {'member_id': uid, 'domain': domain, 'profiles': profiles, 'grouped': grouped}

class TaskBody(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    owner_id: Optional[int] = None
    due: Optional[float] = None
    done: bool = False

@app.get('/api/groups/{gid}/tasks')
def list_tasks(gid: int, user=Depends(current)):
    access(gid, user)
    with DB() as db:
        return [dict(key=r.key, **r.data) for r in records(db, 'task', gid)]

@app.post('/api/groups/{gid}/tasks')
async def add_task(gid: int, body: TaskBody, user=Depends(current)):
    return await update_task(gid, str(uuid.uuid4()), body, user)

@app.put('/api/groups/{gid}/tasks/{key}')
async def update_task(gid: int, key: str, body: TaskBody, user=Depends(current)):
    access(gid, user)
    with DB() as db:
        if body.owner_id and not db.query(Member).filter_by(group_id=gid, user_id=body.owner_id).first():
            raise HTTPException(400, '负责人不在本群')
        put(db, 'task', gid, key, body.model_dump())
        db.commit()
    await broadcast(gid, {'type': 'refresh'})
    return {'key': key, **body.model_dump()}

class SettingsBody(BaseModel):
    agent_name: str = Field(min_length=1, max_length=20, pattern=r'^[\w\u3400-\u9fff]+$')
    prompt: str = Field(min_length=1, max_length=12000)
    active: bool
    wait_seconds: int = Field(ge=1, le=86400)
    cooldown_seconds: int = Field(default=300, ge=0, le=86400)
    context_budget: int = Field(default=24000, ge=4000, le=64000)
    care_group_limit: int = Field(default=1, ge=0, le=10)
    participation_shadow: bool = False
    memory_auto: bool = True
    memory_short_days: int = Field(default=7, ge=1, le=30)
    memory_review_seconds: int = Field(default=21600, ge=3600, le=604800)

@app.get('/api/groups/{gid}/settings')
def settings(gid: int, user=Depends(current)):
    access(gid, user)
    with DB() as db:
        return {**get(db, 'group', gid, 'settings').data, 'model': os.getenv('DEEPSEEK_MODEL', 'deepseek-flash'), 'configured': bool(os.getenv('DEEPSEEK_API_KEY'))}

@app.put('/api/groups/{gid}/settings')
async def update_settings(gid: int, body: SettingsBody, user=Depends(current)):
    access(gid, user)
    with DB() as db:
        old = get(db, 'group', gid, 'settings').data
        d = {**old, **body.model_dump(), 'version': old['version']+1}
        put(db, 'group', gid, 'settings', d)
        if old.get('memory_review_seconds',21600) != d['memory_review_seconds']:
            maintenance=get(db,'memory_maintenance',gid,'latest')
            if maintenance:
                state=maintenance.data
                # New cadence applies immediately; do not postpone dirty work.
                due=time.time()+d['memory_review_seconds']
                maintenance.set({**state,'next_due':min(state['next_due'],due) if state.get('dirty') else due})
        # Invalidate existing candidates; new settings apply to subsequent needs.
        for r in records(db, 'demand', gid):
            if r.data['status'] == 'waiting':
                value = r.data
                value['status'] = 'cancelled'
                r.set(value)
        db.commit()
    await broadcast(gid, {'type': 'refresh'})
    return d

@app.get('/api/groups/{gid}/activity')
def activity(gid: int, user=Depends(current)):
    access(gid, user)
    with DB() as db:
        logs = [r.data for r in records(db, 'log', gid)][-50:][::-1]
        failed = [dict(key=r.key, **r.data) for r in records(db, 'job', gid) if r.data['status'] in ('failed', 'reply_failed')][-20:]
        failed += [dict(key='demand:'+r.key, error=r.data.get('error', '候选生成失败'), mention=False) for r in records(db, 'demand', gid) if r.data['status'] == 'failed'][-20:]
        return {'logs': logs, 'failed': failed}

@app.get('/api/groups/{gid}/agent/status')
def agent_status(gid: int, user=Depends(current)):
    access(gid, user)
    return snapshot(agent, gid)

@app.get('/api/groups/{gid}/agent/chains')
def agent_chains(gid: int, ids: str = '', user=Depends(current)):
    access(gid, user)
    if not user.get('observer'):
        raise HTTPException(403, '仅 Agent 观察者可查看执行链路')
    try:
        selected = [int(value) for value in ids.split(',') if value]
    except ValueError:
        raise HTTPException(422, '消息编号格式不正确')
    if len(selected) > 100:
        raise HTTPException(422, '每次最多查询100条消息')
    from .execution_chain import query
    return query(gid, selected)


@app.get('/api/groups/{gid}/agent/annotations')
def agent_annotations(gid: int, ids: str = '', user=Depends(current)):
    access(gid, user)
    try:
        selected = [int(value) for value in ids.split(',') if value]
    except ValueError:
        raise HTTPException(422, '消息编号格式不正确')
    if len(selected) > 100:
        raise HTTPException(422, '每次最多查询100条消息')
    return message_annotations(gid, selected)

@app.get('/api/groups/{gid}/agent/messages')
def agent_messages(gid: int, before: Optional[int] = None, user=Depends(current)):
    access(gid, user)
    return message_list(gid, before)

@app.get('/api/groups/{gid}/agent/messages/{mid}')
def agent_message(gid: int, mid: int, user=Depends(current)):
    access(gid, user)
    detail = message_detail(gid, mid)
    if detail is None:
        raise HTTPException(404, '消息不存在')
    return detail

@app.post('/api/groups/{gid}/retry/{key}')
async def retry(gid: int, key: str, user=Depends(current)):
    access(gid, user)
    with DB() as db:
        if key.startswith('demand:'):
            r = get(db, 'demand', gid, key[len('demand:'):])
            if not r or r.data['status'] != 'failed':
                raise HTTPException(400, '任务不可重试')
            d = r.data
            d.update(status='waiting', candidate=None, version=d['version']+1)
            r.set(d)
            db.commit()
            return {'ok': True}
        r = get(db, 'job', gid, key)
        if not r or r.data['status'] not in ('failed', 'reply_failed'):
            raise HTTPException(400, '任务不可重试')
        d = r.data
        d['status'] = 'pending'
        d.pop('error', None)
        r.set(d)
        db.commit()
    return {'ok': True}

@app.websocket('/ws/{gid}')
async def websocket(ws: WebSocket, gid: int):
    try:
        user = websocket_user(ws)
        access(gid, user)
        origin = ws.headers.get('origin', '')
        allowed = {f'http://{ws.headers.get("host")}', f'https://{ws.headers.get("host")}', 'http://localhost:5173', 'http://127.0.0.1:5173'}
        if origin not in allowed:
            raise HTTPException(403)
    except HTTPException:
        await ws.close(code=1008)
        return
    await ws.accept()
    connections[gid][ws] = user['id']
    await broadcast(gid, {'type': 'presence'})
    try:
        while True:
            await ws.receive_text()
            websocket_user(ws)
            await ws.send_json({'type': 'pong'})
    except (WebSocketDisconnect, HTTPException):
        pass
    finally:
        connections[gid].pop(ws, None)
        await broadcast(gid, {'type': 'presence'})

from .harness_api import router as harness_router
app.include_router(harness_router(agent))

from .cards import install_routes
install_routes(app, current, access)

# 家人帮：就医守护编排、演示导演台、模拟医院数据接口
from .care import install_routes as install_care_routes
install_care_routes(app, current, access, agent)
from .hospital_data import router as hospital_router, app_router as hospital_app_router
app.include_router(hospital_router)
app.include_router(hospital_app_router)

DIST = Path(__file__).resolve().parent.parent / 'frontend' / 'dist'
if DIST.exists():
    app.mount('/assets', StaticFiles(directory=DIST / 'assets'), name='assets')

@app.get('/hospital')
def hospital_root():
    return RedirectResponse('/hospital/')


@app.get('/hospital/')
def hospital_index():
    return hospital_app('')


@app.get('/hospital/{path:path}')
def hospital_app(path: str):
    root = Path(__file__).resolve().parent.parent / 'hospital' / 'dist'
    index = root / 'index.html'
    if not index.exists():
        raise HTTPException(503, '请先构建模拟医院：cd hospital; npm install; npm run build')
    candidate = (root / path).resolve()
    if path and candidate.is_relative_to(root.resolve()) and candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(index)


@app.get('/{path:path}')
def index(path: str):
    if path.startswith(('api/', 'ws/')):
        raise HTTPException(404)
    if not (DIST / 'index.html').exists():
        raise HTTPException(503, '请先运行前端构建：cd frontend; npm install; npm run build')
    return FileResponse(DIST / 'index.html')

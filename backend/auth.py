"""Authenticated personal spaces alongside the optional URL group demo."""
import hashlib
import secrets
import time
from fastapi import HTTPException, Request
from .db import DB, User, Session, get, put, password_hash, password_ok

COOKIE = 'xiaoyi_session'
SESSION_SECONDS = 7 * 86400


def session_user(token):
    if not token:
        return None
    digest = hashlib.sha256(token.encode()).hexdigest()
    with DB() as db:
        s = db.get(Session, digest)
        if not s or s.expires <= time.time():
            return None
        u = db.get(User, s.user_id)
        if not u:
            return None
        return {'id': u.id, 'name': u.name, 'username': u.username, 'authenticated': True}


def authenticated(request: Request):
    user = session_user(request.cookies.get(COOKIE))
    if not user:
        raise HTTPException(401, '请使用密码登录个人空间')
    return user


def login(username, password, address):
    now = time.time()
    key = hashlib.sha256((address + ':' + username).encode()).hexdigest()
    with DB() as db:
        attempts = get(db, 'auth_attempt', 0, key)
        state = attempts.data if attempts and now - attempts.data['since'] < 900 else {'since': now, 'count': 0}
        if state['count'] >= 5:
            raise HTTPException(429, '尝试过多，请15分钟后重试')
        u = db.query(User).filter_by(username=username).first()
        configured = bool(u and ':' in u.password)
        stored = u.password if configured else password_hash('not-a-user', 'dummy-auth-salt')
        try:
            valid = password_ok(password, stored)
        except (ValueError, TypeError):
            valid = False
        if not configured or not valid:
            state['count'] += 1
            put(db, 'auth_attempt', 0, key, state)
            db.commit()
            raise HTTPException(401, '成员或密码不正确；首次使用需由本机管理员设置密码')
        put(db, 'auth_attempt', 0, key, {'since': now, 'count': 0})
        token = secrets.token_urlsafe(32)
        db.add(Session(token=hashlib.sha256(token.encode()).hexdigest(), user_id=u.id, expires=now + SESSION_SECONDS))
        # A separate namespace prevents private data appearing in any group API.
        from .db import DEFAULT_PROMPT
        if not get(db, 'group', -u.id, 'settings'):
            put(db, 'group', -u.id, 'settings', {'name': '个人空间', 'agent_name': '小忆',
                'prompt': DEFAULT_PROMPT + ' 当前是仅本人可见的个人会话，不向家庭群传播私人信息。',
                'active': False, 'wait_seconds': 30, 'version': 1})
        db.commit()
        return token, {'id': u.id, 'name': u.name, 'username': u.username, 'authenticated': True}


def configure_password(username, password):
    if len(password) < 10:
        raise ValueError('密码至少10个字符')
    with DB() as db:
        u = db.query(User).filter_by(username=username).first()
        if not u:
            raise ValueError('成员不存在')
        u.password = password_hash(password)
        db.query(Session).filter_by(user_id=u.id).delete()
        db.commit()


if __name__ == '__main__':
    import argparse
    import getpass
    from .db import migrate
    parser = argparse.ArgumentParser(description='本机管理员为家庭成员设置密码，不提供远程抢注入口')
    parser.add_argument('username', choices=['dad', 'mom', 'child'])
    args = parser.parse_args()
    first = getpass.getpass('新密码（至少10位）：')
    if first != getpass.getpass('再次输入：'):
        raise SystemExit('两次密码不一致')
    migrate()
    configure_password(args.username, first)
    print('密码已更新，原有会话已注销。')

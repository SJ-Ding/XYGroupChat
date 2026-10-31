"""Drive the local simulator to an unpaid reservation; payment is confirmed by the user."""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import threading
import time
import uuid
import webbrowser

import httpx

from .db import DB, Message, get, put
from .appointment_intent import appointment_operation
from .cards import save_card
from .skills import REGISTRY, Tool, register, schema


HOSPITAL_RE = re.compile(r"医院|挂.{0,8}号|预约|门诊|就诊|科室|医生|模拟器")
_CONFIRM_DETAILS_JS = r"""
() => {
  const labels = ['院区', '科室', '医生', '就诊日期', '就诊时间', '就诊人', '挂号费'];
  const values = {};
  for (const dt of document.querySelectorAll('dt')) {
    const label = (dt.textContent || '').trim();
    if (!labels.includes(label) || values[label]) continue;
    const dd = dt.nextElementSibling;
    if (dd) values[label] = (dd.textContent || '').trim();
  }
  const fee = Number((values['挂号费'] || '').replace(/[^\d.]/g, ''));
  return {
    campus: values['院区'] || '',
    department: values['科室'] || '',
    doctor: values['医生'] || '',
    date: values['就诊日期'] || '',
    time: values['就诊时间'] || '',
    patient: values['就诊人'] || '',
    fee: Number.isFinite(fee) ? fee : null,
  };
}
"""
# 代为操作时高亮将要点击的元素，并更新医院页面顶部“小艺正在代为操作”横幅
_HIGHLIGHT_JS = r"""
([sel, label]) => {
  try {
    const hospital = location.pathname.match(/\/hospital\/apps\/([^/]+)/)?.[1] || 'legacy';
    sessionStorage.setItem('agent_driving:' + hospital, '1');
    sessionStorage.setItem('agent_step:' + hospital, label);
    window.dispatchEvent(new Event('agent-step'));
  } catch (e) {}
  const el = sel ? document.querySelector(sel) : null;
  if (!el) return false;
  el.scrollIntoView({ block: 'center', behavior: 'instant' });
  el.style.outline = '3px solid #FF7A45';
  el.style.outlineOffset = '3px';
  el.style.boxShadow = '0 0 0 8px rgba(255,122,69,.18)';
  return true;
}
"""
DEPARTMENTS = (
    "普通内科", "呼吸内科", "心血管内科", "消化内科", "内分泌科", "神经内科",
    "肾内科", "普通外科", "骨科", "神经外科", "泌尿外科", "胸外科",
    "妇科", "产科", "儿科", "眼科", "耳鼻喉科", "口腔科",
    "皮肤科", "肿瘤科", "中医科", "老年医学科",
)
SYMPTOM_DEPARTMENTS = {
    "骨折": "骨科", "关节": "骨科", "膝盖": "骨科", "腰痛": "骨科", "腰间盘": "骨科",
    "颈椎": "骨科", "扭伤": "骨科", "腿疼": "骨科",
    "咳嗽": "呼吸内科", "气喘": "呼吸内科", "哮喘": "呼吸内科", "肺炎": "呼吸内科",
    "心慌": "心血管内科", "胸闷": "心血管内科", "胸痛": "心血管内科", "高血压": "心血管内科",
    "胃痛": "消化内科", "胃胀": "消化内科", "反酸": "消化内科", "腹泻": "消化内科",
    "糖尿病": "内分泌科", "甲状腺": "内分泌科",
    "头痛": "神经内科", "头晕": "神经内科", "失眠": "神经内科", "手脚发麻": "神经内科",
    "尿频": "泌尿外科", "尿急": "泌尿外科", "血尿": "泌尿外科", "肾结石": "泌尿外科",
    "月经": "妇科", "白带": "妇科", "产检": "产科", "怀孕": "产科",
    "儿童发热": "儿科", "湿疹": "皮肤科", "近视": "眼科", "白内障": "眼科",
    "鼻塞": "耳鼻喉科", "耳鸣": "耳鼻喉科", "牙痛": "口腔科",
    "皮肤过敏": "皮肤科", "荨麻疹": "皮肤科", "针灸": "中医科", "调理": "中医科",
}


def hospital_relevant(text: str) -> bool:
    return bool(HOSPITAL_RE.search(text or "") or appointment_operation(text))


def hospital_base(hospital_id=None) -> str:
    value = os.getenv("HOSPITAL_BASE", "http://127.0.0.1:8000/hospital/").strip()
    base = value.rstrip("/") + "/"
    return base + "apps/" + hospital_id + "/" if hospital_id else base


def booking_context(instruction: str) -> dict:
    department = next(
        (name for name in sorted(DEPARTMENTS, key=len, reverse=True) if name in instruction),
        None,
    )
    if department is None:
        department = next(
            (name for symptom, name in SYMPTOM_DEPARTMENTS.items() if symptom in instruction),
            None,
        )
    patient_name = "林志强" if "爸爸" in instruction or "林志强" in instruction else ("小林" if "小林" in instruction or "女儿" in instruction else "王秀兰")
    return {
        "hospital": "附近两家医院 · 模拟挂号",
        "department": department,
        "preferred_time": "下午" if "下午" in instruction else "上午",
        "patient_name": patient_name,
        "patient_id": "p-003" if patient_name == "林志强" else ("p-002" if patient_name == "小林" else "p-001"),
    }


def _model_chat(system_prompt: str, user_prompt: str, *, json_mode: bool = False) -> str:
    """Synchronous callback retained for the standalone run_web_task harness."""
    from .model import _PROXY, _VERIFY

    key = os.getenv("DEEPSEEK_API_KEY", "")
    if not key:
        raise RuntimeError("尚未配置 DEEPSEEK_API_KEY")
    body = {
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 1000,
        "stream": False,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/") + "/chat/completions"
    with httpx.Client(timeout=65, proxy=_PROXY, verify=_VERIFY) as client:
        response = client.post(url, headers={"Authorization": "Bearer " + key}, json=body)
    response.raise_for_status()
    content = response.json()["choices"][0]["message"].get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("网页操作模型返回为空")
    return content


def _source_text(ctx) -> str:
    if not ctx.source_id:
        return ""
    with DB() as db:
        message = db.get(Message, ctx.source_id)
        if message and message.group_id == ctx.group_id and message.user_id == ctx.user_id:
            return message.content or ""
    return ""


def _explicit_booking(text: str) -> bool:
    return appointment_operation(text) == 'book'


def _explicit_cancel(text: str) -> bool:
    return bool(re.search(r"(取消|停止|终止)", text))


def _run_key(gid, user_id, instruction, hospital_id=None):
    identity = f"{gid}:{user_id}:{instruction}" + (f":{hospital_id}" if hospital_id else "")
    return "appt-" + hashlib.sha256(identity.encode()).hexdigest()[:16]


# ---------------- 浏览器会话（后台线程 + 同步 Playwright） ----------------
class _Session:
    def __init__(self, task_id, gid, user_id, run_key, context):
        self.task_id = task_id
        self.gid = gid
        self.user_id = user_id
        self.run_key = run_key
        self.context = context
        self.status = "starting"
        self.error = None
        self.appointment = None
        self.details = None
        self.step = ''
        self.proceed = threading.Event()
        self.stop = threading.Event()

    def snapshot(self):
        return {"task_id": self.task_id, "status": self.status, "error": self.error,
                "appointment": self.appointment, "details": self.details, "step": self.step,
                "url": hospital_base(self.context.get("hospital_id"))}


class AppointmentManager:
    def __init__(self):
        self.sessions: dict[str, _Session] = {}
        self._lock = threading.Lock()

    def start(self, task_id, gid, user_id, run_key, context) -> _Session:
        with self._lock:
            existing = self.sessions.get(task_id)
            if existing:
                return existing
            session = _Session(task_id, gid, user_id, run_key, context)
            self.sessions[task_id] = session
        threading.Thread(target=self._run, args=(session,), daemon=True, name=f"hospital-{task_id[:8]}").start()
        return session

    def get(self, task_id) -> _Session | None:
        with self._lock:
            return self.sessions.get(task_id)

    def confirm(self, task_id) -> bool:
        session = self.get(task_id)
        if not session:
            return False
        session.proceed.set()
        return True

    def cancel(self, task_id) -> bool:
        session = self.get(task_id)
        if not session:
            return False
        session.stop.set()
        session.proceed.set()
        return True

    def shutdown(self):
        for session in list(self.sessions.values()):
            session.stop.set()
            session.proceed.set()

    @staticmethod
    def _prepare_playwright_env():
        # The migrated project owns its Playwright dependency. An optional
        # shared browser cache can be selected explicitly through the env var.
        browsers = os.getenv("PLAYWRIGHT_BROWSERS_PATH")
        if browsers:
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = browsers

    @staticmethod
    def _pause():
        return 1500

    def _launch(self, pw):
        headless = os.getenv("HOSPITAL_HEADLESS", "").lower() in ("1", "true", "yes")
        options = {"headless": headless, "slow_mo": int(os.getenv("HOSPITAL_SLOWMO", "120")),
                   "args": ["--window-size=1300,900"]}
        try:
            return pw.chromium.launch(**options)
        except Exception as first_error:
            for executable in (
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            ):
                if os.path.exists(executable):
                    try:
                        return pw.chromium.launch(executable_path=executable, **options)
                    except Exception:
                        continue
            raise RuntimeError("未找到可用浏览器，请安装 Chrome/Edge 或运行 playwright install chromium") from first_error

    def _run(self, session: _Session):
        try:
            self._prepare_playwright_env()
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # noqa: BLE001
            self._fail(session, f"无法加载浏览器组件：{exc}")
            return
        with sync_playwright() as pw:
            browser = None
            try:
                browser = self._launch(pw)
                page = browser.new_page(viewport={"width": 1280, "height": 800})
                self._fill_until_confirm(page, session)
                if session.stop.is_set():
                    self._fail(session, "任务已取消")
                    return
                session.status = "submitting"
                session.proceed.set()
                self._wait_for_submit(page, session)
            except Exception as exc:  # noqa: BLE001
                self._fail(session, str(exc)[:300])
            finally:
                if browser is not None:
                    try:
                        browser.close()
                    except Exception:
                        pass
        if session.status == "done" and session.appointment:
            self._finalize_run(session)
            _schedule(_care_booked(session.gid, session.run_key, session.appointment))

    def _click(self, page, locator, session):
        delay = max(0, 1.5 - (time.monotonic() - getattr(session, "last_click", 0)))
        if delay:
            page.wait_for_timeout(int(delay * 1000) + 1)
        if session.stop.is_set():
            raise RuntimeError("任务已取消")
        locator.click(timeout=10000)
        session.last_click = time.monotonic()

    def _act(self, page, testid, label, session, pause=None):
        """高亮 → 停顿 → 点击。选择器统一用 data-testid，不依赖页面视觉位置。"""
        selector = f'[data-testid="{testid}"]'
        page.wait_for_selector(selector, timeout=10000)
        page.evaluate(_HIGHLIGHT_JS, [selector, label])
        session.step = label
        _schedule(_progress(session.gid, session.run_key, label))
        page.wait_for_timeout(self._pause() if pause is None else pause)
        self._click(page, page.locator(selector).first, session)

    def _announce(self, page, label, session):
        page.evaluate(_HIGHLIGHT_JS, [None, label])
        session.step = label
        _schedule(_progress(session.gid, session.run_key, label))

    def _fill_targeted(self, page, session):
        """精确代办：家人在号源对比卡上选定的院区/医生/时间，逐步点到核对页。"""
        from .hospital_data import department_by_name, campus, doctor, patient
        c = session.context
        dept = department_by_name(c["department"])
        doc, camp, pat = doctor(c["doctor_id"]), campus(c["campus_id"]), patient(c["patient_id"])
        page.goto(hospital_base(session.context.get("hospital_id")) + "appointment/departments", wait_until="domcontentloaded", timeout=15000)
        page.wait_for_selector('[data-testid^="dept-"]', timeout=15000)
        self._announce(page, "打开模拟医院 · 预约挂号", session)
        page.wait_for_timeout(self._pause())
        self._act(page, f"campus-{camp['id']}", f"选择院区：{camp['name']}", session)
        self._act(page, f"dept-{dept['id']}", f"选择科室：{dept['name']}", session)
        page.wait_for_url(re.compile(r"/appointment/schedule"), timeout=15000)
        self._act(page, f"date-{c['date']}", f"选择日期：{c['date']}", session)
        self._act(page, f"doctor-{doc['id']}", f"选择医生：{doc['name']}（{doc['title']}）", session)
        self._act(page, f"slot-{c['slot_id']}", f"选择号源：{c['preferred_time']} {c.get('time', '')}".strip(), session)
        page.wait_for_url(re.compile(r"/appointment/patient"), timeout=15000)
        self._act(page, f"patient-{pat['id']}", f"选择就诊人：{pat['name']}", session)
        # 任务标识用于请求幂等。
        page.evaluate(
            "([t, k, h]) => { sessionStorage.setItem('hospital_task_id:' + h, t); sessionStorage.setItem('hospital_token:' + h, k); }",
            [session.task_id, "tk-" + uuid.uuid4().hex[:16], session.context.get("hospital_id") or "legacy"],
        )
        self._act(page, "patient-next", "下一步：核对预约信息", session)
        page.wait_for_url(re.compile(r"/appointment/confirm"), timeout=15000)
        self._act(page, "agree", "勾选预约须知", session)
        session.details = page.evaluate(_CONFIRM_DETAILS_JS)
        self._announce(page, "信息已核对 · 正在锁号", session)

    def _fill_until_confirm(self, page, session):
        if session.context.get("slot_id"):
            return self._fill_targeted(page, session)
        base = hospital_base(session.context.get("hospital_id"))
        page.goto(base + "appointment/departments", wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(800)
        dept = session.context["department"]
        try:
            page.get_by_label("搜索科室").fill(dept)
            page.wait_for_timeout(500)
        except Exception:
            pass
        self._click(page, page.locator("button", has_text=dept).first, session)
        page.wait_for_url(re.compile(r"/appointment/schedule"), timeout=15000)
        page.wait_for_timeout(800)
        self._pick_slot(page, session)
        page.wait_for_url(re.compile(r"/appointment/patient"), timeout=15000)
        page.wait_for_timeout(500)
        patient = session.context["patient_name"]
        self._click(page, page.locator(f'button[aria-label="选择就诊人 {patient}"]'), session)
        # 保留任务标识，刷新后提交仍保持幂等。
        page.evaluate(
            "([t, k, h]) => { sessionStorage.setItem('hospital_task_id:' + h, t); sessionStorage.setItem('hospital_token:' + h, k); }",
            [session.task_id, "tk-" + uuid.uuid4().hex[:16], session.context.get("hospital_id") or "legacy"],
        )
        self._click(page, page.get_by_role("button", name="下一步"), session)
        page.wait_for_url(re.compile(r"/appointment/confirm"), timeout=15000)
        page.wait_for_timeout(800)
        self._click(page, page.get_by_label("同意预约须知"), session)
        page.wait_for_timeout(300)
        session.details = page.evaluate(_CONFIRM_DETAILS_JS)

    def _pick_slot(self, page, session):
        session_word = session.context["preferred_time"]
        dates = page.locator('button[aria-label^="选择"]')
        for i in range(dates.count()):
            date_btn = dates.nth(i)
            if "无号" in (date_btn.inner_text() or ""):
                continue
            self._click(page, date_btn, session)
            page.wait_for_timeout(700)
            doctors = page.locator('button:not([aria-label])', has_text="个号源")
            for j in range(doctors.count()):
                if session.stop.is_set():
                    return
                self._click(page, doctors.nth(j), session)
                page.wait_for_timeout(600)
                slots = page.locator('button[aria-label*="挂号费"]')
                for k in range(slots.count()):
                    aria = slots.nth(k).get_attribute("aria-label") or ""
                    if session_word in aria and "可预约" in aria:
                        self._click(page, slots.nth(k), session)
                        return
        raise RuntimeError("未找到符合时间的可预约号源，请更换日期或时段")

    def _wait_for_submit(self, page, session):
        deadline = time.time() + 300
        while time.time() < deadline:
            if session.stop.is_set():
                self._fail(session, "任务已取消")
                return
            if "/appointment/result" in page.url:
                self._complete(session, page)
                return
            if session.proceed.wait(1.0):
                session.status = "submitting"
                try:
                    self._act(page, "submit-appointment", "自动提交模拟预约", session, pause=400)
                except Exception:
                    self._click(page, page.get_by_role("button", name=re.compile("确认提交预约")), session)
                page.wait_for_url(re.compile(r"/appointment/result"), timeout=20000)
                try:
                    page.wait_for_selector('[data-testid="appointment-id"]', timeout=8000)
                except Exception:
                    pass
                self._announce(page, "锁号成功 · 支付请在小艺的支付卡中由本人完成", session)
                self._complete(session, page)
                page.wait_for_timeout(int(os.getenv("HOSPITAL_RESULT_HOLD", "2500")))
                return
        self._fail(session, "等待确认超时")

    @staticmethod
    def _complete(session, page):
        text = page.inner_text("body")
        m = re.search(r"AP-[A-Z0-9]+", text)
        if not m:
            raise RuntimeError("页面未返回预约编号")
        appt_id = m.group(0)
        session.appointment = {"id": appt_id, "url": page.url, "hospital_id": session.context.get("hospital_id")}
        if session.details:
            session.appointment.update({k: session.details[k] for k in
                                        ("campus", "department", "doctor", "date", "time", "patient", "fee")
                                        if session.details.get(k)})
        session.status = "done"

    def _fail(self, session, error):
        session.status = "failed"
        session.error = error
        self._finalize_run(session)

    def _finalize_run(self, session):
        with DB() as db:
            r = get(db, "run", session.gid, session.run_key)
            if not r:
                return
            value = r.data
            if session.status == "done" and session.appointment:
                content = "预约成功：编号 " + session.appointment["id"]
                for key, label in (("campus", "院区"), ("department", "科室"), ("doctor", "医生"),
                                   ("date", "日期"), ("time", "时间"), ("patient", "就诊人")):
                    if session.appointment.get(key):
                        content += f" · {label} {session.appointment[key]}"
                if value.get("status") not in ("succeeded", "cancelled"):
                    value["status"] = "succeeded"
                    if value.get("steps"):
                        value["steps"][0]["status"] = "succeeded"
                        value["steps"][0]["result"] = {"appointment": session.appointment, "content": content}
            elif value.get("status") not in ("succeeded", "cancelled"):
                value["status"] = "failed"
                if value.get("steps"):
                    value["steps"][0]["status"] = "failed"
                value["error"] = session.error or "预约未完成"
            value.pop("intervention", None)
            value["updated"] = time.time()
            r.set(value)
            card = get(db, "card", session.gid, f"review:{session.run_key}:confirm")
            if card and session.status != "done":
                cval = card.data
                cval["status"] = "resolved"
                card.set(cval)
            db.commit()
        _schedule(_publish_and_notify(session.gid, session.run_key, None))


automation = AppointmentManager()

_main_loop = None
_latest_tasks: dict[tuple[int, int], str] = {}
_started_tasks: set[str] = set()
_latest_lock = threading.Lock()


def reset_sessions():
    """演示重置：停止所有浏览器任务并清空任务索引。"""
    automation.shutdown()
    automation.sessions = {}
    with _latest_lock:
        _latest_tasks.clear()
        _started_tasks.clear()


async def _progress(gid, run_key, label):
    """把浏览器当前步骤同步到聊天里的任务进度条。"""
    try:
        from .cards import update_progress
        with DB() as db:
            run = get(db, "run", gid, run_key)
            if not run or run.data.get("status") in ("succeeded", "failed", "cancelled"):
                return
        await update_progress(gid, run_key, "小艺正在操作医院网页：" + label)
    except Exception:  # noqa: BLE001
        pass


async def _care_booked(gid, run_key, appointment):
    try:
        from .care import on_booked
        await on_booked(gid, run_key, appointment)
    except Exception:  # noqa: BLE001 - 回调失败不影响预约结果
        import logging
        logging.getLogger(__name__).exception('就医守护回调失败')


def set_event_loop(loop):
    global _main_loop
    _main_loop = loop


def _schedule(coro):
    loop = _main_loop
    if loop is not None and loop.is_running():
        asyncio.run_coroutine_threadsafe(coro, loop)
    else:
        coro.close()


def _owned_session(ctx, task_id):
    session = automation.get(task_id)
    if not session:
        return None
    if getattr(session, "gid", ctx.group_id) != ctx.group_id:
        return None
    if getattr(session, "user_id", ctx.user_id) != ctx.user_id:
        return None
    return session


async def _publish_and_notify(gid, key, card=None):
    from .cards import publish_run, notify
    try:
        await publish_run(gid, key)
        if card:
            await notify(gid, card)
    except Exception:
        pass


def _poll_done(task_id, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        session = automation.get(task_id)
        if session is None:
            return {"error": "任务不存在"}
        if session.status == "done" and session.appointment:
            return {"status": "confirmed", "appointment": session.appointment,
                    "content": "预约成功：编号 " + session.appointment["id"]}
        if session.status == "failed":
            return {"error": session.error or "预约失败"}
        time.sleep(0.3)
    session = automation.get(task_id)
    return {"status": "pending", "task_id": task_id,
            "message": "已确认，浏览器正在提交，稍后可在结果卡片查看预约编号",
            "session": session.snapshot() if session else None}


async def hospital_simulator(ctx, args):
    action = args["action"]
    if action == "nearby":
        from .hospital_discovery import discover
        from .memory import list_memories
        address = args.get('address', '').strip()
        with DB() as db:
            memories = list_memories(db, ctx.group_id, viewer_id=ctx.user_id if ctx.group_id < 0 else None)
        if not address or not any(address in m['content'] for m in memories):
            return {'error': '请先补充并记住父母所在城市及道路，再查询附近医院'}
        try:
            return {'hospitals': await discover(address), 'source': '高德 MCP'}
        except ValueError as error:
            return {'error': str(error)}
    if action == "query":
        from . import hospital_data as H
        dept = H.department_by_name(args.get("department", ""))
        if not dept:
            return {"error": "请明确要查询的科室"}
        dates = [args["date"]] if args.get("date") else H.window()
        result = [s for s in H.generate_slots(dates) if s['departmentId'] == dept['id']
                  and (not args.get('hospital_id') or s.get('hospitalId') == args['hospital_id'])
                  and (not args.get('campus_id') or s['campusId'] == args['campus_id'])
                  and (not args.get('doctor_id') or s['doctorId'] == args['doctor_id'])
                  and (not args.get('time') or s['startTime'] == args['time'])
                  and (not args.get('preferred_time') or s['session'] == ('morning' if args['preferred_time'] == '上午' else 'afternoon'))]
        return {"slots": result, "simulated": True, "hospitals": H.catalog().get('hospitals', []),
                "query": {"department": dept['name'], "dates": dates,
                    **{key: args[key] for key in ('date', 'time', 'preferred_time', 'hospital_id', 'campus_id', 'doctor_id') if args.get(key)}}}
    if action == "open":
        source_text = _source_text(ctx)
        if source_text and not (re.search(r"(打开|访问|进入|看看|启动)", source_text) and hospital_relevant(source_text)):
            return {"error": "当前消息没有明确要求打开模拟医院"}
        hospital_id = args.get('hospital_id')
        if hospital_id:
            from .hospital_data import catalog
            if not any(h['id'] == hospital_id for h in catalog()['hospitals']):
                return {'error': '所选医院应用不存在'}
        url = hospital_base(hospital_id)
        opened = await asyncio.to_thread(webbrowser.open, url, 2)
        return {"ok": True, "url": url, "opened": opened, "message": "模拟医院已打开"}

    if action == "book":
        instruction = args.get("instruction", "").strip()
        if not instruction:
            return {"error": "请提供完整的挂号指令"}
        source_text = _source_text(ctx)
        if source_text and not _explicit_booking(source_text):
            return {"error": "当前消息没有明确要求预约或打开模拟医院"}
        from . import hospital_data as H
        selected_hospital = args.get('hospital_id') or next((h['id'] for h in H.catalog()['hospitals'] if h['name'] in instruction), None)
        if not selected_hospital:
            return {'status': 'awaiting_hospital_selection', 'hospitals': H.catalog()['hospitals'], 'message': '请先选择一家医院，再执行模拟挂号'}
        if not any(h['id'] == selected_hospital for h in H.catalog()['hospitals']):
            return {'error': '所选医院应用不存在'}
        args = {**args, 'hospital_id': selected_hospital}
        key = _run_key(ctx.group_id, ctx.user_id, instruction, args.get("hospital_id"))
        with DB() as db:
            existing = get(db, 'run', ctx.group_id, key)
        if existing:
            session = _owned_session(ctx, key)
            return {'ok': True, 'task_id': key, 'status': session.status if session else existing.data['status']}
        context = booking_context(instruction)
        if not context.get("department") and not args.get("department"):
            return {"error": "请明确科室或症状"}
        if args.get("department"):
            context["department"] = args["department"]
        if args.get("patient_name"):
            context["patient_name"] = args["patient_name"]
            from .hospital_data import catalog
            pat = next((p for p in catalog()['patients'] if p['name'] == args['patient_name']), None)
            if not pat:
                return {'error': '请明确已登记的就诊人'}
            context['patient_id'] = pat['id']
        if args.get("preferred_time"):
            context["preferred_time"] = args["preferred_time"]
        for name in ("slot_id", "campus_id", "doctor_id", "date", "patient_id"):
            if args.get(name):
                context[name] = args[name]
        if context.get("slot_id"):
            context["time"] = context["slot_id"][-4:-2] + ":" + context["slot_id"][-2:]
        from . import hospital_data as H
        if not context.get('slot_id'):
            dept = H.department_by_name(context['department'])
            candidates = [s for s in H.generate_slots([context['date']] if context.get('date') else H.window())
                if dept and s['departmentId'] == dept['id'] and s['status'] == 'available'
                and s['session'] == ('morning' if context['preferred_time'] == '上午' else 'afternoon')
                and (not args.get('hospital_id') or s.get('hospitalId') == args['hospital_id'])]
            if not candidates:
                return {'error': '没有符合条件的可用号源'}
            chosen = candidates[0]
            context.update(slot_id=chosen['id'], campus_id=chosen['campusId'], doctor_id=chosen['doctorId'], date=chosen['date'], time=chosen['startTime'])
        chosen = H.slot(context['slot_id'])
        if chosen and args.get('hospital_id') and chosen.get('hospitalId') != args['hospital_id']:
            return {'error': '号源不属于所选医院，请重新查询'}
        if not chosen or chosen['status'] != 'available':
            return {'error': '指定号源已失效，请重新查询'}
        if not H.patient(context['patient_id']):
            return {'error': '就诊人不存在'}
        context.update(hospital_id=chosen.get('hospitalId'), campus_id=chosen['campusId'],
            doctor_id=chosen['doctorId'], date=chosen['date'], time=chosen['startTime'],
            department=H.department(chosen['departmentId'])['name'])
        key = _run_key(ctx.group_id, ctx.user_id, instruction, args.get("hospital_id"))
        with DB() as db:
            run = get(db, "run", ctx.group_id, key)
            if not run:
                step = {"id": "0", "tool": "hospital_simulator",
                        "arguments": {"action": "status", "task_id": key}, "status": "running"}
                put(db, "run", ctx.group_id, key, {
                    "title": f"门诊预约 · {context['department']} · {context['preferred_time']}",
                    "user_id": ctx.user_id, "source_id": ctx.source_id,
                    "status": "running", "steps": [step], "grants": [],
                    "updated": time.time()})
                db.commit()
        with _latest_lock:
            already_started = key in _started_tasks
            _latest_tasks[(ctx.group_id, ctx.user_id)] = key
        session = automation.get(key)
        if session is None and not already_started:
            session = automation.start(key, ctx.group_id, ctx.user_id, key, context)
            with _latest_lock:
                _started_tasks.add(key)
        from .cards import publish_run
        await publish_run(ctx.group_id, key)
        return {"ok": True, "task_id": key, "status": session.status if session else "starting",
                "message": "已启动预约，正在打开模拟医院浏览器，锁号后请本人确认支付"}

    if action == "status":
        task_id = args.get("task_id", "")
        if not task_id:
            with _latest_lock:
                task_id = _latest_tasks.get((ctx.group_id, ctx.user_id), "")
        session = _owned_session(ctx, task_id)
        if not session:
            return {"error": "没有找到对应的预约任务"}
        return session.snapshot()

    if action == "approve":
        if not ctx.task_key:
            return {"error": "提交确认只能通过卡片“确认并继续”触发，不能在聊天中直接执行"}
        session = _owned_session(ctx, args.get("task_id", ""))
        if not session:
            return {"error": "没有找到对应的预约任务"}
        if not automation.confirm(args["task_id"]):
            return {"error": "没有找到对应的预约任务"}
        return await asyncio.to_thread(_poll_done, args["task_id"], 8.0)

    if action == "cancel":
        source_text = _source_text(ctx)
        if not ctx.task_key and source_text and not _explicit_cancel(source_text):
            return {"error": "需要当前消息明确要求取消"}
        task_id = args.get("task_id", "")
        if not task_id:
            with _latest_lock:
                task_id = _latest_tasks.get((ctx.group_id, ctx.user_id), "")
        session = _owned_session(ctx, task_id)
        if not session:
            return {"error": "没有找到可取消的预约任务"}
        automation.cancel(task_id)
        return {"ok": True, "status": "cancelled", "task_id": task_id}

    return {"error": "未知操作"}


register(Tool(
    "hospital_simulator",
    "本机模拟医院。nearby 从记忆地址查询高德附近医院；query 只查模拟号源；book 自动填表并锁号，"
    "status 查询实际结果；cancel 取消任务。支付仅由本人在模拟收银台确认。",
    schema({
        "action": {"enum": ["open", "nearby", "query", "book", "status", "approve", "cancel"]},
        "instruction": {"type": "string", "maxLength": 2000},
        "department": {"type": "string", "maxLength": 40},
        "address": {"type": "string", "maxLength": 200},
        "hospital_id": {"type": "string", "maxLength": 80},
        "patient_name": {"type": "string", "maxLength": 40},
        "preferred_time": {"enum": ["上午", "下午"]},
        "layout": {"enum": ["grid", "search"]},
        "mode": {"enum": ["mock", "model"]},
        "task_id": {"type": "string", "maxLength": 128},
        "slot_id": {"type": "string", "maxLength": 120},
        "campus_id": {"type": "string", "maxLength": 40},
        "doctor_id": {"type": "string", "maxLength": 40},
        "date": {"type": "string", "maxLength": 10},
        "time": {"type": "string", "pattern": "^([01][0-9]|2[0-3]):[0-5][0-9]$"},
        "patient_id": {"type": "string", "maxLength": 40},
    }, ["action"]),
    hospital_simulator,
))

REGISTRY["hospital_simulator"].instructions = (
    "query 只查询模拟号源；book 仅在用户明确要求办理时使用。先核对患者、科室和时间，"
    "book 必须传用户选定的 hospital_id；缺少医院时先请用户选择，不能替用户选择。指定 slot_id 可精确办理。浏览器自动填写并锁号，不需要子女授权；支付由本人确认完成。"
    "用 status 查询结果，不得编造预约编号。"
)

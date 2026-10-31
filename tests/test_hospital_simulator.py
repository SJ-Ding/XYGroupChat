import threading

import pytest

from backend.db import DB, get
from backend import hospital_data as H
from backend.hospital_simulator import (
    automation,
    booking_context,
    hospital_relevant,
    _run_key,
    _latest_tasks,
    _latest_lock,
)
from backend.skills import SkillContext, execute, tools


def test_hospital_request_detection_and_context():
    assert hospital_relevant("打开模拟医院")
    assert hospital_relevant("帮我挂个骨科的号")
    assert not hospital_relevant("今晚吃什么")
    context = booking_context("帮女儿预约市第一人民医院骨科下午的号")
    assert context["department"] == "骨科"
    assert context["preferred_time"] == "下午"
    assert context["patient_name"] == "小林"
    assert context["patient_id"] == "p-002"


def test_hospital_tool_is_available_only_when_selected():
    selected = tools(False, [], {"hospital_simulator"})
    assert [item["function"]["name"] for item in selected] == ["hospital_simulator"]
    assert tools(False, [], {"memory_search"}) == [
        next(item for item in tools(False, [], None) if item["function"]["name"] == "memory_search")
    ]


class FakeSession:
    def __init__(self, task_id, status="starting"):
        self.task_id = task_id
        self.gid = 1
        self.user_id = 1
        self.status = status
        self.error = None
        self.appointment = None
        self.details = None
        self.proceed = threading.Event()
        self.stop = threading.Event()

    def snapshot(self):
        return {"task_id": self.task_id, "status": self.status, "error": self.error,
                "appointment": self.appointment, "details": self.details}


def install_fake_session(task_id, status="starting"):
    session = FakeSession(task_id, status)
    automation.sessions[task_id] = session
    return session


def reset_latest_tasks():
    with _latest_lock:
        _latest_tasks.clear()


@pytest.mark.asyncio
async def test_book_creates_run_and_card():
    old_start = automation.start
    reset_latest_tasks()
    automation.sessions = {}
    calls = []

    def fake_start(task_id, gid, user_id, run_key, context):
        calls.append(task_id)
        automation.sessions[task_id] = FakeSession(task_id, "starting")
        return automation.sessions[task_id]

    automation.start = fake_start
    ctx = SkillContext(1, 1, "hospital-run", 0, False, grants=[], selected={"hospital_simulator"})
    try:
        result = await execute(
            "hospital_simulator",
            {"action": "book", "instruction": "预约眼科上午", "hospital_id": H.campus("c-main")["hospitalId"], "mode": "mock"},
            ctx,
        )
        assert result["ok"] and result["task_id"].startswith("appt-")
        task_id = result["task_id"]
        with DB() as db:
            run = get(db, "run", 1, task_id)
            assert run.data["status"] == "running"
            assert run.data["steps"][0]["tool"] == "hospital_simulator"
            assert run.data["steps"][0]["arguments"] == {"action": "status", "task_id": task_id}
            assert get(db, "card", 1, "run:" + task_id) is not None

        # 同一条指令幂等复用，不重复启动浏览器
        again = await execute(
            "hospital_simulator",
            {"action": "book", "instruction": "预约眼科上午", "hospital_id": H.campus("c-main")["hospitalId"], "mode": "mock"},
            ctx,
        )
        assert again["task_id"] == task_id
        assert len(calls) == 1
    finally:
        automation.start = old_start
        automation.sessions = {}


@pytest.mark.asyncio
async def test_approve_requires_run_step_context():
    ctx = SkillContext(1, 1, "chat-run", 0, False, grants=[], selected={"hospital_simulator"})
    result = await execute("hospital_simulator", {"action": "approve", "task_id": "appt-x"}, ctx)
    assert "error" in result


@pytest.mark.asyncio
async def test_approve_submits_and_reports_appointment():
    old_sessions = automation.sessions
    reset_latest_tasks()
    automation.sessions = {}
    task_id = "appt-test"
    session = install_fake_session(task_id, "awaiting_confirmation")
    session.appointment = {"id": "AP-ABC123"}
    session.status = "done"

    old_confirm = automation.confirm
    confirmed = []
    automation.confirm = lambda tid: confirmed.append(tid) or True
    ctx = SkillContext(1, 1, "run:key:step:0", 0, True, grants=[], selected={"hospital_simulator"}, task_key="key")
    try:
        result = await execute("hospital_simulator", {"action": "approve", "task_id": task_id}, ctx)
        assert result["status"] == "confirmed"
        assert result["appointment"]["id"] == "AP-ABC123"
        assert confirmed == [task_id]
    finally:
        automation.confirm = old_confirm
        automation.sessions = old_sessions


@pytest.mark.asyncio
async def test_cancel_closes_session():
    old_sessions = automation.sessions
    reset_latest_tasks()
    automation.sessions = {}
    task_id = "appt-cancel"
    session = install_fake_session(task_id, "awaiting_confirmation")
    ctx = SkillContext(1, 1, "chat-run", 0, False, grants=[], selected={"hospital_simulator"})
    try:
        result = await execute("hospital_simulator", {"action": "cancel", "task_id": task_id}, ctx)
        assert result["ok"] and result["status"] == "cancelled"
        assert session.stop.is_set()
    finally:
        automation.sessions = old_sessions

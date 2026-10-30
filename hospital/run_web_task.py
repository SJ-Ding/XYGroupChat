r"""
小艺·家人帮 · DOM+LLM 网页操作 独立测试脚本
=================================================
直接调用 web_executor（不依赖 FastAPI），输入文本命令即可操作模拟医院网页。
用于单独验证 DOM+LLM 网页操作接口能力，方便后续迁移到别的项目。

用法（在项目根目录）:
    # 1. 启动小艺服务（模拟医院由同一服务托管）
    .\start.ps1                        # http://localhost:8000/hospital/

    # 2. 运行测试脚本
    .\.venv\Scripts\python.exe hospital\run_web_task.py
    .\.venv\Scripts\python.exe hospital\run_web_task.py "帮我挂市一院骨科上午的号"
    .\.venv\Scripts\python.exe hospital\run_web_task.py "帮我挂市一院骨科下午的号" --no-llm
    .\.venv\Scripts\python.exe hospital\run_web_task.py --layout search

参数:
    指令文本（可选，默认骨科预约）
    --no-llm / --mock   使用 Mock 决策（不调用 DeepSeek，纯规则匹配）
    --llm               使用真实 DeepSeek 决策（默认）
    --layout grid|search  医院科室页布局（默认 grid）
    --no-approval        跳过审批（自动签发 token 恢复）
"""
from __future__ import annotations

import argparse
import os
import sys
import time

# 加载环境变量
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# 确保能同时导入项目后端与迁移后的医院模块
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))
from hospital.web_executor import executor  # noqa: E402
from backend.hospital_simulator import _model_chat  # noqa: E402

# 医院基础 URL（可覆盖布局）
DEFAULT_BASE = os.getenv("HOSPITAL_BASE", "http://127.0.0.1:8000/hospital/")


def build_context(instruction: str = "") -> dict:
    """从家庭记忆构造上下文。从指令文本提取科室/时间偏好（真实场景从家庭记忆提取）。"""
    # 从指令文本提取科室（先匹配科室名，再匹配疾病关键词）
    # 科室名直接匹配
    dept_names = [
        "骨科", "普通内科", "呼吸内科", "心内科", "消化内科", "内分泌科",
        "神经内科", "肾内科", "普通外科", "神经外科", "泌尿外科", "胸外科",
        "妇科", "产科", "儿科", "眼科", "耳鼻喉科", "口腔科",
        "皮肤科", "肿瘤科", "中医科", "老年医学科",
    ]
    department = next((d for d in sorted(dept_names, key=len, reverse=True) if d in instruction), None)
    # 若没匹配到科室名，按疾病/症状关键词匹配科室
    if not department:
        symptom_dept_map = {
            "骨折": "骨科", "关节": "骨科", "膝盖": "骨科", "腰痛": "骨科", "腰间盘": "骨科", "颈椎": "骨科", "扭伤": "骨科",
            "咳嗽": "呼吸内科", "气喘": "呼吸内科", "哮喘": "呼吸内科", "肺炎": "呼吸内科",
            "心慌": "心内科", "胸闷": "心内科", "胸痛": "心内科", "高血压": "心内科", "心悸": "心内科",
            "胃痛": "消化内科", "胃胀": "消化内科", "反酸": "消化内科", "腹泻": "消化内科", "便秘": "消化内科",
            "糖尿病": "内分泌科", "甲状腺": "内分泌科", "甲亢": "内分泌科", "甲减": "内分泌科",
            "头痛": "神经内科", "头晕": "神经内科", "失眠": "神经内科", "手抖": "神经内科", "手脚发麻": "神经内科",
            "尿频": "泌尿外科", "尿急": "泌尿外科", "血尿": "泌尿外科", "肾结石": "泌尿外科",
            "月经": "妇科", "白带": "妇科",
            "产检": "产科", "怀孕": "产科",
            "发热": "儿科", "湿疹": "儿科",
            "视力": "眼科", "近视": "眼科", "白内障": "眼科", "眼痛": "眼科",
            "鼻塞": "耳鼻喉科", "耳鸣": "耳鼻喉科", "嗓子疼": "耳鼻喉科", "咽炎": "耳鼻喉科",
            "牙痛": "口腔科", "拔牙": "口腔科", "口腔溃疡": "口腔科",
            "皮炎": "皮肤科", "痤疮": "皮肤科", "皮肤过敏": "皮肤科", "荨麻疹": "皮肤科",
            "调理": "中医科", "针灸": "中医科",
        }
        department = next((dept for symptom, dept in symptom_dept_map.items() if symptom in instruction), "骨科")
    # 从指令文本提取时间偏好
    preferred_time = "下午" if "下午" in instruction else "上午"
    # 从指令文本提取就诊人（默认王秀兰=长辈）
    patient_name = "小林" if "小林" in instruction or "女儿" in instruction else "王秀兰"
    return {
        "hospital": "市第一人民医院",
        "department": department,
        "preferred_time": preferred_time,
        "patient_name": patient_name,
        "patient_id": "p-001" if patient_name == "王秀兰" else "p-002",
        "approval_threshold": 50,
    }


def llm_chat(system_prompt: str, user_prompt: str, *, json_mode: bool = False) -> str:
    """调用与聊天服务共用的 DeepSeek 配置。"""
    return _model_chat(system_prompt, user_prompt, json_mode=json_mode)


def issue_token(task_id: str, fee: float) -> str:
    """模拟签发授权 token"""
    import uuid

    return f"tk-{uuid.uuid4().hex[:12]}"


def run(
    instruction: str,
    mock_decision: bool,
    layout: str,
    auto_approve: bool,
) -> int:
    # 覆盖医院基础 URL（控制布局）
    base = DEFAULT_BASE
    # 注入布局到环境（web_executor 用 HOSPITAL_BASE 打开首页，布局在科室页才生效）
    print(f"\n{'='*60}")
    print(f"  小艺·家人帮 · DOM+LLM 网页操作测试")
    print(f"{'='*60}")
    print(f"指令: {instruction}")
    print(f"决策模式: {'Mock（规则匹配）' if mock_decision else 'DeepSeek LLM'}")
    print(f"布局: {layout}")
    print(f"自动审批: {'是' if auto_approve else '否'}")
    print(f"医院地址: {base}")
    print(f"{'='*60}\n")

    # 启动任务
    context = build_context(instruction)
    context["layout"] = layout
    # 布局通过 URL query 传递，在 instruction 里不体现
    # web_executor 打开 HOSPITAL_BASE（首页），到科室页时会用 ?layout=
    # 这里临时设置环境变量，让 web_executor 首页打开后，LLM 决策导航到带 layout 的科室页
    os.environ["HOSPITAL_BASE"] = base

    task_id = executor.start(instruction, context, llm_chat, mock_decision=mock_decision)
    print(f"✅ 任务已启动: {task_id}")
    print(f"   浏览器任务已启动（{'无头调试' if os.getenv('HOSPITAL_HEADLESS', '').lower() in ('1', 'true', 'yes') else '可见窗口'}）\n")

    # 轮询输出进度
    last_event = 0
    waited_approval = False
    while True:
        task = executor.get(task_id)
        if not task:
            print("❌ 任务不存在")
            return 1

        # 输出新事件
        while last_event < len(task.events):
            ev = task.events[last_event]
            last_event += 1
            _print_event(ev)
            # decide/act 步骤后加延时，让你看清浏览器操作过程
            if ev.get("kind") in ("decide", "act", "page_opened", "page_resumed"):
                time.sleep(1.5)

        # 自动审批
        if task.status == "WAITING_APPROVAL" and auto_approve and not waited_approval:
            waited_approval = True
            fee = task.approval_needed["fee"] if task.approval_needed else 80
            print(f"\n⏸️  任务暂停等待审批（费用 {fee} 元超阈值）")
            print(f"   自动签发授权 token 并恢复执行...\n")
            token = issue_token(task_id, fee)
            ok = executor.resume(task_id, token, llm_chat, mock_decision)
            print(f"   恢复结果: {'成功' if ok else '失败'}\n")

        # 结束
        if task.status in ("COMPLETED", "FAILED", "CANCELLED"):
            print(f"\n{'='*60}")
            print(f"  任务结束: {task.status}")
            print(f"{'='*60}")
            if task.status == "COMPLETED" and task.appointment:
                print(f"  ✅ 预约成功！")
                print(f"  预约编号: {task.appointment.get('id')}")
                print(f"  预约页面: {task.appointment.get('url')}")
                print(f"{'='*60}\n")
                return 0
            elif task.status == "FAILED":
                print(f"  ❌ 失败原因: {task.error}")
                print(f"{'='*60}\n")
                return 1
            else:
                print(f"  任务已取消")
                print(f"{'='*60}\n")
                return 1

        time.sleep(1)


def _print_event(ev: dict):
    kind = ev.get("kind", "")
    step = ev.get("step", "")
    if kind == "task_started":
        print(f"[启动] {ev.get('instruction', '')}")
    elif kind == "browser_starting":
        print(f"[浏览器] 正在启动浏览器...")
    elif kind == "browser_fallback":
        print(f"[浏览器] ⚠️ 改用系统 Chrome/Edge（Playwright chromium 未安装）")
    elif kind == "page_opened":
        print(f"[{step}] 📄 打开页面: {ev.get('title', '')} — {ev.get('detail', '')}")
    elif kind == "page_resumed":
        print(f"[{step}] 🔄 带授权重新打开: {ev.get('detail', '')}")
    elif kind == "mock_state":
        pass  # 调试用，默认不打印
    elif kind == "decide":
        action = ev.get("action", "")
        reason = ev.get("reason", "")
        print(f"[{step}] 🧠 决策: {action} — {reason}")
    elif kind == "act":
        print(f"[{step}] 🖱️  执行: {ev.get('detail', '')}")
    elif kind == "act_error":
        print(f"[{step}] ❌ 执行错误: {ev.get('error', '')}")
    elif kind == "approval_needed":
        print(f"[{step}] ⏸️  需要审批: 费用 {ev.get('fee', '')} 元，暂停提交")
    elif kind == "approval_resumed":
        print(f"[{step}] ▶️  审批通过，恢复执行")
    elif kind == "task_completed":
        print(f"[完成] ✅ {ev.get('detail', '')}")
    elif kind == "task_failed":
        print(f"[失败] ❌ {ev.get('error', '')}")
    elif kind == "task_cancelled":
        print(f"[取消] {ev.get('detail', '')}")
    elif kind == "security_block":
        print(f"[安全] 🚫 拒绝访问: {ev.get('detail', '')}")


def main():
    parser = argparse.ArgumentParser(description="DOM+LLM 网页操作测试")
    parser.add_argument("instruction", nargs="?", default="帮妈妈预约市第一人民医院骨科上午的号，挂号费超过50元需家人确认", help="操作指令")
    parser.add_argument("--no-llm", "--mock", action="store_true", help="使用 Mock 决策（不调 DeepSeek）")
    parser.add_argument("--llm", action="store_true", help="使用真实 DeepSeek 决策")
    parser.add_argument("--layout", choices=["grid", "search"], default="grid", help="科室页布局")
    parser.add_argument("--auto-approve", "--no-approval", action="store_true", help="自动审批（跳过手动确认）")
    args = parser.parse_args()

    mock_decision = args.no_llm or (not args.llm and not os.getenv("DEEPSEEK_API_KEY"))
    # 默认优先 DeepSeek，若无 key 则 Mock
    if not args.no_llm and (args.llm or os.getenv("DEEPSEEK_API_KEY")):
        mock_decision = False

    code = run(args.instruction, mock_decision, args.layout, args.auto_approve)
    sys.exit(code)


if __name__ == "__main__":
    main()

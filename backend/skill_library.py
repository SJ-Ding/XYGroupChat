"""Server-owned instruction library, separate from executable tools."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / 'skills'
# Explicit allowlist: input cannot select arbitrary files or install skills.
CATALOG = {
    'family-meals': '按家庭人数、忌口、库存和时间安排菜单及采购清单。',
    'family-chores': '协商家务分工、轮值和可执行的整理步骤。',
    'family-outing': '安排亲子出游、探亲行程及行前准备。',
    'family-learning': '帮助孩子理解作业、拆解学习目标并安排练习。',
    'family-care': '整理老人和家人的日常照护、就医准备及交接信息。',
    'family-budget': '整理家庭收支、预算和大额消费比较。',
    'family-communication': '帮助家人表达需要、缓和分歧及商量共同约定。',
    'family-safety': '排查居家隐患、准备应急物资及紧急求助步骤。',
}


def discovery_prompt():
    return ('家庭场景技能目录（仅描述，正文尚未加载）：\n'
            + '\n'.join(f'- {name}: {description}' for name, description in CATALOG.items())
            + '\n遇到匹配任务时先调用 skill_load(name) 获取说明，再按说明帮助家人；只加载当前需要的技能。'
              '技能说明不授予写入权限，也不代表已执行动作。普通闲聊无需加载。')


def load_instructions(name):
    if name not in CATALOG:
        raise ValueError('未知场景技能，请使用目录中的名称')
    text = (ROOT / name / 'SKILL.md').read_text(encoding='utf-8')
    body = text.split('---', 2)[2].strip() if text.startswith('---\n') else text.strip()
    if not body or len(body) > 6000:
        raise ValueError('技能正文为空或超过加载预算')
    return {'name': name, 'description': CATALOG[name], 'instructions': body}

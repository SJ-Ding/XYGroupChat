import json
import pytest
from backend.agent import Agent
from backend.db import DB, get, records
from backend.skill_library import CATALOG, discovery_prompt, load_instructions
from backend.skills import SkillContext, execute
from test_system import seed_demand, no_broadcast


def test_catalog_is_description_only_and_all_skills_load():
    prompt = discovery_prompt()
    for name in CATALOG:
        loaded = load_instructions(name)
        assert name in prompt
        assert loaded['instructions'] not in prompt
        assert len(loaded['instructions']) > 100
    with pytest.raises(ValueError):
        load_instructions('../family/SKILL.md')


@pytest.mark.asyncio
async def test_load_preserves_permissions_and_space():
    ctx = SkillContext(1, 1, 'load', 0, False, grants=[], selected={'skill_load', 'family_tasks'})
    result = await execute('skill_load', {'name': 'family-meals'}, ctx)
    assert result['name'] == 'family-meals'
    assert ctx.grants == [] and not ctx.allow_writes
    assert 'error' in await execute('family_tasks', {'action': 'create', 'title': '买菜'}, ctx)
    assert 'error' in await execute('skill_load', {'name': '../../.env'}, ctx)
    ctx.user_id = 999999
    assert 'error' in await execute('skill_load', {'name': 'family-meals'}, ctx)
    with DB() as db:
        assert records(db, 'task', 1) == []


@pytest.mark.asyncio
async def test_agent_loads_on_demand_and_starts_fresh_each_request():
    mid = seed_demand()
    class LoadingModel:
        def __init__(self):
            self.count = 0

        async def call(self, messages, tools=None, **kwargs):
            self.count += 1
            names = {t['function']['name'] for t in tools}
            assert 'skill_load' in names and 'remember' not in names
            if self.count % 2:
                assert not any(m['role'] == 'tool' for m in messages)
                assert load_instructions('family-meals')['instructions'] not in str(messages)
                return {'role': 'assistant', 'content': '', 'tool_calls': [
                    {'id': 'load', 'type': 'function', 'function': {
                        'name': 'skill_load', 'arguments': json.dumps({'name': 'family-meals'})}}]}
            result = json.loads(messages[-1]['content'])
            assert result['instructions'] == load_instructions('family-meals')['instructions']
            return {'role': 'assistant', 'content': '今晚可以做番茄炒蛋。'}

    model = LoadingModel()
    agent = Agent(no_broadcast, model)
    with DB() as db:
        settings = get(db, 'group', 1, 'settings').data
    for run in ('first', 'second'):
        assert await agent.generate(1, mid, settings, run) == '今晚可以做番茄炒蛋。'
    assert model.count == 4

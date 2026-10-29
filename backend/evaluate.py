"""Offline policy fixtures; --live additionally evaluates model recognition.

Only the synthetic fixtures in evals/ are sent in live mode, never family data.
"""
import argparse
import asyncio
import json
from pathlib import Path
from .contracts import ConversationEvent
from .intent import direct_mention, parse_intent, recognize
from .participation import decide
from .persona import DEFAULT_AGENT_NAME


async def evaluate(live=False):
    cases = json.loads((Path(__file__).resolve().parent.parent / 'evals' / 'participation.json').read_text(encoding='utf-8'))
    model = None
    if live:
        from .model import Model
        model = Model()
    results = []
    for i, case in enumerate(cases):
        data = {'intent': case['intent']}
        if model:
            data = await recognize(model.call, waiting=[], memories=[], names={1:'爸爸',2:'妈妈',3:'小宇'},
                messages=[{'id':i+1,'sender':1,'text':case['text']}])
        event = ConversationEvent(1,1,i+1,case['text'],0,direct_mention(case['text'],DEFAULT_AGENT_NAME))
        action = decide(event,parse_intent(data),{'active':True}).action
        results.append({'id':case['id'],'expected':case['expected'],'actual':action,'passed':action==case['expected']})
    return {'mode':'live_recognition' if live else 'annotated_policy', 'cases':len(results),
        'passed':sum(x['passed'] for x in results), 'results':results}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true',help='使用配置模型识别合成群聊样例；会消耗模型额度')
    args=parser.parse_args()
    result=asyncio.run(evaluate(args.live))
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result['passed']==result['cases'] else 1)

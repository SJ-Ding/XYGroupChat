"""Content-free operational metrics and explicit user feedback."""
import time
import uuid
from collections import Counter
from .db import DB, put, records


async def measured_call(model, gid, *args, **kwargs):
    started = time.monotonic()
    result, error, attempts = None, None, 1
    try:
        result = await model.call(*args, **kwargs)
        attempts = result.get('_attempts', 1) if isinstance(result, dict) else 1
        return result
    except Exception as exc:
        error = type(exc).__name__
        attempts = getattr(exc, 'attempts', 1)
        raise
    finally:
        with DB() as db:
            usage = result.get('_usage', {}) if isinstance(result, dict) else {}
            put(db, 'metric', gid, str(uuid.uuid4()), {'at': time.time(), 'latency_ms': round((time.monotonic() - started) * 1000),
                'failed': error is not None, 'error_type': error, 'tokens': usage.get('total_tokens'), 'http_attempts': attempts,
                'kind': 'analysis' if kwargs.get('structured') else 'generation'})
            db.commit()


def metrics(db, gid):
    calls = [r.data for r in records(db, 'metric', gid)][-1000:]
    feedback = Counter(r.data['kind'] for r in records(db, 'feedback', gid))
    runs = Counter(r.data['status'] for r in records(db, 'run', gid))
    return {'model_calls': len(calls), 'model_failures': sum(x['failed'] for x in calls),
        'http_attempts': sum(x.get('http_attempts', 1) for x in calls),
        'mean_latency_ms': round(sum(x['latency_ms'] for x in calls) / len(calls)) if calls else None,
        'reported_tokens': sum(x.get('tokens') or 0 for x in calls),
        'usage_available': bool(calls) and all(x.get('tokens') is not None for x in calls),
        'feedback': dict(feedback), 'task_states': dict(runs),
        'decisions': dict(Counter(r.data['action'] for r in records(db, 'decision', gid))),
        'delivery_states': dict(Counter(r.data['status'] for r in records(db, 'delivery', gid)))}

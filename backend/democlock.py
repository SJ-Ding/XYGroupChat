"""演示时钟（DemoClock）：全系统唯一的“现在”。

真实时间 + 偏移量。偏移量保存在 DATA_DIR/demo_clock.json，重启后保持；
默认偏移为 0，与真实时间完全一致，不影响非演示使用。
快进只改变偏移量，不改动任何已有数据。本模块不依赖数据库，避免循环导入。
"""
import json
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Shanghai')
_lock = threading.Lock()
_offset = None


def _path():
    root = Path(os.getenv('DATA_DIR', 'data')).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root / 'demo_clock.json'


def _load():
    global _offset
    if _offset is None:
        try:
            _offset = float(json.loads(_path().read_text(encoding='utf-8')).get('offset', 0))
        except (OSError, ValueError, TypeError):
            _offset = 0.0
    return _offset


def _save(value):
    global _offset
    _offset = float(value)
    try:
        _path().write_text(json.dumps({'offset': _offset}), encoding='utf-8')
    except OSError:
        pass


def now():
    """当前演示时间（Unix 秒）。"""
    with _lock:
        return time.time() + _load()


def offset():
    with _lock:
        return _load()


def set_now(ts):
    """把演示时间设置为 ts（Unix 秒）。"""
    with _lock:
        _save(float(ts) - time.time())


def advance(seconds):
    with _lock:
        _save(_load() + float(seconds))


def reset():
    with _lock:
        _save(0)


def local(ts=None):
    return datetime.fromtimestamp(now() if ts is None else ts, TZ)


def today(ts=None):
    """演示时间对应的本地日期字符串 YYYY-MM-DD。"""
    return local(ts).date().isoformat()


def at(date_str, clock='00:00'):
    """本地日期 + 时刻 → Unix 秒。"""
    hour, minute = map(int, clock.split(':'))
    d = datetime.fromisoformat(date_str)
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=TZ).timestamp()


def shift_date(date_str, days):
    return (datetime.fromisoformat(date_str) + timedelta(days=days)).date().isoformat()


WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']


def label(ts=None):
    """如 “11月3日 周二 20:10”。"""
    d = local(ts)
    return f'{d.month}月{d.day}日 {WEEKDAYS[d.weekday()]} {d:%H:%M}'


def date_label(date_str):
    d = datetime.fromisoformat(date_str)
    return f'{d.month}月{d.day}日{WEEKDAYS[d.weekday()]}'

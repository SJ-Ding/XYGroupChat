"""Amap-backed public hospital directory; never falls back to a private demo address."""
import json
import math
from datetime import datetime, timezone
from .amap_mcp import amap_mcp

async def discover(address):
    async def call(name, arguments):
        result = await amap_mcp(None, {'action': 'call', 'name': name, 'arguments': arguments})
        if 'error' in result:
            raise ValueError(result['error'])
        if result.get('truncated'):
            raise ValueError('高德结果不完整，请缩小查询范围')
        return json.loads(result['content'])
    geo = await call('maps_geo', {'address': address})
    points = geo.get('results') or geo.get('geocodes') or []
    if not points:
        raise ValueError('无法定位记忆中的地址，请补充城市和道路')
    location = points[0]['location']
    origin = list(map(float, location.split(',')))
    around = await call('maps_around_search', {'keywords': '综合医院', 'location': location, 'radius': '5000'})
    hospitals = []
    for poi in around.get('pois', []):
        if poi.get('typecode') != '090101' or any(w in poi.get('name', '') for w in ('科室', '影像', '钢琴', '儿童', '妇幼')):
            continue
        detail = await call('maps_search_detail', {'id': poi['id']})
        if not detail.get('location') or not detail.get('name'):
            continue
        lng, lat = map(float, detail['location'].split(','))
        dx = (lng-origin[0])*math.cos(math.radians(origin[1]))
        km = 111.195 * math.hypot(dx, lat-origin[1])
        hospitals.append({'id': 'amap-' + poi['id'], 'poiId': poi['id'], 'name': detail['name'],
            'address': detail.get('address', ''), 'lng': lng, 'lat': lat,
            'level': '三级甲等' if '三级甲等' in detail.get('type', '') else '',
            'distanceKm': round(km, 2), 'source': '高德 MCP', 'queriedAt': datetime.now(timezone.utc).isoformat(),
            'locationPrecision': points[0].get('level', '道路'), 'originAddress': address})
    # Two distinct hospital organizations, rather than two campuses of one hospital.
    hospitals.sort(key=lambda h: h['distanceKm'])
    selected = []
    for hospital in hospitals:
        base = hospital['name'].split('(')[0].split('（')[0]
        if any(h['name'].split('(')[0].split('（')[0] == base for h in selected):
            continue
        selected.append(hospital)
        if len(selected) == 2:
            return selected
    raise ValueError('没有找到两家信息完整的综合医院，请补充位置或重试')

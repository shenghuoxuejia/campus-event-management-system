"""活动分类相关测试：分类列表、发布带分类、按分类过滤、非法分类、分类替换。"""


import uuid
import time
from datetime import datetime, timedelta


def _unique_window():
    """生成一对唯一的 (start, end)，纳秒时间戳 + uuid 双保险，几乎不会撞。"""
    seed = (time.time_ns() ^ uuid.uuid4().int) % (30 * 365 * 24 * 3600)
    base = datetime(2030, 1, 1) + timedelta(seconds=seed)
    return (base.strftime('%Y-%m-%dT%H:%M:%S'),
            (base + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M:%S'))


def test_list_categories(client, auth, make_user):
    _, token = make_user('student')
    resp = client.get('/api/categories', headers=auth(token))
    assert resp.status_code == 200
    data = resp.get_json()['data']
    assert isinstance(data, list)
    assert len(data) >= 4
    assert all('category_id' in c and 'category_name' in c for c in data)


def test_create_event_with_categories(client, auth, event, find_event):
    org_token = event['org_token']
    cats = client.get('/api/categories', headers=auth(org_token)).get_json()['data']
    venues = client.get('/api/venues', headers=auth(org_token)).get_json()['data']
    cid1, cid2 = cats[0]['category_id'], cats[1]['category_id']

    start, end = _unique_window()
    resp = client.post('/api/create_event', headers=auth(org_token), json={
        'title': '带分类的活动', 'description': '测试',
        'venue_id': venues[0]['venue_id'],
        'start_time': start, 'end_time': end,
        'capacity': 5, 'category_ids': [cid1, cid2],
    })
    assert resp.status_code == 200, resp.get_json()
    eid = resp.get_json()['data']['event_id']

    found = find_event(org_token, eid)
    assert found is not None
    ids = [c['category_id'] for c in found['categories']]
    assert set(ids) == {cid1, cid2}


def test_create_event_invalid_category_fails(client, auth, event):
    org_token = event['org_token']
    venues = client.get('/api/venues', headers=auth(org_token)).get_json()['data']
    resp = client.post('/api/create_event', headers=auth(org_token), json={
        'title': '非法分类', 'description': '',
        'venue_id': venues[1]['venue_id'],
        'start_time': '2030-02-01T10:00', 'end_time': '2030-02-01T12:00',
        'capacity': 5, 'category_ids': [999999],
    })
    assert resp.status_code == 400
    assert '分类不存在' in resp.get_json()['message']


def test_filter_events_by_category(client, auth, event):
    org_token = event['org_token']
    cats = client.get('/api/categories', headers=auth(org_token)).get_json()['data']
    venues = client.get('/api/venues', headers=auth(org_token)).get_json()['data']
    cid = cats[0]['category_id']

    start, end = _unique_window()
    resp = client.post('/api/create_event', headers=auth(org_token), json={
        'title': '可过滤活动', 'description': '',
        'venue_id': venues[2]['venue_id'],
        'start_time': start, 'end_time': end,
        'capacity': 5, 'category_ids': [cid],
    })
    assert resp.status_code == 200, resp.get_json()
    eid = resp.get_json()['data']['event_id']

    result = client.get(f'/api/events?category_id={cid}&page_size=100',
                        headers=auth(org_token)).get_json()
    assert result['code'] == 200
    assert any(e['event_id'] == eid for e in result['data'])
    assert all(cid in [c['category_id'] for c in e['categories']]
               for e in result['data'])


def test_update_event_categories_replace(client, auth, event, find_event):
    org_token = event['org_token']
    cats = client.get('/api/categories', headers=auth(org_token)).get_json()['data']
    venues = client.get('/api/venues', headers=auth(org_token)).get_json()['data']
    cid1, cid2 = cats[0]['category_id'], cats[1]['category_id']
    eid = event['event_id']

    start, end = _unique_window()
    client.put(f'/api/update_event/{eid}', headers=auth(org_token), json={
        'title': '分类更新', 'description': '', 'venue_id': venues[0]['venue_id'],
        'start_time': start, 'end_time': end,
        'capacity': 5, 'category_ids': [cid1],
    })
    found = find_event(org_token, eid)
    assert [c['category_id'] for c in found['categories']] == [cid1]

    client.put(f'/api/update_event/{eid}', headers=auth(org_token), json={
        'title': '分类更新2', 'description': '', 'venue_id': venues[0]['venue_id'],
        'start_time': start, 'end_time': end,
        'capacity': 5, 'category_ids': [cid2],
    })
    found = find_event(org_token, eid)
    assert [c['category_id'] for c in found['categories']] == [cid2]


def test_update_event_without_categories_keeps_existing(client, auth, event, find_event):
    org_token = event['org_token']
    cats = client.get('/api/categories', headers=auth(org_token)).get_json()['data']
    venues = client.get('/api/venues', headers=auth(org_token)).get_json()['data']
    cid = cats[0]['category_id']
    eid = event['event_id']
    start, end = _unique_window()

    resp = client.put(f'/api/update_event/{eid}', headers=auth(org_token), json={
        'title': '保留分类', 'description': '', 'venue_id': venues[0]['venue_id'],
        'start_time': start, 'end_time': end,
        'capacity': 5, 'category_ids': [cid],
    })
    assert resp.status_code == 200, resp.get_json()

    # 不带 category_ids 再更新，应保持原分类不变
    resp = client.put(f'/api/update_event/{eid}', headers=auth(org_token), json={
        'title': '保留分类2', 'description': '', 'venue_id': venues[0]['venue_id'],
        'start_time': start, 'end_time': end,
        'capacity': 5,
    })
    assert resp.status_code == 200, resp.get_json()

    found = find_event(org_token, eid)
    assert [c['category_id'] for c in found['categories']] == [cid]
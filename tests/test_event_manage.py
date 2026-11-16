"""活动管理相关测试：编辑活动、移除报名、分页。"""


import uuid
import time
from datetime import datetime, timedelta


def _unique_window():
    """生成一对唯一的 (start, end)，纳秒时间戳 + uuid 双保险，几乎不会撞。"""
    seed = (time.time_ns() ^ uuid.uuid4().int) % (30 * 365 * 24 * 3600)
    base = datetime(2030, 1, 1) + timedelta(seconds=seed)
    return (base.strftime('%Y-%m-%dT%H:%M:%S'),
            (base + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M:%S'))


def test_update_event_by_owner(client, auth, event, find_event):
    start, end = _unique_window()
    resp = client.put(f"/api/update_event/{event['event_id']}",
                      headers=auth(event['org_token']), json={
                          'title': '改名后的活动',
                          'description': '新的描述',
                          'venue_id': 1,
                          'start_time': start,
                          'end_time': end,
                          'capacity': 20,
                      })
    assert resp.status_code == 200, resp.get_json()

    updated = find_event(event['org_token'], event['event_id'])
    assert updated is not None
    assert updated['title'] == '改名后的活动'
    assert updated['capacity'] == 20


def test_update_event_by_other_organizer_forbidden(client, auth, event, make_user):
    _, other_token = make_user('organizer')
    resp = client.put(f"/api/update_event/{event['event_id']}",
                      headers=auth(other_token), json={
                          'title': '恶意改名',
                          'description': '',
                          'venue_id': 1,
                          'start_time': '2031-05-01T09:00',
                          'end_time': '2031-05-01T11:00',
                          'capacity': 5,
                      })
    assert resp.status_code == 403
    assert resp.get_json()['code'] == 403


def test_update_event_capacity_below_registrations_fails(client, auth, event, registration, make_user):
    # 再加一个学生，使有效报名人数变为 2
    _, other_token = make_user('student')
    resp = client.post('/api/register_event', headers=auth(other_token),
                       json={'event_id': event['event_id']})
    assert resp.status_code == 200, resp.get_json()

    resp = client.put(f"/api/update_event/{event['event_id']}",
                      headers=auth(event['org_token']), json={
                          'title': '容量不足',
                          'description': '',
                          'venue_id': 1,
                          'start_time': '2031-05-01T09:00',
                          'end_time': '2031-05-01T11:00',
                          'capacity': 1,
                      })
    assert resp.status_code == 400
    assert '已报名人数' in resp.get_json()['message']


def test_update_event_end_before_start_fails(client, auth, event):
    resp = client.put(f"/api/update_event/{event['event_id']}",
                      headers=auth(event['org_token']), json={
                          'title': '时间颠倒',
                          'description': '',
                          'venue_id': 1,
                          'start_time': '2031-05-01T11:00',
                          'end_time': '2031-05-01T09:00',
                          'capacity': 5,
                      })
    assert resp.status_code == 400


def test_remove_registration_by_organizer(client, auth, event, registration):
    resp = client.delete(f"/api/remove_registration/{registration['registration_id']}",
                         headers=auth(event['org_token']))
    assert resp.status_code == 200
    assert resp.get_json()['code'] == 200

    regs = client.get(f"/api/user_registrations/{registration['student']['user_id']}",
                      headers=auth(registration['stu_token'])).get_json()['data']
    row = next(r for r in regs if r['event_id'] == event['event_id'])
    assert row['registration_status'] == 'cancelled'


def test_remove_registration_by_other_organizer_forbidden(client, auth, event, registration, make_user):
    _, other_token = make_user('organizer')
    resp = client.delete(f"/api/remove_registration/{registration['registration_id']}",
                         headers=auth(other_token))
    assert resp.status_code == 403
    assert resp.get_json()['code'] == 403


def test_events_pagination_meta(client, auth, event):
    result = client.get('/api/events?page=1&page_size=2',
                        headers=auth(event['org_token'])).get_json()
    assert result['code'] == 200
    assert isinstance(result['data'], list)
    assert len(result['data']) <= 2
    assert result['page'] == 1
    assert result['page_size'] == 2
    assert result['total'] >= 1
    assert result['pages'] == (result['total'] + 1) // 2


def test_comments_pagination_meta(client, auth, event, registration):
    stu_token = registration['stu_token']
    for i in range(3):
        client.post('/api/comments', headers=auth(stu_token), json={
            'event_id': event['event_id'], 'content': f'评论{i}',
        })

    page1 = client.get(f"/api/comments/{event['event_id']}?page=1&page_size=2",
                       headers=auth(stu_token)).get_json()
    assert page1['code'] == 200
    assert len(page1['data']) == 2
    assert page1['total'] >= 3

    page2 = client.get(f"/api/comments/{event['event_id']}?page=2&page_size=2",
                       headers=auth(stu_token)).get_json()
    assert len(page2['data']) >= 1
    # 两页内容不重复
    ids1 = {c['comment_id'] for c in page1['data']}
    ids2 = {c['comment_id'] for c in page2['data']}
    assert ids1.isdisjoint(ids2)

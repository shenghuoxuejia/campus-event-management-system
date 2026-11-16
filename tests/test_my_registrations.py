"""「我的报名」分页测试。"""
import uuid
from datetime import datetime, timedelta


def _unique_window():
    seed = (uuid.uuid4().int) % (30 * 365 * 24 * 3600)
    base = datetime(2030, 1, 1) + timedelta(seconds=seed)
    return (base.strftime('%Y-%m-%dT%H:%M:%S'),
            (base + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M:%S'))


def _create_event(client, auth, org_token, venue_id):
    start, end = _unique_window()
    resp = client.post('/api/create_event', headers=auth(org_token), json={
        'title': f'分页测试_{uuid.uuid4().hex[:8]}',
        'description': '',
        'venue_id': venue_id,
        'start_time': start,
        'end_time': end,
        'capacity': 5,
    })
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()['data']['event_id']


def test_my_registrations_pagination_meta(client, auth, make_user):
    """报名 3 个活动，每页 2 条，验证分页元信息与不重复。"""
    org_user, org_token = make_user('organizer')
    stu_user, stu_token = make_user('student')
    venues = client.get('/api/venues', headers=auth(org_token)).get_json()['data']

    # 报 3 个活动
    event_ids = []
    for _ in range(3):
        eid = _create_event(client, auth, org_token, venues[0]['venue_id'])
        event_ids.append(eid)
        r = client.post('/api/register_event', headers=auth(stu_token),
                        json={'event_id': eid})
        assert r.status_code == 200, r.get_json()

    page1 = client.get(
        f"/api/user_registrations/{stu_user['user_id']}?page=1&page_size=2",
        headers=auth(stu_token),
    ).get_json()
    assert page1['code'] == 200
    assert len(page1['data']) == 2
    assert page1['total'] >= 3
    assert page1['page'] == 1
    assert page1['page_size'] == 2
    assert page1['pages'] >= 2

    page2 = client.get(
        f"/api/user_registrations/{stu_user['user_id']}?page=2&page_size=2",
        headers=auth(stu_token),
    ).get_json()
    ids1 = {r['registration_id'] for r in page1['data']}
    ids2 = {r['registration_id'] for r in page2['data']}
    assert ids1.isdisjoint(ids2)


def test_my_registrations_default_page(client, auth, event, registration):
    """不传分页参数时，默认第 1 页、page_size=20。"""
    resp = client.get(
        f"/api/user_registrations/{registration['student']['user_id']}",
        headers=auth(registration['stu_token']),
    )
    data = resp.get_json()
    assert data['code'] == 200
    assert data['page'] == 1
    assert data['page_size'] == 20
    assert isinstance(data['data'], list)
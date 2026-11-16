"""活动详情接口测试。"""


def test_event_detail_requires_login(client, event):
    resp = client.get(f"/api/events/{event['event_id']}")
    assert resp.status_code == 401


def test_event_detail_returns_fields(client, auth, event):
    resp = client.get(f"/api/events/{event['event_id']}",
                      headers=auth(event['org_token']))
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()['data']
    for key in ('event_id', 'title', 'organizer_id', 'venue_id', 'start_time',
                'end_time', 'capacity', 'status', 'registered_count',
                'is_registered', 'remaining', 'categories', 'started', 'ended'):
        assert key in data, f'缺少字段 {key}'
    assert data['event_id'] == event['event_id']
    assert data['remaining'] == data['capacity'] - data['registered_count']


def test_event_detail_404(client, auth, event):
    resp = client.get('/api/events/99999999',
                      headers=auth(event['org_token']))
    assert resp.status_code == 404
    assert resp.get_json()['code'] == 404


def test_event_detail_reflects_registration(client, auth, event, registration):
    data = client.get(f"/api/events/{event['event_id']}",
                      headers=auth(registration['stu_token'])).get_json()['data']
    assert data['is_registered'] >= 1
    assert data['registered_count'] >= 1
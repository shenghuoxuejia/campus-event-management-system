"""关闭 / 重新开放活动报名的测试。"""


def test_close_event_success(client, auth, event, find_event):
    resp = client.put(f"/api/close_event/{event['event_id']}",
                      headers=auth(event['org_token']), json={'action': 'close'})
    assert resp.status_code == 200
    assert resp.get_json()['code'] == 200

    row = find_event(event['org_token'], event['event_id'])
    assert row is not None
    assert row['status'] == 'closed'


def test_reopen_closed_event_success(client, auth, event):
    rid = event['event_id']
    client.put(f'/api/close_event/{rid}', headers=auth(event['org_token']),
               json={'action': 'close'})
    resp = client.put(f'/api/close_event/{rid}', headers=auth(event['org_token']),
                      json={'action': 'open'})
    assert resp.status_code == 200


def test_cannot_reopen_ended_event(client, auth, ended_scene):
    resp = client.put(f"/api/close_event/{ended_scene['event_id']}",
                      headers=auth(ended_scene['org_token']), json={'action': 'open'})
    assert resp.status_code == 400
    assert '已结束' in resp.get_json()['message']


def test_cannot_reopen_started_event(client, auth, active_scene):
    resp = client.put(f"/api/close_event/{active_scene['event_id']}",
                      headers=auth(active_scene['org_token']), json={'action': 'open'})
    assert resp.status_code == 400
    assert '已经开始' in resp.get_json()['message']


def test_close_event_by_other_organizer_forbidden(client, auth, event, make_user):
    _, other_token = make_user('organizer')
    resp = client.put(f"/api/close_event/{event['event_id']}",
                      headers=auth(other_token), json={'action': 'close'})
    assert resp.status_code == 403


def test_close_event_invalid_action(client, auth, event):
    resp = client.put(f"/api/close_event/{event['event_id']}",
                      headers=auth(event['org_token']), json={'action': 'nonsense'})
    assert resp.status_code == 400

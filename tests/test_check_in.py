"""签到接口测试。"""


def test_check_in_success(client, auth, active_scene):
    resp = client.put(f"/api/check_in/{active_scene['registration_id']}",
                      headers=auth(active_scene['org_token']))
    assert resp.status_code == 200
    assert resp.get_json()['code'] == 200


def test_check_in_twice_fails(client, auth, active_scene):
    rid = active_scene['registration_id']
    first = client.put(f'/api/check_in/{rid}', headers=auth(active_scene['org_token']))
    assert first.status_code == 200

    second = client.put(f'/api/check_in/{rid}', headers=auth(active_scene['org_token']))
    assert second.status_code == 400
    assert second.get_json()['code'] == 400


def test_check_in_before_start_fails(client, auth, event, registration):
    """活动还没开始就不能签到。"""
    resp = client.put(f"/api/check_in/{registration['registration_id']}",
                      headers=auth(event['org_token']))
    assert resp.status_code == 400
    assert '还未开始' in resp.get_json()['message']


def test_check_in_after_end_fails(client, auth, ended_scene):
    """活动结束后不能再签到。"""
    resp = client.put(f"/api/check_in/{ended_scene['registration_id']}",
                      headers=auth(ended_scene['org_token']))
    assert resp.status_code == 400
    assert '已结束' in resp.get_json()['message']


def test_check_in_by_non_organizer_forbidden(client, auth, event, registration, make_user):
    _, other_token = make_user('student')
    resp = client.put(f"/api/check_in/{registration['registration_id']}",
                      headers=auth(other_token))
    assert resp.status_code == 403
    assert resp.get_json()['code'] == 403

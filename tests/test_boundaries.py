"""报名相关边界：角色限制、过去时间、已签到不能取消、超长输入、404。"""


def test_organizer_cannot_register_event(client, auth, event, make_user):
    """组织者账号不能报名活动。"""
    _, org_token = make_user('organizer')
    resp = client.post('/api/register_event', headers=auth(org_token),
                       json={'event_id': event['event_id']})
    assert resp.status_code == 403
    assert '只有学生账号' in resp.get_json()['message']


def test_cannot_create_event_in_the_past(client, auth, event):
    resp = client.post('/api/create_event', headers=auth(event['org_token']), json={
        'title': '过去的活动',
        'description': '时间已经过了',
        'venue_id': 1,
        'start_time': '2000-01-01T10:00',
        'end_time': '2000-01-01T12:00',
        'capacity': 5,
    })
    assert resp.status_code == 400
    assert '开始时间必须晚于当前时间' in resp.get_json()['message']


def test_cannot_cancel_checked_in_registration(client, auth, active_scene):
    """已签到的报名不能被「取消报名」抹掉。"""
    rid = active_scene['registration_id']
    check = client.put(f'/api/check_in/{rid}', headers=auth(active_scene['org_token']))
    assert check.status_code == 200

    resp = client.put(f'/api/cancel_registration/{rid}',
                      headers=auth(active_scene['stu_token']))
    assert resp.status_code == 400
    assert '已签到' in resp.get_json()['message']

    # 后端数据仍是已签到
    regs = client.get(f"/api/user_registrations/{active_scene['student']['user_id']}",
                      headers=auth(active_scene['stu_token'])).get_json()['data']
    row = next(r for r in regs if r['event_id'] == active_scene['event_id'])
    assert row['registration_status'] == 'checked_in'


def test_register_rejects_too_long_name(client):
    resp = client.post('/api/register', json={
        'name': 'N' * 300,
        'email': 'long_name_check@test.com',
        'password': 'Passw0rd123',
        'role': 'student',
    })
    assert resp.status_code == 400
    assert '姓名不能超过' in resp.get_json()['message']


def test_register_rejects_too_long_email(client):
    email = ('a' * 95) + '@test.com'
    resp = client.post('/api/register', json={
        'name': '测试',
        'email': email,
        'password': 'Passw0rd123',
        'role': 'student',
    })
    assert resp.status_code == 400
    assert '邮箱不能超过' in resp.get_json()['message']


def test_create_event_rejects_too_long_title(client, auth, event):
    resp = client.post('/api/create_event', headers=auth(event['org_token']), json={
        'title': 'T' * 300,
        'description': '',
        'venue_id': 1,
        'start_time': '2030-01-01T10:00',
        'end_time': '2030-01-01T12:00',
        'capacity': 5,
    })
    assert resp.status_code == 400
    assert '标题不能超过' in resp.get_json()['message']


def test_unknown_non_api_path_returns_404(client):
    resp = client.get('/no-such-page')
    assert resp.status_code == 404


def test_unknown_api_path_returns_json_404(client):
    resp = client.get('/api/no-such-endpoint')
    assert resp.status_code == 404
    assert resp.get_json()['code'] == 404

"""本轮复核修复项的回归用例（v2）。

覆盖：
- 活动列表接口返回 started / ended（前端状态机依赖）
- close_event 兼容 'close' / 'closed' 两种取值（前后端取值不一致的历史 bug）
- 已开始的活动不能修改开始时间，但其它字段仍可编辑
- 名额不能小于当前有效报名数
- 退出登录 / 修改密码后旧令牌立即失效
- 报名名单支持 include_cancelled，并能读到取消人 / 取消时间
- 重新报名不会覆盖首次报名时间
"""

import uuid


def _h(token):
    return {'Authorization': f'Bearer {token}'}


def _payload(venue_id, start, end, capacity=10, title=None):
    return {
        'title': title or f'回归活动_{uuid.uuid4().hex[:8]}',
        'description': '回归用例',
        'venue_id': venue_id,
        'start_time': start,
        'end_time': end,
        'capacity': capacity,
    }


def _detail(client, token, event_id):
    return client.get(f'/api/events/{event_id}', headers=_h(token)).get_json()['data']


def test_event_list_exposes_started_and_ended(client, auth, event, db):
    """列表页拿不到 started/ended 会让前端把所有活动显示成「报名中」。"""
    db(
        "UPDATE events SET start_time = NOW() - INTERVAL 3 HOUR, "
        "end_time = NOW() - INTERVAL 1 HOUR WHERE event_id = %s",
        (event['event_id'],),
    )
    result = client.get('/api/events?page=1&page_size=100',
                        headers=auth(event['org_token'])).get_json()
    row = next(e for e in result['data'] if e['event_id'] == event['event_id'])
    assert 'started' in row and 'ended' in row
    assert row['started'] is True
    assert row['ended'] is True


def test_close_event_accepts_close_and_closed(client, auth, event):
    """前端曾发 {'action':'closed'}，后端只认 'close'，导致「关闭报名」100% 失败。"""
    resp = client.put(f"/api/close_event/{event['event_id']}",
                      headers=auth(event['org_token']), json={'action': 'closed'})
    assert resp.status_code == 200, resp.get_json()

    resp = client.put(f"/api/close_event/{event['event_id']}",
                      headers=auth(event['org_token']), json={'action': 'open'})
    assert resp.status_code == 200, resp.get_json()


def test_cannot_move_start_time_of_started_event(client, auth, active_scene):
    """已开始的活动把开始时间改到未来，会重新开放报名/签到，必须拦住。"""
    detail = _detail(client, active_scene['org_token'], active_scene['event_id'])
    payload = _payload(venue_id=detail['venue_id'],
                       start='2035-01-01 10:00:00',
                       end='2035-01-01 12:00:00',
                       capacity=10, title=detail['title'])
    resp = client.put(f"/api/update_event/{active_scene['event_id']}",
                      headers=auth(active_scene['org_token']), json=payload)
    assert resp.status_code == 400
    assert '不能修改开始时间' in resp.get_json()['message']


def test_started_event_can_still_edit_other_fields(client, auth, active_scene):
    detail = _detail(client, active_scene['org_token'], active_scene['event_id'])
    payload = _payload(venue_id=detail['venue_id'],
                       start=detail['start_time'],
                       end=detail['end_time'],
                       capacity=max(int(detail['capacity']), 10),
                       title=detail['title'])
    resp = client.put(f"/api/update_event/{active_scene['event_id']}",
                      headers=auth(active_scene['org_token']), json=payload)
    assert resp.status_code == 200, resp.get_json()


def test_capacity_cannot_drop_below_active(client, auth, event, registration, db):
    # 再造 2 个报名，共 3 个有效报名
    for _ in range(2):
        email = f'bulk_{uuid.uuid4().hex[:10]}@test.com'
        client.post('/api/register', json={
            'name': '批量学生', 'email': email,
            'password': 'Passw0rd123', 'role': 'student',
        })
        token = client.post('/api/login', json={
            'email': email, 'password': 'Passw0rd123'}).get_json()['token']
        client.post('/api/register_event', headers=_h(token),
                    json={'event_id': event['event_id']})

    detail = _detail(client, event['org_token'], event['event_id'])
    payload = _payload(venue_id=detail['venue_id'],
                       start=detail['start_time'],
                       end=detail['end_time'],
                       capacity=2, title=detail['title'])
    resp = client.put(f"/api/update_event/{event['event_id']}",
                      headers=auth(event['org_token']), json=payload)
    assert resp.status_code == 400
    assert '名额不能小于当前已报名人数' in resp.get_json()['message']


def test_logout_invalidates_token(client, make_user, auth):
    _, token = make_user('student')
    assert client.get('/api/me', headers=auth(token)).status_code == 200

    assert client.post('/api/logout', headers=auth(token)).status_code == 200
    # 旧令牌必须立即失效（不再等 24 小时自然过期）
    assert client.get('/api/me', headers=auth(token)).status_code == 401


def test_change_password_flow(client, make_user, auth):
    user, token = make_user('student')
    new_password = 'NewPassw0rd9'

    resp = client.put('/api/change_password', headers=auth(token), json={
        'old_password': 'WrongPass1', 'new_password': new_password,
    })
    assert resp.status_code == 400

    resp = client.put('/api/change_password', headers=auth(token), json={
        'old_password': 'Passw0rd123', 'new_password': new_password,
    })
    assert resp.status_code == 200, resp.get_json()
    new_token = resp.get_json()['token']
    assert client.get('/api/me', headers=auth(token)).status_code == 401
    assert client.get('/api/me', headers=auth(new_token)).status_code == 200

    assert client.post('/api/login', json={
        'email': user['email'], 'password': 'Passw0rd123'}).status_code == 400
    assert client.post('/api/login', json={
        'email': user['email'], 'password': new_password}).status_code == 200


def test_event_registrations_include_cancelled(client, auth, event, registration):
    organizer_token = event['org_token']
    resp = client.put(f"/api/cancel_registration/{registration['registration_id']}",
                      headers=auth(registration['stu_token']))
    assert resp.status_code == 200, resp.get_json()

    default = client.get(f"/api/event_registrations/{event['event_id']}",
                         headers=auth(organizer_token)).get_json()
    assert all(r['registration_status'] != 'cancelled' for r in default['data'])

    all_rows = client.get(
        f"/api/event_registrations/{event['event_id']}?include_cancelled=1",
        headers=auth(organizer_token)).get_json()
    row = next(r for r in all_rows['data']
               if r['registration_id'] == registration['registration_id'])
    assert row['registration_status'] == 'cancelled'
    assert row['cancelled_at']
    assert row['cancelled_by'] == registration['student']['user_id']


def test_re_register_keeps_original_registered_at(client, auth, event, registration, db_fetch):
    rows = db_fetch("SELECT registered_at FROM registrations WHERE registration_id = %s",
                    (registration['registration_id'],))
    original = rows[0]['registered_at']

    client.put(f"/api/cancel_registration/{registration['registration_id']}",
               headers=auth(registration['stu_token']))
    client.post('/api/register_event', headers=auth(registration['stu_token']),
                json={'event_id': event['event_id']})

    rows = db_fetch("SELECT registered_at, status FROM registrations WHERE registration_id = %s",
                    (registration['registration_id'],))
    assert rows[0]['registered_at'] == original
    assert rows[0]['status'] == 'registered'

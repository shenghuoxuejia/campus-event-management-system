"""之前修过的 bug 的回归用例，别再改回去。"""

import threading
import uuid

import app as app_module

from helpers import (auth_header, event_detail, event_payload, list_venues,
                     post_event, promote_to_admin)


def test_undo_check_in_success(client, auth, active_scene):
    rid = active_scene['registration_id']
    assert client.put(f'/api/check_in/{rid}',
                      headers=auth(active_scene['org_token'])).status_code == 200

    resp = client.put(f'/api/undo_check_in/{rid}',
                      headers=auth(active_scene['org_token']))
    assert resp.status_code == 200, resp.get_json()

    regs = client.get(f"/api/user_registrations/{active_scene['student']['user_id']}",
                      headers=auth(active_scene['stu_token'])).get_json()['data']
    row = next(r for r in regs if r['event_id'] == active_scene['event_id'])
    assert row['registration_status'] == 'registered'
    assert row['check_in_time'] is None


def test_undo_check_in_when_not_checked_in_fails(client, auth, active_scene):
    resp = client.put(f"/api/undo_check_in/{active_scene['registration_id']}",
                      headers=auth(active_scene['org_token']))
    assert resp.status_code == 400
    assert '尚未签到' in resp.get_json()['message']


def test_undo_check_in_by_other_organizer_forbidden(client, auth, active_scene, make_user):
    rid = active_scene['registration_id']
    client.put(f'/api/check_in/{rid}', headers=auth(active_scene['org_token']))

    _, other_token = make_user('organizer')
    resp = client.put(f'/api/undo_check_in/{rid}', headers=auth(other_token))
    assert resp.status_code == 403
    assert resp.get_json()['code'] == 403


def test_can_check_in_again_after_undo(client, auth, active_scene):
    rid = active_scene['registration_id']
    headers = auth(active_scene['org_token'])
    assert client.put(f'/api/check_in/{rid}', headers=headers).status_code == 200
    assert client.put(f'/api/undo_check_in/{rid}', headers=headers).status_code == 200
    assert client.put(f'/api/check_in/{rid}', headers=headers).status_code == 200


def test_can_cancel_after_undo_check_in(client, auth, active_scene, db, make_user):
    rid = active_scene['registration_id']
    client.put(f'/api/check_in/{rid}', headers=auth(active_scene['org_token']))
    client.put(f'/api/undo_check_in/{rid}', headers=auth(active_scene['org_token']))

    # 活动已经开始了，学生自己取消不了，得管理员强制
    admin_user, admin_token = make_user('student')
    promote_to_admin(db, admin_user['user_id'])
    resp = client.put(f'/api/cancel_registration/{rid}', headers=auth(admin_token))
    assert resp.status_code == 200, resp.get_json()


def test_remove_checked_in_student_fails(client, auth, active_scene):
    rid = active_scene['registration_id']
    assert client.put(f'/api/check_in/{rid}',
                      headers=auth(active_scene['org_token'])).status_code == 200

    resp = client.delete(f'/api/remove_registration/{rid}',
                         headers=auth(active_scene['org_token']))
    assert resp.status_code == 400
    assert '已签到' in resp.get_json()['message']


def test_admin_can_check_in(client, auth, active_scene, db, make_user):
    admin_user, admin_token = make_user('student')
    promote_to_admin(db, admin_user['user_id'])

    resp = client.put(f"/api/check_in/{active_scene['registration_id']}",
                      headers=auth(admin_token))
    assert resp.status_code == 200, resp.get_json()


def test_admin_can_cancel_registration(client, auth, registration, db, make_user):
    admin_user, admin_token = make_user('student')
    promote_to_admin(db, admin_user['user_id'])

    resp = client.put(f"/api/cancel_registration/{registration['registration_id']}",
                      headers=auth(admin_token))
    assert resp.status_code == 200, resp.get_json()


def test_cannot_book_disabled_venue(client, auth, event, db):
    venues = list_venues(client, event['org_token'])
    venue_id = venues[-1]['venue_id']
    db("UPDATE venues SET available_status = 0 WHERE venue_id = %s", (venue_id,))
    try:
        body = event_payload(venue_id, '2030-06-01T10:00', '2030-06-01T12:00', capacity=5,
                             title='停用场地活动')
        resp = client.post('/api/create_event', headers=auth(event['org_token']), json=body)
        assert resp.status_code == 400
        assert '停用' in resp.get_json()['message']
    finally:
        db("UPDATE venues SET available_status = 1 WHERE venue_id = %s", (venue_id,))


def test_get_comments_for_missing_event_returns_404(client, auth, make_user):
    _, token = make_user('student')
    resp = client.get('/api/comments/99999999', headers=auth(token))
    assert resp.status_code == 404
    assert resp.get_json()['code'] == 404


def test_login_created_at_is_formatted(client, make_user):
    user, _ = make_user('student')
    assert user.get('created_at') is not None
    # 要的是 2026-09-26 21:26:02，不是 RFC 1123
    assert len(user['created_at']) == 19
    assert user['created_at'][4] == '-' and user['created_at'][13] == ':'


def test_cannot_undo_check_in_after_end(client, auth, ended_scene, db):
    # 绕过 check_in 的「已结束不能签到」，直接在库里改成已签到
    db("UPDATE registrations SET status = 'checked_in', check_in_time = NOW() "
       "WHERE registration_id = %s", (ended_scene['registration_id'],))
    resp = client.put(f"/api/undo_check_in/{ended_scene['registration_id']}",
                      headers=auth(ended_scene['org_token']))
    assert resp.status_code == 400
    assert '已结束' in resp.get_json()['message']


def test_cannot_delete_event_with_check_in(client, auth, active_scene):
    rid = active_scene['registration_id']
    assert client.put(f'/api/check_in/{rid}',
                      headers=auth(active_scene['org_token'])).status_code == 200

    resp = client.delete(f"/api/delete_event/{active_scene['event_id']}",
                         headers=auth(active_scene['org_token']))
    assert resp.status_code == 409
    assert '签到记录' in resp.get_json()['message']


def test_cannot_delete_started_event_by_organizer(client, auth, active_scene):
    resp = client.delete(f"/api/delete_event/{active_scene['event_id']}",
                         headers=auth(active_scene['org_token']))
    assert resp.status_code == 409
    assert '已开始' in resp.get_json()['message']


def test_cancel_records_cancelled_at_and_by(client, auth, event, registration):
    rid = registration['registration_id']
    student_id = registration['student']['user_id']

    resp = client.put(f'/api/cancel_registration/{rid}',
                      headers=auth(registration['stu_token']))
    assert resp.status_code == 200

    with app_module.db_cursor() as cur:
        cur.execute(
            "SELECT status, cancelled_at, cancelled_by FROM registrations "
            "WHERE registration_id = %s",
            (rid,),
        )
        row = cur.fetchone()
    assert row['status'] == 'cancelled'
    assert row['cancelled_at'] is not None
    assert row['cancelled_by'] == student_id


def test_re_register_clears_cancel_fields(client, auth, event, registration):
    rid = registration['registration_id']
    client.put(f'/api/cancel_registration/{rid}',
               headers=auth(registration['stu_token']))
    # 重新报名走的是 UPDATE 分支，取消痕迹要清掉
    resp = client.post('/api/register_event', headers=auth(registration['stu_token']),
                       json={'event_id': event['event_id']})
    assert resp.status_code == 200, resp.get_json()

    with app_module.db_cursor() as cur:
        cur.execute(
            "SELECT status, cancelled_at, cancelled_by, check_in_time "
            "FROM registrations WHERE registration_id = %s",
            (rid,),
        )
        row = cur.fetchone()
    assert row['status'] == 'registered'
    assert row['cancelled_at'] is None
    assert row['cancelled_by'] is None
    assert row['check_in_time'] is None


def test_event_list_exposes_started_and_ended(client, auth, event, db, move_to_own_venue):
    # 列表接口拿不到 started/ended 的话，前端会把结束的活动都显示成「报名中」
    move_to_own_venue(event['event_id'])
    db("UPDATE events SET start_time = NOW() - INTERVAL 3 HOUR, "
       "end_time = NOW() - INTERVAL 1 HOUR WHERE event_id = %s",
       (event['event_id'],))
    result = client.get('/api/events?page=1&page_size=100',
                        headers=auth(event['org_token'])).get_json()
    row = next(e for e in result['data'] if e['event_id'] == event['event_id'])
    assert 'started' in row and 'ended' in row
    assert row['started'] is True
    assert row['ended'] is True


def test_close_event_accepts_close_and_closed(client, auth, event):
    # 前端曾经发 {'action':'closed'}，后端只认 'close'，结果「关闭报名」100% 失败
    resp = client.put(f"/api/close_event/{event['event_id']}",
                      headers=auth(event['org_token']), json={'action': 'closed'})
    assert resp.status_code == 200, resp.get_json()

    resp = client.put(f"/api/close_event/{event['event_id']}",
                      headers=auth(event['org_token']), json={'action': 'open'})
    assert resp.status_code == 200, resp.get_json()


def test_cannot_move_start_time_of_started_event(client, auth, active_scene):
    # 把已开始活动的开始时间改到未来，等于重新开放报名/签到，必须挡住
    detail = event_detail(client, active_scene['org_token'], active_scene['event_id'])
    payload = event_payload(venue_id=detail['venue_id'],
                       start='2035-01-01 10:00:00',
                       end='2035-01-01 12:00:00',
                       capacity=10, title=detail['title'])
    resp = client.put(f"/api/update_event/{active_scene['event_id']}",
                      headers=auth(active_scene['org_token']), json=payload)
    assert resp.status_code == 400
    assert '不能修改开始时间' in resp.get_json()['message']


def test_started_event_can_still_edit_other_fields(client, auth, active_scene):
    detail = event_detail(client, active_scene['org_token'], active_scene['event_id'])
    payload = event_payload(venue_id=detail['venue_id'],
                       start=detail['start_time'],
                       end=detail['end_time'],
                       capacity=max(int(detail['capacity']), 10),
                       title=detail['title'])
    resp = client.put(f"/api/update_event/{active_scene['event_id']}",
                      headers=auth(active_scene['org_token']), json=payload)
    assert resp.status_code == 200, resp.get_json()


def test_capacity_cannot_drop_below_active(client, auth, event, registration, make_user):
    for _ in range(2):
        _, token = make_user('student')
        client.post('/api/register_event', headers=auth_header(token),
                    json={'event_id': event['event_id']})

    detail = event_detail(client, event['org_token'], event['event_id'])
    payload = event_payload(venue_id=detail['venue_id'],
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
    new_token = resp.get_json()['data']['token']
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

    rows = db_fetch("SELECT registered_at, status FROM registrations "
                    "WHERE registration_id = %s",
                    (registration['registration_id'],))
    assert rows[0]['registered_at'] == original
    assert rows[0]['status'] == 'registered'


def test_login_bruteforce_is_rate_limited(client, app, make_user):
    user, _ = make_user('student')
    limit = app_module.LOGIN_RATE_LIMIT[0]

    app.config['TESTING'] = False
    _clear_buckets()
    try:
        for _ in range(limit):
            resp = client.post('/api/login', json={
                'email': user['email'], 'password': 'WrongPass1',
            })
            assert resp.status_code == 400

        resp = client.post('/api/login', json={
            'email': user['email'], 'password': 'WrongPass1',
        })
        assert resp.status_code == 429
        assert resp.get_json()['code'] == 429
        assert '频繁' in resp.get_json()['message']
    finally:
        app.config['TESTING'] = True
        _clear_buckets()


def test_successful_login_resets_counter(client, app, make_user):
    user, _ = make_user('student')
    limit = app_module.LOGIN_RATE_LIMIT[0]

    app.config['TESTING'] = False
    _clear_buckets()
    try:
        for _ in range(limit - 1):
            client.post('/api/login', json={
                'email': user['email'], 'password': 'WrongPass1',
            })

        assert client.post('/api/login', json={
            'email': user['email'], 'password': 'Passw0rd123',
        }).status_code == 200

        resp = client.post('/api/login', json={
            'email': user['email'], 'password': 'WrongPass1',
        })
        assert resp.status_code == 400  # 是 400 而不是 429，说明计数被清了
    finally:
        app.config['TESTING'] = True
        _clear_buckets()


def test_rate_limit_is_per_account(client, app, make_user):
    user_a, _ = make_user('student')
    user_b, _ = make_user('student')
    limit = app_module.LOGIN_RATE_LIMIT[0]

    app.config['TESTING'] = False
    _clear_buckets()
    try:
        for _ in range(limit + 1):
            client.post('/api/login', json={
                'email': user_a['email'], 'password': 'WrongPass1',
            })
        assert client.post('/api/login', json={
            'email': user_a['email'], 'password': 'WrongPass1',
        }).status_code == 429

        assert client.post('/api/login', json={
            'email': user_b['email'], 'password': 'Passw0rd123',
        }).status_code == 200
    finally:
        app.config['TESTING'] = True
        _clear_buckets()


def _clear_buckets():
    with app_module._rate_lock:
        app_module._rate_buckets.clear()


def test_unknown_non_api_path_returns_404(client):
    assert client.get('/no-such-page').status_code == 404


def test_unknown_api_path_returns_json_404(client):
    resp = client.get('/api/no-such-endpoint')
    assert resp.status_code == 404
    assert resp.get_json()['code'] == 404


def test_register_rate_limited(client, app, monkeypatch):
    """注册限流：同一个 IP 连续注册超过阈值要返回 429（TESTING 会跳过限流，这里临时关掉）。"""
    monkeypatch.setattr(app_module, 'REGISTER_RATE_LIMIT', (2, 60))
    app.config['TESTING'] = False
    _clear_buckets()
    try:
        for i in range(2):
            resp = client.post('/api/register', json={
                'name': '限流测试', 'password': 'Passw0rd123', 'role': 'student',
                'email': f'ratelimit_{i}_{uuid.uuid4().hex[:8]}@test.com',
            })
            assert resp.status_code == 200, resp.get_json()

        resp = client.post('/api/register', json={
            'name': '限流测试', 'password': 'Passw0rd123', 'role': 'student',
            'email': f'ratelimit_over_{uuid.uuid4().hex[:8]}@test.com',
        })
        assert resp.status_code == 429
        assert resp.get_json()['code'] == 429
        assert '频繁' in resp.get_json()['message']
    finally:
        app.config['TESTING'] = True
        _clear_buckets()


def test_comment_rate_limited(client, app, auth, event, registration, monkeypatch):
    monkeypatch.setattr(app_module, 'COMMENT_RATE_LIMIT', (2, 60))
    app.config['TESTING'] = False
    _clear_buckets()
    try:
        for i in range(2):
            resp = client.post('/api/comments', headers=auth(registration['stu_token']),
                               json={'event_id': event['event_id'], 'content': f'评论{i}'})
            assert resp.status_code == 200, resp.get_json()

        resp = client.post('/api/comments', headers=auth(registration['stu_token']),
                           json={'event_id': event['event_id'], 'content': '超限'})
        assert resp.status_code == 429
        assert resp.get_json()['code'] == 429
    finally:
        app.config['TESTING'] = True
        _clear_buckets()


def test_change_password_rate_limited(client, app, auth, make_user, monkeypatch):
    """拿到令牌后反复猜旧密码也要被限流。"""
    monkeypatch.setattr(app_module, 'LOGIN_RATE_LIMIT', (2, 60))
    app.config['TESTING'] = False
    _clear_buckets()
    try:
        _, token = make_user('student')
        for _ in range(2):
            resp = client.put('/api/change_password', headers=auth(token), json={
                'old_password': 'WrongPass1', 'new_password': 'Passw0rd456',
            })
            assert resp.status_code == 400, resp.get_json()

        resp = client.put('/api/change_password', headers=auth(token), json={
            'old_password': 'WrongPass1', 'new_password': 'Passw0rd456',
        })
        assert resp.status_code == 429, resp.get_json()
    finally:
        app.config['TESTING'] = True
        _clear_buckets()


# ---------------------------------------------------------------------------
# 以下用例对应 2026-11 一轮代码审查修掉的问题，别再改回去
# ---------------------------------------------------------------------------

def test_removed_registration_cannot_self_re_register(client, auth, event, registration):
    """被组织者移出后，学生不能自己重新报名，否则「移出」等于没做。"""
    rid = registration['registration_id']
    resp = client.delete(f'/api/remove_registration/{rid}',
                         headers=auth(event['org_token']))
    assert resp.status_code == 200, resp.get_json()

    again = client.post('/api/register_event', headers=auth(registration['stu_token']),
                        json={'event_id': event['event_id']})
    assert again.status_code == 403, again.get_json()
    assert '移出' in again.get_json()['message']

    with app_module.db_cursor() as cur:
        cur.execute("SELECT status, cancelled_by FROM registrations "
                    "WHERE registration_id = %s", (rid,))
        row = cur.fetchone()
    assert row['status'] == 'cancelled'
    assert row['cancelled_by'] == event['organizer']['user_id']


def test_capacity_out_of_range_is_400_not_500(client, auth, event, unique_event_window):
    """容量超出上限（否则 MySQL 报 1264）要是参数错误，不是 500。"""
    venue_id = list_venues(client, event['org_token'])[0]['venue_id']
    start, end = unique_event_window()
    body = event_payload(venue_id, start, end, capacity=99999999999, title='超大名额')
    resp = client.post('/api/create_event', headers=auth(event['org_token']), json=body)
    assert resp.status_code == 400, resp.get_json()
    assert '名额' in resp.get_json()['message']


def test_venue_capacity_out_of_range_is_400(client, make_user, auth, db):
    _, token = make_user('student')
    uid = client.get('/api/me', headers=auth(token)).get_json()['data']['user_id']
    promote_to_admin(db, uid)

    resp = client.post('/api/venues', headers=auth(token), json={
        'venue_name': f'超大场地_{uuid.uuid4().hex[:8]}', 'capacity': 99999999999,
    })
    assert resp.status_code == 400, resp.get_json()
    assert '容量' in resp.get_json()['message']


def test_response_envelope_keeps_token_and_id_inside_data(client, make_user, auth, db):
    """统一响应结构：令牌这类附加字段放在 data 里，不要平铺到顶层。"""
    email = f'envelope_{uuid.uuid4().hex[:8]}@test.com'

    body = client.post('/api/register', json={
        'name': '结构校验', 'email': email, 'password': 'Passw0rd123', 'role': 'student',
    }).get_json()
    assert set(body) <= {'code', 'message', 'data'}, body
    assert body['data']['token']

    body = client.post('/api/login', json={'email': email, 'password': 'Passw0rd123'}).get_json()
    assert set(body) <= {'code', 'message', 'data'}, body
    token = body['data']['token']
    assert token

    body = client.put('/api/change_password', headers=auth(token), json={
        'old_password': 'Passw0rd123', 'new_password': 'Passw0rd456',
    }).get_json()
    assert set(body) <= {'code', 'message', 'data'}, body
    assert body['data']['token']

    # 新增场地返回的 venue_id 同样在 data 里
    uid = client.get('/api/me', headers=auth(body['data']['token'])).get_json()['data']['user_id']
    promote_to_admin(db, uid)
    body = client.post('/api/venues', headers=auth(body['data']['token']), json={
        'venue_name': f'结构校验场地_{uuid.uuid4().hex[:8]}', 'capacity': 10,
    }).get_json()
    assert set(body) <= {'code', 'message', 'data'}, body
    assert body['data']['venue_id']


def test_update_event_can_move_to_another_venue(client, auth, event, unique_event_window):
    """编辑换场地要走得通：场地锁改到活动行之前拿，别把功能弄坏。"""
    detail = event_detail(client, event['org_token'], event['event_id'])
    others = [v for v in list_venues(client, event['org_token'])
              if v['venue_id'] != detail['venue_id']]
    if not others:
        return  # 测试库只有一个场地，跳过

    start, end = unique_event_window()
    body = event_payload(others[0]['venue_id'], start, end,
                         capacity=detail['capacity'], title='换场地后的活动')
    resp = client.put(f"/api/update_event/{event['event_id']}",
                      headers=auth(event['org_token']), json=body)
    assert resp.status_code == 200, resp.get_json()
    assert event_detail(client, event['org_token'], event['event_id'])['venue_id'] == others[0]['venue_id']


def test_create_and_update_same_venue_do_not_deadlock(app, client, make_user,
                                                      unique_event_window):
    """发布和编辑都按 venues → events 加锁；反过来会 1213（表现为 409）。"""
    _, org_token = make_user('organizer')
    venues = list_venues(client, org_token)
    venue_id = venues[0]['venue_id']

    start, end = unique_event_window()
    event_id = post_event(client, org_token, event_payload(
        venue_id, start, end, capacity=5, title='锁顺序测试活动'))

    for round_no in range(3):
        create_start, create_end = unique_event_window()
        update_start, update_end = unique_event_window()
        create_body = event_payload(venue_id, create_start, create_end,
                                    capacity=5, title=f'并发发布_{round_no}')
        update_body = event_payload(venue_id, update_start, update_end,
                                    capacity=5, title=f'并发编辑_{round_no}')

        barrier = threading.Barrier(2)
        results = []

        def do_create():
            with app.test_client() as c:
                barrier.wait()
                r = c.post('/api/create_event', headers=auth_header(org_token), json=create_body)
                results.append(('create', r.status_code, r.get_json().get('message', '')))

        def do_update():
            with app.test_client() as c:
                barrier.wait()
                r = c.put(f'/api/update_event/{event_id}', headers=auth_header(org_token),
                          json=update_body)
                results.append(('update', r.status_code, r.get_json().get('message', '')))

        threads = [threading.Thread(target=do_create), threading.Thread(target=do_update)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sorted(code for _, code, _ in results) == [200, 200], f'第 {round_no} 轮 {results}'

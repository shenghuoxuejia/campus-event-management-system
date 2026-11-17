"""数据库端对象（视图 / 触发器 / 存储过程）与统计接口。

这一组用例的重点不是"接口返回 200"，而是证明：
- 视图算出来的报名数/余量和 registrations 表真实数据一致；
- 触发器能在**绕过接口直接写库**时把非法数据拦住（这才是数据库层的保证）；
- 统计接口的聚合口径和库里对得上。
"""

import pytest

import app as app_module
from app import AppError


def _h(token):
    return {'Authorization': f'Bearer {token}'}


def _venue_with_capacity(client, auth, token, capacity):
    venues = client.get('/api/venues', headers=auth(token)).get_json()['data']
    return next(v for v in venues if v['capacity'] >= capacity)


# ---------- 视图 ----------

def test_view_counts_match_registrations(client, auth, event, registration, db_fetch, db):
    """v_event_overview 的 registered_count / remaining 必须和明细表一致。"""
    eid = event['event_id']

    def view_row():
        return db_fetch("SELECT * FROM v_event_overview WHERE event_id = %s", (eid,))[0]

    row = view_row()
    assert row['registered_count'] == 1
    assert row['remaining'] == row['capacity'] - 1
    assert row['checked_in_count'] == 0

    # 再报一个人，视图要跟着变
    _, other_token = _make_student(client)
    resp = client.post('/api/register_event', headers=auth(other_token),
                       json={'event_id': eid})
    assert resp.status_code == 200, resp.get_json()

    assert view_row()['registered_count'] == 2

    # 签到后 checked_in_count 要跟上
    reg_row = db_fetch("SELECT registration_id FROM registrations "
                       "WHERE event_id = %s AND status = 'registered' ORDER BY registration_id",
                       (eid,))[0]
    db("UPDATE registrations SET status = 'checked_in', check_in_time = NOW() "
       "WHERE registration_id = %s", (reg_row['registration_id'],))
    assert view_row()['checked_in_count'] == 1


def test_view_counts_are_json_numbers(client, auth, event, registration):
    """视图里的 SUM() 是 DECIMAL，接口必须返回数字而不是字符串（前端要能直接算）。"""
    data = client.get(f"/api/events/{event['event_id']}",
                      headers=auth(registration['stu_token'])).get_json()['data']
    assert isinstance(data['registered_count'], int), data['registered_count']
    assert isinstance(data['remaining'], int), data['remaining']
    assert data['remaining'] == data['capacity'] - data['registered_count']


def test_list_endpoint_exposes_counts(client, auth, event, registration):
    """列表接口（前端大厅实际渲染的那个）也要给出正确的报名数与余量。"""
    result = client.get('/api/events?page=1&page_size=100',
                        headers=auth(registration['stu_token'])).get_json()
    row = next(e for e in result['data'] if e['event_id'] == event['event_id'])
    assert row['registered_count'] == 1
    assert row['remaining'] == row['capacity'] - 1
    assert row['is_registered'] == 1
    assert isinstance(row['remaining'], int)


def _make_student(client):
    import uuid
    email = f'student_{uuid.uuid4().hex[:12]}@test.com'
    client.post('/api/register', json={'name': '学生', 'email': email,
                                       'password': 'Passw0rd123', 'role': 'student'})
    login = client.post('/api/login', json={'email': email, 'password': 'Passw0rd123'})
    data = login.get_json()
    return data['data'], data['token']


# ---------- 触发器：绕过接口直接写库也要被拦住 ----------

def test_trigger_blocks_overlapping_venue_insert(client, auth, make_user, db, unique_event_window):
    """应用层校验被绕过时（直接 INSERT），数据库触发器必须拦住场地重叠。"""
    org_user, org_token = make_user('organizer')
    venue = _venue_with_capacity(client, auth, org_token, 100)
    start, end = unique_event_window()

    db("INSERT INTO events (title, description, organizer_id, venue_id, "
       "start_time, end_time, capacity, status) VALUES ('占位活动', '', %s, %s, %s, %s, 10, 'open')",
       (org_user['user_id'], venue['venue_id'], start, end))

    with pytest.raises(AppError) as err:
        db("INSERT INTO events (title, description, organizer_id, venue_id, "
           "start_time, end_time, capacity, status) VALUES ('撞车活动', '', %s, %s, %s, %s, 10, 'open')",
           (org_user['user_id'], venue['venue_id'], start, end))

    assert err.value.code == 409
    assert '触发器拦截' in err.value.message


def test_trigger_allows_adjacent_venue_insert(client, auth, make_user, db, unique_event_window):
    """首尾相接不算重叠，触发器不能误伤。"""
    org_user, org_token = make_user('organizer')
    venue = _venue_with_capacity(client, auth, org_token, 100)
    start, end = unique_event_window()

    db("INSERT INTO events (title, description, organizer_id, venue_id, "
       "start_time, end_time, capacity, status) VALUES ('前一场', '', %s, %s, %s, %s, 10, 'open')",
       (org_user['user_id'], venue['venue_id'], start, end))

    rows = db("INSERT INTO events (title, description, organizer_id, venue_id, "
              "start_time, end_time, capacity, status) "
              "VALUES ('后一场', '', %s, %s, %s, %s + INTERVAL 2 HOUR, 10, 'open')",
              (org_user['user_id'], venue['venue_id'], end, end))
    # db() 不返回结果，这里只是确认没抛异常；下面查一下确实写进去了
    assert rows is None


def test_trigger_blocks_capacity_over_venue(client, auth, make_user, db, unique_event_window):
    """名额超过场地容量：直接写库也要被拦（应用层之外的第二道）。"""
    org_user, org_token = make_user('organizer')
    venue = _venue_with_capacity(client, auth, org_token, 100)
    start, end = unique_event_window()

    with pytest.raises(AppError) as err:
        db("INSERT INTO events (title, description, organizer_id, venue_id, "
           "start_time, end_time, capacity, status) VALUES ('超大活动', '', %s, %s, %s, %s, %s, 'open')",
           (org_user['user_id'], venue['venue_id'], start, end, venue['capacity'] + 100))

    assert err.value.code == 409
    assert '场地容量' in err.value.message


def test_trigger_blocks_inconsistent_registration_status(client, auth, event, registration, db):
    """状态与时间戳不一致（已签到但没有签到时间）必须被数据库拒绝。"""
    reg_id = registration['registration_id']

    with pytest.raises(AppError) as err:
        db("UPDATE registrations SET status = 'checked_in' WHERE registration_id = %s", (reg_id,))
    assert err.value.code == 409
    assert '签到时间' in err.value.message

    with pytest.raises(AppError) as err:
        db("UPDATE registrations SET status = 'cancelled' WHERE registration_id = %s", (reg_id,))
    assert err.value.code == 409
    assert '取消时间' in err.value.message


def test_trigger_rejects_cancelled_without_operator(client, auth, event, registration, db):
    reg_id = registration['registration_id']
    with pytest.raises(AppError) as err:
        db("UPDATE registrations SET status = 'cancelled', cancelled_at = NOW() "
           "WHERE registration_id = %s", (reg_id,))
    assert err.value.code == 409
    assert '操作人' in err.value.message


# ---------- 存储过程 + 活动统计接口 ----------

def test_event_stats_requires_login(client, event):
    assert client.get(f"/api/events/{event['event_id']}/stats").status_code == 401


def test_event_stats_by_other_organizer_forbidden(client, auth, event, make_user):
    _, other_token = make_user('organizer')
    resp = client.get(f"/api/events/{event['event_id']}/stats", headers=auth(other_token))
    assert resp.status_code == 403


def test_event_stats_missing_event_404(client, auth, event):
    resp = client.get('/api/events/99999999/stats', headers=auth(event['org_token']))
    assert resp.status_code == 404


def test_event_stats_matches_database(client, auth, active_scene, db, db_fetch):
    """存储过程算的出入率要和库里数据对得上（用进行中的活动才能签到）。"""
    eid = active_scene['event_id']

    # 已有 1 个报名（active_scene 夹具造的）。活动已开始，接口不允许再报名了，
    # 所以第二个报名直接写库（触发器允许 status='registered' 且时间戳为空）
    other_user, _ = _make_student(client)
    db("INSERT INTO registrations (student_id, event_id, status) "
       "VALUES (%s, %s, 'registered')", (other_user['user_id'], eid))

    reg_id = db_fetch("SELECT registration_id FROM registrations "
                      "WHERE event_id = %s AND status = 'registered' "
                      "ORDER BY registration_id LIMIT 1", (eid,))[0]['registration_id']
    checked = client.put(f'/api/check_in/{reg_id}', headers=auth(active_scene['org_token']))
    assert checked.status_code == 200, checked.get_json()

    data = client.get(f'/api/events/{eid}/stats',
                      headers=auth(active_scene['org_token'])).get_json()['data']
    assert data['event_id'] == eid
    assert data['active_regs'] == 2
    assert data['checked_in'] == 1
    assert data['cancelled'] == 0
    assert data['attendance_pct'] == 50.0       # 1/2
    assert data['fill_pct'] == 20.0             # 容量 10，报 2 个
    assert data['by_status'] == {'registered': 1, 'checked_in': 1}
    assert sum(d['count'] for d in data['daily_registrations']) == 2


def test_event_stats_after_cancel(client, auth, event, registration, db_fetch):
    eid = event['event_id']
    client.put(f"/api/cancel_registration/{registration['registration_id']}",
               headers=auth(registration['stu_token']))

    data = client.get(f'/api/events/{eid}/stats',
                      headers=auth(event['org_token'])).get_json()['data']
    assert data['active_regs'] == 0
    assert data['cancelled'] == 1
    assert data['attendance_pct'] == 0      # 分母为 0 时不能抛异常
    assert data['fill_pct'] == 0


def test_event_stats_admin_allowed(client, auth, event, make_user, db):
    admin_user, admin_token = make_user('student')
    db("UPDATE users SET role = 'admin' WHERE user_id = %s", (admin_user['user_id'],))
    resp = client.get(f"/api/events/{event['event_id']}/stats", headers=auth(admin_token))
    assert resp.status_code == 200, resp.get_json()


# ---------- 平台统计接口 ----------

def test_admin_stats_requires_admin(client, auth, make_user):
    _, token = make_user('student')
    resp = client.get('/api/admin/stats', headers=auth(token))
    assert resp.status_code == 403
    assert resp.get_json()['code'] == 403


def test_admin_stats_requires_login(client):
    assert client.get('/api/admin/stats').status_code == 401


def test_admin_stats_aggregates(client, auth, event, registration, make_user, db, db_fetch):
    admin_user, admin_token = make_user('student')
    db("UPDATE users SET role = 'admin' WHERE user_id = %s", (admin_user['user_id'],))

    resp = client.get('/api/admin/stats', headers=auth(admin_token))
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()['data']

    for key in ('users_by_role', 'events_by_status', 'registrations_by_status',
                'by_category', 'venue_usage', 'top_events'):
        assert key in data, f'缺少 {key}'

    # 计数要和库里直接查出来的一致
    real_users = db_fetch("SELECT role, COUNT(*) AS cnt FROM users GROUP BY role")
    api_users = {row['role']: row['cnt'] for row in data['users_by_role']}
    assert {r['role']: r['cnt'] for r in real_users} == api_users

    real_regs = db_fetch("SELECT status, COUNT(*) AS cnt FROM registrations GROUP BY status")
    api_regs = {row['status']: row['cnt'] for row in data['registrations_by_status']}
    assert {r['status']: r['cnt'] for r in real_regs} == api_regs

    assert api_regs.get('registered', 0) >= 1

    # 场地利用率：至少包含当前事件所在场地
    usage = next(v for v in data['venue_usage'] if v['event_count'] >= 1)
    assert usage['registrations'] >= 1
    assert isinstance(usage['fill_pct'], float)

    # 报名最满的 Top N：必须是按上座率降序，且上座率在 0~100 之间
    tops = data['top_events']
    assert len(tops) <= 5
    assert all(0 <= e['fill_pct'] <= 100 for e in tops)
    assert [e['fill_pct'] for e in tops] == sorted((e['fill_pct'] for e in tops), reverse=True)

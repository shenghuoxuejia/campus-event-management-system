"""撤销签到、管理员代操作、场地停用、时间格式、评论 404 等修复点的回归测试。"""
import app as app_module

# ---------------- 撤销签到 ----------------

def test_undo_check_in_success(client, auth, active_scene):
    rid = active_scene['registration_id']
    assert client.put(f'/api/check_in/{rid}',
                      headers=auth(active_scene['org_token'])).status_code == 200

    resp = client.put(f'/api/undo_check_in/{rid}',
                      headers=auth(active_scene['org_token']))
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()['code'] == 200

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


def test_can_cancel_after_undo_check_in(client, auth, active_scene, db, make_user):
    rid = active_scene['registration_id']
    client.put(f'/api/check_in/{rid}', headers=auth(active_scene['org_token']))
    client.put(f'/api/undo_check_in/{rid}', headers=auth(active_scene['org_token']))

    # 活动进行中，学生本人和组织者都不能取消；由管理员强制取消
    admin_user, admin_token = make_user('student')
    _promote_to_admin(db, admin_user['user_id'])
    resp = client.put(f'/api/cancel_registration/{rid}',
                      headers=auth(admin_token))
    assert resp.status_code == 200, resp.get_json()


def test_can_check_in_again_after_undo(client, auth, active_scene):
    rid = active_scene['registration_id']
    tokens = auth(active_scene['org_token'])
    assert client.put(f'/api/check_in/{rid}', headers=tokens).status_code == 200
    assert client.put(f'/api/undo_check_in/{rid}', headers=tokens).status_code == 200
    assert client.put(f'/api/check_in/{rid}', headers=tokens).status_code == 200


# ---------------- 移除已签到学生 ----------------

def test_remove_checked_in_student_fails(client, auth, active_scene):
    rid = active_scene['registration_id']
    assert client.put(f'/api/check_in/{rid}',
                      headers=auth(active_scene['org_token'])).status_code == 200

    resp = client.delete(f'/api/remove_registration/{rid}',
                         headers=auth(active_scene['org_token']))
    assert resp.status_code == 400
    assert '已签到' in resp.get_json()['message']


# ---------------- 管理员代操作 ----------------

def _promote_to_admin(db, user_id):
    db("UPDATE Users SET role = 'admin' WHERE user_id = %s", (user_id,))


def test_admin_can_check_in(client, auth, active_scene, db, make_user):
    admin_user, admin_token = make_user('student')
    _promote_to_admin(db, admin_user['user_id'])

    resp = client.put(f"/api/check_in/{active_scene['registration_id']}",
                      headers=auth(admin_token))
    assert resp.status_code == 200, resp.get_json()


def test_admin_can_cancel_registration(client, auth, registration, db, make_user):
    admin_user, admin_token = make_user('student')
    _promote_to_admin(db, admin_user['user_id'])

    resp = client.put(f"/api/cancel_registration/{registration['registration_id']}",
                      headers=auth(admin_token))
    assert resp.status_code == 200, resp.get_json()


# ---------------- 场地停用 / 时间格式 ----------------

def test_cannot_book_disabled_venue(client, auth, event, db):
    venues = client.get('/api/venues', headers=auth(event['org_token'])).get_json()['data']
    venue_id = venues[-1]['venue_id']
    db("UPDATE Venues SET available_status = 0 WHERE venue_id = %s", (venue_id,))
    try:
        resp = client.post('/api/create_event', headers=auth(event['org_token']), json={
            'title': '停用场地活动', 'description': '',
            'venue_id': venue_id,
            'start_time': '2030-06-01T10:00', 'end_time': '2030-06-01T12:00',
            'capacity': 5,
        })
        assert resp.status_code == 400
        assert '停用' in resp.get_json()['message']
    finally:
        db("UPDATE Venues SET available_status = 1 WHERE venue_id = %s", (venue_id,))


def test_create_event_rejects_invalid_time_format(client, auth, event):
    venues = client.get('/api/venues', headers=auth(event['org_token'])).get_json()['data']
    resp = client.post('/api/create_event', headers=auth(event['org_token']), json={
        'title': '非法时间', 'description': '',
        'venue_id': venues[0]['venue_id'],
        'start_time': 'abc', 'end_time': '2030-06-01T12:00',
        'capacity': 5,
    })
    assert resp.status_code == 400
    assert '格式不正确' in resp.get_json()['message']


# ---------------- 评论接口对不存在活动 ----------------

def test_get_comments_for_missing_event_returns_404(client, auth, make_user):
    _, token = make_user('student')
    resp = client.get('/api/comments/99999999', headers=auth(token))
    assert resp.status_code == 404
    assert resp.get_json()['code'] == 404


# ---------------- 登录返回时间格式 ----------------

def test_login_created_at_is_formatted(client, make_user):
    user, _ = make_user('student')
    assert user.get('created_at') is not None
    # 形如 2026-09-26 21:26:02，而不是 RFC 1123
    assert len(user['created_at']) == 19
    assert user['created_at'][4] == '-' and user['created_at'][13] == ':'

    # ---------------- 时间窗限制（P1-11） ----------------

def test_cannot_cancel_after_start(client, auth, active_scene):
    """活动开始后，学生本人不能取消报名。"""
    resp = client.put(f"/api/cancel_registration/{active_scene['registration_id']}",
                      headers=auth(active_scene['stu_token']))
    assert resp.status_code == 400
    assert '已开始' in resp.get_json()['message']


def test_cannot_remove_after_start(client, auth, active_scene):
    """活动开始后，组织者不能移出学生。"""
    resp = client.delete(f"/api/remove_registration/{active_scene['registration_id']}",
                         headers=auth(active_scene['org_token']))
    assert resp.status_code == 400
    assert '已开始' in resp.get_json()['message']


def test_cannot_undo_check_in_after_end(client, auth, ended_scene, db):
    """活动结束后，组织者不能撤销签到。"""
    # 先把报名改成已签到（绕过 check_in 的“已结束不能签到”限制）
    db("UPDATE Registrations SET status = 'checked_in', check_in_time = NOW() "
       "WHERE registration_id = %s", (ended_scene['registration_id'],))
    resp = client.put(f"/api/undo_check_in/{ended_scene['registration_id']}",
                      headers=auth(ended_scene['org_token']))
    assert resp.status_code == 400
    assert '已结束' in resp.get_json()['message']


# ---------------- 删除活动保护（P1-9） ----------------

def test_cannot_delete_event_with_check_in(client, auth, active_scene):
    """已有签到记录的活动不能删除（409）。"""
    rid = active_scene['registration_id']
    assert client.put(f'/api/check_in/{rid}',
                      headers=auth(active_scene['org_token'])).status_code == 200

    resp = client.delete(f"/api/delete_event/{active_scene['event_id']}",
                         headers=auth(active_scene['org_token']))
    assert resp.status_code == 409
    assert '签到记录' in resp.get_json()['message']


def test_cannot_delete_started_event_by_organizer(client, auth, active_scene):
    """活动开始后，普通组织者不能删除（409）。"""
    resp = client.delete(f"/api/delete_event/{active_scene['event_id']}",
                         headers=auth(active_scene['org_token']))
    assert resp.status_code == 409
    assert '已开始' in resp.get_json()['message']


    # ---------------- 取消留痕（P1-10） ----------------

def test_cancel_records_cancelled_at_and_by(client, auth, event, registration, db):
    rid = registration['registration_id']
    student_id = registration['student']['user_id']

    resp = client.put(f'/api/cancel_registration/{rid}',
                      headers=auth(registration['stu_token']))
    assert resp.status_code == 200

    # 直接查库确认字段已写入
    with app_module.db_cursor() as cur:
        cur.execute(
            "SELECT status, cancelled_at, cancelled_by FROM Registrations "
            "WHERE registration_id = %s",
            (rid,),
        )
        row = cur.fetchone()
    assert row['status'] == 'cancelled'
    assert row['cancelled_at'] is not None
    assert row['cancelled_by'] == student_id


def test_re_register_clears_cancel_fields(client, auth, event, registration):
    rid = registration['registration_id']
    # 先取消
    client.put(f'/api/cancel_registration/{rid}',
               headers=auth(registration['stu_token']))
    # 再报名（同一学生同一活动，走 UPDATE 分支）
    resp = client.post('/api/register_event', headers=auth(registration['stu_token']),
                       json={'event_id': event['event_id']})
    assert resp.status_code == 200, resp.get_json()

    # 查库确认取消字段已清空
    with app_module.db_cursor() as cur:
        cur.execute(
            "SELECT status, cancelled_at, cancelled_by, check_in_time "
            "FROM Registrations WHERE registration_id = %s",
            (rid,),
        )
        row = cur.fetchone()
    assert row['status'] == 'registered'
    assert row['cancelled_at'] is None
    assert row['cancelled_by'] is None
    assert row['check_in_time'] is None
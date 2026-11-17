"""报名、取消、签到、我的报名、评论。"""

import threading
import uuid


def _h(token):
    return {'Authorization': f'Bearer {token}'}


def _create_event(client, token, venue_id, window):
    start, end = window
    resp = client.post('/api/create_event', headers=_h(token), json={
        'title': f'分页测试_{uuid.uuid4().hex[:8]}',
        'description': '',
        'venue_id': venue_id,
        'start_time': start,
        'end_time': end,
        'capacity': 5,
    })
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()['data']['event_id']


OVERSOLD_ROUNDS = 8


def test_no_oversell(app, client, make_user, unique_event_window, db_fetch):
    """容量 1 的活动，两线程同时抢：只能一个成功，且失败原因必须是名额已满。

    用 threading.Barrier 保证两个请求真的同时发出（否则线程可能先后跑完，
    不加行锁的实现也能通过），并跑多轮降低偶发通过的概率。
    """
    _, org_token = make_user('organizer')
    _, tok_a = make_user('student')
    _, tok_b = make_user('student')

    venues = client.get('/api/venues', headers=_h(org_token)).get_json()['data']

    for round_no in range(OVERSOLD_ROUNDS):
        start, end = unique_event_window()
        resp = client.post('/api/create_event', headers=_h(org_token), json={
            'title': f'并发测试活动_{round_no}_{uuid.uuid4().hex[:8]}',
            'description': '容量 1',
            'venue_id': venues[0]['venue_id'],
            'start_time': start,
            'end_time': end,
            'capacity': 1,
        })
        assert resp.status_code == 200, resp.get_json()
        event_id = resp.get_json()['data']['event_id']

        barrier = threading.Barrier(2)
        results = []

        def attempt(token):
            # 线程之间不能共用 test_client
            with app.test_client() as c:
                barrier.wait()          # 两个请求卡在起跑线上
                r = c.post('/api/register_event', headers=_h(token),
                           json={'event_id': event_id})
                results.append((r.status_code, r.get_json().get('message', '')))

        threads = [threading.Thread(target=attempt, args=(tok,))
                   for tok in (tok_a, tok_b)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        codes = sorted(code for code, _ in results)
        assert codes == [200, 400], f'第 {round_no} 轮结果 {results}'

        loser = next(msg for code, msg in results if code == 400)
        assert '名额已满' in loser, f'失败原因不对：{loser}'

        # 库里必须只有一条有效报名（超卖的话这里会是 2）
        rows = db_fetch(
            "SELECT COUNT(*) AS cnt FROM registrations "
            "WHERE event_id = %s AND status <> 'cancelled'",
            (event_id,),
        )
        assert rows[0]['cnt'] == 1, f'第 {round_no} 轮超卖了：{rows[0]["cnt"]} 条报名'


def test_organizer_cannot_register_event(client, auth, event, make_user):
    _, org_token = make_user('organizer')
    resp = client.post('/api/register_event', headers=auth(org_token),
                       json={'event_id': event['event_id']})
    assert resp.status_code == 403
    assert '只有学生账号' in resp.get_json()['message']


def test_cancel_success(client, auth, event, registration):
    resp = client.put(f"/api/cancel_registration/{registration['registration_id']}",
                      headers=auth(registration['stu_token']))
    assert resp.status_code == 200
    assert resp.get_json()['code'] == 200


def test_cancel_twice_fails(client, auth, event, registration):
    rid = registration['registration_id']
    first = client.put(f'/api/cancel_registration/{rid}',
                       headers=auth(registration['stu_token']))
    assert first.status_code == 200

    second = client.put(f'/api/cancel_registration/{rid}',
                        headers=auth(registration['stu_token']))
    assert second.status_code == 400
    assert second.get_json()['code'] == 400


def test_cancel_by_other_student_forbidden(client, auth, event, registration, make_user):
    _, other_token = make_user('student')
    resp = client.put(f"/api/cancel_registration/{registration['registration_id']}",
                      headers=auth(other_token))
    assert resp.status_code == 403
    assert resp.get_json()['code'] == 403


def test_cannot_cancel_checked_in_registration(client, auth, active_scene):
    rid = active_scene['registration_id']
    check = client.put(f'/api/check_in/{rid}', headers=auth(active_scene['org_token']))
    assert check.status_code == 200

    resp = client.put(f'/api/cancel_registration/{rid}',
                      headers=auth(active_scene['stu_token']))
    assert resp.status_code == 400
    assert '已签到' in resp.get_json()['message']

    regs = client.get(f"/api/user_registrations/{active_scene['student']['user_id']}",
                      headers=auth(active_scene['stu_token'])).get_json()['data']
    row = next(r for r in regs if r['event_id'] == active_scene['event_id'])
    assert row['registration_status'] == 'checked_in'


def test_cannot_cancel_after_start(client, auth, active_scene):
    resp = client.put(f"/api/cancel_registration/{active_scene['registration_id']}",
                      headers=auth(active_scene['stu_token']))
    assert resp.status_code == 400
    assert '已开始' in resp.get_json()['message']


def test_cannot_remove_after_start(client, auth, active_scene):
    resp = client.delete(f"/api/remove_registration/{active_scene['registration_id']}",
                         headers=auth(active_scene['org_token']))
    assert resp.status_code == 400
    assert '已开始' in resp.get_json()['message']


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
    resp = client.put(f"/api/check_in/{registration['registration_id']}",
                      headers=auth(event['org_token']))
    assert resp.status_code == 400
    assert '还未开始' in resp.get_json()['message']


def test_check_in_after_end_fails(client, auth, ended_scene):
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


def test_my_registrations_pagination_meta(client, auth, make_user, unique_event_window):
    _, org_token = make_user('organizer')
    stu_user, stu_token = make_user('student')
    venues = client.get('/api/venues', headers=auth(org_token)).get_json()['data']

    event_ids = []
    for _ in range(3):
        eid = _create_event(client, org_token, venues[0]['venue_id'], unique_event_window())
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
    assert {r['registration_id'] for r in page1['data']}.isdisjoint(
        {r['registration_id'] for r in page2['data']})


def test_my_registrations_default_page(client, auth, event, registration):
    resp = client.get(
        f"/api/user_registrations/{registration['student']['user_id']}",
        headers=auth(registration['stu_token']),
    )
    data = resp.get_json()
    assert data['code'] == 200
    assert data['page'] == 1
    assert data['page_size'] == 20
    assert isinstance(data['data'], list)


def test_post_and_get_comment(client, auth, event, registration):
    resp = client.post('/api/comments', headers=auth(registration['stu_token']), json={
        'event_id': event['event_id'], 'content': '这个活动真不错！',
    })
    assert resp.status_code == 200
    assert resp.get_json()['code'] == 200

    comments = client.get(f"/api/comments/{event['event_id']}",
                          headers=auth(registration['stu_token'])).get_json()['data']
    assert any(c['content'] == '这个活动真不错！' for c in comments)


def test_post_comment_without_registration_fails(client, auth, event, make_user):
    _, stu_token = make_user('student')
    resp = client.post('/api/comments', headers=auth(stu_token), json={
        'event_id': event['event_id'], 'content': '我没报名，只想来乱说话',
    })
    assert resp.status_code == 403
    assert resp.get_json()['code'] == 403


def test_post_comment_empty_fails(client, auth, event, make_user):
    _, stu_token = make_user('student')
    resp = client.post('/api/comments', headers=auth(stu_token), json={
        'event_id': event['event_id'], 'content': '   ',
    })
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 400


def test_post_comment_too_long_fails(client, auth, event, make_user):
    _, stu_token = make_user('student')
    resp = client.post('/api/comments', headers=auth(stu_token), json={
        'event_id': event['event_id'], 'content': '长' * 501,
    })
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 400


def test_post_comment_nonexistent_event_fails(client, auth, make_user):
    _, stu_token = make_user('student')
    resp = client.post('/api/comments', headers=auth(stu_token), json={
        'event_id': 999999, 'content': '评论',
    })
    assert resp.status_code == 404
    assert resp.get_json()['code'] == 404


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
    assert {c['comment_id'] for c in page1['data']}.isdisjoint(
        {c['comment_id'] for c in page2['data']})

"""活动本身的接口：发布 / 编辑 / 关闭 / 删除 / 详情 / 分类 / 分页。"""

from datetime import datetime, timedelta

from helpers import post_event, event_payload, list_venues


def test_update_event_by_owner(client, auth, event, find_event, unique_event_window):
    start, end = unique_event_window()
    body = event_payload(1, start, end, capacity=20, title='改名后的活动', description='新的描述')
    resp = client.put(f"/api/update_event/{event['event_id']}",
                      headers=auth(event['org_token']), json=body)
    assert resp.status_code == 200, resp.get_json()

    updated = find_event(event['org_token'], event['event_id'])
    assert updated is not None
    assert updated['title'] == '改名后的活动'
    assert updated['capacity'] == 20


def test_update_event_by_other_organizer_forbidden(client, auth, event, make_user):
    _, other_token = make_user('organizer')
    body = event_payload(1, '2031-05-01T09:00', '2031-05-01T11:00', capacity=5,
                         title='恶意改名')
    resp = client.put(f"/api/update_event/{event['event_id']}",
                      headers=auth(other_token), json=body)
    assert resp.status_code == 403
    assert resp.get_json()['code'] == 403


def test_update_event_capacity_below_registrations_fails(client, auth, event, registration,
                                                         make_user):
    _, other_token = make_user('student')
    resp = client.post('/api/register_event', headers=auth(other_token),
                       json={'event_id': event['event_id']})
    assert resp.status_code == 200, resp.get_json()

    body = event_payload(1, '2031-05-01T09:00', '2031-05-01T11:00', capacity=1,
                         title='容量不足')
    resp = client.put(f"/api/update_event/{event['event_id']}",
                      headers=auth(event['org_token']), json=body)
    assert resp.status_code == 400
    assert '已报名人数' in resp.get_json()['message']


def test_update_event_end_before_start_fails(client, auth, event):
    body = event_payload(1, '2031-05-01T11:00', '2031-05-01T09:00', capacity=5,
                         title='时间颠倒')
    resp = client.put(f"/api/update_event/{event['event_id']}",
                      headers=auth(event['org_token']), json=body)
    assert resp.status_code == 400


def test_create_event_rejects_too_long_title(client, auth, event):
    body = event_payload(1, '2030-01-01T10:00', '2030-01-01T12:00', capacity=5,
                         title='T' * 300)
    resp = client.post('/api/create_event', headers=auth(event['org_token']), json=body)
    assert resp.status_code == 400
    assert '标题不能超过' in resp.get_json()['message']


def test_cannot_create_event_in_the_past(client, auth, event):
    body = event_payload(1, '2000-01-01T10:00', '2000-01-01T12:00', capacity=5,
                         title='过去的活动', description='时间已经过了')
    resp = client.post('/api/create_event', headers=auth(event['org_token']), json=body)
    assert resp.status_code == 400
    assert '开始时间必须晚于当前时间' in resp.get_json()['message']


def test_create_event_rejects_invalid_time_format(client, auth, event):
    venues = list_venues(client, event['org_token'])
    body = event_payload(venues[0]['venue_id'], 'abc', '2030-06-01T12:00', capacity=5,
                         title='非法时间')
    resp = client.post('/api/create_event', headers=auth(event['org_token']), json=body)
    assert resp.status_code == 400
    assert '格式不正确' in resp.get_json()['message']


def test_remove_registration_by_organizer(client, auth, event, registration):
    resp = client.delete(f"/api/remove_registration/{registration['registration_id']}",
                         headers=auth(event['org_token']))
    assert resp.status_code == 200
    assert resp.get_json()['code'] == 200

    regs = client.get(f"/api/user_registrations/{registration['student']['user_id']}",
                      headers=auth(registration['stu_token'])).get_json()['data']
    row = next(r for r in regs if r['event_id'] == event['event_id'])
    assert row['registration_status'] == 'cancelled'


def test_remove_registration_by_other_organizer_forbidden(client, auth, event, registration,
                                                          make_user):
    _, other_token = make_user('organizer')
    resp = client.delete(f"/api/remove_registration/{registration['registration_id']}",
                         headers=auth(other_token))
    assert resp.status_code == 403
    assert resp.get_json()['code'] == 403


def test_events_pagination_meta(client, auth, event, unique_event_window):
    # 先造够 3 个活动，保证至少 2 页，分页断言才有意义
    venue_id = list_venues(client, event['org_token'])[0]['venue_id']
    for _ in range(3):
        start, end = unique_event_window()
        body = event_payload(venue_id, start, end, capacity=5, title='分页活动')
        created = post_event(client, event['org_token'], body)

    page1 = client.get('/api/events?page=1&page_size=2',
                       headers=auth(event['org_token'])).get_json()
    assert page1['code'] == 200
    assert isinstance(page1['data'], list)
    assert len(page1['data']) == 2          # 库里至少 4 个活动，第一页必须满
    assert len({e['event_id'] for e in page1['data']}) == 2   # 不能有重复行
    assert page1['page'] == 1
    assert page1['page_size'] == 2
    assert page1['total'] >= 4
    assert page1['pages'] == (page1['total'] + 1) // 2

    page2 = client.get('/api/events?page=2&page_size=2',
                       headers=auth(event['org_token'])).get_json()
    assert {e['event_id'] for e in page1['data']}.isdisjoint(
        {e['event_id'] for e in page2['data']})


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
    # 必须精确等于 1：写成 >= 1 的话，接口把“活动总报名数”当成“我是否报名”也能过
    assert data['is_registered'] == 1
    assert data['registered_count'] == 1
    assert data['remaining'] == data['capacity'] - 1


def test_close_event_success(client, auth, event, find_event):
    resp = client.put(f"/api/close_event/{event['event_id']}",
                      headers=auth(event['org_token']), json={'action': 'close'})
    assert resp.status_code == 200
    assert resp.get_json()['code'] == 200

    row = find_event(event['org_token'], event['event_id'])
    assert row is not None
    assert row['status'] == 'closed'


def test_reopen_closed_event_success(client, auth, event, find_event):
    eid = event['event_id']
    client.put(f'/api/close_event/{eid}', headers=auth(event['org_token']),
               json={'action': 'close'})
    resp = client.put(f'/api/close_event/{eid}', headers=auth(event['org_token']),
                      json={'action': 'open'})
    assert resp.status_code == 200
    # 状态要真的写回去了，只断言 200 的话接口空转也能过
    row = find_event(event['org_token'], eid)
    assert row is not None
    assert row['status'] == 'open'


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


def test_list_categories(client, auth, make_user):
    _, token = make_user('student')
    resp = client.get('/api/categories', headers=auth(token))
    assert resp.status_code == 200
    data = resp.get_json()['data']
    assert isinstance(data, list)
    assert len(data) >= 4
    assert all('category_id' in c and 'category_name' in c for c in data)


def test_create_event_with_categories(client, auth, event, find_event, unique_event_window):
    org_token = event['org_token']
    cats = client.get('/api/categories', headers=auth(org_token)).get_json()['data']
    venues = list_venues(client, org_token)
    cid1, cid2 = cats[0]['category_id'], cats[1]['category_id']

    start, end = unique_event_window()
    body = event_payload(venues[0]['venue_id'], start, end, capacity=5, title='带分类的活动',
                         description='测试', category_ids=[cid1, cid2])
    eid = post_event(client, org_token, body)

    found = find_event(org_token, eid)
    assert found is not None
    assert set(c['category_id'] for c in found['categories']) == {cid1, cid2}


def test_create_event_invalid_category_fails(client, auth, event):
    org_token = event['org_token']
    venues = list_venues(client, org_token)
    body = event_payload(venues[1]['venue_id'], '2030-02-01T10:00', '2030-02-01T12:00',
                         capacity=5, title='非法分类', category_ids=[999999])
    resp = client.post('/api/create_event', headers=auth(org_token), json=body)
    assert resp.status_code == 400
    assert '分类不存在' in resp.get_json()['message']


def test_filter_events_by_category(client, auth, event, unique_event_window):
    org_token = event['org_token']
    cats = client.get('/api/categories', headers=auth(org_token)).get_json()['data']
    venues = list_venues(client, org_token)
    cid = cats[0]['category_id']

    start, end = unique_event_window()
    body = event_payload(venues[2]['venue_id'], start, end, capacity=5, title='可过滤活动',
                         category_ids=[cid])
    eid = post_event(client, org_token, body)

    result = client.get(f'/api/events?category_id={cid}&page_size=100',
                        headers=auth(org_token)).get_json()
    assert result['code'] == 200
    assert any(e['event_id'] == eid for e in result['data'])
    assert all(cid in [c['category_id'] for c in e['categories']]
               for e in result['data'])


def test_update_event_categories_replace(client, auth, event, find_event, unique_event_window):
    org_token = event['org_token']
    cats = client.get('/api/categories', headers=auth(org_token)).get_json()['data']
    venues = list_venues(client, org_token)
    cid1, cid2 = cats[0]['category_id'], cats[1]['category_id']
    eid = event['event_id']
    start, end = unique_event_window()

    body = event_payload(venues[0]['venue_id'], start, end, capacity=5, title='分类更新',
                         category_ids=[cid1])
    client.put(f'/api/update_event/{eid}', headers=auth(org_token), json=body)
    found = find_event(org_token, eid)
    assert [c['category_id'] for c in found['categories']] == [cid1]

    body = event_payload(venues[0]['venue_id'], start, end, capacity=5, title='分类更新2',
                         category_ids=[cid2])
    client.put(f'/api/update_event/{eid}', headers=auth(org_token), json=body)
    found = find_event(org_token, eid)
    assert [c['category_id'] for c in found['categories']] == [cid2]


def test_update_event_without_categories_keeps_existing(client, auth, event, find_event,
                                                        unique_event_window):
    org_token = event['org_token']
    cats = client.get('/api/categories', headers=auth(org_token)).get_json()['data']
    venues = list_venues(client, org_token)
    cid = cats[0]['category_id']
    eid = event['event_id']
    start, end = unique_event_window()

    body = event_payload(venues[0]['venue_id'], start, end, capacity=5, title='保留分类',
                         category_ids=[cid])
    resp = client.put(f'/api/update_event/{eid}', headers=auth(org_token), json=body)
    assert resp.status_code == 200, resp.get_json()

    # 不带 category_ids 再更新一次，原来的分类应该还在
    body = event_payload(venues[0]['venue_id'], start, end, capacity=5, title='保留分类2')
    resp = client.put(f'/api/update_event/{eid}', headers=auth(org_token), json=body)
    assert resp.status_code == 200, resp.get_json()

    found = find_event(org_token, eid)
    assert [c['category_id'] for c in found['categories']] == [cid]


def test_venue_time_conflict_rejected(client, auth, make_user, unique_event_window):
    """同场地时间段有交集要拒绝，紧邻不重叠要放行。"""
    _, org_token = make_user('organizer')
    venue_id = list_venues(client, org_token)[0]['venue_id']
    start, end = unique_event_window()

    body = event_payload(venue_id, start, end, capacity=5, title='场地占用一')
    first = post_event(client, org_token, body)

    # 整体往后挪 30 分钟：和已存在的那段有交集
    base = datetime.fromisoformat(start)
    body = event_payload(venue_id, (base + timedelta(minutes=30)).isoformat(),
                         (datetime.fromisoformat(end) + timedelta(minutes=30)).isoformat(),
                         capacity=5, title='场地占用二')
    overlap = client.post('/api/create_event', headers=auth(org_token), json=body)
    assert overlap.status_code == 400, overlap.get_json()
    assert '已被占用' in overlap.get_json()['message']

    # 从上一个活动结束时间开始：首尾相接，不算重叠
    body = event_payload(venue_id, end,
                         (datetime.fromisoformat(end) + timedelta(hours=1)).isoformat(),
                         capacity=5, title='场地占用三')
    adjacent = post_event(client, org_token, body)

    # 同一时间段换个场地就没事
    other_venue = list_venues(client, org_token)[1]['venue_id']
    body = event_payload(other_venue, start, end, capacity=5, title='换场地')
    elsewhere = post_event(client, org_token, body)


def test_edit_event_after_venue_disabled(client, auth, event, db, find_event):
    """场地被停用后，放在该场地的活动仍要能继续编辑（否则停用场地等于锁死活动）。"""
    detail = client.get(f"/api/events/{event['event_id']}",
                        headers=auth(event['org_token'])).get_json()['data']
    venue_id = detail['venue_id']

    db("UPDATE venues SET available_status = 0 WHERE venue_id = %s", (venue_id,))
    try:
        body = event_payload(venue_id, detail['start_time'].replace(' ', 'T'),
                             detail['end_time'].replace(' ', 'T'),
                             capacity=detail['capacity'], title='场地停用后仍可编辑')
        resp = client.put(f"/api/update_event/{event['event_id']}",
                          headers=auth(event['org_token']), json=body)
        assert resp.status_code == 200, resp.get_json()

        row = find_event(event['org_token'], event['event_id'])
        assert row['title'] == '场地停用后仍可编辑'
    finally:
        db("UPDATE venues SET available_status = 1 WHERE venue_id = %s", (venue_id,))


def test_student_cannot_create_event(client, auth, make_user):
    _, token = make_user('student')
    body = event_payload(1, '2035-01-01T10:00', '2035-01-01T12:00', capacity=5,
                         title='学生发的活动')
    resp = client.post('/api/create_event', headers=auth(token), json=body)
    assert resp.status_code == 403
    assert resp.get_json()['code'] == 403


def test_delete_event_removes_children(client, auth, make_user, unique_event_window, db_fetch):
    """删除活动的成功路径：关联的评论 / 分类 / 报名都要一起清掉，不能留孤儿数据。"""
    _, org_token = make_user('organizer')
    _, stu_token = make_user('student')
    venue = list_venues(client, org_token)[0]
    category = client.get('/api/categories',
                          headers=auth(org_token)).get_json()['data'][0]
    start, end = unique_event_window()

    body = event_payload(venue['venue_id'], start, end, capacity=5, title='待删活动',
                         description='删除级联测试', category_ids=[category['category_id']])
    eid = post_event(client, org_token, body)

    assert client.post('/api/register_event', headers=auth(stu_token),
                       json={'event_id': eid}).status_code == 200
    assert client.post('/api/comments', headers=auth(stu_token),
                       json={'event_id': eid, 'content': '占位评论'}).status_code == 200

    def child_counts():
        return (
            db_fetch('SELECT COUNT(*) AS c FROM comments WHERE event_id = %s', (eid,))[0]['c'],
            db_fetch('SELECT COUNT(*) AS c FROM event_categories WHERE event_id = %s', (eid,))[0]['c'],
            db_fetch('SELECT COUNT(*) AS c FROM registrations WHERE event_id = %s', (eid,))[0]['c'],
        )

    assert child_counts() == (1, 1, 1)

    deleted = client.delete(f'/api/delete_event/{eid}', headers=auth(org_token))
    assert deleted.status_code == 200, deleted.get_json()

    assert child_counts() == (0, 0, 0)
    assert client.get(f'/api/events/{eid}', headers=auth(org_token)).status_code == 404
    # 再删一次就是 404，不能返回 200
    assert client.delete(f'/api/delete_event/{eid}',
                         headers=auth(org_token)).status_code == 404

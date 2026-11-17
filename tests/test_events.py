"""活动本身的接口：发布 / 编辑 / 关闭 / 删除 / 详情 / 分类 / 分页。"""


def _find(client, token, event_id, page_size=100):
    page = 1
    while True:
        result = client.get(
            f'/api/events?page={page}&page_size={page_size}',
            headers={'Authorization': f'Bearer {token}'},
        ).get_json()
        for e in result['data']:
            if e['event_id'] == event_id:
                return e
        if page >= result['pages']:
            return None
        page += 1


def _venues(client, token):
    return client.get('/api/venues',
                      headers={'Authorization': f'Bearer {token}'}).get_json()['data']


def test_update_event_by_owner(client, auth, event, find_event, unique_event_window):
    start, end = unique_event_window()
    resp = client.put(f"/api/update_event/{event['event_id']}",
                      headers=auth(event['org_token']), json={
                          'title': '改名后的活动',
                          'description': '新的描述',
                          'venue_id': 1,
                          'start_time': start,
                          'end_time': end,
                          'capacity': 20,
                      })
    assert resp.status_code == 200, resp.get_json()

    updated = find_event(event['org_token'], event['event_id'])
    assert updated is not None
    assert updated['title'] == '改名后的活动'
    assert updated['capacity'] == 20


def test_update_event_by_other_organizer_forbidden(client, auth, event, make_user):
    _, other_token = make_user('organizer')
    resp = client.put(f"/api/update_event/{event['event_id']}",
                      headers=auth(other_token), json={
                          'title': '恶意改名',
                          'description': '',
                          'venue_id': 1,
                          'start_time': '2031-05-01T09:00',
                          'end_time': '2031-05-01T11:00',
                          'capacity': 5,
                      })
    assert resp.status_code == 403
    assert resp.get_json()['code'] == 403


def test_update_event_capacity_below_registrations_fails(client, auth, event, registration,
                                                         make_user):
    _, other_token = make_user('student')
    resp = client.post('/api/register_event', headers=auth(other_token),
                       json={'event_id': event['event_id']})
    assert resp.status_code == 200, resp.get_json()

    resp = client.put(f"/api/update_event/{event['event_id']}",
                      headers=auth(event['org_token']), json={
                          'title': '容量不足',
                          'description': '',
                          'venue_id': 1,
                          'start_time': '2031-05-01T09:00',
                          'end_time': '2031-05-01T11:00',
                          'capacity': 1,
                      })
    assert resp.status_code == 400
    assert '已报名人数' in resp.get_json()['message']


def test_update_event_end_before_start_fails(client, auth, event):
    resp = client.put(f"/api/update_event/{event['event_id']}",
                      headers=auth(event['org_token']), json={
                          'title': '时间颠倒',
                          'description': '',
                          'venue_id': 1,
                          'start_time': '2031-05-01T11:00',
                          'end_time': '2031-05-01T09:00',
                          'capacity': 5,
                      })
    assert resp.status_code == 400


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


def test_create_event_rejects_invalid_time_format(client, auth, event):
    venues = _venues(client, event['org_token'])
    resp = client.post('/api/create_event', headers=auth(event['org_token']), json={
        'title': '非法时间', 'description': '',
        'venue_id': venues[0]['venue_id'],
        'start_time': 'abc', 'end_time': '2030-06-01T12:00',
        'capacity': 5,
    })
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


def test_events_pagination_meta(client, auth, event):
    result = client.get('/api/events?page=1&page_size=2',
                        headers=auth(event['org_token'])).get_json()
    assert result['code'] == 200
    assert isinstance(result['data'], list)
    assert len(result['data']) <= 2
    assert result['page'] == 1
    assert result['page_size'] == 2
    assert result['total'] >= 1
    assert result['pages'] == (result['total'] + 1) // 2


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


def test_close_event_success(client, auth, event, find_event):
    resp = client.put(f"/api/close_event/{event['event_id']}",
                      headers=auth(event['org_token']), json={'action': 'close'})
    assert resp.status_code == 200
    assert resp.get_json()['code'] == 200

    row = find_event(event['org_token'], event['event_id'])
    assert row is not None
    assert row['status'] == 'closed'


def test_reopen_closed_event_success(client, auth, event):
    eid = event['event_id']
    client.put(f'/api/close_event/{eid}', headers=auth(event['org_token']),
               json={'action': 'close'})
    resp = client.put(f'/api/close_event/{eid}', headers=auth(event['org_token']),
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
    venues = _venues(client, org_token)
    cid1, cid2 = cats[0]['category_id'], cats[1]['category_id']

    start, end = unique_event_window()
    resp = client.post('/api/create_event', headers=auth(org_token), json={
        'title': '带分类的活动', 'description': '测试',
        'venue_id': venues[0]['venue_id'],
        'start_time': start, 'end_time': end,
        'capacity': 5, 'category_ids': [cid1, cid2],
    })
    assert resp.status_code == 200, resp.get_json()
    eid = resp.get_json()['data']['event_id']

    found = find_event(org_token, eid)
    assert found is not None
    assert set(c['category_id'] for c in found['categories']) == {cid1, cid2}


def test_create_event_invalid_category_fails(client, auth, event):
    org_token = event['org_token']
    venues = _venues(client, org_token)
    resp = client.post('/api/create_event', headers=auth(org_token), json={
        'title': '非法分类', 'description': '',
        'venue_id': venues[1]['venue_id'],
        'start_time': '2030-02-01T10:00', 'end_time': '2030-02-01T12:00',
        'capacity': 5, 'category_ids': [999999],
    })
    assert resp.status_code == 400
    assert '分类不存在' in resp.get_json()['message']


def test_filter_events_by_category(client, auth, event, unique_event_window):
    org_token = event['org_token']
    cats = client.get('/api/categories', headers=auth(org_token)).get_json()['data']
    venues = _venues(client, org_token)
    cid = cats[0]['category_id']

    start, end = unique_event_window()
    resp = client.post('/api/create_event', headers=auth(org_token), json={
        'title': '可过滤活动', 'description': '',
        'venue_id': venues[2]['venue_id'],
        'start_time': start, 'end_time': end,
        'capacity': 5, 'category_ids': [cid],
    })
    assert resp.status_code == 200, resp.get_json()
    eid = resp.get_json()['data']['event_id']

    result = client.get(f'/api/events?category_id={cid}&page_size=100',
                        headers=auth(org_token)).get_json()
    assert result['code'] == 200
    assert any(e['event_id'] == eid for e in result['data'])
    assert all(cid in [c['category_id'] for c in e['categories']]
               for e in result['data'])


def test_update_event_categories_replace(client, auth, event, find_event, unique_event_window):
    org_token = event['org_token']
    cats = client.get('/api/categories', headers=auth(org_token)).get_json()['data']
    venues = _venues(client, org_token)
    cid1, cid2 = cats[0]['category_id'], cats[1]['category_id']
    eid = event['event_id']
    start, end = unique_event_window()

    client.put(f'/api/update_event/{eid}', headers=auth(org_token), json={
        'title': '分类更新', 'description': '', 'venue_id': venues[0]['venue_id'],
        'start_time': start, 'end_time': end,
        'capacity': 5, 'category_ids': [cid1],
    })
    found = find_event(org_token, eid)
    assert [c['category_id'] for c in found['categories']] == [cid1]

    client.put(f'/api/update_event/{eid}', headers=auth(org_token), json={
        'title': '分类更新2', 'description': '', 'venue_id': venues[0]['venue_id'],
        'start_time': start, 'end_time': end,
        'capacity': 5, 'category_ids': [cid2],
    })
    found = find_event(org_token, eid)
    assert [c['category_id'] for c in found['categories']] == [cid2]


def test_update_event_without_categories_keeps_existing(client, auth, event, find_event,
                                                        unique_event_window):
    org_token = event['org_token']
    cats = client.get('/api/categories', headers=auth(org_token)).get_json()['data']
    venues = _venues(client, org_token)
    cid = cats[0]['category_id']
    eid = event['event_id']
    start, end = unique_event_window()

    resp = client.put(f'/api/update_event/{eid}', headers=auth(org_token), json={
        'title': '保留分类', 'description': '', 'venue_id': venues[0]['venue_id'],
        'start_time': start, 'end_time': end,
        'capacity': 5, 'category_ids': [cid],
    })
    assert resp.status_code == 200, resp.get_json()

    # 不带 category_ids 再更新一次，原来的分类应该还在
    resp = client.put(f'/api/update_event/{eid}', headers=auth(org_token), json={
        'title': '保留分类2', 'description': '', 'venue_id': venues[0]['venue_id'],
        'start_time': start, 'end_time': end,
        'capacity': 5,
    })
    assert resp.status_code == 200, resp.get_json()

    found = find_event(org_token, eid)
    assert [c['category_id'] for c in found['categories']] == [cid]

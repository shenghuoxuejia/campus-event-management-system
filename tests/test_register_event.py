"""报名接口测试，含并发防超卖。"""
import threading
import uuid


def _headers(token):
    return {'Authorization': f'Bearer {token}'}


def test_no_oversell(app, client, make_user, unique_event_window):
    _, org_token = make_user('organizer')
    _, tok_a = make_user('student')
    _, tok_b = make_user('student')

    venues = client.get('/api/venues', headers=_headers(org_token))
    assert venues.status_code == 200
    venue_id = venues.get_json()['data'][0]['venue_id']

    # 标题使用唯一值，避免与其它活动混淆
    title = f'并发测试活动_{uuid.uuid4().hex[:8]}'
    # 时间窗由 conftest 单调分配，互不重叠，不会撞上「场地时间冲突」校验
    start, end = unique_event_window()
    resp = client.post('/api/create_event', headers=_headers(org_token), json={
        'title': title,
        'description': '容量 1',
        'venue_id': venue_id,
        'start_time': start,
        'end_time': end,
        'capacity': 1,
    })
    assert resp.status_code == 200, resp.get_json()
    event_id = resp.get_json()['data']['event_id']

    results = []

    def attempt(token):
        # 每个线程独立 test_client，避免共享状态
        with app.test_client() as c:
            r = c.post('/api/register_event', headers=_headers(token),
                       json={'event_id': event_id})
            results.append(r.status_code)

    t1 = threading.Thread(target=attempt, args=(tok_a,))
    t2 = threading.Thread(target=attempt, args=(tok_b,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # 容量为 1：两个并发报名只能有一个成功，另一个应「名额已满」
    assert sorted(results) == [200, 400]

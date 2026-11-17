"""测试用例共用的无状态小工具。

放在独立模块而不是 conftest，是因为不少地方要在普通函数里调用
（线程体、夹具内部的闭包），那些位置拿不到 pytest fixture。
这里的函数只依赖显式传进来的 client / token / db。
"""

import uuid


def auth_header(token):
    """Bearer 鉴权头。"""
    return {'Authorization': f'Bearer {token}'}


def list_venues(client, token):
    return client.get('/api/venues', headers=auth_header(token)).get_json()['data']


def venue_with_capacity(client, token, capacity):
    """挑一个容量够大的场地。"""
    return next(v for v in list_venues(client, token) if v['capacity'] >= capacity)


def event_payload(venue_id, start, end, capacity=10, title=None, **extra):
    """创建/编辑活动的请求体，extra 用来追加 categories 之类可选字段。"""
    payload = {
        'title': title or f'测试活动_{uuid.uuid4().hex[:8]}',
        'description': '',
        'venue_id': venue_id,
        'start_time': start,
        'end_time': end,
        'capacity': capacity,
    }
    payload.update(extra)
    return payload


def post_event(client, token, body):
    """发一个创建活动请求，断言成功并返回 event_id。"""
    resp = client.post('/api/create_event', headers=auth_header(token), json=body)
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()['data']['event_id']


def create_event(client, token, venue_id, window, capacity=10, title=None, **extra):
    """建一个活动并返回 event_id，建失败直接让用例挂掉。

    extra 用来追加 description / category_ids 之类可选字段。
    """
    start, end = window
    return post_event(client, token,
                      event_payload(venue_id, start, end, capacity, title, **extra))


def event_detail(client, token, event_id):
    return client.get(f'/api/events/{event_id}',
                      headers=auth_header(token)).get_json()['data']


def find_event_in_list(client, token, event_id, page_size=100):
    """活动列表是分页的，目标活动不一定在第一页，得翻。找不到返回 None。"""
    page = 1
    while True:
        result = client.get(
            f'/api/events?page={page}&page_size={page_size}',
            headers=auth_header(token),
        ).get_json()
        for e in result['data']:
            if e['event_id'] == event_id:
                return e
        if page >= result['pages']:
            return None
        page += 1


def promote_to_admin(db, user_id):
    """注册接口不让自助申请 admin，只能在库里提。"""
    db("UPDATE users SET role = 'admin' WHERE user_id = %s", (user_id,))

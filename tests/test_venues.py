"""场地管理接口测试：只有管理员能增删改，停用的场地不能用于发布活动。"""
import uuid

import pytest


@pytest.fixture()
def admin_headers(client, auth, make_user, db):
    """注册一个普通账号再在库里提成管理员（注册接口不允许自助申请 admin）。"""
    user, token = make_user('student')
    db("UPDATE users SET role = 'admin' WHERE user_id = %s", (user['user_id'],))
    return auth(token)


@pytest.fixture()
def new_venue(client, admin_headers, db):
    """建一个临时场地，用例结束后连活动一起删掉（测试库不清 venues 表）。"""
    created = []

    def _make(capacity=50, location='测试区'):
        name = f'测试场地_{uuid.uuid4().hex[:8]}'
        resp = client.post('/api/venues', headers=admin_headers, json={
            'venue_name': name, 'location': location, 'capacity': capacity,
        })
        assert resp.status_code == 200, resp.get_json()
        venue_id = resp.get_json()['venue_id']
        created.append(venue_id)
        return {'venue_id': venue_id, 'venue_name': name, 'capacity': capacity}

    yield _make

    for venue_id in created:
        db("DELETE FROM events WHERE venue_id = %s", (venue_id,))
        db("DELETE FROM venues WHERE venue_id = %s", (venue_id,))


def test_only_admin_can_manage_venues(client, auth, make_user, new_venue, event):
    """学生和组织者调管理接口都应该 403。"""
    _, stu_token = make_user('student')
    venue = new_venue()

    assert client.post('/api/venues', headers=auth(stu_token), json={
        'venue_name': '越权场地', 'capacity': 10,
    }).status_code == 403
    assert client.put(f"/api/venues/{venue['venue_id']}", headers=auth(stu_token), json={
        'venue_name': venue['venue_name'], 'capacity': 10,
    }).status_code == 403
    assert client.delete(
        f"/api/venues/{venue['venue_id']}", headers=auth(stu_token)
    ).status_code == 403
    assert client.get('/api/admin/venues', headers=auth(stu_token)).status_code == 403

    org_token = event['org_token']
    assert client.post('/api/venues', headers=auth(org_token), json={
        'venue_name': '越权场地', 'capacity': 10,
    }).status_code == 403


def test_create_venue(client, admin_headers, new_venue):
    """新增的场地：管理员列表能看见，发布下拉里也能选到。"""
    venue = new_venue(capacity=88)

    admin_list = client.get('/api/admin/venues', headers=admin_headers).get_json()['data']
    mine = [v for v in admin_list if v['venue_id'] == venue['venue_id']][0]
    assert mine['capacity'] == 88
    assert mine['available_status'] == 1
    assert mine['event_count'] == 0

    public_list = client.get('/api/venues', headers=admin_headers).get_json()['data']
    assert venue['venue_id'] in [v['venue_id'] for v in public_list]


def test_duplicate_venue_name(client, admin_headers, new_venue):
    """场地名唯一，重名返回 409。"""
    venue = new_venue()
    resp = client.post('/api/venues', headers=admin_headers, json={
        'venue_name': venue['venue_name'], 'location': '别处', 'capacity': 20,
    })
    assert resp.status_code == 409
    assert '已存在' in resp.get_json()['message']


@pytest.mark.parametrize('payload,expected', [
    ({'venue_name': '  ', 'capacity': 10}, '请填写场地名称'),
    ({'venue_name': '没有容量场地'}, '场地容量必须是整数'),
    ({'venue_name': '零容量场地', 'capacity': 0}, '场地容量必须大于 0'),
    ({'venue_name': '状态非法场地', 'capacity': 10, 'available_status': 3}, '场地状态'),
    ({'venue_name': 'x' * 101, 'capacity': 10}, '不能超过 100 个字符'),
])
def test_create_venue_validation(client, admin_headers, payload, expected):
    resp = client.post('/api/venues', headers=admin_headers, json=payload)
    assert resp.status_code == 400
    assert expected in resp.get_json()['message']


def test_update_venue(client, admin_headers, new_venue):
    """改名、改容量都生效。"""
    venue = new_venue(capacity=30)
    new_name = f'改过的场地_{uuid.uuid4().hex[:6]}'
    resp = client.put(f"/api/venues/{venue['venue_id']}", headers=admin_headers, json={
        'venue_name': new_name, 'location': '新位置', 'capacity': 60,
    })
    assert resp.status_code == 200

    admin_list = client.get('/api/admin/venues', headers=admin_headers).get_json()['data']
    mine = [v for v in admin_list if v['venue_id'] == venue['venue_id']][0]
    assert mine['venue_name'] == new_name
    assert mine['location'] == '新位置'
    assert mine['capacity'] == 60


def test_update_missing_venue_returns_404(client, admin_headers):
    resp = client.put('/api/venues/999999', headers=admin_headers,
                      json={'venue_name': '不存在的场地', 'capacity': 10})
    assert resp.status_code == 404


def test_capacity_cannot_shrink_below_existing_event(client, admin_headers, new_venue,
                                                     make_user, unique_event_window):
    """已有 30 人活动时，场地容量不能改到小于 30。"""
    venue = new_venue(capacity=100)
    _, org_token = make_user('organizer')
    start, end = unique_event_window()
    create = client.post('/api/create_event',
                         headers={'Authorization': f'Bearer {org_token}'}, json={
                             'title': '容量校验用活动',
                             'venue_id': venue['venue_id'],
                             'start_time': start,
                             'end_time': end,
                             'capacity': 30,
                         })
    assert create.status_code == 200, create.get_json()

    resp = client.put(f"/api/venues/{venue['venue_id']}", headers=admin_headers, json={
        'venue_name': venue['venue_name'], 'capacity': 10,
    })
    assert resp.status_code == 400
    assert '不能小于 30' in resp.get_json()['message']


def test_disable_venue_hides_it_from_event_form(client, admin_headers, new_venue,
                                                make_user, unique_event_window):
    """停用后：发布下拉里没有它，用它发布活动会被拒绝。"""
    venue = new_venue()
    resp = client.put(f"/api/venues/{venue['venue_id']}", headers=admin_headers, json={
        'venue_name': venue['venue_name'],
        'location': '测试区',
        'capacity': venue['capacity'],
        'available_status': 0,
    })
    assert resp.status_code == 200

    public_list = client.get('/api/venues', headers=admin_headers).get_json()['data']
    assert venue['venue_id'] not in [v['venue_id'] for v in public_list]

    admin_list = client.get('/api/admin/venues', headers=admin_headers).get_json()['data']
    mine = [v for v in admin_list if v['venue_id'] == venue['venue_id']][0]
    assert mine['available_status'] == 0

    _, org_token = make_user('organizer')
    start, end = unique_event_window()
    create = client.post('/api/create_event', headers={'Authorization': f'Bearer {org_token}'},
                         json={
                             'title': '停用场地发布',
                             'venue_id': venue['venue_id'],
                             'start_time': start,
                             'end_time': end,
                             'capacity': 10,
                         })
    assert create.status_code == 400
    assert '不存在或已停用' in create.get_json()['message']


def test_delete_venue_in_use_returns_409(client, admin_headers, new_venue, make_user,
                                        unique_event_window):
    """还有活动在用的场地删不掉，提示改成停用。"""
    venue = new_venue()
    _, org_token = make_user('organizer')
    start, end = unique_event_window()
    create = client.post('/api/create_event', headers={'Authorization': f'Bearer {org_token}'},
                         json={
                             'title': '占用场地的活动',
                             'venue_id': venue['venue_id'],
                             'start_time': start,
                             'end_time': end,
                             'capacity': 10,
                         })
    assert create.status_code == 200, create.get_json()

    resp = client.delete(f"/api/venues/{venue['venue_id']}", headers=admin_headers)
    assert resp.status_code == 409
    assert '停用' in resp.get_json()['message']


def test_delete_venue(client, admin_headers, new_venue):
    """没有活动引用的场地可以删除，删完再删返回 404。"""
    venue = new_venue()
    assert client.delete(
        f"/api/venues/{venue['venue_id']}", headers=admin_headers
    ).status_code == 200

    public_list = client.get('/api/venues', headers=admin_headers).get_json()['data']
    assert venue['venue_id'] not in [v['venue_id'] for v in public_list]

    again = client.delete(f"/api/venues/{venue['venue_id']}", headers=admin_headers)
    assert again.status_code == 404

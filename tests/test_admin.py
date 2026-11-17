"""管理员相关的接口：用户角色、场地管理。"""

import uuid

import pytest


@pytest.fixture()
def admin(client, auth, make_user, db):
    # 注册接口不让自助申请 admin，只能在库里提
    user, token = make_user('student')
    db("UPDATE users SET role = 'admin' WHERE user_id = %s", (user['user_id'],))
    return user, auth(token)


@pytest.fixture()
def new_venue(client, admin, db):
    created = []

    def _make(capacity=50, location='测试区'):
        name = f'测试场地_{uuid.uuid4().hex[:8]}'
        resp = client.post('/api/venues', headers=admin[1], json={
            'venue_name': name, 'location': location, 'capacity': capacity,
        })
        assert resp.status_code == 200, resp.get_json()
        venue_id = resp.get_json()['venue_id']
        created.append(venue_id)
        return {'venue_id': venue_id, 'venue_name': name, 'capacity': capacity}

    yield _make

    # 测试库不清理 venues，自己建的自己删
    for venue_id in created:
        db("DELETE FROM events WHERE venue_id = %s", (venue_id,))
        db("DELETE FROM venues WHERE venue_id = %s", (venue_id,))


def test_only_admin_can_change_roles(client, admin, make_user, auth):
    _, org_token = make_user('organizer')
    _, stu_token = make_user('student')
    target = make_user('organizer')[0]

    for token in (org_token, stu_token):
        resp = client.put(f"/api/admin/users/{target['user_id']}/role",
                          headers=auth(token), json={'role': 'admin'})
        assert resp.status_code == 403


def test_promote_organizer_to_admin(client, admin, make_user, auth, db_fetch):
    org_user, org_token = make_user('organizer')
    org_auth = auth(org_token)

    assert client.get('/api/admin/users', headers=org_auth).status_code == 403

    resp = client.put(f"/api/admin/users/{org_user['user_id']}/role",
                      headers=admin[1], json={'role': 'admin'})
    assert resp.status_code == 200
    assert '管理员' in resp.get_json()['message']

    # 角色每次请求都从库里读，所以旧令牌立刻生效
    assert client.get('/api/admin/users', headers=org_auth).status_code == 200
    assert client.get('/api/admin/venues', headers=org_auth).status_code == 200

    rows = db_fetch("SELECT role FROM users WHERE user_id = %s", (org_user['user_id'],))
    assert rows[0]['role'] == 'admin'


def test_demote_admin_to_organizer(client, admin, make_user, auth):
    other_user, other_token = make_user('organizer')
    other_auth = auth(other_token)
    client.put(f"/api/admin/users/{other_user['user_id']}/role",
               headers=admin[1], json={'role': 'admin'})
    assert client.get('/api/admin/users', headers=other_auth).status_code == 200

    resp = client.put(f"/api/admin/users/{other_user['user_id']}/role",
                      headers=admin[1], json={'role': 'organizer'})
    assert resp.status_code == 200
    assert '组织者' in resp.get_json()['message']

    assert client.get('/api/admin/users', headers=other_auth).status_code == 403
    assert client.get('/api/admin/venues', headers=other_auth).status_code == 403
    # 只是没了管理权限，发布活动照旧
    assert client.get('/api/venues', headers=other_auth).get_json()['data']


def test_cannot_change_own_role(client, admin):
    admin_user, admin_h = admin
    resp = client.put(f"/api/admin/users/{admin_user['user_id']}/role",
                      headers=admin_h, json={'role': 'organizer'})
    assert resp.status_code == 400
    assert '自己' in resp.get_json()['message']


@pytest.mark.parametrize('role', ['student', 'root', '', None])
def test_invalid_role_rejected(client, admin, make_user, role):
    target = make_user('organizer')[0]
    resp = client.put(f"/api/admin/users/{target['user_id']}/role",
                      headers=admin[1], json={'role': role})
    assert resp.status_code == 400
    assert 'organizer 或 admin' in resp.get_json()['message']


def test_student_cannot_be_promoted(client, admin, make_user):
    stu_user = make_user('student')[0]
    for role in ('admin', 'organizer'):
        resp = client.put(f"/api/admin/users/{stu_user['user_id']}/role",
                          headers=admin[1], json={'role': role})
        assert resp.status_code == 400
        assert '组织者身份注册' in resp.get_json()['message']


def test_same_role_is_noop(client, admin, make_user):
    org_user = make_user('organizer')[0]
    resp = client.put(f"/api/admin/users/{org_user['user_id']}/role",
                      headers=admin[1], json={'role': 'organizer'})
    assert resp.status_code == 200
    assert resp.get_json()['message'] == '角色未变化'


def test_user_not_found(client, admin):
    resp = client.put('/api/admin/users/999999/role',
                      headers=admin[1], json={'role': 'admin'})
    assert resp.status_code == 404


def test_only_admin_can_manage_venues(client, auth, make_user, new_venue, event):
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


def test_create_venue(client, admin, new_venue):
    venue = new_venue(capacity=88)

    admin_list = client.get('/api/admin/venues', headers=admin[1]).get_json()['data']
    mine = [v for v in admin_list if v['venue_id'] == venue['venue_id']][0]
    assert mine['capacity'] == 88
    assert mine['available_status'] == 1
    assert mine['event_count'] == 0

    public_list = client.get('/api/venues', headers=admin[1]).get_json()['data']
    assert venue['venue_id'] in [v['venue_id'] for v in public_list]


def test_duplicate_venue_name(client, admin, new_venue):
    venue = new_venue()
    resp = client.post('/api/venues', headers=admin[1], json={
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
def test_create_venue_validation(client, admin, payload, expected):
    resp = client.post('/api/venues', headers=admin[1], json=payload)
    assert resp.status_code == 400
    assert expected in resp.get_json()['message']


def test_update_venue(client, admin, new_venue):
    venue = new_venue(capacity=30)
    new_name = f'改过的场地_{uuid.uuid4().hex[:6]}'
    resp = client.put(f"/api/venues/{venue['venue_id']}", headers=admin[1], json={
        'venue_name': new_name, 'location': '新位置', 'capacity': 60,
    })
    assert resp.status_code == 200

    admin_list = client.get('/api/admin/venues', headers=admin[1]).get_json()['data']
    mine = [v for v in admin_list if v['venue_id'] == venue['venue_id']][0]
    assert mine['venue_name'] == new_name
    assert mine['location'] == '新位置'
    assert mine['capacity'] == 60


def test_update_missing_venue_returns_404(client, admin):
    resp = client.put('/api/venues/999999', headers=admin[1],
                      json={'venue_name': '不存在的场地', 'capacity': 10})
    assert resp.status_code == 404


def test_capacity_cannot_shrink_below_existing_event(client, admin, new_venue,
                                                     make_user, unique_event_window):
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

    resp = client.put(f"/api/venues/{venue['venue_id']}", headers=admin[1], json={
        'venue_name': venue['venue_name'], 'capacity': 10,
    })
    assert resp.status_code == 400
    assert '不能小于 30' in resp.get_json()['message']


def test_disable_venue_hides_it_from_event_form(client, admin, new_venue,
                                                make_user, unique_event_window):
    venue = new_venue()
    resp = client.put(f"/api/venues/{venue['venue_id']}", headers=admin[1], json={
        'venue_name': venue['venue_name'],
        'location': '测试区',
        'capacity': venue['capacity'],
        'available_status': 0,
    })
    assert resp.status_code == 200

    public_list = client.get('/api/venues', headers=admin[1]).get_json()['data']
    assert venue['venue_id'] not in [v['venue_id'] for v in public_list]

    admin_list = client.get('/api/admin/venues', headers=admin[1]).get_json()['data']
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


def test_delete_venue_in_use_returns_409(client, admin, new_venue, make_user,
                                        unique_event_window):
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

    resp = client.delete(f"/api/venues/{venue['venue_id']}", headers=admin[1])
    assert resp.status_code == 409
    assert '停用' in resp.get_json()['message']


def test_delete_venue(client, admin, new_venue):
    venue = new_venue()
    assert client.delete(
        f"/api/venues/{venue['venue_id']}", headers=admin[1]
    ).status_code == 200

    public_list = client.get('/api/venues', headers=admin[1]).get_json()['data']
    assert venue['venue_id'] not in [v['venue_id'] for v in public_list]

    again = client.delete(f"/api/venues/{venue['venue_id']}", headers=admin[1])
    assert again.status_code == 404

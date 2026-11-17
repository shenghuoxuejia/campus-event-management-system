"""用户角色管理测试：管理员把组织者提成管理员、把管理员降回组织者。"""
import pytest


@pytest.fixture()
def admin_headers(client, auth, make_user, db):
    """注册一个普通账号再在库里提成管理员（注册接口不允许自助申请 admin）。"""
    user, token = make_user('student')
    db("UPDATE users SET role = 'admin' WHERE user_id = %s", (user['user_id'],))
    return user, auth(token)


def test_only_admin_can_change_roles(client, admin_headers, make_user, auth):
    """学生和组织者都不能改角色。"""
    _, org_token = make_user('organizer')
    _, stu_token = make_user('student')
    target = make_user('organizer')[0]

    for token in (org_token, stu_token):
        resp = client.put(f"/api/admin/users/{target['user_id']}/role",
                          headers=auth(token), json={'role': 'admin'})
        assert resp.status_code == 403


def test_promote_organizer_to_admin(client, admin_headers, make_user, auth, db_fetch):
    """组织者被提成管理员后，可以访问管理员接口。"""
    _, admin_auth = admin_headers
    org_user, org_token = make_user('organizer')
    org_auth = auth(org_token)

    # 提升前：组织者不能看用户列表
    assert client.get('/api/admin/users', headers=org_auth).status_code == 403

    resp = client.put(f"/api/admin/users/{org_user['user_id']}/role",
                      headers=admin_auth, json={'role': 'admin'})
    assert resp.status_code == 200
    assert '管理员' in resp.get_json()['message']

    # 同一个令牌立即具备管理员权限（角色是每次请求从库里读的）
    assert client.get('/api/admin/users', headers=org_auth).status_code == 200
    assert client.get('/api/admin/venues', headers=org_auth).status_code == 200

    rows = db_fetch("SELECT role FROM users WHERE user_id = %s", (org_user['user_id'],))
    assert rows[0]['role'] == 'admin'


def test_demote_admin_to_organizer(client, admin_headers, make_user, auth):
    """把另一个管理员降回组织者后，他立刻失去管理权限，但是还能发布活动。"""
    _, admin_auth = admin_headers
    other_user, other_token = make_user('organizer')
    other_auth = auth(other_token)
    client.put(f"/api/admin/users/{other_user['user_id']}/role",
               headers=admin_auth, json={'role': 'admin'})
    assert client.get('/api/admin/users', headers=other_auth).status_code == 200

    resp = client.put(f"/api/admin/users/{other_user['user_id']}/role",
                      headers=admin_auth, json={'role': 'organizer'})
    assert resp.status_code == 200
    assert '组织者' in resp.get_json()['message']

    assert client.get('/api/admin/users', headers=other_auth).status_code == 403
    assert client.get('/api/admin/venues', headers=other_auth).status_code == 403
    # 组织者身份还在，发布活动的权限不受影响
    venues = client.get('/api/venues', headers=other_auth).get_json()['data']
    assert venues


def test_cannot_change_own_role(client, admin_headers):
    """不能改自己的角色：这是「系统里永远至少有一个管理员」的保证。"""
    admin_user, admin_auth = admin_headers
    resp = client.put(f"/api/admin/users/{admin_user['user_id']}/role",
                      headers=admin_auth, json={'role': 'organizer'})
    assert resp.status_code == 400
    assert '自己' in resp.get_json()['message']


@pytest.mark.parametrize('role', ['student', 'root', '', None])
def test_invalid_role_rejected(client, admin_headers, make_user, role):
    _, admin_auth = admin_headers
    target = make_user('organizer')[0]
    resp = client.put(f"/api/admin/users/{target['user_id']}/role",
                      headers=admin_auth, json={'role': role})
    assert resp.status_code == 400
    assert 'organizer 或 admin' in resp.get_json()['message']


def test_student_cannot_be_promoted(client, admin_headers, make_user):
    """学生不能直接提成管理员，也不能在这里改成组织者。"""
    _, admin_auth = admin_headers
    stu_user = make_user('student')[0]

    for role in ('admin', 'organizer'):
        resp = client.put(f"/api/admin/users/{stu_user['user_id']}/role",
                          headers=admin_auth, json={'role': role})
        assert resp.status_code == 400
        assert '组织者身份注册' in resp.get_json()['message']


def test_same_role_is_noop(client, admin_headers, make_user):
    """角色没变化时返回 200，重复点击不会报错。"""
    _, admin_auth = admin_headers
    org_user = make_user('organizer')[0]
    resp = client.put(f"/api/admin/users/{org_user['user_id']}/role",
                      headers=admin_auth, json={'role': 'organizer'})
    assert resp.status_code == 200
    assert resp.get_json()['message'] == '角色未变化'


def test_user_not_found(client, admin_headers):
    _, admin_auth = admin_headers
    resp = client.put('/api/admin/users/999999/role',
                      headers=admin_auth, json={'role': 'admin'})
    assert resp.status_code == 404

"""认证相关接口测试。"""


def test_me_requires_login(client):
    resp = client.get('/api/me')
    assert resp.status_code == 401
    assert resp.get_json()['code'] == 401


def test_register_login_me(client, make_user):
    user, token = make_user('student')
    assert user['role'] == 'student'

    resp = client.get('/api/me', headers={'Authorization': f'Bearer {token}'})
    assert resp.status_code == 200
    assert resp.get_json()['data']['email'] == user['email']


def test_register_rejects_weak_password(client):
    resp = client.post('/api/register', json={
        'name': '测试', 'email': 'weak_pass@test.com', 'password': 'short',
        'role': 'student',
    })
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 400

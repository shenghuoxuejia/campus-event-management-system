import pytest


def test_me_requires_login(client):
    resp = client.get('/api/me')
    assert resp.status_code == 401
    assert resp.get_json()['code'] == 401


@pytest.mark.parametrize('role', ['student', 'organizer'])
def test_register_returns_token_and_logs_in(client, role):
    # 注册完直接给令牌，不用再登一次
    email = f'auto_login_{role}@test.com'
    resp = client.post('/api/register', json={
        'name': '自动登录测试', 'email': email, 'password': 'Passw0rd123', 'role': role,
    })
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['token']
    assert body['data']['email'] == email
    assert body['data']['role'] == role
    assert 'password_hash' not in body['data']

    me = client.get('/api/me', headers={'Authorization': f"Bearer {body['token']}"})
    assert me.status_code == 200
    assert me.get_json()['data']['email'] == email


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


def test_register_rejects_too_long_name(client):
    resp = client.post('/api/register', json={
        'name': 'N' * 300,
        'email': 'long_name_check@test.com',
        'password': 'Passw0rd123',
        'role': 'student',
    })
    assert resp.status_code == 400
    assert '姓名不能超过' in resp.get_json()['message']


def test_register_rejects_too_long_email(client):
    email = ('a' * 95) + '@test.com'
    resp = client.post('/api/register', json={
        'name': '测试',
        'email': email,
        'password': 'Passw0rd123',
        'role': 'student',
    })
    assert resp.status_code == 400
    assert '邮箱不能超过' in resp.get_json()['message']


# 需要登录的接口至少抽查一遍，别有的路由忘了加 @require_user
UNAUTH_CASES = [
    ('get', '/api/me'),
    ('get', '/api/events'),
    ('get', '/api/admin/users'),
    ('post', '/api/create_event'),
    ('put', '/api/check_in/1'),
    ('delete', '/api/delete_event/1'),
]


@pytest.mark.parametrize('method,path', UNAUTH_CASES)
def test_unauthenticated_returns_401(client, method, path):
    resp = getattr(client, method)(path)
    assert resp.status_code == 401
    assert resp.get_json()['code'] == 401

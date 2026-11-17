"""认证相关接口测试。"""

import pytest


def test_me_requires_login(client):
    resp = client.get('/api/me')
    assert resp.status_code == 401
    assert resp.get_json()['code'] == 401


@pytest.mark.parametrize('role', ['student', 'organizer'])
def test_register_returns_token_and_logs_in(client, role):
    """注册成功后直接返回令牌，不用再走一次登录。"""
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

"""登录 / 注册限流测试。"""

import app as app_module


def _clear_buckets():
    with app_module._rate_lock:
        app_module._rate_buckets.clear()


def test_login_bruteforce_is_rate_limited(client, app, make_user):
    user, _ = make_user('student')
    limit = app_module.LOGIN_RATE_LIMIT[0]

    app.config['TESTING'] = False
    _clear_buckets()
    try:
        for _ in range(limit):
            resp = client.post('/api/login', json={
                'email': user['email'], 'password': 'WrongPass1',
            })
            assert resp.status_code == 400

        resp = client.post('/api/login', json={
            'email': user['email'], 'password': 'WrongPass1',
        })
        assert resp.status_code == 429
        assert resp.get_json()['code'] == 429
        assert '频繁' in resp.get_json()['message']
    finally:
        app.config['TESTING'] = True
        _clear_buckets()


def test_successful_login_resets_counter(client, app, make_user):
    user, _ = make_user('student')
    limit = app_module.LOGIN_RATE_LIMIT[0]

    app.config['TESTING'] = False
    _clear_buckets()
    try:
        for _ in range(limit - 1):
            client.post('/api/login', json={
                'email': user['email'], 'password': 'WrongPass1',
            })

        # 正确密码登录成功，并清空该账号的失败计数
        assert client.post('/api/login', json={
            'email': user['email'], 'password': 'Passw0rd123',
        }).status_code == 200

        resp = client.post('/api/login', json={
            'email': user['email'], 'password': 'WrongPass1',
        })
        assert resp.status_code == 400  # 而不是 429
    finally:
        app.config['TESTING'] = True
        _clear_buckets()


def test_rate_limit_is_per_account(client, app, make_user):
    """不同账号之间互不影响。"""
    user_a, _ = make_user('student')
    user_b, _ = make_user('student')
    limit = app_module.LOGIN_RATE_LIMIT[0]

    app.config['TESTING'] = False
    _clear_buckets()
    try:
        for _ in range(limit + 1):
            client.post('/api/login', json={
                'email': user_a['email'], 'password': 'WrongPass1',
            })
        assert client.post('/api/login', json={
            'email': user_a['email'], 'password': 'WrongPass1',
        }).status_code == 429

        # 另一个账号仍然可以正常登录
        assert client.post('/api/login', json={
            'email': user_b['email'], 'password': 'Passw0rd123',
        }).status_code == 200
    finally:
        app.config['TESTING'] = True
        _clear_buckets()

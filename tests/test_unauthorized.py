"""未登录越权访问测试：所有需要登录的接口都应返回 401。"""
import pytest

UNAUTH_CASES = [
    ('get', '/api/me'),
    ('get', '/api/events'),
    ('get', '/api/venues'),
    ('get', '/api/user_registrations/1'),
    ('get', '/api/event_registrations/1'),
    ('get', '/api/comments/1'),
    ('get', '/api/admin/users'),
    ('get', '/api/admin/venues'),
    ('get', '/api/categories'),
    ('post', '/api/register_event'),
    ('post', '/api/create_event'),
    ('post', '/api/venues'),
    ('post', '/api/comments'),
    ('put', '/api/cancel_registration/1'),
    ('put', '/api/admin/users/1/role'),
    ('put', '/api/venues/1'),
    ('put', '/api/check_in/1'),
    ('put', '/api/update_event/1'),
    ('put', '/api/close_event/1'),
    ('put', '/api/undo_check_in/1'),
    ('delete', '/api/delete_event/1'),
    ('delete', '/api/venues/1'),
    ('delete', '/api/delete_comment/1'),
    ('delete', '/api/remove_registration/1'),
]


@pytest.mark.parametrize('method,path', UNAUTH_CASES)
def test_unauthenticated_returns_401(client, method, path):
    resp = getattr(client, method)(path)
    assert resp.status_code == 401
    assert resp.get_json()['code'] == 401

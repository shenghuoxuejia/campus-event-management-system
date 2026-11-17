"""pytest 公共夹具。跑之前先配好 .env，并且已经执行过 init_db.py。"""

import itertools
import os
import sys
import uuid
from pathlib import Path
from datetime import datetime, timedelta

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'backend'))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / '.env')
except ImportError:
    pass

import app as app_module

TEST_DB_NAME = os.environ.get('TEST_DB_NAME', 'campus_events_test')
DEV_DB_NAME = os.environ.get('DB_NAME', 'campus_events')
if TEST_DB_NAME == DEV_DB_NAME:
    raise RuntimeError('TEST_DB_NAME 不能和 DB_NAME 一样，用单独的测试库')

# 请求还没进来之前就把库切过去，免得连到开发库
app_module.db_config['database'] = TEST_DB_NAME

# 场地时间窗冲突是按 (venue, 时间段) 判的，所以测试里每次建活动都往后挪 4 小时，
# 不用随机时间，免得撞车偶发失败
_window_counter = itertools.count()


def unique_window():
    idx = next(_window_counter)
    base = datetime(2033, 1, 1) + timedelta(hours=4 * idx)
    return (base.strftime('%Y-%m-%dT%H:%M:%S'),
            (base + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M:%S'))


def _wipe_test_data():
    tables = ('comments', 'event_categories', 'registrations', 'events', 'users')
    with app_module.db_cursor(commit=True) as cur:
        cur.execute('SET FOREIGN_KEY_CHECKS = 0')
        try:
            for table in tables:
                cur.execute(f'DELETE FROM `{table}`')
        finally:
            cur.execute('SET FOREIGN_KEY_CHECKS = 1')


@pytest.fixture(scope='session', autouse=True)
def _ensure_test_db():
    try:
        with app_module.db_cursor() as cur:
            cur.execute("SELECT 1 FROM users LIMIT 1")
            cur.fetchone()  # 不读完结果连接池会报 Unread result found
    except Exception as e:
        pytest.exit(f'测试库 {TEST_DB_NAME} 还没初始化：{e}\n'
                    f'先跑 $env:DB_NAME = "{TEST_DB_NAME}"; python backend/init_db.py',
                    returncode=1)

    _wipe_test_data()
    yield
    _wipe_test_data()


@pytest.fixture()
def unique_event_window():
    return unique_window


@pytest.fixture()
def app():
    app_module.app.config['TESTING'] = True
    return app_module.app


@pytest.fixture()
def client(app):
    with app.test_client() as c:
        yield c


@pytest.fixture()
def make_user(client):
    def _make(role='student'):
        email = f'{role}_{uuid.uuid4().hex[:12]}@test.com'
        password = 'Passw0rd123'
        resp = client.post('/api/register', json={
            'name': '测试用户', 'email': email, 'password': password, 'role': role,
        })
        assert resp.status_code == 200, resp.get_json()
        login = client.post('/api/login', json={'email': email, 'password': password})
        assert login.status_code == 200, login.get_json()
        return login.get_json()['data'], login.get_json()['token']

    return _make


@pytest.fixture()
def auth():
    def _auth(token):
        return {'Authorization': f'Bearer {token}'}

    return _auth


@pytest.fixture()
def db():
    # 每条 SQL 单独一个连接并立即提交，不然夹具会一直占着行锁
    def _execute(sql, params=()):
        with app_module.db_cursor(commit=True) as cur:
            cur.execute(sql, params)
    return _execute


@pytest.fixture()
def db_fetch():
    def _query(sql, params=()):
        with app_module.db_cursor(commit=True) as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    return _query


@pytest.fixture()
def event(client, make_user, auth):
    org_user, org_token = make_user('organizer')
    venues = client.get('/api/venues', headers=auth(org_token)).get_json()['data']
    assert venues, '库里没有场地，先跑 init_db.py 灌种子数据'
    venue_id = venues[uuid.uuid4().int % len(venues)]['venue_id']

    start, end = unique_window()
    resp = client.post('/api/create_event', headers=auth(org_token), json={
        'title': f'测试活动_{uuid.uuid4().hex[:8]}',
        'description': '测试用活动',
        'venue_id': venue_id,
        'start_time': start,
        'end_time': end,
        'capacity': 10,
    })
    assert resp.status_code == 200, resp.get_json()

    return {'organizer': org_user, 'org_token': org_token,
            'event_id': resp.get_json()['data']['event_id']}


@pytest.fixture()
def registration(client, make_user, auth, event):
    stu_user, stu_token = make_user('student')
    resp = client.post('/api/register_event', headers=auth(stu_token),
                       json={'event_id': event['event_id']})
    assert resp.status_code == 200, resp.get_json()

    return {'student': stu_user, 'stu_token': stu_token,
            'registration_id': resp.get_json()['data']['registration_id']}


@pytest.fixture()
def active_scene(client, make_user, auth, event, db):
    # 接口不允许建过去的活动，所以先正常报名，再把时间直接改到进行中
    stu_user, stu_token = make_user('student')
    resp = client.post('/api/register_event', headers=auth(stu_token),
                       json={'event_id': event['event_id']})
    assert resp.status_code == 200, resp.get_json()

    db("UPDATE events SET start_time = NOW() - INTERVAL 1 HOUR, "
       "end_time = NOW() + INTERVAL 1 HOUR WHERE event_id = %s",
       (event['event_id'],))
    return dict(event, student=stu_user, stu_token=stu_token,
                registration_id=resp.get_json()['data']['registration_id'])


@pytest.fixture()
def ended_scene(client, make_user, auth, event, db):
    stu_user, stu_token = make_user('student')
    resp = client.post('/api/register_event', headers=auth(stu_token),
                       json={'event_id': event['event_id']})
    assert resp.status_code == 200, resp.get_json()

    db("UPDATE events SET start_time = NOW() - INTERVAL 3 HOUR, "
       "end_time = NOW() - INTERVAL 1 HOUR WHERE event_id = %s",
       (event['event_id'],))
    return dict(event, student=stu_user, stu_token=stu_token,
                registration_id=resp.get_json()['data']['registration_id'])


@pytest.fixture()
def find_event(client, auth):
    # 活动列表分页，目标活动不一定在第一页，得翻
    def _find(token, event_id, page_size=100):
        page = 1
        while True:
            result = client.get(
                f'/api/events?page={page}&page_size={page_size}', headers=auth(token)
            ).get_json()
            for e in result['data']:
                if e['event_id'] == event_id:
                    return e
            if page >= result['pages']:
                return None
            page += 1
    return _find

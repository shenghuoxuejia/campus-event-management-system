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


def _move_to_dedicated_venue(db, db_fetch, event_id):
    """把活动挪到一个专属新建场地。

    active_scene / ended_scene 这类夹具会把活动时间改成「相对 NOW()」，
    而库里其他用例的活动可能用同一个场地 —— 数据库触发器会（正确地）
    把它们当成时间段重叠而拒绝。给这类夹具一个专属场地就没冲突了。
    """
    name = f'测试场地_{uuid.uuid4().hex[:10]}'
    db("INSERT INTO venues (venue_name, location, capacity, available_status) "
       "VALUES (%s, '测试区', 500, 1)", (name,))
    venue_id = db_fetch('SELECT venue_id FROM venues WHERE venue_name = %s', (name,))[0]['venue_id']
    db('UPDATE events SET venue_id = %s WHERE event_id = %s', (venue_id, event_id))


def _wipe_test_data():
    tables = ('comments', 'event_categories', 'registrations', 'events', 'users')
    with app_module.db_cursor(commit=True) as cur:
        # 先确认连的真是测试库：名字比较可能被大小写/连接串绕过，这里看实际库名
        cur.execute('SELECT DATABASE() AS db')
        active = (cur.fetchone() or {}).get('db') or ''
        if active.lower() != TEST_DB_NAME.lower():
            raise RuntimeError(
                f'拒绝清理数据：当前连接的是 {active!r}，不是测试库 {TEST_DB_NAME!r}'
            )
        cur.execute('SET FOREIGN_KEY_CHECKS = 0')
        try:
            for table in tables:
                cur.execute(f'DELETE FROM `{table}`')
            # 测试自己造的场地也清掉，种子场地（不叫这个名字）保留
            cur.execute("DELETE FROM venues WHERE venue_name LIKE '测试场地\\_%'")
            # 种子场地可能被某个用例停用过，恢复到可用状态，不影响下个用例
            cur.execute('UPDATE venues SET available_status = 1')
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


@pytest.fixture(autouse=True)
def _clean_before_each_test():
    """每个用例开始前清一次业务数据。

    只在 session 开始/结束清的话，跑一半 Ctrl-C 或 pytest -x 中断后，
    下一次会话会从脏数据开始，用例互相影响（比如场地时间段全被占完）。
    """
    _wipe_test_data()
    with app_module._rate_lock:
        app_module._rate_buckets.clear()   # 限流计数也别跨用例残留
    yield


@pytest.fixture()
def unique_event_window():
    return unique_window


@pytest.fixture()
def move_to_own_venue(db, db_fetch):
    """给活动换一个专属场地（需要把时间改成「相对 NOW()」的用例用）。"""
    def _move(event_id):
        _move_to_dedicated_venue(db, db_fetch, event_id)
    return _move


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
def active_scene(client, make_user, auth, event, db, db_fetch):
    # 接口不允许建过去的活动，所以先正常报名，再把时间直接改到进行中
    stu_user, stu_token = make_user('student')
    resp = client.post('/api/register_event', headers=auth(stu_token),
                       json={'event_id': event['event_id']})
    assert resp.status_code == 200, resp.get_json()

    _move_to_dedicated_venue(db, db_fetch, event['event_id'])
    db("UPDATE events SET start_time = NOW() - INTERVAL 1 HOUR, "
       "end_time = NOW() + INTERVAL 1 HOUR WHERE event_id = %s",
       (event['event_id'],))
    return dict(event, student=stu_user, stu_token=stu_token,
                registration_id=resp.get_json()['data']['registration_id'])


@pytest.fixture()
def ended_scene(client, make_user, auth, event, db, db_fetch):
    stu_user, stu_token = make_user('student')
    resp = client.post('/api/register_event', headers=auth(stu_token),
                       json={'event_id': event['event_id']})
    assert resp.status_code == 200, resp.get_json()

    _move_to_dedicated_venue(db, db_fetch, event['event_id'])
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

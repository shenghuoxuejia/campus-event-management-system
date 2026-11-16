"""pytest 公共夹具。

运行前提：
1. 根目录 .env 已配置（DB_PASSWORD / APP_SECRET_KEY）；
2. 已执行 python backend/init_db.py 建库建表（并已写入场地/分类种子数据）；
3. 已安装 pytest：pip install -r requirements-dev.txt。
"""

import sys
import time
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

import os

TEST_DB_NAME = os.environ.get('TEST_DB_NAME', 'campus_events_test')
DEV_DB_NAME = os.environ.get('DB_NAME', 'campus_events')
if TEST_DB_NAME == DEV_DB_NAME:
    raise RuntimeError(
        'TEST_DB_NAME 不能和 DB_NAME 相同，请把测试库单独设为 campus_events_test'
    )
# 在任何请求触发连接池之前，把 app 的库切到测试库
app_module.db_config['database'] = TEST_DB_NAME

def unique_window():
    """生成一对唯一的 (start, end)，纳秒时间戳 + uuid 双保险，几乎不会撞。"""
    seed = (time.time_ns() ^ uuid.uuid4().int) % (30 * 365 * 24 * 3600)
    base = datetime(2030, 1, 1) + timedelta(seconds=seed)
    return (base.strftime('%Y-%m-%dT%H:%M:%S'),
            (base + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M:%S'))


@pytest.fixture(scope='session', autouse=True)
def _ensure_test_db():
    """第一个测试前检查测试库已初始化；未初始化直接退出并提示命令。"""
    try:
        with app_module.db_cursor() as cur:
            cur.execute("SELECT 1 FROM Users LIMIT 1")
            cur.fetchone()  # 必须消费结果，否则连接池报 Unread result found
    except Exception as e:
        pytest.exit(
            f'测试库 `{TEST_DB_NAME}` 未初始化或连不上：{e}\n'
            f'请先执行（PowerShell）：\n'
            f'  $env:DB_NAME = "{TEST_DB_NAME}"\n'
            f'  python backend/init_db.py\n'
            f'然后重新运行 pytest。',
            returncode=1,
        )


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
    """注册并登录一个新用户，返回 (user_dict, token)。"""

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
    """构造 Authorization 请求头。"""

    def _auth(token):
        return {'Authorization': f'Bearer {token}'}

    return _auth


@pytest.fixture()
def db():
    """执行单条 SQL 并立即提交的辅助函数。

    用于构造测试前置条件（例如把活动改成「进行中」）。
    每条语句用独立连接并立即 commit，避免夹具持有行锁导致用例里的事务等待。
    """
    def _execute(sql, params=()):
        with app_module.db_cursor(commit=True) as cur:
            cur.execute(sql, params)
    return _execute


@pytest.fixture()
def event(client, make_user, auth):
    """创建组织者 + 一个活动，返回 dict(organizer, org_token, event_id)。"""
    org_user, org_token = make_user('organizer')
    venues = client.get('/api/venues', headers=auth(org_token)).get_json()['data']
    assert venues, '数据库无可用场地，请先初始化种子数据'
    # 随机选场地，把活动分散到多个场地，降低时间窗口撞车概率
    venue_id = venues[uuid.uuid4().int % len(venues)]['venue_id']

    title = f'测试活动_{uuid.uuid4().hex[:8]}'
    start, end = unique_window()
    resp = client.post('/api/create_event', headers=auth(org_token), json={
        'title': title,
        'description': '测试用活动',
        'venue_id': venue_id,
        'start_time': start,
        'end_time': end,
        'capacity': 10,
    })
    assert resp.status_code == 200, resp.get_json()
    event_id = resp.get_json()['data']['event_id']

    return {'organizer': org_user, 'org_token': org_token, 'event_id': event_id}


@pytest.fixture()
def registration(client, make_user, auth, event):
    """学生报名活动，返回 dict(student, stu_token, registration_id)。"""
    stu_user, stu_token = make_user('student')
    resp = client.post('/api/register_event', headers=auth(stu_token),
                       json={'event_id': event['event_id']})
    assert resp.status_code == 200, resp.get_json()
    registration_id = resp.get_json()['data']['registration_id']

    return {'student': stu_user, 'stu_token': stu_token,
            'registration_id': registration_id}


@pytest.fixture()
def active_scene(client, make_user, auth, event, db):
    """「正在进行中」的活动 + 一条报名。

    报名接口不允许创建/报名过去的活动，所以先正常报名，再直接把时间改到进行中。
    """
    stu_user, stu_token = make_user('student')
    resp = client.post('/api/register_event', headers=auth(stu_token),
                       json={'event_id': event['event_id']})
    assert resp.status_code == 200, resp.get_json()
    registration_id = resp.get_json()['data']['registration_id']

    db(
        "UPDATE Events SET start_time = NOW() - INTERVAL 1 HOUR, "
        "end_time = NOW() + INTERVAL 1 HOUR WHERE event_id = %s",
        (event['event_id'],),
    )
    return dict(event, student=stu_user, stu_token=stu_token,
                registration_id=registration_id)


@pytest.fixture()
def ended_scene(client, make_user, auth, event, db):
    """「已结束」的活动 + 一条报名。"""
    stu_user, stu_token = make_user('student')
    resp = client.post('/api/register_event', headers=auth(stu_token),
                       json={'event_id': event['event_id']})
    assert resp.status_code == 200, resp.get_json()
    registration_id = resp.get_json()['data']['registration_id']

    db(
        "UPDATE Events SET start_time = NOW() - INTERVAL 3 HOUR, "
        "end_time = NOW() - INTERVAL 1 HOUR WHERE event_id = %s",
        (event['event_id'],),
    )
    return dict(event, student=stu_user, stu_token=stu_token,
                registration_id=registration_id)


@pytest.fixture()
def find_event(client, auth):
    """按 event_id 逐页查找活动（活动列表已分页，可能不在第一页）。"""
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

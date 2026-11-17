"""后端主程序：接口都在 /api/ 下，前端静态页也由这里托管。"""

import os
import re
import threading
import time
from collections import deque
from contextlib import closing, contextmanager
from datetime import datetime

import bcrypt
import mysql.connector
from mysql.connector import pooling
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

# 路径常量：app.py 在 backend/ 里，资源按项目根目录找
BASE_DIR = os.path.dirname(os.path.abspath(__file__))   # backend/
PROJECT_ROOT = os.path.dirname(BASE_DIR)                 # 项目根目录
FRONTEND_DIR = os.path.join(PROJECT_ROOT, 'frontend')    # 根目录/frontend

# 装了 python-dotenv 就顺手读一下 .env
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, '.env'))
except ImportError:
    pass

# 数据库配置，全部从环境变量取
db_config = {
    'host': os.environ.get('DB_HOST', '127.0.0.1'),
    'port': int(os.environ.get('DB_PORT', '3306')),
    'user': os.environ.get('DB_USER'),
    'password': os.environ.get('DB_PASSWORD'),          # 必填，见 .env.example
    'database': os.environ.get('DB_NAME', 'campus_events'),
    'charset': 'utf8mb4',
    # 固定东八区，否则 MySQL 是 UTC 时 NOW() 会让报名/签到时间窗差 8 小时
    'time_zone': os.environ.get('DB_TIME_ZONE', '+08:00'),
}
APP_SECRET_KEY = os.environ.get('APP_SECRET_KEY')       # 必填，见 .env.example
TOKEN_MAX_AGE = int(os.environ.get('TOKEN_MAX_AGE', '86400'))  # 令牌有效期（秒），默认 24 小时
DEBUG = os.environ.get('FLASK_DEBUG', '0') == '1'       # 默认关闭调试模式

_PLACEHOLDER_SECRETS = {
    '在这里填一段随机长字符串', 'change-me', 'your-secret-key',
    'secret', 'changeme', 'please-change-me',
}
if not APP_SECRET_KEY:
    raise RuntimeError(
        '未设置 APP_SECRET_KEY 环境变量，拒绝启动。请复制 .env.example 为 .env，'
        '并用 python -c "import secrets; print(secrets.token_urlsafe(48))" 生成随机密钥。'
    )
if APP_SECRET_KEY in _PLACEHOLDER_SECRETS or len(APP_SECRET_KEY) < 32:
    raise RuntimeError(
        'APP_SECRET_KEY 不合法：必须 ≥32 个字符，且不能是 .env.example 里的占位符。'
        '请用 python -c "import secrets; print(secrets.token_urlsafe(48))" 重新生成。'
    )

# 密码还是占位符时只警告，不拦启动（init_db.py 还得能跑）
if os.environ.get('DB_PASSWORD') and '在这里填' in os.environ['DB_PASSWORD']:
    print('[警告] DB_PASSWORD 仍是占位符，连库会失败。请打开 .env 填入真实密码。')

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
ALLOWED_REGISTER_ROLES = ('student', 'organizer')       # 不允许自助注册 admin

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path='')
app.config['SECRET_KEY'] = APP_SECRET_KEY
app.json.ensure_ascii = False
_cors_origins = [o.strip() for o in os.environ.get('CORS_ORIGINS', '*').split(',') if o.strip()] or ['*']
CORS(app, origins=_cors_origins, allow_headers=['Content-Type', 'Authorization'])

serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='campus-events-auth')


class AppError(Exception):
    """业务错误：统一转成 JSON 响应。"""
    def __init__(self, message, code=400, http_status=400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.http_status = http_status


@app.after_request
def add_no_cache_header(response):
    # API 不缓存，静态页照旧缓存
    if request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response


# 连接池
_db_pool = None


def _get_pool():
    """第一次用到时才建池子。"""
    global _db_pool
    if _db_pool is None:
        _db_pool = pooling.MySQLConnectionPool(
            pool_name='campus_events_pool',
            pool_size=int(os.environ.get('DB_POOL_SIZE', '5')),
            connection_timeout=5,
            **db_config,
        )
    return _db_pool


def get_conn():
    """从池里取个连接，调用方负责关。池里的连接可能已被 wait_timeout 掐掉，先 ping 一下。"""
    conn = _get_pool().get_connection()
    try:
        conn.ping(reconnect=True, attempts=1, delay=0)
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        conn = _get_pool().get_connection()
    return conn


@contextmanager
def db_cursor(*, commit=False, action=None, error_message=None,
              conflict_message=None):
    """数据库操作的统一入口：开连接、开游标、提交 / 回滚、关连接，顺手把 DB 异常转成 500。

    action 是写日志用的中文名，error_message / conflict_message 是出错和唯一键冲突时给前端的文案。
    """
    conn = get_conn()
    try:
        with closing(conn.cursor(dictionary=True)) as cur:
            yield cur
            if commit:
                conn.commit()
    except Exception as err:
        try:
            conn.rollback()
        except Exception:
            pass
        if isinstance(err, mysql.connector.Error):
            if err.errno == 1062:
                app.logger.warning('%s：唯一键冲突 %s', action or '数据库操作', err)
                raise AppError(conflict_message or '数据已存在，请勿重复提交') from err
            app.logger.exception('%s失败（数据库错误）', action or '数据库操作')
            raise AppError(error_message or '服务异常，请稍后重试',
                           code=500, http_status=500) from err
        raise
    finally:
        conn.close()


def issue_token(user_id, token_version=0):
    """为用户签发令牌（带 token_version，登出/改密后旧令牌立即失效）。"""
    return serializer.dumps({'uid': user_id, 'tv': int(token_version or 0)})


def _load_user_row(user_id, include_version=False):
    """按主键读取用户；include_version=True 时额外带上 token_version（仅供鉴权）。"""
    columns = 'user_id, name, email, role, created_at'
    if include_version:
        columns += ', token_version'
    with db_cursor(action='读取用户信息') as cur:
        cur.execute(f"SELECT {columns} FROM users WHERE user_id = %s", (user_id,))
        return cur.fetchone()


def load_user(user_id):
    """按主键读取用户（只取安全字段，不含 token_version）。"""
    row = _load_user_row(user_id)
    return fmt_row(row, 'created_at') if row is not None else row


def auth_user():
    """从 Authorization: Bearer <token> 解析当前用户；无令牌或无效返回 None。"""
    header = request.headers.get('Authorization', '')
    if not header.startswith('Bearer '):
        return None
    token = header[len('Bearer '):].strip()
    if not token:
        return None
    try:
        payload = serializer.loads(token, max_age=TOKEN_MAX_AGE)
    except SignatureExpired:
        return None
    except BadSignature:
        return None

    row = _load_user_row(payload.get('uid'), include_version=True)
    if row is None:
        return None
    # token_version 对不上 = 已登出或改过密码，旧令牌作废
    if int(payload.get('tv') or 0) != int(row.get('token_version') or 0):
        return None
    row.pop('token_version', None)
    return fmt_row(row, 'created_at')


def require_user():
    """要求已登录；未登录抛 AppError。"""
    user = auth_user()
    if not user:
        raise AppError("未登录或登录已过期，请重新登录", code=401, http_status=401)
    return user


def require_role(role):
    """要求已登录且角色匹配。"""
    user = require_user()
    if user['role'] != role:
        raise AppError("权限不足", code=403, http_status=403)
    return user


def is_admin(user):
    """是否为管理员（管理员不受「仅活动组织者本人」限制）。"""
    return user.get('role') == 'admin'


def fail(message, code=400, http_status=400):
    return jsonify({"code": code, "message": message}), http_status


def ok(message=None, **extra):
    payload = {"code": 200}
    if message:
        payload["message"] = message
    payload.update(extra)
    return jsonify(payload)


@app.errorhandler(AppError)
def handle_app_error(e):
    return jsonify({"code": e.code, "message": e.message}), e.http_status


def fmt_row(row, *fields, time_fmt='%Y-%m-%d %H:%M:%S'):
    """把行内的 datetime 字段格式化成字符串，便于前端直接展示。"""
    for f in fields:
        if row.get(f) is not None:
            try:
                row[f] = row[f].strftime(time_fmt)
            except AttributeError:
                row[f] = str(row[f])
    return row


# 分页工具
DEFAULT_EVENT_PAGE_SIZE = 12
DEFAULT_LIST_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def _int_arg(name, default, *, maximum=None):
    """读取正整数查询参数，非法值回退到默认值。"""
    raw = request.args.get(name)
    if raw is None or raw == '':
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    if value < 1:
        return default
    return min(value, maximum) if maximum is not None else value


def _pagination(default_size):
    """解析 ?page=&page_size=，返回 (page, page_size, offset)。"""
    page = _int_arg('page', 1)
    page_size = _int_arg('page_size', default_size, maximum=MAX_PAGE_SIZE)
    return page, page_size, (page - 1) * page_size


def _page_payload(page, page_size, total):
    """分页元信息，随 data 一起返回（保持 data 仍是列表，兼容旧前端）。"""
    pages = (total + page_size - 1) // page_size if page_size else 0
    return {'total': total, 'page': page, 'page_size': page_size, 'pages': pages}


# 简易限流（单进程内存版），防暴力破解和恶意注册
# 配置写成「次数/窗口秒数」，比如 LOGIN_RATE_LIMIT=10/60
_rate_lock = threading.Lock()
_rate_buckets = {}


def _parse_rate_limit(env_name, default):
    """读取环境变量里的限流配置，格式 '次数/窗口秒数'；非法值回退到默认。"""
    raw = os.environ.get(env_name)
    if not raw:
        return default
    try:
        count, window = raw.split('/')
        count, window = int(count), int(window)
        if count < 1 or window < 1:
            return default
        return count, window
    except (TypeError, ValueError):
        return default


LOGIN_RATE_LIMIT = _parse_rate_limit('LOGIN_RATE_LIMIT', (10, 60))
REGISTER_RATE_LIMIT = _parse_rate_limit('REGISTER_RATE_LIMIT', (20, 3600))
COMMENT_RATE_LIMIT = _parse_rate_limit('COMMENT_RATE_LIMIT', (20, 60))


_TRUSTED_PROXIES = {
    ip.strip() for ip in os.environ.get('TRUSTED_PROXIES', '').split(',') if ip.strip()
}

def _client_ip():
    """默认只信 remote_addr；仅当请求来自可信代理时才解析 X-Forwarded-For。"""
    remote = request.remote_addr or 'unknown'
    if remote in _TRUSTED_PROXIES:
        forwarded = request.headers.get('X-Forwarded-For', '')
        if forwarded:
            return forwarded.split(',')[0].strip()
    return remote


def rate_limit(key, config, message):
    """滑动窗口限流：超限抛 429。key 为限流维度（如 ip、ip+邮箱）。"""
    # 测试环境默认不限流，避免用例互相影响
    if app.config.get('TESTING'):
        return

    limit, window = config
    now = time.monotonic()
    with _rate_lock:
        bucket = _rate_buckets.setdefault(key, deque())
        # 丢弃窗口外的旧记录
        while bucket and now - bucket[0] > window:
            bucket.popleft()
        if len(bucket) >= limit:
            retry_after = max(int(window - (now - bucket[0])) + 1, 1)
            raise AppError(
                f"{message}，请在 {retry_after} 秒后重试",
                code=429,
                http_status=429,
            )
        bucket.append(now)

        # 防止大量不同 key 导致内存无限增长
        if len(_rate_buckets) > 5000:
            for k in [k for k, v in _rate_buckets.items() if not v or now - v[-1] > window]:
                _rate_buckets.pop(k, None)


def reset_rate_limit(key):
    """成功后清除限流记录（避免正常用户被早前的输错拖累）。"""
    with _rate_lock:
        _rate_buckets.pop(key, None)


def validate_password(password):
    """校验密码规则。返回 (ok, message)。"""
    if len(password) < 8:
        return False, "密码长度不能少于 8 位"
    # bcrypt 只吃 72 字节，超了直接报错，先拦一下
    if len(password.encode('utf-8')) > 72:
        return False, "密码过长（最多 72 个字节）"
    if not any(c.isupper() for c in password):
        return False, "密码必须包含至少一个大写字母"
    if not any(c.islower() for c in password):
        return False, "密码必须包含至少一个小写字母"
    if not any(c.isdigit() for c in password):
        return False, "密码必须包含至少一个数字"
    return True, None


def _normalize_datetime(value):
    """把前端 datetime-local 的 'YYYY-MM-DDTHH:MM' 转成 MySQL 认可格式。"""
    if isinstance(value, str):
        return value.replace('T', ' ').strip()
    return value


def _validate_datetime(value, field_label):
    """校验时间字符串格式，返回规整后的 'YYYY-MM-DD HH:MM:SS'。"""
    value = _normalize_datetime(value)
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            return datetime.strptime(value, fmt).strftime('%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            continue
    raise AppError(f"{field_label}格式不正确，请使用 YYYY-MM-DD HH:MM")


def _get_venue(cur, venue_id):
    """读可用场地并加行锁，不然两个并发发布可能同时通过时间冲突检查。"""
    cur.execute(
        "SELECT venue_id, capacity FROM venues "
        "WHERE venue_id = %s AND available_status = 1 FOR UPDATE",
        (venue_id,),
    )
    return cur.fetchone()


def _fmt_dt(value):
    """把 datetime / 字符串统一成 'YYYY-MM-DD HH:MM:SS' 便于比较。"""
    if value is None:
        return ''
    try:
        return value.strftime('%Y-%m-%d %H:%M:%S')
    except AttributeError:
        return str(value)


def _is_time_order_valid(cur, start, end):
    cur.execute(
        "SELECT (CAST(%s AS DATETIME) < CAST(%s AS DATETIME)) AS ok_time",
        (start, end),
    )
    return bool(cur.fetchone()['ok_time'])


def _is_start_in_future(cur, start):
    """开始时间是否晚于数据库当前时间（避免 Python 与 MySQL 时区不一致）。"""
    cur.execute(
        "SELECT (CAST(%s AS DATETIME) > NOW()) AS ok_time",
        (start,),
    )
    return bool(cur.fetchone()['ok_time'])


def _require_event_owner(cur, event_id, user, deny_message="无权操作该活动"):
    """校验当前用户是否为活动组织者（管理员放行）；是则返回活动行，否则抛 AppError。"""
    cur.execute("SELECT organizer_id FROM events WHERE event_id = %s", (event_id,))
    event = cur.fetchone()
    if not event:
        raise AppError("活动不存在", code=404, http_status=404)
    if not is_admin(user) and event['organizer_id'] != user['user_id']:
        raise AppError(deny_message, code=403, http_status=403)
    return event


def _lock_event(cur, event_id):
    """锁定活动行并读取容量/状态/时间信息。"""
    cur.execute(
        """
        SELECT capacity, status,
               (NOW() > start_time) AS started,
               (end_time IS NOT NULL AND NOW() > end_time) AS ended
        FROM events WHERE event_id = %s FOR UPDATE
        """,
        (event_id,),
    )
    return cur.fetchone()


def _get_registration_for_update(cur, user_id, event_id):
    cur.execute(
        "SELECT registration_id, status FROM registrations "
        "WHERE student_id = %s AND event_id = %s FOR UPDATE",
        (user_id, event_id),
    )
    return cur.fetchone()


def _count_active_registrations(cur, event_id):
    cur.execute(
        "SELECT COUNT(*) AS cnt FROM registrations "
        "WHERE event_id = %s AND status <> 'cancelled'",
        (event_id,),
    )
    return cur.fetchone()['cnt']


def _upsert_registration(cur, existing, user_id, event_id):
    """报名或重新报名。返回 (提示语, registration_id)。"""
    if existing:
        # 重新报名复用原来那行，首次报名时间不被覆盖
        cur.execute(
            "UPDATE registrations SET status = 'registered', "
            "check_in_time = NULL, cancelled_at = NULL, cancelled_by = NULL "
            "WHERE registration_id = %s AND status = 'cancelled'",
            (existing['registration_id'],),
        )
        if cur.rowcount != 1:
            raise AppError("该报名状态已变化，请刷新后重试", code=409, http_status=409)
        return "重新报名成功！", existing['registration_id']
    cur.execute(
        "INSERT INTO registrations (student_id, event_id, status) "
        "VALUES (%s, %s, 'registered')",
        (user_id, event_id),
    )
    return "报名成功！", cur.lastrowid


def _validated_event_fields(cur, data, *, require_future=True, exclude_event_id=None, current=None):
    """校验并规整发布 / 编辑活动的字段，通过就返回能直接入库的 dict。"""
    title = (data.get('title') or '').strip()
    description = (data.get('description') or '').strip()
    venue_id = data.get('venue_id')
    start_time = data.get('start_time')
    end_time = data.get('end_time')
    capacity = data.get('capacity')

    if not all([title, venue_id, start_time, end_time, capacity]):
        raise AppError("请填写所有必填字段")

    start_time = _validate_datetime(start_time, '开始时间')
    end_time = _validate_datetime(end_time, '结束时间')
    if len(title) > 200:
        raise AppError("活动标题不能超过 200 个字符")
    if len(description) > 5000:
        raise AppError("活动描述不能超过 5000 个字符")
    try:
        capacity = int(capacity)
    except (TypeError, ValueError):
        raise AppError("名额必须是整数")
    if capacity <= 0:
        raise AppError("名额必须大于 0")

    venue = _get_venue(cur, venue_id)
    if not venue:
        raise AppError("所选场地不存在或已停用")
    if venue['capacity'] is not None and capacity > venue['capacity']:
        raise AppError(f"名额超过了场地容量（{venue['capacity']}）")

    # 结束时间必须晚于开始时间（DB 层也有 CHECK 兜底）
    if not _is_time_order_valid(cur, start_time, end_time):
        raise AppError("结束时间必须晚于开始时间")

    if require_future and not _is_start_in_future(cur, start_time):
        raise AppError("开始时间必须晚于当前时间")

    # 区间重叠：existing.start < new.end AND existing.end > new.start
    unchanged = bool(
        current
        and venue['venue_id'] == current.get('venue_id')
        and start_time == _fmt_dt(current.get('start_time'))
        and end_time == _fmt_dt(current.get('end_time'))
    )
    if not unchanged:
        cur.execute(
            """
            SELECT event_id FROM events
             WHERE venue_id = %s
               AND event_id <> %s
               AND start_time < %s
               AND end_time > %s
             LIMIT 1
             FOR UPDATE
            """,
            (venue['venue_id'], exclude_event_id or 0, end_time, start_time),
        )
        if cur.fetchone():
            raise AppError("该场地在该时间段已被占用，请更换场地或时间")

    return {
        'title': title,
        'description': description,
        'venue_id': venue['venue_id'],
        'start_time': start_time,
        'end_time': end_time,
        'capacity': capacity,
    }


def _parse_category_ids(raw):
    """把前端传来的 category_ids 规整为去重后的正整数列表；非法值抛 AppError。"""
    if raw is None:
        return []
    if isinstance(raw, (str, int)):
        raw = [raw]
    try:
        ids = [int(x) for x in raw]
    except (TypeError, ValueError):
        raise AppError("分类参数不合法")
    seen, result = set(), []
    for cid in ids:
        if cid > 0 and cid not in seen:
            seen.add(cid)
            result.append(cid)
    return result


def _ensure_categories_exist(cur, category_ids):
    """校验分类都存在，不存在则抛 AppError。"""
    if not category_ids:
        return
    placeholders = ','.join(['%s'] * len(category_ids))
    cur.execute(
        f"SELECT category_id FROM categories WHERE category_id IN ({placeholders})",
        tuple(category_ids),
    )
    found = {row['category_id'] for row in cur.fetchall()}
    missing = [cid for cid in category_ids if cid not in found]
    if missing:
        raise AppError(f"分类不存在：{', '.join(map(str, missing))}")


def _apply_event_categories(cur, event_id, raw_category_ids):
    """解析、校验并整体替换活动的分类（先删后插）。"""
    category_ids = _parse_category_ids(raw_category_ids)
    if category_ids:
        _ensure_categories_exist(cur, category_ids)
    cur.execute("DELETE FROM event_categories WHERE event_id = %s", (event_id,))
    for cid in category_ids:
        cur.execute(
            "INSERT INTO event_categories (event_id, category_id) VALUES (%s, %s)",
            (event_id, cid),
        )
    return category_ids


@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    role = data.get('role', 'student')

    if not name or not email or not password:
        raise AppError("姓名、邮箱和密码不能为空")
    rate_limit(f'register:{_client_ip()}', REGISTER_RATE_LIMIT, "注册过于频繁")
    if len(name) > 100:
        raise AppError("姓名不能超过 100 个字符")
    if len(email) > 100:
        raise AppError("邮箱不能超过 100 个字符")
    if not EMAIL_RE.match(email):
        raise AppError("邮箱格式不正确")
    if role not in ALLOWED_REGISTER_ROLES:
        raise AppError("注册身份不合法")
    password_ok, password_msg = validate_password(password)
    if not password_ok:
        raise AppError(password_msg)

    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    with db_cursor(commit=True, action='注册', error_message='注册失败，请稍后重试',
                   conflict_message='该邮箱已被注册') as cur:
        cur.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, %s)",
            (name, email, hashed, role),
        )
        new_user_id = cur.lastrowid
        cur.execute(
            "SELECT user_id, name, email, role, created_at FROM users WHERE user_id = %s",
            (new_user_id,),
        )
        user = cur.fetchone()

    # 注册完直接发令牌，前端不用再登一次
    token = issue_token(user['user_id'], 0)
    return ok("注册成功，已自动登录", data=fmt_row(user, 'created_at'), token=token)


@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not email or not password:
        raise AppError("邮箱和密码不能为空")

    # 按 IP + 邮箱限流，防止盯着一个账号试密码
    login_key = f'login:{_client_ip()}:{email}'
    rate_limit(login_key, LOGIN_RATE_LIMIT, "登录尝试过于频繁")

    with db_cursor(action='登录查询') as cur:
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cur.fetchone()

    # 提示统一，别暴露邮箱存不存在
    if not user or not bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
        raise AppError("邮箱或密码错误")

    token = issue_token(user['user_id'], user.get('token_version', 0))
    user.pop('password_hash', None)
    user.pop('token_version', None)
    reset_rate_limit(login_key)
    return ok("登录成功", data=fmt_row(user, 'created_at'), token=token)


@app.route('/api/events', methods=['GET'])
def get_events():
    user = require_user()
    page, page_size, offset = _pagination(DEFAULT_EVENT_PAGE_SIZE)

    # ?category_id= 是可选的分类过滤
    category_id = None
    raw_cat = request.args.get('category_id')
    if raw_cat:
        try:
            category_id = int(raw_cat)
        except (TypeError, ValueError):
            category_id = None
    if category_id is not None and category_id < 1:
        category_id = None

    cat_where = ''
    cat_params = []
    if category_id:
        cat_where = ' AND e.event_id IN (SELECT event_id FROM event_categories WHERE category_id = %s)'
        cat_params = [category_id]

    sql = f"""
        SELECT
            e.event_id, e.title, e.description, e.organizer_id, e.venue_id,
            e.start_time, e.end_time, e.capacity, e.status,
            v.venue_name, v.location AS venue_location,
            (NOW() > e.start_time) AS started,
            (e.end_time < NOW()) AS ended,
            (SELECT COUNT(*) FROM registrations r
              WHERE r.event_id = e.event_id AND r.status <> 'cancelled') AS registered_count,
            (SELECT COUNT(*) FROM registrations r
              WHERE r.event_id = e.event_id AND r.student_id = %s
                AND r.status <> 'cancelled') AS is_registered
        FROM events e
        LEFT JOIN venues v ON e.venue_id = v.venue_id
        WHERE 1=1{cat_where}
        ORDER BY (e.end_time < NOW()) ASC,
                 e.start_time ASC, e.event_id ASC
        LIMIT %s OFFSET %s
    """
    with db_cursor(action='查询活动列表') as cur:
        cur.execute(
            f"SELECT COUNT(*) AS total FROM events e WHERE 1=1{cat_where}",
            tuple(cat_params),
        )
        total = cur.fetchone()['total']
        # 参数顺序要和 SQL 里 %s 的顺序对上：user_id, category_id, LIMIT, OFFSET
        cur.execute(sql, (user['user_id'],) + tuple(cat_params) + (page_size, offset))
        events = cur.fetchall()

        # 聚合每个活动的分类
        event_ids = [e['event_id'] for e in events]
        categories_by_event = {eid: [] for eid in event_ids}
        if event_ids:
            placeholders = ','.join(['%s'] * len(event_ids))
            cur.execute(
                f"""
                SELECT ec.event_id, c.category_id, c.category_name
                FROM event_categories ec
                JOIN categories c ON ec.category_id = c.category_id
                WHERE ec.event_id IN ({placeholders})
                ORDER BY c.category_id ASC
                """,
                tuple(event_ids),
            )
            for row in cur.fetchall():
                categories_by_event[row['event_id']].append(
                    {'category_id': row['category_id'], 'category_name': row['category_name']}
                )

    for e in events:
        fmt_row(e, 'start_time', 'end_time')
        e['started'] = bool(e.get('started'))
        e['ended'] = bool(e.get('ended'))
        registered = int(e.get('registered_count') or 0)
        capacity = int(e.get('capacity') or 0)
        e['remaining'] = max(capacity - registered, 0)
        e['categories'] = categories_by_event.get(e['event_id'], [])
    return ok(data=events, **_page_payload(page, page_size, total))


@app.route('/api/events/<int:event_id>', methods=['GET'])
def get_event_detail(event_id):
    user = require_user()
    with db_cursor(action='查询活动详情') as cur:
        cur.execute(
            """
            SELECT e.event_id, e.title, e.description, e.organizer_id, e.venue_id,
                   e.start_time, e.end_time, e.capacity, e.status, e.updated_at,
                   v.venue_name, v.location AS venue_location,
                   u.name AS organizer_name,
                   (SELECT COUNT(*) FROM registrations r
                     WHERE r.event_id = e.event_id AND r.status <> 'cancelled') AS registered_count,
                   (SELECT COUNT(*) FROM registrations r
                     WHERE r.event_id = e.event_id AND r.student_id = %s
                       AND r.status <> 'cancelled') AS is_registered,
                   (NOW() > e.start_time) AS started,
                   (e.end_time IS NOT NULL AND NOW() > e.end_time) AS ended
              FROM events e
              LEFT JOIN venues v ON e.venue_id = v.venue_id
              LEFT JOIN users u ON e.organizer_id = u.user_id
             WHERE e.event_id = %s
            """,
            (user['user_id'], event_id),
        )
        event = cur.fetchone()
        if not event:
            raise AppError("活动不存在", code=404, http_status=404)

        cur.execute(
            "SELECT c.category_id, c.category_name "
            "  FROM event_categories ec "
            "  JOIN categories c ON ec.category_id = c.category_id "
            " WHERE ec.event_id = %s ORDER BY c.category_id ASC",
            (event_id,),
        )
        event['categories'] = cur.fetchall()

    fmt_row(event, 'start_time', 'end_time', 'updated_at')
    event['remaining'] = max(int(event['capacity'] or 0) - int(event['registered_count'] or 0), 0)
    return ok(data=event)


# 报名：事务 + 行锁，防超卖
@app.route('/api/register_event', methods=['POST'])
def register_event():
    user = require_user()
    # 组织者和管理员不能报名
    if user['role'] != 'student':
        raise AppError("只有学生账号可以报名活动", code=403, http_status=403)

    data = request.get_json(silent=True) or {}
    event_id = data.get('event_id')
    if not event_id:
        raise AppError("活动ID不能为空")

    with db_cursor(commit=True, action='报名', error_message='报名失败，请稍后重试') as cur:
        # 锁住活动行，容量校验和写入在同一个事务里，防超卖
        event = _lock_event(cur, event_id)
        if not event:
            raise AppError("活动不存在", code=404, http_status=404)
        if event['status'] != 'open':
            raise AppError("活动已关闭，无法报名")
        if event['ended']:
            raise AppError("活动已结束，无法报名")
        if event['started']:
            raise AppError("活动已经开始，无法报名")

        existing = _get_registration_for_update(cur, user['user_id'], event_id)
        if existing and existing['status'] != 'cancelled':
            raise AppError("你已经报名过该活动了，请勿重复报名")

        if _count_active_registrations(cur, event_id) >= (event['capacity'] or 0):
            raise AppError("活动名额已满，报名失败")

        message, registration_id = _upsert_registration(cur, existing, user['user_id'], event_id)
    return ok(message, data={'registration_id': registration_id})


@app.route('/api/user_registrations/<int:user_id>', methods=['GET'])
def get_user_registrations(user_id):
    user = require_user()
    if user_id != user['user_id']:
        raise AppError("无权查看他人报名记录", code=403, http_status=403)

    page, page_size, offset = _pagination(DEFAULT_LIST_PAGE_SIZE)

    sql = """
        SELECT
            r.registration_id,
            r.status AS registration_status,
            r.registered_at,
            r.check_in_time,
            e.event_id,
            e.title AS event_title,
            e.start_time,
            e.end_time,
            v.venue_name,
            v.location
        FROM registrations r
        JOIN events e ON r.event_id = e.event_id
        LEFT JOIN venues v ON e.venue_id = v.venue_id
        WHERE r.student_id = %s
        ORDER BY r.registered_at DESC
    """
    with db_cursor(action='查询报名记录') as cur:
        cur.execute(
            "SELECT COUNT(*) AS total FROM registrations WHERE student_id = %s",
            (user_id,),
        )
        total = cur.fetchone()['total']
        cur.execute(sql + " LIMIT %s OFFSET %s", (user_id, page_size, offset))
        registrations = cur.fetchall()

    for r in registrations:
        fmt_row(r, 'start_time', 'end_time', 'registered_at', 'check_in_time')
    return ok(data=registrations, **_page_payload(page, page_size, total))

@app.route('/api/create_event', methods=['POST'])
def create_event():
    user = require_user()
    if user['role'] not in ('organizer', 'admin'):
        raise AppError("只有组织者可以发布活动", code=403, http_status=403)

    data = request.get_json(silent=True) or {}
    with db_cursor(commit=True, action='发布活动', error_message='发布失败，请检查填写的时间格式是否正确') as cur:
        fields = _validated_event_fields(cur, data)
        cur.execute(
            """
            INSERT INTO events
                (title, description, organizer_id, venue_id, start_time, end_time, capacity, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'open')
            """,
            (fields['title'], fields['description'], user['user_id'], fields['venue_id'],
             fields['start_time'], fields['end_time'], fields['capacity']),
        )
        event_id = cur.lastrowid
        _apply_event_categories(cur, event_id, data.get('category_ids'))
    return ok("活动发布成功！", data={'event_id': event_id})


@app.route('/api/update_event/<int:event_id>', methods=['PUT'])
def update_event(event_id):
    user = require_user()

    data = request.get_json(silent=True) or {}
    with db_cursor(commit=True, action='编辑活动', error_message='保存失败，请检查填写的时间格式是否正确') as cur:
        _require_event_owner(cur, event_id, user, "无权编辑他人发布的活动")

        # 先锁活动行，后面的名额校验才读得到最新数据
        _lock_event(cur, event_id)
        cur.execute(
            "SELECT venue_id, start_time, end_time, "
            "(NOW() > start_time) AS started FROM events WHERE event_id = %s",
            (event_id,),
        )
        current = cur.fetchone()
        started = bool(current['started'])

        # 开始后不能改开始时间，否则等于把报名/签到重新放开
        if started and data.get('start_time'):
            new_start = _validate_datetime(data['start_time'], '开始时间')
            if new_start != _fmt_dt(current['start_time']):
                raise AppError("活动已开始，不能修改开始时间")

        # 已经开始了，就不用再要求开始时间在未来
        fields = _validated_event_fields(cur, data, require_future=not started,
                                        exclude_event_id=event_id, current=current)

        # 锁定读，别拿旧快照判容量
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM registrations "
            "WHERE event_id = %s AND status <> 'cancelled' FOR UPDATE",
            (event_id,),
        )
        active = cur.fetchone()['cnt']
        if fields['capacity'] < active:
            raise AppError(f"名额不能小于当前已报名人数（{active}）")

        cur.execute(
            """
            UPDATE events
               SET title = %s, description = %s, venue_id = %s,
                   start_time = %s, end_time = %s, capacity = %s
             WHERE event_id = %s
            """,
            (fields['title'], fields['description'], fields['venue_id'],
             fields['start_time'], fields['end_time'], fields['capacity'], event_id),
        )
        # 只有显式传了 category_ids 才动分类
        if 'category_ids' in data:
            _apply_event_categories(cur, event_id, data['category_ids'])
    return ok("活动已更新")


@app.route('/api/cancel_registration/<int:registration_id>', methods=['PUT'])
def cancel_registration(registration_id):
    user = require_user()

    with db_cursor(commit=True, action='取消报名', error_message='操作失败，请稍后重试') as cur:
        cur.execute(
            """
            SELECT r.status, r.student_id, e.organizer_id, (NOW() > e.start_time) AS started
            FROM registrations r
            JOIN events e ON r.event_id = e.event_id
            WHERE r.registration_id = %s
            FOR UPDATE
            """,
            (registration_id,),
        )
        reg = cur.fetchone()
        if not reg:
            raise AppError("找不到该报名记录", code=404, http_status=404)

        # 只有报名者本人、该活动的组织者或管理员才能取消
        if not is_admin(user) and user['user_id'] not in (reg['student_id'], reg['organizer_id']):
            raise AppError("无权取消该报名", code=403, http_status=403)

        if reg['status'] == 'cancelled':
            raise AppError("该报名已经取消过了")
        
        # 已签到是出席凭据，不能靠取消抹掉
        if reg['status'] == 'checked_in':
            raise AppError("该报名已签到，不能取消")
        
        # 活动开始后学生本人不能取消（组织者/管理员不受限）
        if reg['started'] and not is_admin(user):
            raise AppError("活动已开始，不能取消报名")

        cur.execute(
            "UPDATE registrations SET status = 'cancelled', "
            "cancelled_at = NOW(), cancelled_by = %s "
            "WHERE registration_id = %s AND status = 'registered'",
            (user['user_id'], registration_id),
        )
        if cur.rowcount != 1:
            raise AppError("该报名状态已变化，请刷新后重试", code=409, http_status=409)
    return ok("取消报名成功")


@app.route('/api/delete_event/<int:event_id>', methods=['DELETE'])
def delete_event(event_id):
    user = require_user()

    with db_cursor(commit=True, action='删除活动', error_message='删除失败，请稍后重试') as cur:
        _require_event_owner(cur, event_id, user, "无权删除他人发布的活动")
        # 加锁顺序和报名接口一致（先 events 后 registrations），避免死锁
        _lock_event(cur, event_id)

        # 有签到或已开始的活动，普通组织者不能删
        cur.execute(
            "SELECT (NOW() > start_time) AS started, "
            "       (SELECT COUNT(*) FROM registrations "
            "         WHERE event_id = %s AND status = 'checked_in') AS checked "
            "  FROM events WHERE event_id = %s",
            (event_id, event_id),
        )
        state = cur.fetchone()
        if state and state['checked']:
            raise AppError("该活动已有签到记录，不能删除", code=409, http_status=409)
        if state and state['started'] and not is_admin(user):
            raise AppError("活动已开始，不能删除", code=409, http_status=409)
        
        # 老库可能没配级联，先手动清关联数据
        cur.execute("DELETE FROM comments WHERE event_id = %s", (event_id,))
        cur.execute("DELETE FROM event_categories WHERE event_id = %s", (event_id,))
        cur.execute("DELETE FROM registrations WHERE event_id = %s", (event_id,))
        cur.execute("DELETE FROM events WHERE event_id = %s", (event_id,))
    return ok("活动已删除")


@app.route('/api/close_event/<int:event_id>', methods=['PUT'])
def close_event(event_id):
    user = require_user()

    data = request.get_json(silent=True) or {}
    action = (data.get('action') or 'close').strip().lower()
    # 前端传过 closed，这里兼容一下
    if action == 'closed':
        action = 'close'
    if action not in ('close', 'open'):
        raise AppError("无效的操作")

    new_status = 'closed' if action == 'close' else 'open'
    with db_cursor(commit=True, action='关闭/开放活动', error_message='操作失败，请稍后重试') as cur:
        _require_event_owner(cur, event_id, user, "无权操作该活动")

        if action == 'open':
            # 开始 / 结束之后不能再开放报名
            cur.execute(
                "SELECT (NOW() > start_time) AS started, "
                "(end_time IS NOT NULL AND NOW() > end_time) AS ended "
                "FROM events WHERE event_id = %s",
                (event_id,),
            )
            state = cur.fetchone()
            if state['ended']:
                raise AppError("活动已结束，无法重新开放报名")
            if state['started']:
                raise AppError("活动已经开始，无法重新开放报名")

        cur.execute(
            "UPDATE events SET status = %s WHERE event_id = %s",
            (new_status, event_id),
        )
    return ok("活动已关闭报名" if action == 'close' else "活动已重新开放")


@app.route('/api/remove_registration/<int:registration_id>', methods=['DELETE'])
def remove_registration(registration_id):
    user = require_user()

    with db_cursor(commit=True, action='移除报名', error_message='操作失败，请稍后重试') as cur:
        cur.execute(
            """
            SELECT r.status, e.organizer_id, (NOW() > e.start_time) AS started
            FROM registrations r
            JOIN events e ON r.event_id = e.event_id
            WHERE r.registration_id = %s
            FOR UPDATE
            """,
            (registration_id,),
        )
        reg = cur.fetchone()
        if not reg:
            raise AppError("找不到该报名记录", code=404, http_status=404)
        if not is_admin(user) and reg['organizer_id'] != user['user_id']:
            raise AppError("无权移除该报名", code=403, http_status=403)
        if reg['status'] == 'cancelled':
            raise AppError("该报名已经是取消状态")
        # 已签到不能移出
        if reg['status'] == 'checked_in':
            raise AppError("该学生已签到，不能移出")

        # 活动开始后不能移出学生（管理员可强制操作）
        if reg['started'] and not is_admin(user):
            raise AppError("活动已开始，不能移出学生")

        cur.execute(
            "UPDATE registrations SET status = 'cancelled', "
            "cancelled_at = NOW(), cancelled_by = %s "
            "WHERE registration_id = %s AND status = 'registered'",
            (user['user_id'], registration_id),
        )
        if cur.rowcount != 1:
            raise AppError("该报名状态已变化，请刷新后重试", code=409, http_status=409)
    return ok("已将该学生移出活动")


@app.route('/api/venues', methods=['GET'])
def get_venues():
    require_user()

    with db_cursor(action='查询场地') as cur:
        cur.execute(
            "SELECT venue_id, venue_name, location, capacity FROM venues "
            "WHERE available_status = 1"
        )
        venues = cur.fetchall()
    return ok(data=venues)



def _venue_fields(data):
    """校验并规整新增 / 修改场地的字段。"""
    name = (data.get('venue_name') or '').strip()
    location = (data.get('location') or '').strip()
    capacity = data.get('capacity')
    available = data.get('available_status', 1)

    if not name:
        raise AppError("请填写场地名称")
    if len(name) > 100:
        raise AppError("场地名称不能超过 100 个字符")
    if len(location) > 255:
        raise AppError("场地位置不能超过 255 个字符")

    try:
        capacity = int(capacity)
    except (TypeError, ValueError):
        raise AppError("场地容量必须是整数")
    if capacity <= 0:
        raise AppError("场地容量必须大于 0")

    if isinstance(available, bool):
        available = int(available)
    try:
        available = int(available)
    except (TypeError, ValueError):
        raise AppError("场地状态只能是 0（停用）或 1（可用）")
    if available not in (0, 1):
        raise AppError("场地状态只能是 0（停用）或 1（可用）")

    return {
        'venue_name': name,
        'location': location or None,
        'capacity': capacity,
        'available_status': available,
    }


def _ensure_venue_name_free(cur, name, exclude_id=0):
    """场地名有唯一约束，提前查一次给出明确的 409 提示。"""
    cur.execute(
        "SELECT venue_id FROM venues WHERE venue_name = %s AND venue_id <> %s",
        (name, exclude_id),
    )
    if cur.fetchone():
        raise AppError(f"场地「{name}」已存在", code=409, http_status=409)


def _load_venue_for_update(cur, venue_id):
    cur.execute(
        "SELECT venue_id, capacity FROM venues WHERE venue_id = %s FOR UPDATE",
        (venue_id,),
    )
    venue = cur.fetchone()
    if not venue:
        raise AppError("场地不存在", code=404, http_status=404)
    return venue


@app.route('/api/admin/venues', methods=['GET'])
def admin_list_venues():
    require_role('admin')

    with db_cursor(action='查询场地列表') as cur:
        cur.execute(
            """
            SELECT v.venue_id, v.venue_name, v.location, v.capacity,
                   v.available_status,
                   (SELECT COUNT(*) FROM events e WHERE e.venue_id = v.venue_id)
                       AS event_count
            FROM venues v
            ORDER BY v.venue_id ASC
            """
        )
        venues = cur.fetchall()

    for v in venues:
        v['available_status'] = int(v['available_status'] or 0)
    return ok(data=venues)


@app.route('/api/venues', methods=['POST'])
def create_venue():
    require_role('admin')
    fields = _venue_fields(request.get_json(silent=True) or {})

    with db_cursor(commit=True, action='新增场地') as cur:
        _ensure_venue_name_free(cur, fields['venue_name'])
        cur.execute(
            "INSERT INTO venues (venue_name, location, capacity, available_status) "
            "VALUES (%s, %s, %s, %s)",
            (fields['venue_name'], fields['location'],
             fields['capacity'], fields['available_status']),
        )
        venue_id = cur.lastrowid

    return ok("场地已添加", venue_id=venue_id)


@app.route('/api/venues/<int:venue_id>', methods=['PUT'])
def update_venue(venue_id):
    require_role('admin')
    fields = _venue_fields(request.get_json(silent=True) or {})

    with db_cursor(commit=True, action='修改场地') as cur:
        _load_venue_for_update(cur, venue_id)
        _ensure_venue_name_free(cur, fields['venue_name'], venue_id)

        # 容量不能缩到比已有活动的名额还小
        cur.execute(
            "SELECT MAX(capacity) AS max_capacity FROM events WHERE venue_id = %s",
            (venue_id,),
        )
        biggest = cur.fetchone()['max_capacity']
        if biggest and fields['capacity'] < biggest:
            raise AppError(
                f"该场地已有名额为 {biggest} 的活动，容量不能小于 {biggest}"
            )

        cur.execute(
            "UPDATE venues SET venue_name = %s, location = %s, "
            "capacity = %s, available_status = %s WHERE venue_id = %s",
            (fields['venue_name'], fields['location'], fields['capacity'],
             fields['available_status'], venue_id),
        )

    return ok("场地已更新")


# 管理员删场地：还有活动在用就不给删
@app.route('/api/venues/<int:venue_id>', methods=['DELETE'])
def delete_venue(venue_id):
    require_role('admin')

    with db_cursor(commit=True, action='删除场地') as cur:
        _load_venue_for_update(cur, venue_id)
        cur.execute(
            "SELECT COUNT(*) AS total FROM events WHERE venue_id = %s",
            (venue_id,),
        )
        total = cur.fetchone()['total']
        if total:
            raise AppError(
                f"该场地还有 {total} 个活动在用，不能删除，可以改成停用",
                code=409, http_status=409,
            )
        cur.execute("DELETE FROM venues WHERE venue_id = %s", (venue_id,))

    return ok("场地已删除")


@app.route('/api/categories', methods=['GET'])
def get_categories():
    require_user()

    with db_cursor(action='查询分类') as cur:
        cur.execute(
            "SELECT category_id, category_name, description "
            "FROM categories ORDER BY category_id ASC"
        )
        categories = cur.fetchall()
    return ok(data=categories)


# 学生签到
@app.route('/api/check_in/<int:registration_id>', methods=['PUT'])
def check_in(registration_id):
    user = require_user()

    with db_cursor(commit=True, action='签到', error_message='签到失败，请稍后重试') as cur:
        cur.execute(
            """
            SELECT r.status, e.organizer_id,
                   (NOW() < e.start_time) AS not_started,
                   (e.end_time IS NOT NULL AND NOW() > e.end_time) AS ended
            FROM registrations r
            JOIN events e ON r.event_id = e.event_id
            WHERE r.registration_id = %s
            FOR UPDATE
            """,
            (registration_id,),
        )
        reg = cur.fetchone()
        if not reg:
            raise AppError("找不到该报名记录", code=404, http_status=404)
        if not is_admin(user) and reg['organizer_id'] != user['user_id']:
            raise AppError("无权为他人活动签到", code=403, http_status=403)
        if reg['status'] == 'cancelled':
            raise AppError("该报名已取消，无法签到")
        if reg['status'] == 'checked_in':
            raise AppError("该学生已经签到过了")
        # 签到时间窗口：活动开始后 ~ 活动结束前
        if reg['not_started']:
            raise AppError("活动还未开始，无法签到")
        if reg['ended']:
            raise AppError("活动已结束，无法签到")

        cur.execute(
            "UPDATE registrations SET status = 'checked_in', check_in_time = NOW() "
            "WHERE registration_id = %s AND status = 'registered'",
            (registration_id,),
        )
        if cur.rowcount != 1:
            raise AppError("该报名状态已变化，请刷新后重试", code=409, http_status=409)
    return ok("签到成功！")


# 撤销签到（组织者签错了用来纠正）
@app.route('/api/undo_check_in/<int:registration_id>', methods=['PUT'])
def undo_check_in(registration_id):
    user = require_user()

    with db_cursor(commit=True, action='撤销签到', error_message='操作失败，请稍后重试') as cur:
        cur.execute(
            """
            SELECT r.status, e.organizer_id, (e.end_time IS NOT NULL AND NOW() > e.end_time) AS ended
            FROM registrations r
            JOIN events e ON r.event_id = e.event_id
            WHERE r.registration_id = %s
            FOR UPDATE
            """,
            (registration_id,),
        )
        reg = cur.fetchone()
        if not reg:
            raise AppError("找不到该报名记录", code=404, http_status=404)
        if not is_admin(user) and reg['organizer_id'] != user['user_id']:
            raise AppError("无权操作该活动的签到", code=403, http_status=403)
        if reg['status'] != 'checked_in':
            raise AppError("该学生尚未签到，无需撤销")
        
        # 活动结束后不能撤销签到（管理员可强制纠正）
        if reg['ended'] and not is_admin(user):
            raise AppError("活动已结束，不能撤销签到")

        cur.execute(
            "UPDATE registrations SET status = 'registered', check_in_time = NULL "
            "WHERE registration_id = %s AND status = 'checked_in'",
            (registration_id,),
        )
        if cur.rowcount != 1:
            raise AppError("该报名状态已变化，请刷新后重试", code=409, http_status=409)
    return ok("已撤销签到")


@app.route('/api/event_registrations/<int:event_id>', methods=['GET'])
def get_event_registrations(event_id):
    user = require_user()
    page, page_size, offset = _pagination(DEFAULT_LIST_PAGE_SIZE)
    # ?include_cancelled=1 时连取消掉的报名一起返回
    include_cancelled = request.args.get('include_cancelled') in ('1', 'true', 'yes')
    status_where = '' if include_cancelled else " AND r.status <> 'cancelled'"

    with db_cursor(action='查询报名名单') as cur:
        _require_event_owner(cur, event_id, user, "无权查看该活动的报名名单")

        cur.execute(
            "SELECT COUNT(*) AS total FROM registrations r "
            "WHERE r.event_id = %s" + status_where,
            (event_id,),
        )
        total = cur.fetchone()['total']

        cur.execute(
            f"""
            SELECT
                r.registration_id,
                r.status AS registration_status,
                r.registered_at,
                r.check_in_time,
                r.cancelled_at,
                r.cancelled_by,
                cu.name AS cancelled_by_name,
                u.user_id,
                u.name AS student_name,
                u.email AS student_email
            FROM registrations r
            JOIN users u ON r.student_id = u.user_id
            LEFT JOIN users cu ON r.cancelled_by = cu.user_id
            WHERE r.event_id = %s{status_where}
            ORDER BY r.registered_at ASC, r.registration_id ASC
            LIMIT %s OFFSET %s
            """,
            (event_id, page_size, offset),
        )
        registrations = cur.fetchall()

    for r in registrations:
        fmt_row(r, 'registered_at', 'check_in_time', 'cancelled_at')
    return ok(data=registrations, **_page_payload(page, page_size, total))


@app.route('/api/comments/<int:event_id>', methods=['GET'])
def get_comments(event_id):
    require_user()
    page, page_size, offset = _pagination(DEFAULT_LIST_PAGE_SIZE)

    with db_cursor(action='查询评论') as cur:
        cur.execute("SELECT event_id FROM events WHERE event_id = %s", (event_id,))
        if not cur.fetchone():
            raise AppError("活动不存在", code=404, http_status=404)

        cur.execute(
            "SELECT COUNT(*) AS total FROM comments WHERE event_id = %s",
            (event_id,),
        )
        total = cur.fetchone()['total']

        cur.execute(
            """
            SELECT
                c.comment_id,
                c.content,
                c.created_at,
                u.user_id,
                u.name AS user_name,
                u.role AS user_role
            FROM comments c
            JOIN users u ON c.user_id = u.user_id
            WHERE c.event_id = %s
            ORDER BY c.created_at DESC, c.comment_id DESC
            LIMIT %s OFFSET %s
            """,
            (event_id, page_size, offset),
        )
        comments = cur.fetchall()

    for c in comments:
        fmt_row(c, 'created_at')
    return ok(data=comments, **_page_payload(page, page_size, total))


@app.route('/api/comments', methods=['POST'])
def post_comment():
    user = require_user()

    data = request.get_json(silent=True) or {}
    event_id = data.get('event_id')
    content = (data.get('content') or '').strip()
    if not event_id or not content:
        raise AppError("评论内容不能为空")
    if len(content) > 500:
        raise AppError("评论不能超过 500 字")
    rate_limit(f'comment:{user["user_id"]}', COMMENT_RATE_LIMIT, "评论过于频繁")

    with db_cursor(commit=True, action='发表评论', error_message='评论失败，请稍后重试') as cur:
        cur.execute(
            "SELECT event_id, organizer_id FROM events WHERE event_id = %s",
            (event_id,),
        )
        event = cur.fetchone()
        if not event:
            raise AppError("活动不存在", code=404, http_status=404)

        # 只有报名过的学生、活动组织者和管理员能评论
        if not is_admin(user) and user['user_id'] != event['organizer_id']:
            cur.execute(
                "SELECT 1 FROM registrations "
                "WHERE event_id = %s AND student_id = %s AND status <> 'cancelled' LIMIT 1",
                (event_id, user['user_id']),
            )
            if not cur.fetchone():
                raise AppError("只有报名过该活动的同学才能评论", code=403, http_status=403)

        cur.execute(
            "INSERT INTO comments (event_id, user_id, content) VALUES (%s, %s, %s)",
            (event_id, user['user_id'], content),
        )
    return ok("评论成功")


@app.route('/api/delete_comment/<int:comment_id>', methods=['DELETE'])
def delete_comment(comment_id):
    user = require_user()

    with db_cursor(commit=True, action='删除评论', error_message='删除失败，请稍后重试') as cur:
        cur.execute(
            """
            SELECT c.user_id AS comment_author, e.organizer_id
            FROM comments c
            JOIN events e ON c.event_id = e.event_id
            WHERE c.comment_id = %s
            """,
            (comment_id,),
        )
        comment = cur.fetchone()
        if not comment:
            raise AppError("评论不存在", code=404, http_status=404)
        if not is_admin(user) and user['user_id'] not in (comment['comment_author'], comment['organizer_id']):
            raise AppError("无权删除该评论", code=403, http_status=403)

        cur.execute("DELETE FROM comments WHERE comment_id = %s", (comment_id,))
    return ok("评论已删除")


@app.route('/api/me', methods=['GET'])
def me():
    user = require_user()
    return ok(data=user)


# 退出登录：token_version + 1，所有设备上的旧令牌一起失效
@app.route('/api/logout', methods=['POST'])
def logout():
    user = require_user()
    with db_cursor(commit=True, action='退出登录', error_message='操作失败，请稍后重试') as cur:
        cur.execute(
            "UPDATE users SET token_version = token_version + 1 WHERE user_id = %s",
            (user['user_id'],),
        )
    return ok("已退出登录")


@app.route('/api/change_password', methods=['PUT'])
def change_password():
    user = require_user()
    data = request.get_json(silent=True) or {}
    old_password = data.get('old_password') or ''
    new_password = data.get('new_password') or ''

    if not old_password or not new_password:
        raise AppError("旧密码和新密码不能为空")
    password_ok, password_msg = validate_password(new_password)
    if not password_ok:
        raise AppError(password_msg)
    if old_password == new_password:
        raise AppError("新密码不能与旧密码相同")

    with db_cursor(commit=True, action='修改密码', error_message='操作失败，请稍后重试') as cur:
        cur.execute(
            "SELECT password_hash, token_version FROM users WHERE user_id = %s FOR UPDATE",
            (user['user_id'],),
        )
        row = cur.fetchone()
        if not row or not bcrypt.checkpw(old_password.encode('utf-8'), row['password_hash'].encode('utf-8')):
            raise AppError("旧密码不正确")

        hashed = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cur.execute(
            "UPDATE users SET password_hash = %s, token_version = token_version + 1 "
            "WHERE user_id = %s",
            (hashed, user['user_id']),
        )
        new_version = int(row['token_version'] or 0) + 1
    return ok("密码已修改，请使用新密码重新登录", token=issue_token(user['user_id'], new_version))


@app.route('/api/admin/users', methods=['GET'])
def admin_list_users():
    require_role('admin')
    page, page_size, offset = _pagination(50)

    with db_cursor(action='查询用户列表') as cur:
        cur.execute("SELECT COUNT(*) AS total FROM users")
        total = cur.fetchone()['total']
        cur.execute(
            """
            SELECT user_id, name, email, role, created_at
            FROM users
            ORDER BY user_id ASC
            LIMIT %s OFFSET %s
            """,
            (page_size, offset),
        )
        users = cur.fetchall()

    for u in users:
        fmt_row(u, 'created_at')
    return ok(data=users, **_page_payload(page, page_size, total))


@app.route('/api/admin/users/<int:user_id>/role', methods=['PUT'])
def admin_set_user_role(user_id):
    admin = require_role('admin')

    role = (request.get_json(silent=True) or {}).get('role')
    if role not in ('organizer', 'admin'):
        raise AppError("角色只能是 organizer 或 admin")
    # 不能改自己，这样系统里至少留一个管理员
    if user_id == admin['user_id']:
        raise AppError("不能修改自己的角色")

    with db_cursor(commit=True, action='修改用户角色') as cur:
        cur.execute(
            "SELECT user_id, name, role FROM users WHERE user_id = %s",
            (user_id,),
        )
        target = cur.fetchone()
        if not target:
            raise AppError("用户不存在", code=404, http_status=404)
        if target['role'] == role:
            return ok("角色未变化")
        # 只允许组织者和管理员之间互相切换
        if (target['role'], role) not in (('organizer', 'admin'), ('admin', 'organizer')):
            raise AppError("学生不能直接设为管理员，请让他以组织者身份注册后再提权")

        cur.execute("UPDATE users SET role = %s WHERE user_id = %s", (role, user_id))

    label = '管理员' if role == 'admin' else '组织者'
    return ok(f"已把「{target['name']}」设为{label}")


@app.route('/')
def index_page():
    return send_from_directory(FRONTEND_DIR, 'login.html')


@app.errorhandler(404)
def handle_404(e):
    if request.path.startswith('/api/'):
        return fail("接口不存在", code=404, http_status=404)
    # 非 API 路径：返回登录页，但状态码仍然是 404
    return send_from_directory(FRONTEND_DIR, 'login.html'), 404


@app.errorhandler(405)
def handle_405(e):
    return fail("请求方法不被允许", code=405, http_status=405)


@app.errorhandler(500)
def handle_500(e):
    return fail("服务器内部错误", code=500, http_status=500)


if __name__ == '__main__':
    if not os.environ.get('DB_PASSWORD'):
        print("[警告] 环境变量 DB_PASSWORD 未设置，请参考 .env.example 配置后再启动。")
    app.run(debug=DEBUG, port=int(os.environ.get('PORT', '5000')))

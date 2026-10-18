"""
校园活动报名与管理系统 - 后端主程序（修改版）

相对原始版本的改动要点：
1. 数据库凭据 / 应用密钥全部从环境变量读取，不再硬编码。
2. 引入基于签名令牌（Bearer Token）的身份认证，服务端从令牌推导 user_id，
   不再信任前端传来的 user_id / organizer_id。
3. 报名接口改为「事务 + 行锁（SELECT ... FOR UPDATE）」，杜绝并发超卖。
4. 时间判断交给数据库 NOW()，避免 Python 与 MySQL 时钟/时区不一致。
5. 统一连接管理（用完必关）、统一 JSON 错误响应、异常不再回显内部信息。
6. 补齐输入校验：邮箱格式、角色白名单、活动时间与容量、场地存在性等。
7. 活动列表补充「已报名人数 / 剩余名额」。
"""

import os
import re
from contextlib import closing

import bcrypt
import mysql.connector
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

# 可选：如果安装了 python-dotenv，则自动加载同目录下的 .env（便于本地开发）
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
except ImportError:
    pass

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'frontend')

# ================= 配置：凭据只来自环境变量 =================
db_config = {
    'host': os.environ.get('DB_HOST', '127.0.0.1'),
    'port': int(os.environ.get('DB_PORT', '3306')),
    'user': os.environ.get('DB_USER', 'root'),
    'password': os.environ.get('DB_PASSWORD'),          # 必填，见 .env.example
    'database': os.environ.get('DB_NAME', 'campus_events'),
    'charset': 'utf8mb4',
}
APP_SECRET_KEY = os.environ.get('APP_SECRET_KEY')       # 必填，见 .env.example
TOKEN_MAX_AGE = int(os.environ.get('TOKEN_MAX_AGE', '86400'))  # 令牌有效期（秒），默认 24 小时
DEBUG = os.environ.get('FLASK_DEBUG', '0') == '1'       # 默认关闭调试模式

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
ALLOWED_REGISTER_ROLES = ('student', 'organizer')       # 不允许自助注册 admin

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path='')
app.config['SECRET_KEY'] = APP_SECRET_KEY or 'insecure-dev-key-change-me'
app.json.ensure_ascii = False
CORS(app, allow_headers=['Content-Type', 'Authorization'])

serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='campus-events-auth')


@app.after_request
def add_no_cache_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


# ================= 基础工具 =================
def get_conn():
    """新建一个数据库连接。调用方负责关闭。"""
    return mysql.connector.connect(**db_config)


def issue_token(user_id):
    """为用户签发令牌。"""
    return serializer.dumps({'uid': user_id})


def load_user(user_id):
    """按主键读取用户（只取安全字段）。"""
    with closing(get_conn()) as conn, closing(conn.cursor(dictionary=True)) as cur:
        cur.execute(
            "SELECT user_id, name, email, role, created_at FROM Users WHERE user_id = %s",
            (user_id,),
        )
        return cur.fetchone()


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
    return load_user(payload.get('uid'))


def require_user():
    """要求已登录。返回 (user, None) 或 (None, error_response)。"""
    user = auth_user()
    if not user:
        return None, (jsonify({"code": 401, "message": "未登录或登录已过期，请重新登录"}), 401)
    return user, None


def require_role(role):
    """要求已登录且角色匹配。"""
    user, err = require_user()
    if err:
        return None, err
    if user['role'] != role:
        return None, (jsonify({"code": 403, "message": "权限不足"}), 403)
    return user, None


def fail(message, code=400, http_status=400):
    return jsonify({"code": code, "message": message}), http_status


def ok(message=None, **extra):
    payload = {"code": 200}
    if message:
        payload["message"] = message
    payload.update(extra)
    return jsonify(payload)


def fmt_row(row, *fields, time_fmt='%Y-%m-%d %H:%M:%S'):
    """把行内的 datetime 字段格式化成字符串，便于前端直接展示。"""
    for f in fields:
        if row.get(f) is not None:
            try:
                row[f] = row[f].strftime(time_fmt)
            except AttributeError:
                row[f] = str(row[f])
    return row


# ================= 1. 用户注册 =================
@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    role = data.get('role', 'student')

    if not name or not email or not password:
        return fail("姓名、邮箱和密码不能为空")
    if not EMAIL_RE.match(email):
        return fail("邮箱格式不正确")
    if role not in ALLOWED_REGISTER_ROLES:
        return fail("注册身份不合法")
    if len(password) < 8:
        return fail("密码长度不能少于 8 位")
    if not any(c.isupper() for c in password):
        return fail("密码必须包含至少一个大写字母")
    if not any(c.islower() for c in password):
        return fail("密码必须包含至少一个小写字母")
    if not any(c.isdigit() for c in password):
        return fail("密码必须包含至少一个数字")

    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    conn = get_conn()
    try:
        with closing(conn.cursor()) as cur:
            cur.execute(
                "INSERT INTO Users (name, email, password_hash, role) VALUES (%s, %s, %s, %s)",
                (name, email, hashed, role),
            )
        conn.commit()
    except mysql.connector.Error as err:
        conn.rollback()
        if err.errno == 1062:
            return fail("该邮箱已被注册")
        app.logger.exception("注册失败")
        return fail("注册失败，请稍后重试", code=500, http_status=500)
    finally:
        conn.close()
    return ok("注册成功！")


# ================= 2. 用户登录 =================
@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not email or not password:
        return fail("邮箱和密码不能为空")

    conn = get_conn()
    try:
        with closing(conn.cursor(dictionary=True)) as cur:
            cur.execute("SELECT * FROM Users WHERE email = %s", (email,))
            user = cur.fetchone()
    except mysql.connector.Error:
        app.logger.exception("登录查询失败")
        return fail("服务异常，请稍后重试", code=500, http_status=500)
    finally:
        conn.close()

    # 统一提示，避免暴露「邮箱是否存在」
    if not user or not bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
        return fail("邮箱或密码错误")

    user.pop('password_hash', None)
    return ok("登录成功", data=user, token=issue_token(user['user_id']))


# ================= 3. 获取活动列表 =================
@app.route('/api/events', methods=['GET'])
def get_events():
    user, err = require_user()
    if err:
        return err

    sql = """
        SELECT
            e.event_id, e.title, e.description, e.organizer_id, e.venue_id,
            e.start_time, e.end_time, e.capacity, e.status,
            v.venue_name, v.location AS venue_location,
            (SELECT COUNT(*) FROM Registrations r
              WHERE r.event_id = e.event_id AND r.status <> 'cancelled') AS registered_count,
            (SELECT COUNT(*) FROM Registrations r
              WHERE r.event_id = e.event_id AND r.student_id = %s
                AND r.status <> 'cancelled') AS is_registered
        FROM Events e
        LEFT JOIN Venues v ON e.venue_id = v.venue_id
        ORDER BY e.start_time ASC
    """
    conn = get_conn()
    try:
        with closing(conn.cursor(dictionary=True)) as cur:
            cur.execute(sql, (user['user_id'],))
            events = cur.fetchall()
    except mysql.connector.Error:
        app.logger.exception("查询活动列表失败")
        return fail("服务异常，请稍后重试", code=500, http_status=500)
    finally:
        conn.close()

    for e in events:
        fmt_row(e, 'start_time', 'end_time')
        registered = int(e.get('registered_count') or 0)
        capacity = int(e.get('capacity') or 0)
        e['remaining'] = max(capacity - registered, 0)
    return ok(data=events)


# ================= 4. 学生报名活动（事务 + 行锁） =================
@app.route('/api/register_event', methods=['POST'])
def register_event():
    user, err = require_user()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    event_id = data.get('event_id')
    if not event_id:
        return fail("活动ID不能为空")

    conn = get_conn()
    try:
        conn.start_transaction()
        with closing(conn.cursor(dictionary=True)) as cur:
            # 锁住该活动行，容量校验与写入在同一事务内完成，避免并发超卖
            cur.execute(
                """
                SELECT capacity, status,
                       (NOW() > start_time) AS started,
                       (end_time IS NOT NULL AND NOW() > end_time) AS ended
                FROM Events WHERE event_id = %s FOR UPDATE
                """,
                (event_id,),
            )
            event = cur.fetchone()
            if not event:
                conn.rollback()
                return fail("活动不存在", code=404, http_status=404)
            if event['status'] != 'open':
                conn.rollback()
                return fail("活动已关闭，无法报名")
            if event['ended']:
                conn.rollback()
                return fail("活动已结束，无法报名")
            if event['started']:
                conn.rollback()
                return fail("活动已经开始，无法报名")

            cur.execute(
                "SELECT registration_id, status FROM Registrations "
                "WHERE student_id = %s AND event_id = %s FOR UPDATE",
                (user['user_id'], event_id),
            )
            existing = cur.fetchone()

            if existing and existing['status'] != 'cancelled':
                conn.rollback()
                return fail("你已经报名过该活动了，请勿重复报名")

            cur.execute(
                "SELECT COUNT(*) AS cnt FROM Registrations "
                "WHERE event_id = %s AND status <> 'cancelled'",
                (event_id,),
            )
            registered_count = cur.fetchone()['cnt']
            if registered_count >= (event['capacity'] or 0):
                conn.rollback()
                return fail("活动名额已满，报名失败")

            if existing:
                cur.execute(
                    "UPDATE Registrations SET status = 'registered', registered_at = NOW(), "
                    "check_in_time = NULL WHERE registration_id = %s",
                    (existing['registration_id'],),
                )
                message = "重新报名成功！"
            else:
                cur.execute(
                    "INSERT INTO Registrations (student_id, event_id, status) "
                    "VALUES (%s, %s, 'registered')",
                    (user['user_id'], event_id),
                )
                message = "报名成功！"
        conn.commit()
        return ok(message)
    except mysql.connector.Error:
        try:
            conn.rollback()
        except mysql.connector.Error:
            pass
        app.logger.exception("报名失败")
        return fail("报名失败，请稍后重试", code=500, http_status=500)
    finally:
        conn.close()


# ================= 5. 获取个人报名记录 =================
@app.route('/api/user_registrations/<int:user_id>', methods=['GET'])
def get_user_registrations(user_id):
    user, err = require_user()
    if err:
        return err
    if user_id != user['user_id']:
        return fail("无权查看他人报名记录", code=403, http_status=403)

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
        FROM Registrations r
        JOIN Events e ON r.event_id = e.event_id
        LEFT JOIN Venues v ON e.venue_id = v.venue_id
        WHERE r.student_id = %s
        ORDER BY r.registered_at DESC
    """
    conn = get_conn()
    try:
        with closing(conn.cursor(dictionary=True)) as cur:
            cur.execute(sql, (user_id,))
            registrations = cur.fetchall()
    except mysql.connector.Error:
        app.logger.exception("查询报名记录失败")
        return fail("服务异常，请稍后重试", code=500, http_status=500)
    finally:
        conn.close()

    for r in registrations:
        fmt_row(r, 'start_time', 'end_time', 'registered_at', 'check_in_time')
    return ok(data=registrations)


# ================= 6. 组织者发布活动 =================
@app.route('/api/create_event', methods=['POST'])
def create_event():
    user, err = require_role('organizer')
    if err:
        return err

    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    description = (data.get('description') or '').strip()
    venue_id = data.get('venue_id')
    start_time = data.get('start_time')
    end_time = data.get('end_time')
    capacity = data.get('capacity')

    # 前端 datetime-local 控件提交的是 'YYYY-MM-DDTHH:MM'，统一成 MySQL 认可的格式
    if isinstance(start_time, str):
        start_time = start_time.replace('T', ' ').strip()
    if isinstance(end_time, str):
        end_time = end_time.replace('T', ' ').strip()

    if not all([title, venue_id, start_time, end_time, capacity]):
        return fail("请填写所有必填字段")
    try:
        capacity = int(capacity)
    except (TypeError, ValueError):
        return fail("名额必须是整数")
    if capacity <= 0:
        return fail("名额必须大于 0")

    conn = get_conn()
    try:
        with closing(conn.cursor(dictionary=True)) as cur:
            cur.execute(
                "SELECT venue_id, capacity FROM Venues WHERE venue_id = %s", (venue_id,)
            )
            venue = cur.fetchone()
            if not venue:
                return fail("所选场地不存在")
            if venue['capacity'] is not None and capacity > venue['capacity']:
                return fail(f"名额超过了场地容量（{venue['capacity']}）")

            # 时间校验交给数据库：结束时间必须晚于开始时间
            cur.execute(
                "SELECT (CAST(%s AS DATETIME) < CAST(%s AS DATETIME)) AS ok_time",
                (start_time, end_time),
            )
            if not cur.fetchone()['ok_time']:
                return fail("结束时间必须晚于开始时间")

            cur.execute(
                """
                INSERT INTO Events
                    (title, description, organizer_id, venue_id, start_time, end_time, capacity, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'open')
                """,
                (title, description, user['user_id'], venue_id, start_time, end_time, capacity),
            )
        conn.commit()
        return ok("活动发布成功！")
    except mysql.connector.Error:
        conn.rollback()
        app.logger.exception("发布活动失败")
        return fail("发布失败，请检查填写的时间格式是否正确", code=500, http_status=500)
    finally:
        conn.close()


# ================= 7. 取消报名 =================
@app.route('/api/cancel_registration/<int:registration_id>', methods=['PUT'])
def cancel_registration(registration_id):
    user, err = require_user()
    if err:
        return err

    conn = get_conn()
    try:
        with closing(conn.cursor(dictionary=True)) as cur:
            cur.execute(
                """
                SELECT r.status, r.student_id, e.organizer_id
                FROM Registrations r
                JOIN Events e ON r.event_id = e.event_id
                WHERE r.registration_id = %s
                """,
                (registration_id,),
            )
            reg = cur.fetchone()
            if not reg:
                return fail("找不到该报名记录", code=404, http_status=404)

            # 只有报名者本人或该活动的组织者才能取消
            if user['user_id'] not in (reg['student_id'], reg['organizer_id']):
                return fail("无权取消该报名", code=403, http_status=403)

            if reg['status'] == 'cancelled':
                return fail("该报名已经取消过了")

            cur.execute(
                "UPDATE Registrations SET status = 'cancelled' WHERE registration_id = %s",
                (registration_id,),
            )
        conn.commit()
        return ok("取消报名成功")
    except mysql.connector.Error:
        conn.rollback()
        app.logger.exception("取消报名失败")
        return fail("操作失败，请稍后重试", code=500, http_status=500)
    finally:
        conn.close()


# ================= 8. 组织者删除活动 =================
@app.route('/api/delete_event/<int:event_id>', methods=['DELETE'])
def delete_event(event_id):
    user, err = require_role('organizer')
    if err:
        return err

    conn = get_conn()
    try:
        with closing(conn.cursor(dictionary=True)) as cur:
            cur.execute("SELECT organizer_id FROM Events WHERE event_id = %s", (event_id,))
            event = cur.fetchone()
            if not event:
                return fail("活动不存在", code=404, http_status=404)
            if event['organizer_id'] != user['user_id']:
                return fail("无权删除他人发布的活动", code=403, http_status=403)

            # 兼容旧版未加级联的库：先显式清理关联数据，再删除活动
            cur.execute("DELETE FROM Comments WHERE event_id = %s", (event_id,))
            cur.execute("DELETE FROM Event_Categories WHERE event_id = %s", (event_id,))
            cur.execute("DELETE FROM Registrations WHERE event_id = %s", (event_id,))
            cur.execute("DELETE FROM Events WHERE event_id = %s", (event_id,))
        conn.commit()
        return ok("活动已删除")
    except mysql.connector.Error:
        conn.rollback()
        app.logger.exception("删除活动失败")
        return fail("删除失败，请稍后重试", code=500, http_status=500)
    finally:
        conn.close()


# ================= 9. 获取所有场地 =================
@app.route('/api/venues', methods=['GET'])
def get_venues():
    user, err = require_user()
    if err:
        return err

    conn = get_conn()
    try:
        with closing(conn.cursor(dictionary=True)) as cur:
            cur.execute(
                "SELECT venue_id, venue_name, location, capacity FROM Venues "
                "WHERE available_status = 1"
            )
            venues = cur.fetchall()
    except mysql.connector.Error:
        app.logger.exception("查询场地失败")
        return fail("服务异常，请稍后重试", code=500, http_status=500)
    finally:
        conn.close()
    return ok(data=venues)


# ================= 10. 学生签到（仅活动组织者可操作） =================
@app.route('/api/check_in/<int:registration_id>', methods=['PUT'])
def check_in(registration_id):
    user, err = require_user()
    if err:
        return err

    conn = get_conn()
    try:
        with closing(conn.cursor(dictionary=True)) as cur:
            cur.execute(
                """
                SELECT r.status, e.organizer_id
                FROM Registrations r
                JOIN Events e ON r.event_id = e.event_id
                WHERE r.registration_id = %s
                """,
                (registration_id,),
            )
            reg = cur.fetchone()
            if not reg:
                return fail("找不到该报名记录", code=404, http_status=404)
            if reg['organizer_id'] != user['user_id']:
                return fail("无权为他人活动签到", code=403, http_status=403)
            if reg['status'] == 'cancelled':
                return fail("该报名已取消，无法签到")
            if reg['status'] == 'checked_in':
                return fail("该学生已经签到过了")

            cur.execute(
                "UPDATE Registrations SET status = 'checked_in', check_in_time = NOW() "
                "WHERE registration_id = %s",
                (registration_id,),
            )
        conn.commit()
        return ok("签到成功！")
    except mysql.connector.Error:
        conn.rollback()
        app.logger.exception("签到失败")
        return fail("签到失败，请稍后重试", code=500, http_status=500)
    finally:
        conn.close()


# ================= 11. 获取活动报名名单（仅组织者本人） =================
@app.route('/api/event_registrations/<int:event_id>', methods=['GET'])
def get_event_registrations(event_id):
    user, err = require_user()
    if err:
        return err

    conn = get_conn()
    try:
        with closing(conn.cursor(dictionary=True)) as cur:
            cur.execute("SELECT organizer_id FROM Events WHERE event_id = %s", (event_id,))
            event = cur.fetchone()
            if not event:
                return fail("活动不存在", code=404, http_status=404)
            if event['organizer_id'] != user['user_id']:
                return fail("无权查看该活动的报名名单", code=403, http_status=403)

            cur.execute(
                """
                SELECT
                    r.registration_id,
                    r.status AS registration_status,
                    r.registered_at,
                    r.check_in_time,
                    u.user_id,
                    u.name AS student_name,
                    u.email AS student_email
                FROM Registrations r
                JOIN Users u ON r.student_id = u.user_id
                WHERE r.event_id = %s AND r.status <> 'cancelled'
                ORDER BY r.registered_at ASC
                """,
                (event_id,),
            )
            registrations = cur.fetchall()
    except mysql.connector.Error:
        app.logger.exception("查询报名名单失败")
        return fail("服务异常，请稍后重试", code=500, http_status=500)
    finally:
        conn.close()

    for r in registrations:
        fmt_row(r, 'registered_at', 'check_in_time')
    return ok(data=registrations)


# ================= 12. 获取活动评论 =================
@app.route('/api/comments/<int:event_id>', methods=['GET'])
def get_comments(event_id):
    user, err = require_user()
    if err:
        return err

    conn = get_conn()
    try:
        with closing(conn.cursor(dictionary=True)) as cur:
            cur.execute(
                """
                SELECT
                    c.comment_id,
                    c.content,
                    c.created_at,
                    u.user_id,
                    u.name AS user_name,
                    u.role AS user_role
                FROM Comments c
                JOIN Users u ON c.user_id = u.user_id
                WHERE c.event_id = %s
                ORDER BY c.created_at DESC
                """,
                (event_id,),
            )
            comments = cur.fetchall()
    except mysql.connector.Error:
        app.logger.exception("查询评论失败")
        return fail("服务异常，请稍后重试", code=500, http_status=500)
    finally:
        conn.close()

    for c in comments:
        fmt_row(c, 'created_at')
    return ok(data=comments)


# ================= 13. 发表评论 =================
@app.route('/api/comments', methods=['POST'])
def post_comment():
    user, err = require_user()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    event_id = data.get('event_id')
    content = (data.get('content') or '').strip()
    if not event_id or not content:
        return fail("评论内容不能为空")
    if len(content) > 500:
        return fail("评论不能超过 500 字")

    conn = get_conn()
    try:
        with closing(conn.cursor(dictionary=True)) as cur:
            cur.execute("SELECT event_id FROM Events WHERE event_id = %s", (event_id,))
            if not cur.fetchone():
                return fail("活动不存在", code=404, http_status=404)
            cur.execute(
                "INSERT INTO Comments (event_id, user_id, content) VALUES (%s, %s, %s)",
                (event_id, user['user_id'], content),
            )
        conn.commit()
        return ok("评论成功")
    except mysql.connector.Error:
        conn.rollback()
        app.logger.exception("发表评论失败")
        return fail("评论失败，请稍后重试", code=500, http_status=500)
    finally:
        conn.close()


# ================= 14. 删除评论（作者本人或活动组织者） =================
@app.route('/api/delete_comment/<int:comment_id>', methods=['DELETE'])
def delete_comment(comment_id):
    user, err = require_user()
    if err:
        return err

    conn = get_conn()
    try:
        with closing(conn.cursor(dictionary=True)) as cur:
            cur.execute(
                """
                SELECT c.user_id AS comment_author, e.organizer_id
                FROM Comments c
                JOIN Events e ON c.event_id = e.event_id
                WHERE c.comment_id = %s
                """,
                (comment_id,),
            )
            comment = cur.fetchone()
            if not comment:
                return fail("评论不存在", code=404, http_status=404)
            if user['user_id'] not in (comment['comment_author'], comment['organizer_id']):
                return fail("无权删除该评论", code=403, http_status=403)

            cur.execute("DELETE FROM Comments WHERE comment_id = %s", (comment_id,))
        conn.commit()
        return ok("评论已删除")
    except mysql.connector.Error:
        conn.rollback()
        app.logger.exception("删除评论失败")
        return fail("删除失败，请稍后重试", code=500, http_status=500)
    finally:
        conn.close()


# ================= 15. 当前登录用户信息 =================
@app.route('/api/me', methods=['GET'])
def me():
    user, err = require_user()
    if err:
        return err
    return ok(data=user)


# ================= 前端页面托管 =================
@app.route('/')
def index_page():
    return send_from_directory(FRONTEND_DIR, 'login.html')


# ================= 统一错误响应（API 一律返回 JSON） =================
@app.errorhandler(404)
def handle_404(e):
    if request.path.startswith('/api/'):
        return fail("接口不存在", code=404, http_status=404)
    return send_from_directory(FRONTEND_DIR, 'login.html')


@app.errorhandler(405)
def handle_405(e):
    return fail("请求方法不被允许", code=405, http_status=405)


@app.errorhandler(500)
def handle_500(e):
    return fail("服务器内部错误", code=500, http_status=500)


if __name__ == '__main__':
    for key in ('DB_PASSWORD', 'APP_SECRET_KEY'):
        if not os.environ.get(key):
            print(f"[警告] 环境变量 {key} 未设置，请参考 .env.example 配置后再启动。")
    app.run(debug=DEBUG, port=int(os.environ.get('PORT', '5000')))

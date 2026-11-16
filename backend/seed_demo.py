"""生成演示数据：1 管理员、2 组织者、3 学生 + 3 个不同状态的活动 + 报名/签到/评论。

用法：
    python backend/seed_demo.py

默认密码都是 Passw0rd123。可重复运行：
- 用户按 email 幂等；
- 活动按 title 幂等，但每次会把时间刷新为「相对当前时刻」，方便演示；
- 报名/评论只在不存在时插入。
"""

import os
import sys
from pathlib import Path

import bcrypt
import mysql.connector

PROJECT_ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / '.env')
except ImportError:
    pass

DEMO_PASSWORD = 'Passw0rd123'

USERS = [
    ('演示管理员', 'demo_admin@example.com', 'admin'),
    ('演示组织者A', 'demo_org_a@example.com', 'organizer'),
    ('演示组织者B', 'demo_org_b@example.com', 'organizer'),
    ('演示学生1', 'demo_stu_1@example.com', 'student'),
    ('演示学生2', 'demo_stu_2@example.com', 'student'),
    ('演示学生3', 'demo_stu_3@example.com', 'student'),
]


def connect():
    cfg = dict(
        host=os.environ.get('DB_HOST', '127.0.0.1'),
        port=int(os.environ.get('DB_PORT', '3306')),
        user=os.environ.get('DB_USER'),
        password=os.environ.get('DB_PASSWORD'),
        database=os.environ.get('DB_NAME', 'campus_events'),
        charset='utf8mb4',
    )
    if not cfg['user'] or not cfg['password']:
        print('[错误] 请先在 .env 中配置 DB_USER / DB_PASSWORD')
        sys.exit(1)
    return mysql.connector.connect(**cfg)


def ensure_tables(cur):
    cur.execute(
        "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN ('users','events','categories')"
    )
    if cur.fetchone()[0] < 3:
        print('[错误] 数据库表未初始化，请先执行：python backend/init_db.py')
        sys.exit(1)


def upsert_users(cur, pwd_hash):
    for name, email, role in USERS:
        cur.execute(
            "INSERT INTO Users (name, email, password_hash, role) "
            "VALUES (%s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE name=VALUES(name), "
            "password_hash=VALUES(password_hash), role=VALUES(role)",
            (name, email, pwd_hash, role),
        )


def uid(cur, email):
    cur.execute("SELECT user_id FROM Users WHERE email = %s", (email,))
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f'用户不存在：{email}')
    return row[0]


def pick_venues(cur):
    cur.execute("SELECT venue_id FROM Venues WHERE available_status = 1 ORDER BY venue_id")
    rows = [r[0] for r in cur.fetchall()]
    if len(rows) < 3:
        print('[错误] 可用场地不足 3 个，请先执行 python backend/init_db.py')
        sys.exit(1)
    return rows


def pick_categories(cur):
    cur.execute("SELECT category_id FROM Categories ORDER BY category_id")
    rows = [r[0] for r in cur.fetchall()]
    if not rows:
        print('[错误] 分类表为空，请先执行 python backend/init_db.py')
        sys.exit(1)
    return rows


def upsert_event(cur, title, org_id, venue_id, capacity, status,
                 start_expr, end_expr, category_ids):
    """存在则刷新时间/场地/状态，不存在则插入；返回 event_id。"""
    cur.execute("SELECT event_id FROM Events WHERE title = %s", (title,))
    row = cur.fetchone()
    if row:
        eid = row[0]
        cur.execute(
            f"UPDATE Events SET organizer_id=%s, venue_id=%s, capacity=%s, status=%s, "
            f"start_time={start_expr}, end_time={end_expr} WHERE event_id=%s",
            (org_id, venue_id, capacity, status, eid),
        )
    else:
        cur.execute(
            f"INSERT INTO Events (title, description, organizer_id, venue_id, "
            f"start_time, end_time, capacity, status) "
            f"VALUES (%s, %s, %s, %s, {start_expr}, {end_expr}, %s, %s)",
            (title, '演示数据，可安全删除。', org_id, venue_id, capacity, status),
        )
        eid = cur.lastrowid

    cur.execute("DELETE FROM Event_Categories WHERE event_id = %s", (eid,))
    for cid in category_ids:
        cur.execute(
            "INSERT IGNORE INTO Event_Categories (event_id, category_id) VALUES (%s, %s)",
            (eid, cid),
        )
    return eid


def ensure_registration(cur, student_id, event_id, checked_in=False):
    cur.execute(
        "SELECT registration_id, status FROM Registrations "
        "WHERE student_id = %s AND event_id = %s",
        (student_id, event_id),
    )
    row = cur.fetchone()
    if row:
        rid = row[0]
        if checked_in and row[1] != 'checked_in':
            cur.execute(
                "UPDATE Registrations SET status='checked_in', check_in_time=NOW(), "
                "cancelled_at=NULL, cancelled_by=NULL WHERE registration_id=%s",
                (rid,),
            )
        return rid
    cur.execute(
        "INSERT INTO Registrations (student_id, event_id, status, check_in_time) "
        "VALUES (%s, %s, %s, %s)",
        (student_id, event_id,
         'checked_in' if checked_in else 'registered',
         None),
    )
    rid = cur.lastrowid
    if checked_in:
        cur.execute(
            "UPDATE Registrations SET status='checked_in', check_in_time=NOW() "
            "WHERE registration_id=%s",
            (rid,),
        )
    return rid


def ensure_comment(cur, event_id, user_id, content):
    cur.execute(
        "SELECT COUNT(*) FROM Comments WHERE event_id=%s AND content=%s",
        (event_id, content),
    )
    if cur.fetchone()[0] == 0:
        cur.execute(
            "INSERT INTO Comments (event_id, user_id, content) VALUES (%s, %s, %s)",
            (event_id, user_id, content),
        )


def main():
    conn = connect()
    cur = conn.cursor()
    try:
        ensure_tables(cur)
        pwd_hash = bcrypt.hashpw(DEMO_PASSWORD.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        upsert_users(cur, pwd_hash)
        conn.commit()

        org_a = uid(cur, 'demo_org_a@example.com')
        org_b = uid(cur, 'demo_org_b@example.com')
        stu_1 = uid(cur, 'demo_stu_1@example.com')
        stu_2 = uid(cur, 'demo_stu_2@example.com')
        stu_3 = uid(cur, 'demo_stu_3@example.com')

        venues = pick_venues(cur)
        cats = pick_categories(cur)
        cat_pair = cats[:2] if len(cats) >= 2 else cats

        # 1) 即将开始（明天）
        e_upcoming = upsert_event(
            cur, '演示·即将开始的讲座', org_a, venues[0], 50, 'open',
            'DATE_ADD(NOW(), INTERVAL 1 DAY)',
            'DATE_ADD(NOW(), INTERVAL 1 DAY) + INTERVAL 2 HOUR',
            cat_pair,
        )
        # 2) 进行中（现在前后各 1 小时）
        e_live = upsert_event(
            cur, '演示·进行中的活动', org_a, venues[1], 30, 'open',
            'DATE_SUB(NOW(), INTERVAL 1 HOUR)',
            'DATE_ADD(NOW(), INTERVAL 1 HOUR)',
            cat_pair,
        )
        # 3) 已结束（两天前）
        e_ended = upsert_event(
            cur, '演示·已结束的活动', org_b, venues[2], 40, 'closed',
            'DATE_SUB(NOW(), INTERVAL 2 DAY)',
            'DATE_SUB(NOW(), INTERVAL 2 DAY) + INTERVAL 2 HOUR',
            cat_pair,
        )
        conn.commit()

        # 进行中活动：3 人报名，学生 1 已签到
        ensure_registration(cur, stu_1, e_live, checked_in=True)
        ensure_registration(cur, stu_2, e_live)
        ensure_registration(cur, stu_3, e_live)
        # 即将开始：1 人报名
        ensure_registration(cur, stu_1, e_upcoming)
        conn.commit()

        # 每个活动一条评论
        ensure_comment(cur, e_upcoming, stu_2, '很期待这场讲座！')
        ensure_comment(cur, e_live, stu_2, '现场氛围很好，组织得不错。')
        ensure_comment(cur, e_ended, stu_3, '活动已结束，收获很大。')
        conn.commit()
    finally:
        cur.close()
        conn.close()

    print('[完成] 演示数据已写入。可用账号（密码均为 Passw0rd123）：')
    for name, email, role in USERS:
        print(f'  - {role:9s} {email}')
    print()
    print('建议演示流程：')
    print('  1. 用 demo_org_a 登录，大厅能看到「即将开始」「进行中」两个活动；')
    print('  2. 点「进行中」活动详情，能看到 3 条报名、1 人已签到；')
    print('  3. 用 demo_stu_1 登录，个人中心能看到 2 条报名记录；')
    print('  4. 用 demo_admin 登录，管理员面板能看到全部用户。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
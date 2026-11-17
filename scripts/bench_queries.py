"""在临时库里造数据，测「索引 vs 无索引」的查询耗时，输出 markdown 片段。

用法：python scripts/bench_queries.py
（会创建并最后删除临时库 campus_events_bench，不影响开发库/测试库）
"""

import os
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')

BENCH_DB = 'campus_events_bench'
N_EVENTS = 3000
N_STUDENTS = 500
N_REGS = 9000
N_COMMENTS = 4000

cfg = dict(
    host=os.environ.get('DB_HOST', '127.0.0.1'),
    port=int(os.environ.get('DB_PORT', '3306')),
    user=os.environ.get('DB_USER'),
    password=os.environ.get('DB_PASSWORD'),
    charset='utf8mb4',
    time_zone='+08:00',
)


def build_db():
    env = dict(os.environ, DB_NAME=BENCH_DB)
    subprocess.run([sys.executable, str(ROOT / 'backend' / 'init_db.py')],
                   env=env, check=True, capture_output=True)

    conn = mysql.connector.connect(database=BENCH_DB, **cfg)
    cur = conn.cursor()
    cur.execute('SELECT venue_id FROM venues')
    venue_ids = [r[0] for r in cur.fetchall()]

    # 用户
    cur.executemany(
        "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, %s)",
        [(f'压测用户{i}', f'bench{i}@bench.com', 'x', 'organizer' if i < 20 else 'student')
         for i in range(1, N_STUDENTS + 1)],
    )
    conn.commit()
    cur.execute('SELECT user_id, role FROM users')
    users = cur.fetchall()
    org_ids = [u[0] for u in users if u[1] == 'organizer']
    stu_ids = [u[0] for u in users if u[1] == 'student']

    # 活动：均匀铺在 2027-01-01 起的两年内，每 4 小时一个，场地轮转
    cur.executemany(
        "INSERT INTO events (title, description, organizer_id, venue_id, start_time, end_time, capacity, status) "
        "VALUES (%s, %s, %s, %s, DATE_ADD('2027-01-01', INTERVAL %s MINUTE), "
        "DATE_ADD('2027-01-01', INTERVAL %s MINUTE), %s, %s)",
        [(f'压测活动{i}', 'bench', random.choice(org_ids), venue_ids[i % len(venue_ids)],
          i * 240, i * 240 + 120, 100, 'open') for i in range(N_EVENTS)],
    )
    conn.commit()

    cur.execute('SELECT event_id FROM events')
    event_ids = [r[0] for r in cur.fetchall()]

    # 报名：随机学生 / 活动，用 INSERT IGNORE 跳过重复
    regs = set()
    while len(regs) < N_REGS:
        regs.add((random.choice(stu_ids), random.choice(event_ids)))
    cur.executemany(
        "INSERT IGNORE INTO registrations (student_id, event_id, status) VALUES (%s, %s, 'registered')",
        list(regs),
    )
    conn.commit()

    comments = [(random.choice(event_ids), random.choice(stu_ids), f'压测评论{i}')
                for i in range(N_COMMENTS)]
    cur.executemany(
        "INSERT INTO comments (event_id, user_id, content) VALUES (%s, %s, %s)", comments)
    conn.commit()

    cur.execute('ANALYZE TABLE events, registrations, comments')
    cur.fetchall()
    cur.close()
    conn.close()
    print(f'[造数完成] events={N_EVENTS} registrations={len(regs)} comments={N_COMMENTS} users={N_STUDENTS}')


QUERIES = {
    '活动列表（当前实现：ORDER BY 含表达式）': (
        "SELECT e.event_id, e.title, v.venue_name, "
        "(NOW() > e.start_time) AS started, (e.end_time < NOW()) AS ended, "
        "(SELECT COUNT(*) FROM registrations r WHERE r.event_id = e.event_id AND r.status <> 'cancelled') AS cnt "
        "FROM events e LEFT JOIN venues v ON e.venue_id = v.venue_id "
        "ORDER BY (e.end_time < NOW()) ASC, e.start_time ASC, e.event_id ASC LIMIT 12",
        None),
    '活动列表（仅按 start_time 排序，索引可用）': (
        "SELECT e.event_id, e.title, v.venue_name, "
        "(SELECT COUNT(*) FROM registrations r WHERE r.event_id = e.event_id AND r.status <> 'cancelled') AS cnt "
        "FROM events e LEFT JOIN venues v ON e.venue_id = v.venue_id "
        "ORDER BY e.start_time ASC, e.event_id ASC LIMIT 12",
        None),
    '场地时间冲突检测（idx_events_venue_time）': (
        "SELECT event_id FROM events WHERE venue_id = %s AND event_id <> %s "
        "AND start_time < %s AND end_time > %s LIMIT 1",
        ('venue',)),
    '某活动有效报名人数（idx_reg_event_status）': (
        "SELECT COUNT(*) FROM registrations WHERE event_id = %s AND status <> 'cancelled'",
        ('event',)),
    '活动评论分页（idx_comments_event_created）': (
        "SELECT c.comment_id, c.content FROM comments c WHERE c.event_id = %s "
        "ORDER BY c.created_at DESC, c.comment_id DESC LIMIT 20",
        ('event',)),
}


# 被测索引，对照实验时通过 INVISIBLE / VISIBLE 切换
BENCH_INDEXES = [
    ('events', 'idx_start_time'),
    ('events', 'idx_events_venue_time'),
    ('events', 'idx_events_org_start'),
    ('registrations', 'idx_reg_event_status'),
    ('comments', 'idx_comments_event_created'),
]


def run_bench(conn, idx_on):
    cur = conn.cursor()

    def toggle_indexes(visible):
        """把被测索引设为 INVISIBLE / VISIBLE。

        用 INVISIBLE 而不是 DROP INDEX：对优化器来说等价于“没有这条索引”
        （EXPLAIN 与耗时都能反映出来），但索引本身还在，外键要求的支撑索引
        不会因为切换而报 1553 Cannot drop index needed in a foreign key constraint。
        """
        state = 'VISIBLE' if visible else 'INVISIBLE'
        for table, index in BENCH_INDEXES:
            cur.execute(f'ALTER TABLE `{table}` ALTER INDEX `{index}` {state}')

    toggle_indexes(idx_on)
    cur.execute('ANALYZE TABLE events, registrations, comments')
    cur.fetchall()

    cur.execute('SELECT venue_id FROM events LIMIT 1')
    venue = cur.fetchone()[0]
    cur.execute('SELECT event_id FROM events ORDER BY event_id LIMIT 1')
    event = cur.fetchone()[0]

    out = {}
    for label, (sql, params) in QUERIES.items():
        args = ()
        if params == ('venue',):
            args = (venue, 0, '2029-06-01 12:00:00', '2029-06-01 10:00:00')
        elif params == ('event',):
            args = (event,)
        timings = []
        for _ in range(15):
            t0 = time.perf_counter()
            cur.execute(sql, args)
            cur.fetchall()
            timings.append((time.perf_counter() - t0) * 1000)
        cur.execute('EXPLAIN ' + sql, args)
        plan = cur.fetchall()
        out[label] = (statistics.median(timings), plan)
    cur.close()
    return out


def fmt_plan(plan):
    parts = []
    for row in plan:
        table = row[2]
        key = row[6] or 'NULL'
        rows = row[9]
        extra = row[11] or ''
        extra = extra.replace('Using temporary', 'temp').replace('Using filesort', 'filesort')
        parts.append(f'{table}/{key}/{rows}行 {extra}'.strip())
    return '<br>'.join(parts)


def main():
    try:
        build_db()
        conn = mysql.connector.connect(database=BENCH_DB, **cfg)

        print('\n### 有索引（schema.sql 里的索引全部存在）\n')
        with_idx = run_bench(conn, True)
        for label, (ms, plan) in with_idx.items():
            print(f'- {label}: **{ms:.2f} ms**  \n  `{fmt_plan(plan)}`')

        print('\n### 去掉索引（对照）\n')
        without_idx = run_bench(conn, False)
        for label, (ms, plan) in without_idx.items():
            print(f'- {label}: **{ms:.2f} ms**  \n  `{fmt_plan(plan)}`')

        conn.close()
    finally:
        drop = mysql.connector.connect(**cfg)
        c = drop.cursor()
        c.execute(f'DROP DATABASE IF EXISTS {BENCH_DB}')
        drop.close()
        print(f'\n[清理] 已删除临时库 {BENCH_DB}')


if __name__ == '__main__':
    main()
    # mysql-connector 会留下后台线程，强制退出避免脚本挂住
    sys.stdout.flush()
    os._exit(0)

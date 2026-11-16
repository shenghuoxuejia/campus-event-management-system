"""把一个已存在的账号提升为管理员。

用法：
    python backend/make_admin.py someone@example.com

说明：
- 管理员不能通过注册页自助获得（注册接口只接受 student / organizer）。
- 管理员可以：删除任意活动、删除任意评论、查看 /api/admin/users 全部用户列表。
"""

import os
import sys
from contextlib import closing
from pathlib import Path

import mysql.connector

PROJECT_ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / '.env')
except ImportError:
    pass


def main():
    if len(sys.argv) != 2:
        print('用法：python backend/make_admin.py <邮箱>')
        return 1

    email = sys.argv[1].strip().lower()
    password = os.environ.get('DB_PASSWORD')
    if not password:
        print('[错误] 没有读到 DB_PASSWORD，请先运行 python backend/setup_env.py')
        return 1

    cfg = dict(
        host=os.environ.get('DB_HOST', '127.0.0.1'),
        port=int(os.environ.get('DB_PORT', '3306')),
        user=os.environ.get('DB_USER', 'root'),
        password=password,
        database=os.environ.get('DB_NAME', 'campus_events'),
        charset='utf8mb4',
    )

    try:
        conn = mysql.connector.connect(**cfg)
    except mysql.connector.Error as err:
        print(f'[错误] 连接 MySQL 失败：{err}')
        return 1

    try:
        with closing(conn.cursor()) as cur:
            cur.execute('SELECT user_id FROM Users WHERE email = %s', (email,))
            row = cur.fetchone()
            if not row:
                print(f'[错误] 找不到邮箱为 {email} 的用户，请先注册该账号。')
                return 1

            cur.execute("UPDATE Users SET role = 'admin' WHERE email = %s", (email,))
            conn.commit()
            print(f'[完成] 已将 {email} 设为管理员（user_id={row[0]}）。')
    finally:
        conn.close()

    return 0


if __name__ == '__main__':
    sys.exit(main())

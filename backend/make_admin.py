"""创建管理员账号，或把已有账号提升为管理员。

用法：
    python backend/make_admin.py someone@example.com
        把已注册的账号提升为管理员。

    python backend/make_admin.py admin@campus.local --create Admin@2026
        账号不存在就创建一个管理员（密码按给出的值设置）；
        账号已存在则把它设为管理员，并把密码重置为该值（忘记密码时这样救）。

说明：管理员不能通过注册页自助获得（注册接口只接受 student / organizer）。
"""

import os
import sys
from contextlib import closing
from pathlib import Path

import bcrypt
import mysql.connector

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_NAME = '管理员'

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / '.env')
except ImportError:
    pass


def parse_args(argv):
    """返回 (邮箱, 创建/重置用的密码或 None)。"""
    if len(argv) < 2 or argv[1].startswith('-'):
        return None, None

    email = argv[1].strip().lower()
    password = None
    if '--create' in argv:
        index = argv.index('--create')
        if index + 1 >= len(argv):
            print('用法：python backend/make_admin.py <邮箱> --create <密码>')
            return None, None
        password = argv[index + 1]
    return email, password


def main():
    email, password = parse_args(sys.argv)
    if not email:
        print('用法：')
        print('  python backend/make_admin.py <邮箱>                     # 提升已有账号')
        print('  python backend/make_admin.py <邮箱> --create <密码>     # 不存在则创建')
        return 1

    if password is not None:
        # 和注册接口保持一致的底线要求，避免设置出一个登不进去的弱密码
        if len(password) < 8:
            print('[错误] 密码至少 8 位')
            return 1
        if not (any(c.isupper() for c in password)
                and any(c.islower() for c in password)
                and any(c.isdigit() for c in password)):
            print('[错误] 密码需要同时包含大写字母、小写字母和数字')
            return 1

    db_password = os.environ.get('DB_PASSWORD')
    if not db_password:
        print('[错误] 没有读到 DB_PASSWORD，请先运行 python backend/setup_env.py')
        return 1

    cfg = dict(
        host=os.environ.get('DB_HOST', '127.0.0.1'),
        port=int(os.environ.get('DB_PORT', '3306')),
        user=os.environ.get('DB_USER', 'root'),
        password=db_password,
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
            cur.execute('SELECT user_id, role FROM users WHERE email = %s', (email,))
            row = cur.fetchone()

            if not row:
                if password is None:
                    print(f'[错误] 找不到邮箱为 {email} 的用户，请先注册该账号，'
                          f'或加上 --create <密码> 直接创建。')
                    return 1
                cur.execute(
                    'INSERT INTO users (name, email, password_hash, role) '
                    "VALUES (%s, %s, %s, 'admin')",
                    (DEFAULT_NAME, email, bcrypt.hashpw(
                        password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')),
                )
                conn.commit()
                print(f'[完成] 已创建管理员账号 {email}（user_id={cur.lastrowid}）。')
                return 0

            if password is None:
                cur.execute("UPDATE users SET role = 'admin' WHERE email = %s", (email,))
                conn.commit()
                print(f'[完成] 已将 {email} 设为管理员（user_id={row[0]}）。')
            else:
                cur.execute(
                    "UPDATE users SET role = 'admin', password_hash = %s WHERE email = %s",
                    (bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8'),
                     email),
                )
                conn.commit()
                print(f'[完成] 已将 {email} 设为管理员，并把密码重置为指定的值'
                      f'（user_id={row[0]}）。')
    finally:
        conn.close()

    return 0


if __name__ == '__main__':
    sys.exit(main())

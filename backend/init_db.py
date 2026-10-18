"""初始化数据库：创建库、建表、写入基础数据。

用法：
    python init_db.py            # 库和表已存在就跳过，安全
    python init_db.py --force    # 删表重建（会清空数据，需要输入 YES 确认）

依赖 .env 里的连接信息（先运行 setup_env.py 生成）。
"""

import os
import sys
from pathlib import Path

import mysql.connector

BASE = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv
    load_dotenv(BASE / '.env')
except ImportError:
    pass

SCHEMA_PATH = BASE / 'database' / 'schema.sql'


def load_statements(sql_text):
    """把 schema.sql 拆成单条语句（跳过注释与空行）。"""
    statements, buf = [], []
    for raw in sql_text.splitlines():
        line = raw.strip()
        if not line or line.startswith('--'):
            continue
        buf.append(raw)
        if line.endswith(';'):
            stmt = '\n'.join(buf).strip().rstrip(';').strip()
            if stmt:
                statements.append(stmt)
            buf = []
    if buf:
        stmt = '\n'.join(buf).strip().rstrip(';').strip()
        if stmt:
            statements.append(stmt)
    return statements


def main():
    force = '--force' in sys.argv

    host = os.environ.get('DB_HOST', '127.0.0.1')
    port = int(os.environ.get('DB_PORT', '3306'))
    user = os.environ.get('DB_USER', 'root')
    password = os.environ.get('DB_PASSWORD')
    dbname = os.environ.get('DB_NAME', 'campus_events')

    if not password:
        print('[错误] 没有读到 DB_PASSWORD。')
        print('       请先运行：python setup_env.py')
        return 1

    base_cfg = dict(host=host, port=port, user=user, password=password,
                    charset='utf8mb4')

    try:
        conn = mysql.connector.connect(**base_cfg)
    except mysql.connector.Error as err:
        print(f'[错误] 连接 MySQL 失败：{err}')
        print('       请确认 MySQL 服务已启动，且 .env 里的主机/端口/用户名/密码正确。')
        return 1

    try:
        cur = conn.cursor()
        cur.execute(
            'SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME = %s',
            (dbname,),
        )
        db_exists = cur.fetchone() is not None

        has_tables = False
        if db_exists:
            cur.execute(
                'SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES '
                'WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s',
                (dbname, 'users'),
            )
            has_tables = cur.fetchone()[0] > 0

        if has_tables and not force:
            print(f'数据库 `{dbname}` 已存在且已建表，跳过初始化。')
            print('（如需重建，运行：python init_db.py --force）')
            return 0

        if force:
            print(f'[警告] 即将删除 `{dbname}` 中所有表并重建，现有数据会全部丢失。')
            if input('确认请输入 YES：').strip() != 'YES':
                print('已取消。')
                return 1

        cur.execute(f'CREATE DATABASE IF NOT EXISTS `{dbname}` '
                    'DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_unicode_ci')
        conn.commit()
        cur.close()
    finally:
        conn.close()

    statements = load_statements(SCHEMA_PATH.read_text(encoding='utf-8'))
    skipped = ('CREATE DATABASE', 'USE ')
    statements = [s for s in statements if not s.upper().startswith(skipped)]

    conn = mysql.connector.connect(database=dbname, **base_cfg)
    try:
        cur = conn.cursor()
        for stmt in statements:
            cur.execute(stmt)
        conn.commit()
        cur.close()
    except mysql.connector.Error as err:
        conn.rollback()
        print(f'[错误] 执行建表语句失败：{err}')
        return 1
    finally:
        conn.close()

    print(f'数据库 `{dbname}` 初始化完成，共执行 {len(statements)} 条语句。')
    return 0


if __name__ == '__main__':
    sys.exit(main())

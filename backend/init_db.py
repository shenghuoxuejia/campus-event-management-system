"""初始化数据库：创建库、建表、写入基础数据。

用法：
    python init_db.py            # 库和表已存在就跳过，安全
    python init_db.py --force    # 删表重建（会清空数据，需要输入 YES 确认）

依赖 .env 里的连接信息（先运行 setup_env.py 生成）。
"""

import os
import re
import sys
from contextlib import closing
from pathlib import Path

import mysql.connector

BASE = Path(__file__).resolve().parent          # backend/
PROJECT_ROOT = BASE.parent                      # 项目根目录

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / '.env')
except ImportError:
    pass

SCHEMA_PATH = PROJECT_ROOT / 'database' / 'schema.sql'

DB_NAME_RE = re.compile(r'^[A-Za-z0-9_]+$')

# 后续版本加的索引：(表名, 索引名, 定义)，老库跑一次会自动补上
REQUIRED_INDEXES = [
    ('events', 'idx_start_time', '(`start_time`)'),
    ('events', 'idx_events_venue_time', '(`venue_id`, `start_time`, `end_time`)'),
    ('events', 'idx_events_org_start', '(`organizer_id`, `start_time`)'),
    ('comments', 'idx_comments_event_created', '(`event_id`, `created_at`)'),
    ('registrations', 'idx_reg_event_status', '(`event_id`, `status`)'),
    ('registrations', 'idx_reg_cancelled_by', '(`cancelled_by`)'),
]

# 后续版本加的列：(表名, 列名, 列定义)，不补的话应用会报 1054 Unknown column
REQUIRED_COLUMNS = [
    ('users', 'token_version', 'int NOT NULL DEFAULT 0'),
    ('registrations', 'cancelled_at', 'datetime DEFAULT NULL'),
    ('registrations', 'cancelled_by', 'int DEFAULT NULL'),
    ('registrations', 'updated_at',
     'datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'),
    ('events', 'updated_at',
     'datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'),
]

# 早期版本用 TIMESTAMP，会随会话时区换算且有 2038 上限；统一改成 DATETIME
DATETIME_COLUMNS = [
    ('users', 'created_at', 'datetime NULL DEFAULT CURRENT_TIMESTAMP'),
    ('comments', 'created_at', 'datetime NULL DEFAULT CURRENT_TIMESTAMP'),
]

# 外键要求：(表名, 约束名, 定义, 期望的 DELETE_RULE)
REQUIRED_FOREIGN_KEYS = [
    ('registrations', 'registrations_ibfk_2',
     'FOREIGN KEY (`event_id`) REFERENCES `events` (`event_id`) ON DELETE CASCADE',
     'CASCADE'),
    ('registrations', 'registrations_ibfk_3',
     'FOREIGN KEY (`cancelled_by`) REFERENCES `users` (`user_id`) ON DELETE SET NULL',
     'SET NULL'),
]


def ensure_columns(conn, dbname):
    """补齐缺失的列（幂等）。返回新增的列个数。"""
    added = 0
    with closing(conn.cursor()) as cur:
        for table, column, definition in REQUIRED_COLUMNS:
            cur.execute(
                'SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS '
                'WHERE TABLE_SCHEMA = %s AND LOWER(TABLE_NAME) = LOWER(%s) '
                'AND LOWER(COLUMN_NAME) = LOWER(%s)',
                (dbname, table, column),
            )
            if cur.fetchone()[0] == 0:
                cur.execute(
                    f'ALTER TABLE `{dbname}`.`{table}` ADD COLUMN `{column}` {definition}'
                )
                added += 1
    conn.commit()
    return added


def ensure_datetime_columns(conn, dbname):
    """把早期版本的 TIMESTAMP 列统一改成 DATETIME（幂等）。返回改动个数。"""
    changed = 0
    with closing(conn.cursor()) as cur:
        # 先统一会话时区，保证 TIMESTAMP → DATETIME 转换不会整体偏移
        cur.execute("SET time_zone = '+08:00'")
        for table, column, definition in DATETIME_COLUMNS:
            cur.execute(
                'SELECT DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS '
                'WHERE TABLE_SCHEMA = %s AND LOWER(TABLE_NAME) = LOWER(%s) '
                'AND LOWER(COLUMN_NAME) = LOWER(%s)',
                (dbname, table, column),
            )
            row = cur.fetchone()
            if row and str(row[0]).lower() == 'timestamp':
                cur.execute(
                    f'ALTER TABLE `{dbname}`.`{table}` MODIFY COLUMN `{column}` {definition}'
                )
                changed += 1
    conn.commit()
    return changed


def ensure_foreign_keys(conn, dbname):
    """补齐 / 修正外键的级联规则（幂等）。返回改动个数。"""
    changed = 0
    with closing(conn.cursor()) as cur:
        for table, name, definition, expected_rule in REQUIRED_FOREIGN_KEYS:
            cur.execute(
                'SELECT DELETE_RULE FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS '
                'WHERE CONSTRAINT_SCHEMA = %s AND CONSTRAINT_NAME = %s',
                (dbname, name),
            )
            row = cur.fetchone()
            if row:
                if str(row[0]).upper().replace('_', ' ') == expected_rule:
                    continue
                cur.execute(f'ALTER TABLE `{dbname}`.`{table}` DROP FOREIGN KEY `{name}`')
            try:
                cur.execute(f'ALTER TABLE `{dbname}`.`{table}` ADD CONSTRAINT `{name}` {definition}')
                changed += 1
            except mysql.connector.Error as err:
                print(f'[警告] 补外键 {name} 失败（老数据可能有脏值）：{err}')
    conn.commit()
    return changed


def migrate_existing_db(conn, dbname):
    """对已存在的库做幂等升级：列 → 类型 → 外键 → 索引。返回改动项汇总。"""
    return {
        'columns': ensure_columns(conn, dbname),
        'datetime': ensure_datetime_columns(conn, dbname),
        'foreign_keys': ensure_foreign_keys(conn, dbname),
        'indexes': ensure_indexes(conn, dbname),
    }


def ensure_indexes(conn, dbname):
    """补齐缺失的索引（幂等）。返回新增的索引个数。"""
    added = 0
    with closing(conn.cursor()) as cur:
        for table, index, definition in REQUIRED_INDEXES:
            cur.execute(
                'SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATISTICS '
                'WHERE TABLE_SCHEMA = %s AND LOWER(TABLE_NAME) = LOWER(%s) '
                'AND INDEX_NAME = %s',
                (dbname, table, index),
            )
            if cur.fetchone()[0] == 0:
                cur.execute(
                    f'ALTER TABLE `{dbname}`.`{table}` ADD INDEX `{index}` {definition}'
                )
                added += 1
    conn.commit()
    return added


def drop_all_tables(conn, dbname):
    """删除库内所有表（--force 重建用）。返回删除的表数量。"""
    with closing(conn.cursor()) as cur:
        cur.execute(
            'SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES '
            'WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = %s',
            (dbname, 'BASE TABLE'),
        )
        tables = [row[0] for row in cur.fetchall()]
        if not tables:
            return 0
        cur.execute('SET FOREIGN_KEY_CHECKS = 0')
        try:
            for table in tables:
                cur.execute(f'DROP TABLE IF EXISTS `{dbname}`.`{table}`')
        finally:
            cur.execute('SET FOREIGN_KEY_CHECKS = 1')
    conn.commit()
    return len(tables)


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
    user = os.environ.get('DB_USER')
    password = os.environ.get('DB_PASSWORD')
    dbname = os.environ.get('DB_NAME', 'campus_events')

    if not user or not password:
        print('[错误] 没有读到 DB_USER 或 DB_PASSWORD。')
        print('       请先在 .env 中配置数据库专用账号及密码。')
        return 1

    if not DB_NAME_RE.fullmatch(dbname):
        print('[错误] 数据库名只能包含字母、数字、下划线。')
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
        with closing(conn.cursor()) as cur:
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
                print(f'数据库 `{dbname}` 已存在且已建表，跳过建表。')
                # 老库升级：幂等补齐后续版本新增的列 / 索引 / 外键
                changes = migrate_existing_db(conn, dbname)
                if any(changes.values()):
                    print('已升级老库：'
                          f"新增列 {changes['columns']} 个，"
                          f"时间类型修正 {changes['datetime']} 个，"
                          f"外键 {changes['foreign_keys']} 个，"
                          f"索引 {changes['indexes']} 个。")
                else:
                    print('库结构已是最新，无需升级。')
                print('（如需重建，运行：python backend/init_db.py --force）')
                return 0

            if force and has_tables:
                print(f'[警告] 即将删除 `{dbname}` 中所有表并重建，现有数据会全部丢失。')
                if input('确认请输入 YES：').strip() != 'YES':
                    print('已取消。')
                    return 1
                dropped = drop_all_tables(conn, dbname)
                print(f'已删除 {dropped} 个旧表。')

            cur.execute(f'CREATE DATABASE IF NOT EXISTS `{dbname}` '
                        'DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_unicode_ci')
            conn.commit()
    finally:
        conn.close()

    statements = load_statements(SCHEMA_PATH.read_text(encoding='utf-8'))
    skipped = ('CREATE DATABASE', 'USE ')
    statements = [s for s in statements if not s.upper().startswith(skipped)]

    conn = mysql.connector.connect(database=dbname, **base_cfg)
    try:
        with closing(conn.cursor()) as cur:
            for stmt in statements:
                cur.execute(stmt)
            conn.commit()
        migrate_existing_db(conn, dbname)
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

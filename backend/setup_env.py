"""交互式生成 .env 配置文件。

用法：
    python setup_env.py

会在当前目录生成 .env（如果已存在则跳过），并随机生成 APP_SECRET_KEY。
密码通过 getpass 读取，不会显示、也不会出现在命令行历史里。
"""

import getpass
import secrets
import sys
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / '.env'   # 项目根目录/.env


def ask(prompt, default):
    value = input(f'{prompt} [{default}]: ').strip()
    return value or default


def env_value(value):
    """把值安全写入 .env（含 #、空格、引号等特殊字符时用双引号包裹）。"""
    if value and any(ch in value for ch in '# "\\=\n\r'):
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
    return value


def main():
    if ENV_PATH.exists():
        print(f'{ENV_PATH.name} 已存在，跳过。'
              f'如需修改，直接用编辑器打开 {ENV_PATH}。')
        return 0

    print('=' * 46)
    print(' 配置数据库连接（直接回车使用方括号里的默认值）')
    print('=' * 46)

    host = ask('MySQL 主机', '127.0.0.1')
    port = ask('MySQL 端口', '3306')
    user = ask('MySQL 用户名', 'root')
    password = getpass.getpass('MySQL 密码（输入时不显示）: ')
    dbname = ask('数据库名', 'campus_events')
    while True:
        app_port = ask('后端端口', '5000')
        if app_port.isdigit() and 1 <= int(app_port) <= 65535:
            break
        print('端口必须是 1-65535 的数字，请重新输入。')

    lines = [
        '# 由 setup_env.py 生成，请勿提交到 git',
        f'DB_HOST={host}',
        f'DB_PORT={port}',
        f'DB_USER={user}',
        f'DB_PASSWORD={env_value(password)}',
        f'DB_NAME={dbname}',
        '',
        '# 登录令牌签名密钥（已随机生成）',
        f'APP_SECRET_KEY={secrets.token_urlsafe(48)}',
        'TOKEN_MAX_AGE=86400',
        '',
        '# 登录 / 注册限流（次数/窗口秒数）',
        'LOGIN_RATE_LIMIT=10/60',
        'REGISTER_RATE_LIMIT=20/3600',
        '',
        'FLASK_DEBUG=0',
        f'PORT={app_port}',
        '',
    ]
    ENV_PATH.write_text('\n'.join(lines), encoding='utf-8')
    print()
    print(f'已生成 {ENV_PATH}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

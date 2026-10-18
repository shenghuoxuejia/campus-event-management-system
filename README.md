# 校园活动报名与管理系统 (Campus Event System) — 修改版

## 📖 项目简介
基于 Flask + MySQL 的全栈校园活动管理平台。三种角色：学生（报名活动）、组织者（发布活动 / 签到 / 管理报名）、管理员。
核心功能：用户注册登录、活动发布、活动报名（含名额与时间校验）、取消 / 重新报名、签到、评论、个人报名记录查询。

> 本目录是**修改版副本**。原始版本保留在 `C:\Users\hanjingyao\Desktop\CampusEventProject`，未做改动。
> 具体改了什么，见 [修改说明.md](修改说明.md)。

## 🛠️ 技术栈
- 后端：Python 3.10+、Flask、mysql-connector-python、bcrypt、itsdangerous（签发登录令牌）
- 数据库：MySQL 8.0.16+（用到 CHECK 约束与 enum）
- 前端：HTML5 / CSS3 / 原生 JavaScript（Fetch API），由 Flask 直接托管
- 开发工具：VS Code、MySQL Workbench、Postman

## 📁 项目结构
```text
CampusEventProject-fixed/
├── app.py                  # 后端主程序（路由、认证、事务逻辑）
├── requirements.txt        # Python 依赖
├── .env.example            # 环境变量模板（复制为 .env 后填写）
├── .gitignore              # 忽略 .env / 虚拟环境 / 缓存
├── 修改说明.md             # 本次修改清单
├── frontend/
│   ├── login.html          # 登录 / 注册页
│   ├── index.html          # 活动大厅（发布、报名、签到、评论）
│   └── profile.html        # 个人中心（我的报名、取消报名）
└── database/
    └── schema.sql          # 建表脚本（含约束与基础场地/分类数据）
```

## 🚀 启动步骤

1. 安装依赖

```bash
pip install -r requirements.txt
```

2. 初始化数据库（会创建 `campus_events` 库并重建所有表）

```bash
mysql -u root -p < database/schema.sql
```

3. 配置环境变量：把 `.env.example` 复制为 `.env`，填入数据库密码和一段随机密钥

```bash
# Windows PowerShell
Copy-Item .env.example .env
# 生成随机密钥
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`.env` 内容示例（**该文件不要提交到 git**）：

```ini
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=你的数据库密码
DB_NAME=campus_events
APP_SECRET_KEY=上一步生成的长随机串
FLASK_DEBUG=0
PORT=5000
```

4. 启动后端

```bash
python app.py
```

5. 浏览器打开 `http://127.0.0.1:5000/`（前端由 Flask 托管，不需要另外开 Live Server）

## 👥 组员使用（一键安装）

前提：装好 Python 3.10+（安装时勾选 *Add python.exe to PATH*）和 MySQL。

1. 解压本项目，**双击 `首次安装并启动.bat`**。
2. 脚本会自动：创建 `.venv` 虚拟环境 → 安装依赖 → 引导你填数据库连接（生成 `.env`）→ 建库建表 → 启动服务并打开浏览器。
3. 以后每次使用，双击 **`启动校园活动系统.bat`** 即可（服务没运行会自动启动，已经在跑就直接开浏览器）。
4. 用完想关掉服务：双击 **`停止校园活动系统.bat`**。

说明：

1. 首次安装时输入的 MySQL 密码只写进本机的 `.env`，不会上传、也不会进 git。
2. `init_db.py` 默认**不会**动已存在的库；只有显式运行 `python init_db.py --force` 才会删表重建。
3. 换电脑 / 换同学，重复「双击首次安装」即可；每个环境独立配置。

## 🔐 认证方式
登录成功后后端返回 `token`，前端存到 `localStorage`，之后所有请求自动带上：

```text
Authorization: Bearer <token>
```

服务端从令牌里解析 `user_id`，**不再信任前端传来的 user_id / organizer_id**。令牌默认 24 小时过期，过期后前端会自动跳回登录页。

## 📡 接口一览

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| POST | `/api/register` | 注册（学生 / 组织者） | 公开 |
| POST | `/api/login` | 登录，返回用户信息与令牌 | 公开 |
| GET | `/api/me` | 当前登录用户信息 | 登录 |
| GET | `/api/events` | 活动列表（含已报名人数 / 剩余名额 / 我是否已报名） | 登录 |
| POST | `/api/register_event` | 报名活动（事务 + 行锁，防超卖） | 登录 |
| GET | `/api/user_registrations/<user_id>` | 我的报名记录 | 仅本人 |
| PUT | `/api/cancel_registration/<id>` | 取消报名 | 本人或该活动组织者 |
| POST | `/api/create_event` | 发布活动 | 组织者 |
| DELETE | `/api/delete_event/<event_id>` | 删除活动 | 该活动组织者 |
| GET | `/api/event_registrations/<event_id>` | 活动报名名单 | 该活动组织者 |
| PUT | `/api/check_in/<registration_id>` | 学生签到 | 该活动组织者 |
| GET | `/api/venues` | 可用场地列表 | 登录 |
| GET | `/api/comments/<event_id>` | 活动评论 | 登录 |
| POST | `/api/comments` | 发表评论 | 登录 |
| DELETE | `/api/delete_comment/<comment_id>` | 删除评论 | 评论作者或活动组织者 |

所有接口统一返回 `{"code": 200|4xx|5xx, "message": "...", "data": ...}`。

## 🧪 测试建议
1. 注册一个学生账号和一个组织者账号（密码需 ≥8 位，含大小写字母与数字）。
2. 组织者登录后发布活动；学生登录后报名、取消、重新报名。
3. 并发测试：对同一个满员活动同时发起多个报名请求，验证不再超卖。

# 校园活动报名与管理系统

**Campus Event System** · 基于 Flask + MySQL 的全栈校园活动管理平台，支持「学生报名」与「组织者管理」两大角色，内置基于签名令牌的安全认证与并发安全的活动报名。

本文档同时是**项目文件的完整说明书**：除运行方式外，还逐一说明了仓库里每一个源码、脚本、配置、测试与文档文件的作用；交付包只包含运行所需文件与 `docs/` 交付材料。

| 项 | 地址 |
| --- | --- |
| 在线代码仓库（GitHub） | <https://github.com/shenghuoxuejia/campus-event-management-system> |
| 克隆命令 | `git clone https://github.com/shenghuoxuejia/campus-event-management-system.git` |

## 目录

- [功能特性](#功能特性)
- [技术栈](#技术栈)
- [项目结构与文件清单](#项目结构与文件清单)
  - [目录树](#目录树)
  - [后端文件](#后端文件-backend)
  - [前端文件](#前端文件-frontend)
  - [数据库与脚本](#数据库与脚本)
  - [测试文件](#测试文件-tests)
  - [根目录配置与元文件](#根目录配置与元文件)
- [文档地图（每份文档讲什么）](#文档地图每份文档讲什么)
  - [docs/ 交付文档](#docs-交付文档)
  - [作业要求/](#作业要求)
- [数据库设计](#数据库设计)
- [快速开始](#快速开始)
- [环境变量](#环境变量)
- [认证与安全](#认证与安全)
- [API 接口](#api-接口)
- [业务规则](#业务规则)
- [管理员](#管理员)
- [测试](#测试)
- [已知限制与后续计划](#已知限制与后续计划)
- [交付前 checklist](#交付前-checklist)
- [文档维护约定](#文档维护约定)

## 功能特性

- **双角色自助注册**：学生报名活动；组织者发布 / 编辑活动、负责签到与报名管理。
- **认证与安全**：登录签发 `Bearer Token`，服务端从令牌解析身份，不信任前端传来的用户标识；支持退出登录（令牌立即吊销）与修改密码。
- **并发安全报名**：事务 + 行锁（`SELECT ... FOR UPDATE`）防止名额超卖。
- **完整业务闭环**：发布 → 报名 → 签到 → 评论 → 取消 / 重新报名，覆盖活动全生命周期。
- **活动分类**：活动支持多分类（N:M），发布时可多选，大厅支持按分类筛选。
- **权限精细管控**：按「角色 + 资源归属」双重校验（学生 / 组织者 / 管理员）。
- **统一响应规范**：所有接口返回 `{"code", "message", "data"}` 结构，分页接口附带分页元信息。
- **自动化测试**：pytest 覆盖认证、边界校验、并发报名、签到、评论、分类、限流、权限等核心场景。

## 技术栈

| 层次 | 技术 |
| --- | --- |
| 后端 | Python 3.10+ · Flask 3 · Flask-Cors · mysql-connector-python · bcrypt · itsdangerous · python-dotenv |
| 数据库 | MySQL 8.0+（utf8mb4，状态字段使用 `enum` 约束） |
| 前端 | HTML5 · CSS3 · 原生 JavaScript（Fetch API），由 Flask 直接托管 |
| 认证 | 签名令牌（Bearer Token），默认 24 小时过期，`TOKEN_MAX_AGE` 可配 |
| 测试 | pytest + pytest-cov |
| 报表工具 | Pillow（`scripts/er_diagram.py` 画 ER 图） |
| 开发工具 | VS Code · MySQL Workbench · Postman |

## 项目结构与文件清单

### 目录树

```text
CampusEventProject-fixed/
├── backend/                     # 后端（Flask 应用 + 数据库运维脚本）
│   ├── app.py                   # 主程序：路由、认证、限流、事务与锁逻辑
│   ├── init_db.py               # 建库建表 + 老库幂等升级（--force 删表重建）
│   ├── make_admin.py            # 把已有账号提升为管理员
│   ├── seed_demo.py             # 一键写入演示数据
│   └── setup_env.py             # 交互式生成 .env
├── frontend/                    # 前端静态页（由 Flask 托管，无需单独起服务）
│   ├── login.html               # 登录 / 注册页
│   ├── index.html               # 活动大厅（发布、报名、签到、评论、分类筛选）
│   └── profile.html             # 个人中心（我的报名、取消报名、修改密码）
├── database/
│   └── schema.sql               # 建表脚本（含约束、索引与场地 / 分类种子数据）
├── scripts/                     # 安装、启动、停止、清理与报告生成脚本
│   ├── 首次安装并启动.bat
│   ├── 启动校园活动系统.bat
│   ├── 停止校园活动系统.bat
│   ├── 交付前清理.bat
│   ├── er_diagram.py
│   └── bench_queries.py
├── tests/                       # pytest 自动化测试（15 个文件 / 101 个用例）
│   ├── conftest.py
│   ├── test_auth.py             …（详见「测试文件」一节）
│   └── test_v2_regressions.py
├── docs/                        # 交付文档与图（入口：docs/README.md）
│   ├── README.md                # 文档索引：清单 / 阅读顺序 / 图表维护
│   ├── 数据库设计说明.md
│   ├── 测试报告.md
│   └── images/
│       ├── er-diagram.png
│       └── coverage.png
├── 作业要求/                    # 课程作业要求截图（仅本地参考，已被 .gitignore 排除，不在仓库中）
│   ├── 屏幕截图 2026-11-17 031158.png
│   ├── 屏幕截图 2026-11-17 031216.png
│   └── 屏幕截图 2026-11-17 031256.png
├── README.md                    # 本文件
├── requirements.txt             # 运行时依赖
├── requirements-dev.txt         # 测试 / 报告依赖
├── pytest.ini                   # pytest 配置（testpaths = tests）
├── .env.example                 # 环境变量模板（复制为 .env 使用）
├── .env                         # 本机真实配置（已被 git 忽略，交付前必须删除）
├── .gitignore                   # 忽略虚拟环境 / 密钥 / 缓存 / 备份
└── .vscode/settings.json        # 让 VS Code 终端自动读取 .env
```

### 后端文件 `backend/`

| 文件 | 作用 | 什么时候需要动它 |
| --- | --- | --- |
| `app.py` | **唯一入口**，约 1600 行。包含：配置加载与启动校验（`APP_SECRET_KEY` 强度）、连接池 `get_conn()`（`ping(reconnect=True)`）、令牌签发与校验 `issue_token()` / `auth_user()`（含 `token_version` 比对）、装饰器 `require_user()` / `require_role()`、限流 `rate_limit()`（按 IP / 邮箱，`TRUSTED_PROXIES` 控制是否解析 `X-Forwarded-For`）、统一响应 `ok()` / `fail()` 与全局错误处理、活动字段校验 `_validated_event_fields()`（含场地冲突 `FOR UPDATE` 检查）、行锁工具 `_lock_event()`、以及全部 `/api/*` 路由，最后托管 `frontend/` 静态页 | 改接口、改校验、改并发逻辑 |
| `init_db.py` | 建库建表；对**老库**执行幂等迁移 `migrate_existing_db()`：按 `INFORMATION_SCHEMA` 补列（`token_version` / `cancelled_at` / `cancelled_by` / `updated_at`）、把 `TIMESTAMP` 改成 `DATETIME`、补 / 重建外键与级联规则、补 6 条索引，并打印升级摘要。默认不动已存在的库，`--force` 才删表重建 | 拉代码后升级本机数据库、换电脑首次初始化 |
| `make_admin.py` | 命令行把已有邮箱提升为 `role='admin'`（管理员不能自助注册） | 需要一个管理员账号时 |
| `seed_demo.py` | 写入 1 管理员 + 2 组织者 + 3 学生、3 个不同状态的活动、若干报名 / 签到 / 评论，方便答辩演示 | 演示前想一键造数据 |
| `setup_env.py` | 交互式询问数据库连接，生成 `.env`（含 `TEST_DB_NAME`、限流、连接池、时区、CORS、可信代理等全部键） | 首次安装（`首次安装并启动.bat` 会调用） |

### 前端文件 `frontend/`

| 文件 | 作用 | 关键实现 |
| --- | --- | --- |
| `login.html` | 登录 / 注册页，可选「学生 / 组织者」角色，含密码强度前端校验 | 登录成功后把 `token` 与用户信息写入 `localStorage`，跳转 `index.html` |
| `index.html` | 活动大厅：分页列表、分类筛选、活动详情弹窗、发布 / 编辑 / 删除 / 关闭报名、报名 / 取消、报名名单（含「显示已取消」）、签到 / 撤销签到、评论、管理员用户列表 | `parseDbTime()` 兼容 Safari 时间解析；`loadEvents('reset' / 'more' / 'refresh')` 三种刷新模式；所有核心按钮请求期间禁用防连点；用户输入统一 HTML 转义 |
| `profile.html` | 个人中心：「我的报名」分页与取消报名、「修改密码」面板 | 取消按钮在活动开始后自动隐藏；改密成功后写入返回的新令牌 |

### 数据库与脚本

| 文件 | 作用 |
| --- | --- |
| `database/schema.sql` | 全部 DDL：`CREATE DATABASE IF NOT EXISTS` + `USE` + 7 张业务表 + 约束（`UNIQUE` / `CHECK` / `enum` / 双向 `CASCADE`）+ 索引 + 4 个分类与 5 个场地的种子数据。可直接 `mysql -u root -p < database/schema.sql` |
| `scripts/首次安装并启动.bat` | 一键安装：检测 Python → 建 `.venv` → 装依赖 → 引导生成 `.env` → 建库建表 → 启动服务并打开浏览器 |
| `scripts/启动校园活动系统.bat` | 日常启动：服务未运行则后台启动，已运行则直接开浏览器（端口读 `.env` 的 `PORT`） |
| `scripts/停止校园活动系统.bat` | 只停止本项目的进程，不会误杀其它占端口的程序 |
| `scripts/交付前清理.bat` | 打包 / 提交前工具：交互确认后把 `.env` 备份到 `%USERPROFILE%\campus_events_env_backup.txt`，再删除 `.env` / `.venv` / `__pycache__` / `.pytest_cache` / `.coverage` / `htmlcov`，并打印自查清单 |
| `scripts/er_diagram.py` | 用 Pillow 直接绘制 ER 图（不依赖 Graphviz），输出 `docs/images/er-diagram.png`，改表结构后重跑即可保持图文一致 |
| `scripts/bench_queries.py` | 在临时库造数（3000 活动 / 9000 报名 / 4000 评论 / 500 用户），对同一批 SQL 做「有索引 vs 去索引」的 `EXPLAIN` + 耗时对比，跑完自动删库；课程报告「性能实测」直接引用 |

### 测试文件 `tests/`

`conftest.py` 是所有用例的公共基座：把连接切到 `TEST_DB_NAME`（默认 `campus_events_test`）、会话前后清空业务数据（保留 `venues` / `categories` 种子）、提供 `client` / `db_fetch` / `unique_event_window` 等夹具，并用「单调递增、互不重叠」的时间窗避免场地冲突导致的偶发失败。

| 文件 | 用例数 | 覆盖内容 |
| --- | --- | --- |
| `conftest.py` | — | 测试库切换、数据清理、公共夹具与工具函数 |
| `test_auth.py` | 3 | 注册 / 登录 / 令牌基础 |
| `test_unauthorized.py` | 19 | 未登录访问各接口一律 401 |
| `test_boundaries.py` | 8 | 超长姓名 / 邮箱 / 标题、过去时间、角色限制、非 API 路径 404 |
| `test_register_event.py` | 1 | 并发报名防超卖（两线程抢 1 个名额） |
| `test_cancel_registration.py` | 3 | 取消报名、重复取消、取消后重新报名 |
| `test_check_in.py` | 5 | 签到时间窗、重复签到、越权签到 |
| `test_close_event.py` | 6 | 关闭 / 重新开放报名及其状态约束 |
| `test_event_manage.py` | 8 | 发布 / 编辑 / 删除保护 + 分页元信息 |
| `test_event_detail.py` | 4 | 活动详情字段完整性、404、报名状态 |
| `test_comments.py` | 5 | 评论发布 / 长度 / 空内容 / 404 / 未报名不得评论 |
| `test_categories.py` | 6 | 分类列表、多分类发布、按分类筛选、非法分类 |
| `test_my_registrations.py` | 2 | 我的报名与分页、仅本人可见 |
| `test_rate_limit.py` | 3 | 登录限流、按账号隔离、成功后重置 |
| `test_fixes.py` | 19 | 修复点回归：撤销签到、管理员代操作、时间窗、删除保护、取消留痕 |
| `test_v2_regressions.py` | 9 | 本轮复核修复的回归：`started/ended`、`close/closed` 兼容、开始时间锁定、缩容下限、登出、改密、取消留痕、保留首次报名时间 |
| **合计** | **101** | 可用 `pytest --collect-only -q` 核对 |

### 根目录配置与元文件

| 文件 | 作用 |
| --- | --- |
| `requirements.txt` | 运行时依赖：Flask、Flask-Cors、mysql-connector-python、bcrypt、itsdangerous、python-dotenv |
| `requirements-dev.txt` | 开发依赖：`-r requirements.txt` + pytest、pytest-cov、pillow（画 ER 图） |
| `pytest.ini` | 固定 `testpaths = tests`；覆盖率参数以注释形式给出，按需临时启用 |
| `.env.example` | 环境变量模板，含全部键与注释；复制为 `.env` 后填真实值 |
| `.env` | 本机真实配置（数据库密码 + 签名密钥）。已被 `.gitignore` 忽略，**交付前必须删除** |
| `.gitignore` | 忽略 `.venv/`、`__pycache__/`、`.pytest_cache/`、`.coverage*`、`htmlcov/`、`.env`、日志、`*.bak`、`backup*.sql` 等 |
| `.vscode/settings.json` | `python.terminal.useEnvFile = true`，让 VS Code 终端自动带上 `.env` |

## 文档地图（每份文档讲什么）

仓库里只保留**交付材料**（老师 / 助教看的）：`README.md` 与 `docs/` 下的文档。团队自查用的「问题清单 / 修复记录」属于内部过程材料，**不随交付包提供**（已归档到仓库外的同级目录 `归档-过程文档/`），其中与本项目相关的结论已全部反映在本文档与 `docs/` 中。

### docs/ 交付文档

| 文档 | 类型 | 内容概要 | 读者 |
| --- | --- | --- | --- |
| `README.md` | 交付 | 项目总览、文件清单、安装运行、环境变量、接口、业务规则、测试与交付清单 | 所有人，入口 |
| `docs/README.md` | 交付 | **docs 目录索引**：4 份材料的清单与用途、3 条阅读路线（跑起来 / 写报告 / 答辩）、图表生成与更新约定 | 先看这个，再深入 |
| `docs/数据库设计说明.md` | 交付 | 带目录。系统结构图与并发控制点、ER 图、Schema 设计决策与 1NF/2NF/3NF 论证、约束一览、索引清单 + 已知局限、6 条示例查询（大厅聚合 / 场地冲突 / 报名名单 / 取消留痕 / 出勤率 / 组织者统计）、含与不含索引的 `EXPLAIN` + 实测耗时 | 写报告、准备答辩 |
| `docs/测试报告.md` | 交付 | 带目录。测试环境与运行命令、按模块的测试范围表、15 个文件 101 个用例的分布、5 个关键场景（并发防超卖 / 权限矩阵 / 时间窗 / 删除保护 / 场地冲突）、覆盖率（79%，870 语句 / 181 未覆盖）、结论 | 写报告、需要「测试证据」 |
| `docs/images/er-diagram.png` | 交付 | 7 张表的全部列与类型、PK/FK/UQ/CK 标记、8 条关系连线（含 `cancelled_by`）、图例（枚举取值 / 级联规则 / 索引） | 报告插图、答辩 |
| `docs/images/coverage.png` | 交付 | 早期覆盖率截图（78%），以测试报告正文的 79% 为准；可用 `pytest --cov=app --cov-report=html` 重生成 | 报告插图 |

### 作业要求/

`作业要求/` 下是课程作业要求的截图（3 张 PNG），只用于对照评分点，不参与运行、不被代码引用。

该目录（以及本地的 `作业完成情况清单.txt`）属于课程/个人材料，已写入 `.gitignore`，**不会提交到在线仓库**；因此克隆仓库后看不到这两项，属正常现象。

## 数据库设计

共 7 张业务表，建表脚本见 [`database/schema.sql`](database/schema.sql)。

![ER 图](docs/images/er-diagram.png)

> ER 图由 `scripts/er_diagram.py` 根据本表生成（`pip install pillow` 后运行该脚本），
> 表结构改动后重跑即可保证图与 `schema.sql` 一致。

| 表 | 说明 | 关键约束 |
| --- | --- | --- |
| `users` | 用户（学生 / 组织者 / 管理员） | `email` 唯一；`role` 为 `enum`；`token_version` 用于令牌吊销 |
| `venues` | 场地 | `available_status` 标记是否可用；`venue_name` 唯一 |
| `events` | 活动 | `organizer_id` / `venue_id` 外键；`status` 为 `enum('open','closed')`；`CHECK (capacity > 0)`、`CHECK (end_time > start_time)`；`(venue_id, start_time, end_time)` 复合索引用于场地冲突检测 |
| `registrations` | 报名记录 | `UNIQUE(student_id, event_id)` 防重复报名；`status` 为 `enum('registered','cancelled','checked_in')`；`cancelled_at` / `cancelled_by`（外键 `ON DELETE SET NULL`）记录取消人与时间；`idx_reg_event_status(event_id, status)` 服务名单与计数查询 |
| `categories` | 活动分类 | — |
| `event_categories` | 活动 ↔ 分类（N:M） | 复合主键 `(event_id, category_id)`，双向外键级联 |
| `comments` | 活动评论 | `event_id` / `user_id` 外键，双向外键级联；`idx_event(event_id)` |

关系要点：

- 一个组织者可发布多个活动（1:N），一个活动归属一个场地（N:1）。
- 一个学生可报名多个活动，一个活动可被多个学生报名（N:M，通过 `registrations` 关联）。
- 一个活动可挂多个分类（N:M，通过 `event_categories` 关联）。
- 删除活动时：`comments` / `event_categories` / `registrations` 均由 DB 外键级联清理（`ON DELETE CASCADE`），应用层再显式兜底清理一次以兼容未升级的旧库（见 `delete_event()`）。
- 所有时间列统一为 `DATETIME`，连接时固定会话时区 `DB_TIME_ZONE`（默认 `+08:00`），避免 Python/MySQL 时区不一致导致报名窗口错位。
- 范式、索引策略、示例 SQL 与「有/无索引」的实测对比见 [`docs/数据库设计说明.md`](docs/数据库设计说明.md)。
- 表名在 SQL 中统一使用**小写**（`users` / `events` / …），因此可在 `lower_case_table_names=0` 的 Linux / macOS MySQL 上直接运行。

建表脚本同时写入基础种子数据：4 个活动分类、5 个场地。

## 快速开始

### 环境要求

- Python 3.10+（安装时勾选 *Add python.exe to PATH*）
- MySQL 8.0+
- Git（可选，用于克隆仓库）

### 手动安装

1. 安装依赖

   ```bash
   pip install -r requirements.txt
   ```

2. 初始化数据库（会创建 `campus_events` 库并重建所有表）

   ```bash
   mysql -u root -p < database/schema.sql
   ```

   也可以使用项目自带脚本（会读取 `.env` 中的连接信息，且对老库幂等补齐列 / 外键 / 索引）：

   ```bash
   python backend/init_db.py
   ```

   初始化演示数据（方便第一次打开就有内容可看）：

   ```bash
   python backend/seed_demo.py
   ```

3. 配置环境变量：复制模板并生成应用密钥

   ```bash
   # Windows PowerShell
   Copy-Item .env.example .env
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

   将生成的随机串填入 `.env` 的 `APP_SECRET_KEY`，并填写数据库密码。

4. 启动后端

   ```bash
   python backend/app.py
   ```

5. 浏览器访问 <http://127.0.0.1:5000/>（前端由 Flask 托管，无需额外开启 Live Server）。

### 一键安装

> 适合组员快速体验，前提是已装好 Python 3.10+ 与 MySQL。

1. 解压项目，**双击 `scripts/首次安装并启动.bat`**。
2. 脚本自动完成：创建 `.venv` 虚拟环境 → 安装依赖 → 引导填写数据库连接（生成 `.env`）→ 建库建表 → 启动服务并打开浏览器。
3. 后续使用双击 **`scripts/启动校园活动系统.bat`**（服务未运行则自动启动，已运行则直接打开浏览器）。
4. 关闭服务双击 **`scripts/停止校园活动系统.bat`**。
5. 打包 / 提交前双击 **`scripts/交付前清理.bat`**。

说明：

- 首次安装输入的 MySQL 密码仅写入本机 `.env`，不会上传、也不会进入 git。
- `backend/init_db.py` 默认**不会**改动已存在的库；只有显式运行 `python backend/init_db.py --force` 才会删表重建。
- 启动 / 停止脚本会从 `.env` 读取 `PORT`，改端口后无需修改脚本。
- 换电脑 / 换同学重复「双击首次安装」即可，各环境配置相互独立。

## 环境变量

| 变量 | 默认 / 示例 | 说明 |
| --- | --- | --- |
| `DB_HOST` / `DB_PORT` | `127.0.0.1` / `3306` | MySQL 地址与端口 |
| `DB_USER` / `DB_PASSWORD` | `root` / （必填） | MySQL 账号密码 |
| `DB_NAME` | `campus_events` | 开发库名 |
| `TEST_DB_NAME` | `campus_events_test` | 测试库名，`tests/conftest.py` 自动切换 |
| `APP_SECRET_KEY` | 随机长串 | 令牌签名密钥；**缺失、占位符或长度 < 32 会拒绝启动** |
| `TOKEN_MAX_AGE` | `86400` | 令牌有效期（秒） |
| `FLASK_DEBUG` | `0` | 调试模式开关，生产环境用 `0` |
| `PORT` | `5000` | 后端端口，启动脚本也读它 |
| `LOGIN_RATE_LIMIT` | `10/60` | 登录限流（同一 IP + 邮箱 的次数 / 窗口秒数） |
| `REGISTER_RATE_LIMIT` | `20/3600` | 注册限流（同一 IP） |
| `COMMENT_RATE_LIMIT` | `20/60` | 评论限流（同一用户） |
| `DB_POOL_SIZE` | `5` | 连接池大小 |
| `DB_TIME_ZONE` | `+08:00` | 会话时区，保证 `NOW()` 判断与页面展示一致 |
| `CORS_ORIGINS` | `*` | 允许的跨域来源，逗号分隔；生产环境建议收紧 |
| `TRUSTED_PROXIES` | （空） | 可信反向代理 IP；只有来自这些 IP 的请求才解析 `X-Forwarded-For`，避免伪造 XFF 绕过限流 |

## 认证与安全

- 登录成功后返回 `token`，前端保存到 `localStorage`，后续请求自动携带：

  ```text
  Authorization: Bearer <token>
  ```

- 服务端从令牌解析 `user_id`，**不信任前端传来的 `user_id` / `organizer_id`**。
- 令牌默认 24 小时过期，过期后前端自动跳回登录页；令牌中带 `token_version`，退出登录 / 修改密码后旧令牌**立即失效**（不用等 24 小时）。
- 密码使用 bcrypt 加盐哈希存储，校验规则为「≥8 位且包含大小写字母与数字」，并限制 bcrypt 72 字节上限。
- 登录按「IP + 邮箱」限流（默认 10 次 / 60 秒），注册按 IP 限流（默认 20 次 / 小时），评论按用户限流（默认 20 条 / 60 秒），超限返回 `429`。
- 数据库凭据与应用密钥全部从 `.env` 读取，`.env` 已被 `.gitignore` 忽略；`APP_SECRET_KEY` 弱密钥直接拒绝启动。
- **打包 / 提交前请同步删掉 `.env`（以及 `.venv`、`__pycache__`、`.pytest_cache`），否则真实数据库密码与签名密钥会一起交出**。可直接双击 `scripts/交付前清理.bat`。
- 跨域来源由 `CORS_ORIGINS` 控制（默认 `*`，生产环境建议收紧为具体地址）。
- 前端对活动标题、描述、评论、用户名等用户输入统一做 HTML 转义，防范存储型 XSS。
- 所有接口的异常统一转换为 `{"code", "message", "data"}`，不向前端回显内部堆栈或 SQL 细节。

## API 接口

所有接口统一返回 `{"code", "message", "data"}` 结构，`code` 为业务码（2xx 成功、4xx / 5xx 失败）：

```json
{ "code": 200, "message": "ok", "data": { } }
```

出错时返回 `{"code", "message"}`（如 `{"code": 403, "message": "权限不足"}`），HTTP 状态码与 `code` 一致。分页接口额外返回 `total` / `page` / `page_size` / `pages`，`data` 仍为数组。

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| POST | `/api/register` | 注册（学生 / 组织者） | 公开 |
| POST | `/api/login` | 登录，返回用户信息与令牌 | 公开 |
| POST | `/api/logout` | 退出登录（令牌立即失效） | 登录 |
| PUT | `/api/change_password` | 修改密码（校验旧密码，返回新令牌） | 登录 |
| GET | `/api/me` | 当前登录用户信息 | 登录 |
| GET | `/api/events` | 活动列表（`?page=&page_size=` 分页，`?category_id=` 分类筛选，含 `started` / `ended`） | 登录 |
| GET | `/api/events/<event_id>` | 活动详情（组织者、分类、余量、是否已报名、是否开始/结束） | 登录 |
| POST | `/api/register_event` | 报名活动（仅学生；事务 + 行锁，防超卖） | 学生 |
| GET | `/api/user_registrations/<user_id>` | 我的报名记录（分页） | 仅本人 |
| PUT | `/api/cancel_registration/<registration_id>` | 取消报名 | 本人 / 该活动组织者 / 管理员 |
| POST | `/api/create_event` | 发布活动（可选 `category_ids`） | 组织者 / 管理员 |
| PUT | `/api/update_event/<event_id>` | 编辑活动（带 `category_ids` 时更新分类；已开始的活动不可改开始时间） | 该活动组织者 |
| DELETE | `/api/delete_event/<event_id>` | 删除活动（已有签到或已开始则 409） | 该活动组织者 / 管理员 |
| PUT | `/api/close_event/<event_id>` | 关闭 / 重新开放活动报名（`{"action":"close"}` 或 `"open"`，兼容 `"closed"`） | 该活动组织者 |
| GET | `/api/event_registrations/<event_id>` | 活动报名名单（分页；`?include_cancelled=1` 可看取消留痕） | 该活动组织者 |
| DELETE | `/api/remove_registration/<registration_id>` | 将学生移出活动 | 该活动组织者 |
| PUT | `/api/check_in/<registration_id>` | 学生签到 | 该活动组织者 / 管理员 |
| PUT | `/api/undo_check_in/<registration_id>` | 撤销签到（误签纠正） | 该活动组织者 / 管理员 |
| GET | `/api/venues` | 可用场地列表 | 登录 |
| GET | `/api/categories` | 活动分类列表 | 登录 |
| GET | `/api/comments/<event_id>` | 活动评论（分页） | 登录 |
| POST | `/api/comments` | 发表评论（需报名过该活动 / 组织者 / 管理员） | 登录 |
| DELETE | `/api/delete_comment/<comment_id>` | 删除评论 | 评论作者 / 活动组织者 / 管理员 |
| GET | `/api/admin/users` | 全部用户列表（分页） | 管理员 |

## 业务规则

- 只有学生账号可以报名；组织者负责发布 / 编辑 / 关闭活动与签到，管理员负责监管。
- 发布活动要求开始时间晚于当前时间、结束时间晚于开始时间、名额不超过场地容量，且不能选择已停用的场地；同一场地时间重叠会被拒绝（`SELECT ... FOR UPDATE` 串行化校验）。
- 报名要求：活动 `status='open'`、未开始、未结束、名额未满、未重复报名。
- 签到仅允许在活动开始后 ~ 结束前，由该活动组织者（或管理员）操作；已签到的报名不可再取消或移出，误签可通过「撤销签到」纠正。
- 已开始 / 已结束的活动不能重新开放报名。
- 编辑活动时，新名额不能小于当前有效报名人数；活动一旦开始，开始时间不再允许修改。
- 删除活动前会校验：活动未开始、且没有签到记录，否则返回 409。
- 评论 = 活动评价：只有报名过该活动的学生、该活动组织者或管理员可以评论（并有频次限制）。
- 取消报名会写入 `cancelled_at` / `cancelled_by`；重新报名保留首次报名时间，并清空取消留痕。
- 退出登录会递增 `users.token_version`，所有已签发的旧令牌立即失效；修改密码同样会让旧令牌失效并返回新令牌。

## 管理员

管理员不能自助注册（注册页仅可选学生 / 组织者），需将已有账号提升：

```bash
python backend/make_admin.py someone@example.com
```

管理员可删除任意活动 / 评论、代组织者签到与撤销签到、取消任意报名、发布活动，并在活动大厅的「用户管理」中查看全部用户。

## 测试

手动验收流程：

1. 注册一个学生账号和一个组织者账号（密码需 ≥8 位，含大小写字母与数字）。
2. 组织者发布活动（可选择分类），学生报名、取消、重新报名。
3. 并发测试：对满员活动同时发起多个报名请求，验证不再超卖。
4. 组织者签到 → 撤销签到 → 再次签到，验证状态流转正确。

自动化测试（需先初始化数据库并配置好 `.env`）：

```bash
pip install -r requirements-dev.txt

# 快速跑（不显示覆盖率）
pytest tests/ -q

# 看覆盖率
pytest tests/ --cov=app --cov-report=term-missing

# 生成 HTML 覆盖率报告
pytest tests/ --cov=app --cov-report=html
```

首次跑测试前先初始化测试库（`conftest.py` 会自动切到 `TEST_DB_NAME`）：

```powershell
$env:DB_NAME = 'campus_events_test'
python backend/init_db.py
```

测试库隔离：会话开始 / 结束时清空业务数据、时间窗单调分配，因此可反复运行、不会污染开发库，也不会因历史数据累积或场地冲突而偶发失败。

覆盖范围：认证与权限、输入边界、并发报名防超卖、取消 / 重新报名、签到与撤销签到、评论、分类、活动管理、分页、限流、404 处理、登出与改密。每个测试文件对应内容见「[测试文件](#测试文件-tests)」一节。

> 当前 **101 个用例全部通过**（连续 3 次，约 56s/次），行覆盖率约 **79%**（实测 870 条语句 / 181 条未覆盖）。
> 详细报告与覆盖率截图见 [`docs/测试报告.md`](docs/测试报告.md)。

## 已知限制与后续计划

1. 活动列表排序含表达式 `(e.end_time < NOW())`，走不了 `idx_start_time`；实测 3000 行时 1.17ms，完全够用，彻底解法（物化「是否已结束」列或拆两条查询）与取舍记录在 `docs/数据库设计说明.md §4`。
2. 管理员能力偏窄：只能看用户列表，不能改角色 / 禁用账号；场地、分类只有查询接口，没有后台主数据增删改。
3. 超卖与场地冲突由应用层事务 + 行锁保证，数据库层没有触发器 / 存储过程兜底；若课程要求展示 DB 级约束，可加 `BEFORE INSERT` 触发器。
4. 令牌放在 `localStorage`（有 XSS 风险）、无 refresh token；本轮只做到「登出 / 改密即失效」，未改造成 HttpOnly Cookie。
5. 前端无自动化 E2E 测试（只有语法检查 + 人工冒烟），建议补 Playwright 冒烟脚本。
6. 依赖版本仍为 `>=` 不锁版本，换环境可能装到不兼容的新版本。
7. 作业要求里的视频演示与正式报告 PDF 不在代码仓库范围内：报告可直接引用 `docs/数据库设计说明.md`（ER / 范式 / 索引 / 示例 SQL / 性能实测）与 `docs/测试报告.md`（用例分布 / 覆盖率 / 关键场景）。

## 交付前 checklist

- [ ] 1. `python backend/init_db.py`（开发库）与测试库各执行一次，确认打印「库结构已是最新」或升级摘要。
- [ ] 2. `pytest tests -q` → `101 passed`。
- [ ] 3. 双击 `scripts/交付前清理.bat`（删除 `.env` / `.venv` / 缓存，`.env` 自动备份到用户目录）。
- [ ] 4. 确认压缩包里没有 `.env` / `.venv` / `__pycache__` / `.pytest_cache` / `htmlcov`，也没有过程记录（问题清单、修复记录）。
- [ ] 5. 在一台干净环境按「快速开始」再走一遍（可选但强烈建议）。
- [ ] 6. 若改了表结构，重跑 `python scripts/er_diagram.py` 并更新 `docs/` 与 README 中的表说明。

## 文档维护约定

- **代码变了，同步四处**：`README.md`（接口 / 环境变量 / 文件清单）、`docs/README.md`（文档清单与阅读路线）、`docs/数据库设计说明.md`（表结构与索引）、`docs/测试报告.md`（用例数与覆盖率）。
- 表结构改动后必须重生成 `docs/images/er-diagram.png`；新增 / 删除 docs 下的文件要同步 `docs/README.md` 与本文件的目录树。
- 过程材料（问题清单、逐文件修复记录）**不随交付包提供**；每轮修复完成后把它们归档到仓库外的 `归档-过程文档/`，仓库内只保留「当前事实」（`README.md` + `docs/` + 代码）。
- 交付材料（`README.md` + `docs/`）是「当前事实」，过程文档是「演进历史」；两者冲突时以交付材料与代码为准。

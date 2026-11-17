# 校园活动报名与管理系统

数据库课程作业（Track 1：数据库应用开发）。Flask + MySQL 实现的校园活动发布、报名、签到与统计平台：
学生报名参加活动，组织者发布活动并负责签到，管理员维护用户角色与场地。

前端是原生 HTML/CSS/JS 三个页面，由 Flask 直接托管，不用另外起服务。

| 项 | 内容 |
| --- | --- |
| 后端 | Python 3.10+ / Flask 3 / mysql-connector-python / bcrypt / itsdangerous |
| 数据库 | MySQL 8.0.19+（CHECK 约束需 8.0.16+，种子脚本的行别名写法需 8.0.19+） |
| 前端 | 原生 HTML + CSS + JavaScript，无构建步骤 |
| 测试 | pytest，156 个用例，行覆盖率 89% |
| 代码仓库 | <https://github.com/shenghuoxuejia/campus-event-management-system> |

## 目录

- [1. 功能概览](#1-功能概览)
- [2. 目录结构](#2-目录结构)
- [3. 快速开始](#3-快速开始)
- [4. 环境变量](#4-环境变量)
- [5. 数据库设计](#5-数据库设计)
- [6. 接口](#6-接口)
- [7. 关键业务规则](#7-关键业务规则)
- [8. 测试](#8-测试)
- [9. 性能基准](#9-性能基准)
- [10. 已知限制](#10-已知限制)
- [11. 文档与交付物](#11-文档与交付物)

## 1. 功能概览

**学生**：注册后浏览活动大厅（分页、按分类筛选）、报名 / 取消报名、看自己的报名状态、在活动下评论、改密码。

**组织者**：发布 / 编辑 / 关闭活动、查看报名名单与出入率统计、为学生签到 / 撤销签到、把学生移出活动、删除自己发起的活动。

**管理员**：管理用户角色（组织者 ↔ 管理员）、维护场地（新增 / 改容量 / 停用 / 删除）、管理任意活动与评论、查看平台概览（分类分布、场地利用率、最热活动）。

面向的技术点：多对多建模（活动 ↔ 分类、学生 ↔ 活动）、事务与行锁防超卖、数据库端约束（CHECK / 外键 / 唯一键 / 触发器 / 视图 / 存储过程）、索引策略与查询性能实测。

## 2. 目录结构

```text
backend/         Flask 应用与运维脚本
  app.py           主程序：31 个接口、鉴权、限流、事务与行锁、数据库异常映射
  init_db.py       建库建表（幂等），老库自动补列 / 索引 / 外键并校验数据库端对象
  make_admin.py    创建管理员，或把已注册账号提权
  setup_env.py     交互式生成 .env（随机生成 APP_SECRET_KEY）
frontend/        三个静态页，由 Flask 托管
  login.html       登录 / 注册（注册即登录）
  index.html       活动大厅：列表筛选、详情、报名、评论、组织者面板、管理员面板
  profile.html     我的报名：报名状态、取消报名、改密码
database/
  schema.sql       建库建表 + 约束 + 索引 + 种子数据 + 视图 / 触发器 / 存储过程
scripts/
  启动校园活动系统.bat   一键：建虚拟环境 → 装依赖 → 生成 .env → 建库 → 启动
  停止校园活动系统.bat   只杀本项目（按 PORT 找到监听进程并核对命令行）的进程
  er_diagram.py         按 schema.sql 生成 ER 图（docs/images/er-diagram.png）
  bench_queries.py      在临时库里造 3000 活动 / 9000 报名，测有索引 vs 无索引
tests/           pytest：156 个用例，含并发、触发器、限流、一致性回归
docs/            数据库设计说明（ER、范式、索引、示例 SQL、性能实测）、测试报告、配图
```

## 3. 快速开始

### 3.1 一键启动（Windows）

双击 `scripts/启动校园活动系统.bat`。它会依次：找 Python → 建 `.venv` → 装依赖 → 首次运行时问你数据库信息并生成 `.env` → 建库建表 → 启动服务。关服务用 `scripts/停止校园活动系统.bat`。

### 3.2 手动四步

```bash
# 1) 装依赖
pip install -r requirements.txt

# 2) 建库建表（二选一）
mysql -u root -p < database/schema.sql
python backend/init_db.py          # 读 .env 里的连接信息，老库会顺手补齐缺的列/索引/外键

# 3) 配置环境变量：复制 .env.example 为 .env，填数据库密码
python -c "import secrets; print(secrets.token_urlsafe(48))"   # 生成 APP_SECRET_KEY

# 4) 启动
python backend/app.py
```

浏览器打开 <http://127.0.0.1:5000/>（未登录会跳到登录页）。建完库只有场地和分类的种子数据，账号在注册页自己注册（可选角色：学生 / 组织者）。

### 3.3 创建管理员

管理员不能自助注册，用脚本提权或创建：

```bash
python backend/make_admin.py 你的邮箱@example.com                    # 已注册账号提权
python backend/make_admin.py admin@campus.local --create Admin@2026  # 直接建一个（已存在则重置密码）
```

## 4. 环境变量

`.env` 已被 `.gitignore` 忽略，模板见 `.env.example`。启动时 `APP_SECRET_KEY` 缺失、是占位符或短于 32 字符会直接拒绝启动。

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `DB_HOST` / `DB_PORT` | `127.0.0.1` / `3306` | MySQL 地址 |
| `DB_USER` / `DB_PASSWORD` | `root` / 必填 | MySQL 账号密码 |
| `DB_NAME` | `campus_events` | 开发库 |
| `TEST_DB_NAME` | `campus_events_test` | 测试库，测试前自动切过去；不能和 `DB_NAME` 相同 |
| `APP_SECRET_KEY` | 必填 | 令牌签名密钥，长度 < 32 或占位符直接拒绝启动 |
| `TOKEN_MAX_AGE` | `86400` | 令牌有效期（秒） |
| `FLASK_DEBUG` | `0` | 调试开关，生产请用 0 |
| `PORT` | `5000` | 后端端口，启动 / 停止脚本也读它 |
| `LOGIN_RATE_LIMIT` | `10/60` | 登录限流：同一 IP + 邮箱，次数 / 窗口秒数；改密码也复用它（按用户） |
| `REGISTER_RATE_LIMIT` | `20/3600` | 注册限流，按 IP |
| `COMMENT_RATE_LIMIT` | `20/60` | 评论限流，按用户 |
| `DB_POOL_SIZE` | `5` | 连接池大小 |
| `DB_TIME_ZONE` | `+08:00` | 会话时区，保证 `NOW()` 判断与页面展示一致 |
| `CORS_ORIGINS` | `*` | 允许的跨域来源，逗号分隔 |
| `TRUSTED_PROXIES` | 空 | 只有来自这些 IP 的请求才解析 `X-Forwarded-For`（防伪造绕过限流） |

## 5. 数据库设计

7 张业务表：`users`、`venues`、`categories`、`events`、`event_categories`、`registrations`、`comments`。
完整 ER 图、范式论证（3NF / BCNF）、索引清单和示例 SQL 见 [docs/数据库设计说明.md](docs/数据库设计说明.md)。

**建模要点**

- `users.role` 为 `student / organizer / admin`，注册接口只接受前两种，管理员由脚本产生。
- `event_categories`、`registrations` 分别承载「活动 ↔ 分类」「学生 ↔ 活动」的多对多关系；`registrations` 上 `UNIQUE(student_id, event_id)` 保证一人一活动一条记录（取消后复用同一行，保留首次报名时间）。
- `registrations.status` 为 `registered / cancelled / checked_in`，签到与取消的时间戳分别落库，`cancelled_by` 区分本人取消与组织者移出。

**库内约束（不只靠应用层）**

| 类型 | 内容 |
| --- | --- |
| CHECK | `events.capacity > 0`、`events.end_time > start_time`、`venues.capacity > 0`、`venues.available_status IN (0,1)` |
| UNIQUE | `users.email`、`venues.venue_name`、`categories.category_name`、`registrations(student_id, event_id)` |
| 外键 | `events.organizer_id → users`、`events.venue_id → venues`、`registrations.event_id → events`（级联删除）、评论随活动/用户级联 |
| 视图 | `v_event_overview`：报名数 / 签到数 / 余量 / 是否开始结束一次算完，列表、详情、统计共用同一口径 |
| 触发器 | `trg_events_check_venue_bi` / `_bu`（同场地时间段重叠、名额超场地容量、停用场地）、`trg_registrations_status_bi` / `_bu`（状态与时间戳一致）——绕过接口直接写库也能拦住 |
| 存储过程 | `sp_event_attendance(event_id)`：报名数、签到数、取消数、出入率、上座率 |

**索引**：`idx_start_time`、`idx_events_venue_time(venue_id, start_time, end_time)`、`idx_events_org_start`、`idx_reg_event_status(event_id, status)`、`idx_comments_event_created(event_id, created_at)`，加上唯一键自带索引。索引取舍和「有索引 / 无索引」实测对比见设计文档第 4、5 节。

**种子数据**：4 个分类、5 个场地（活动中心 / 图书馆报告厅 / 体育馆 / 教学楼 A101 / 操场）。不含任何账号。

## 6. 接口

所有接口统一返回 `{"code", "message", "data"}`，`code` 与 HTTP 状态码一致（200 / 400 / 401 / 403 / 404 / 409 / 429 / 500）。
额外返回值一律放进 `data`，不平铺顶层：注册 / 登录 / 改密码的令牌是 `data.token`，新增场地是 `data.venue_id`。
分页接口在 `data` 之外还返回 `total` / `page` / `page_size` / `pages`，`data` 仍是数组；`page_size` 上限 100，活动列表默认 12，其他列表默认 20。
鉴权用 `Authorization: Bearer <token>`，服务端从令牌解析身份，不信任前端传的 `user_id`。

### 公开

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/register` | 注册，只接受 `student` / `organizer`，成功直接返回令牌 |
| POST | `/api/login` | 登录，返回用户信息与令牌 |

### 登录后可用（任意角色）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/me` | 当前用户 |
| POST | `/api/logout` | 退出登录（旧令牌立即失效） |
| PUT | `/api/change_password` | 改密码，返回新令牌，旧令牌立即失效 |
| GET | `/api/events` | 活动列表，`?page=&page_size=&category_id=`，走 `v_event_overview` |
| GET | `/api/events/<id>` | 活动详情，附当前用户的 `is_registered` |
| GET | `/api/venues` | 可用场地 |
| GET | `/api/categories` | 分类列表 |
| GET | `/api/comments/<event_id>` | 评论列表（分页） |

### 学生

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/register_event` | 报名（事务 + 行锁，名额不超卖） |
| PUT | `/api/cancel_registration/<id>` | 取消报名：本人 / 该活动组织者 / 管理员 |
| GET | `/api/user_registrations/<user_id>` | 我的报名（仅本人） |

### 组织者 / 管理员（限本人发布的活动，管理员不限）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/create_event` | 发布活动 |
| PUT | `/api/update_event/<id>` | 编辑活动 |
| DELETE | `/api/delete_event/<id>` | 删除活动（有签到记录或已开始则 409） |
| PUT | `/api/close_event/<id>` | 关闭 / 重新开放报名，body `{"action": "close" \| "open"}` |
| GET | `/api/event_registrations/<id>` | 报名名单，`?include_cancelled=1` 带已取消的 |
| DELETE | `/api/remove_registration/<id>` | 把学生移出活动 |
| PUT | `/api/check_in/<id>` | 签到 |
| PUT | `/api/undo_check_in/<id>` | 撤销签到 |
| GET | `/api/events/<id>/stats` | 活动统计：出入率、状态分布、报名趋势（走存储过程） |

### 评论

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/comments` | 发评论，仅报名过该活动的学生、活动组织者、管理员 |
| DELETE | `/api/delete_comment/<id>` | 删评论：作者 / 该活动组织者 / 管理员 |

### 管理员专有

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/admin/users` | 用户列表（分页） |
| PUT | `/api/admin/users/<id>/role` | 组织者与管理员互转（不能改自己） |
| GET | `/api/admin/venues` | 全部场地（含停用的，附活动数） |
| POST | `/api/venues` | 新增场地 |
| PUT | `/api/venues/<id>` | 修改 / 停用场地 |
| DELETE | `/api/venues/<id>` | 删除场地（有活动在用则 409） |
| GET | `/api/admin/stats` | 平台概览：分类分布、场地利用率、最热活动 |

> 统计类接口：`/api/events/<id>/stats` 和 `/api/admin/stats` 目前只有 API，前端还没做展示页，可以用 `curl` 带令牌查看。

## 7. 关键业务规则

**生命周期与时间窗**

- 发布：开始时间必须在未来、结束晚于开始、名额不超过场地容量（上限 100000）、不能选停用场地，同场地时间段重叠会被拒绝（应用层行锁 + 触发器双保险）。
- 编辑：活动开始后不能改开始时间，名额不能小于当前有效报名数；场地被停用后，原已在该场地的活动仍可继续编辑。
- 签到：只能在活动开始后、结束前，由该活动组织者或管理员操作；已签到的报名不能取消、不能移出，签错用撤销签到。
- 删除：有签到记录、或已开始的活动不能删（409）；场地还有活动在用只能停用不能删。

**报名状态**

- 取消报名记 `cancelled_at` / `cancelled_by`；重新报名复用原记录，首次报名时间保留。
- 被组织者移出（`cancelled_by` 不是本人）的报名，学生不能自己重新报名。
- 名额按「非取消」记录计数，取消即释放名额。

**并发与一致性**

- 加锁顺序固定为 `venues → events → registrations`：发布 / 编辑活动先锁场地行（编辑会把原场地和目标场地按 `venue_id` 升序一起锁），报名类操作先锁活动行再碰报名行，避免反向加锁造成 1213 死锁。
- 报名、缩容、取消、签到、移出都在同一事务里「先锁再判断再写」，并校验 `rowcount`。
- 数据库异常统一在 `db_cursor` 里映射：1062 唯一键冲突 / 1644 触发器 SIGNAL / 1213 死锁 / 1205 锁等待超时 → 409（可重试）；1264 超范围 / 1406 数据过长 / 1452 外键失效 → 400；其余 500。

**鉴权**

- 令牌带 `token_version`，登出 / 改密码时 `token_version + 1`，已签发的旧令牌立刻失效，不用等过期。
- 越权统一 403，未登录 401；登录失败提示不区分「邮箱不存在」和「密码错误」。
- 登录 / 注册 / 评论 / 改密码都有内存滑动窗口限流。

## 8. 测试

```bash
pip install -r requirements-dev.txt

# 第一次跑之前先初始化测试库（测试库和开发库完全隔离）
$env:DB_NAME = 'campus_events_test'; python backend/init_db.py

pytest tests -q
```

**156 个用例，全量跑一遍约 100 秒，行覆盖率 89%（`backend/app.py` 986 条语句 / 109 条未覆盖）。**

| 文件 | 用例数 | 覆盖内容 |
| --- | --- | --- |
| `test_auth.py` | 13 | 注册即登录、登录、令牌、未登录 401 |
| `test_events.py` | 30 | 活动增删改查、关闭、详情、分类、分页、场地时间冲突、停用场地后的编辑、删除级联 |
| `test_registrations.py` | 32 | 报名（含关闭 / 已开始 / 已结束 / 重复报名）、取消、签到、我的报名、评论与删评论权限 |
| `test_admin.py` | 25 | 用户角色、场地管理 |
| `test_regressions.py` | 39 | 修过的 bug 回归（含加锁顺序、响应结构、移出后不能自行复报名）、限流、杂项 |
| `test_stats.py` | 17 | 视图口径、触发器兜底（绕过接口直接写库）、存储过程出入率、平台统计 |

几个值得说的用例：

- `test_no_oversell`：容量 1 的活动，两个线程用 `threading.Barrier` 卡在同一起跑线后同时报名，跑 8 轮，每轮断言「状态码 `[200, 400]` + 失败原因是名额已满 + 库里只有 1 条有效报名」。把 `_lock_event` 里的 `FOR UPDATE` 去掉，第 0 轮就会变红。
- 触发器用例反向验证过：删掉 `trg_events_check_venue_bi`，`test_trigger_blocks_overlapping_venue_insert` 立刻 DID NOT RAISE。
- 每个用例前清一次业务数据，并校验当前连接的确实是测试库，中断后可重跑。

看覆盖率：`pytest tests --cov=app --cov-report=term-missing`（更细的分布见 [docs/测试报告.md](docs/测试报告.md)）。

## 9. 性能基准

```bash
python scripts/bench_queries.py
```

在临时库 `campus_events_bench` 里造 3000 个活动、500 个学生、9000 条报名、4000 条评论，对同一批查询分别在「有索引 / 索引设为 INVISIBLE」两种状态下跑多轮取中位数，输出 markdown 对比片段（跑完自动删库，不影响开发库和测试库）。

实测结论（对比表格见设计文档第 5 节）：活动列表纯按 `start_time` 排序时 0.22 ms vs 12.19 ms（索引只扫 12 行 vs 全表 + filesort）；按 `(end_time < NOW())` 表达式排序时索引用不上，3000 行数据下 1.14 ms，属于已知取舍。

## 10. 已知限制

- 活动列表的排序键含 `(end_time < NOW())` 表达式，用不上 `idx_start_time`，3000 行下 1.14 ms 可接受，没有再优化。
- 防超卖靠应用层事务 + 行锁；触发器只做单语句兜底，不负责并发串行化（触发器里不能对正在写入的同一张表做锁定读，MySQL 1442）。
- 用户管理只有列表和改角色，没有禁用 / 删除账号；分类没有后台增删改接口。
- 组织者把学生移出后没有「重新加回」的接口，属于有意的黑名单语义。
- 限流是单进程内存版，多 worker 部署时各自计数；上生产应换成 Redis 之类。
- 令牌放在 `localStorage`，有 XSS 风险，也没做 refresh token，目前只做到登出 / 改密即失效。
- 统计接口没有对应前端页面；前端没有任何自动化测试，只有人工点。

## 11. 文档与交付物

| 内容 | 位置 |
| --- | --- |
| 数据库设计说明（ER 图、范式论证、索引策略、9 条示例 SQL、有/无索引实测） | [docs/数据库设计说明.md](docs/数据库设计说明.md) |
| 测试报告（跑法、用例分布、关键场景、覆盖率、已知缺口） | [docs/测试报告.md](docs/测试报告.md) |
| 文档目录与配图说明 | [docs/README.md](docs/README.md) |
| ER 图与覆盖率截图 | `docs/images/` |
| 建表脚本（含视图 / 触发器 / 存储过程 / 种子数据） | `database/schema.sql` |
| 源代码仓库 | <https://github.com/shenghuoxuejia/campus-event-management-system> |

提交 / 打包前记得删掉 `.env`、`.venv`、`__pycache__`、`.pytest_cache` —— `.env` 里有真实的数据库密码和签名密钥。

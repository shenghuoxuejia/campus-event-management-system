# 校园活动报名与管理系统

Flask + MySQL 写的校园活动管理平台，两种角色：学生报名参加活动，组织者发布活动并负责签到。前端是原生 HTML/CSS/JS，由 Flask 直接托管，不用单独起服务。

数据库 MySQL 8.0.19+（CHECK 约束需要 8.0.16+，种子脚本的行别名写法需要 8.0.19+），后端 Python 3.10+。

## 功能

- 学生 / 组织者自助注册，注册成功直接登录
- 登录用 `Bearer Token`，服务端从令牌里解析身份，不信前端传的 user_id
- 退出登录和改密码会让旧令牌立刻失效，不用等过期
- 活动支持多分类（N:M），大厅可以按分类筛
- 报名用事务 + 行锁（`SELECT ... FOR UPDATE`），名额不会超卖
- 组织者可以发布 / 编辑 / 关闭活动、签到 / 撤销签到、把学生移出活动
- 活动评论区：只有报名过的学生、组织者本人或管理员能评论
- 管理员可以管用户角色、维护场地、删任意活动和评论
- 活动统计（出入率、报名趋势）给组织者和管理员；平台概览（分类分布、场地利用率、最热活动）给管理员
- 一致性不只靠应用层：库里有 1 个视图 `v_event_overview`、4 个触发器、1 个存储过程 `sp_event_attendance` 兜底（详见 `docs/数据库设计说明.md`）
- 所有接口统一返回 `{"code", "message", "data"}`

## 目录结构

```text
backend/     Flask 应用（app.py 主程序）和建库 / 管理员脚本
frontend/    三个静态页：login.html / index.html / profile.html
database/    schema.sql，建表 + 约束 + 索引 + 视图 + 触发器 + 存储过程 + 种子数据
scripts/     一键启动 / 停止的 bat，以及 ER 图、查询基准两个报告脚本
tests/       pytest 用例
docs/        数据库设计说明、测试报告和配图
```

## 快速开始

1. 装依赖：

   ```bash
   pip install -r requirements.txt
   ```

2. 建库建表：

   ```bash
   mysql -u root -p < database/schema.sql
   ```

   也可以用 `python backend/init_db.py`，它会读 `.env` 里的连接信息，老库还能顺便补齐缺的列和索引。

3. 配环境变量：把 `.env.example` 复制成 `.env`，填上数据库密码，`APP_SECRET_KEY` 用下面这条命令生成一串随机值：

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

4. 启动：

   ```bash
   python backend/app.py
   ```

5. 浏览器打开 <http://127.0.0.1:5000/>。

嫌麻烦的话直接双击 `scripts/启动校园活动系统.bat`，第一次运行会自动建虚拟环境、装依赖、问你数据库密码、建库建表再启动。关服务用 `scripts/停止校园活动系统.bat`，它只杀本项目的进程。

建完库只有场地和分类这些基础数据，账号自己在注册页注册。要一个管理员：

```bash
python backend/make_admin.py 你的邮箱@example.com          # 已注册的账号提权
python backend/make_admin.py admin@campus.local --create Admin@2026   # 直接建一个
```

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `DB_HOST` / `DB_PORT` | `127.0.0.1` / `3306` | MySQL 地址 |
| `DB_USER` / `DB_PASSWORD` | `root` / 必填 | MySQL 账号密码 |
| `DB_NAME` | `campus_events` | 开发库 |
| `TEST_DB_NAME` | `campus_events_test` | 测试库，conftest 会自动切过去 |
| `APP_SECRET_KEY` | 必填 | 令牌签名密钥，长度小于 32 或还是占位符会直接拒绝启动 |
| `TOKEN_MAX_AGE` | `86400` | 令牌有效期（秒） |
| `FLASK_DEBUG` | `0` | 调试开关 |
| `PORT` | `5000` | 后端端口，启动脚本也读这个 |
| `LOGIN_RATE_LIMIT` | `10/60` | 登录限流，同一 IP + 邮箱 次数 / 窗口秒数 |
| `REGISTER_RATE_LIMIT` | `20/3600` | 注册限流，按 IP |
| `COMMENT_RATE_LIMIT` | `20/60` | 评论限流，按用户 |
| `DB_POOL_SIZE` | `5` | 连接池大小 |
| `DB_TIME_ZONE` | `+08:00` | 会话时区，保证 `NOW()` 判断和页面显示对得上 |
| `CORS_ORIGINS` | `*` | 允许的跨域来源，逗号分隔 |
| `TRUSTED_PROXIES` | 空 | 只有来自这些 IP 的请求才解析 `X-Forwarded-For` |

## 接口

| 方法 | 路径 | 说明 | 谁能用 |
| --- | --- | --- | --- |
| POST | `/api/register` | 注册，只接受 student / organizer | 公开 |
| POST | `/api/login` | 登录，返回用户信息和令牌 | 公开 |
| POST | `/api/logout` | 退出登录 | 登录 |
| PUT | `/api/change_password` | 改密码，返回新令牌 | 登录 |
| GET | `/api/me` | 当前用户 | 登录 |
| GET | `/api/events` | 活动列表，`?page=&page_size=&category_id=` | 登录 |
| GET | `/api/events/<id>` | 活动详情 | 登录 |
| POST | `/api/register_event` | 报名 | 学生 |
| GET | `/api/user_registrations/<user_id>` | 我的报名 | 本人 |
| PUT | `/api/cancel_registration/<id>` | 取消报名 | 本人 / 该活动组织者 / 管理员 |
| POST | `/api/create_event` | 发布活动 | 组织者 / 管理员 |
| PUT | `/api/update_event/<id>` | 编辑活动 | 该活动组织者 |
| DELETE | `/api/delete_event/<id>` | 删除活动 | 该活动组织者 / 管理员 |
| PUT | `/api/close_event/<id>` | 关闭 / 重新开放报名 | 该活动组织者 |
| GET | `/api/event_registrations/<id>` | 报名名单，`?include_cancelled=1` 带取消的 | 该活动组织者 |
| DELETE | `/api/remove_registration/<id>` | 把学生移出活动 | 该活动组织者 |
| PUT | `/api/check_in/<id>` | 签到 | 该活动组织者 / 管理员 |
| PUT | `/api/undo_check_in/<id>` | 撤销签到 | 该活动组织者 / 管理员 |
| GET | `/api/venues` | 可用场地 | 登录 |
| GET | `/api/admin/venues` | 全部场地（含停用的） | 管理员 |
| POST | `/api/venues` | 新增场地 | 管理员 |
| PUT | `/api/venues/<id>` | 改 / 停用场地 | 管理员 |
| DELETE | `/api/venues/<id>` | 删场地 | 管理员 |
| GET | `/api/categories` | 分类列表 | 登录 |
| GET | `/api/comments/<event_id>` | 评论列表 | 登录 |
| POST | `/api/comments` | 发评论 | 登录（需报名过） |
| DELETE | `/api/delete_comment/<id>` | 删评论 | 作者 / 该活动组织者 / 管理员 |
| GET | `/api/admin/users` | 用户列表 | 管理员 |
| PUT | `/api/admin/users/<id>/role` | 组织者和管理员互转 | 管理员 |
| GET | `/api/events/<id>/stats` | 活动统计（出入率、状态分布、报名趋势） | 该活动组织者 / 管理员 |
| GET | `/api/admin/stats` | 平台统计（分类分布、场地利用率、最热活动） | 管理员 |
| PUT | `/api/admin/users/<id>/role` | 组织者和管理员互转 | 管理员 |

分页接口额外返回 `total` / `page` / `page_size` / `pages`，`data` 还是数组。

## 业务规则

- 只有学生能报名。活动得是开放状态、没开始、没结束、名额没满、也没重复报过。
- 发布活动要求开始时间在未来、结束晚于开始、名额不超过场地容量，且不能选停用的场地。同场地时间段重叠会被拒绝。
- 签到只能在活动开始后到结束前，由该活动的组织者或管理员操作。已签到的报名不能取消也不能移出，签错了用撤销签到。
- 活动一开始，开始时间就不能再改了（否则等于把报名和签到重新放开），名额也不能缩到比已报名人数少。
- 删除活动前会检查：没签到记录、也没开始，否则返回 409。
- 取消报名会记下 `cancelled_at` / `cancelled_by`。重新报名复用原来那条记录，首次报名时间保留。
- 场地还有活动在用就只能停用不能删，容量也不能改到比该场地已有活动的名额小。
- 管理员不能改自己的角色，所以系统里至少留一个管理员。学生要提权得先以组织者身份注册。

## 测试

```bash
pip install -r requirements-dev.txt

# 第一次跑之前先初始化测试库
$env:DB_NAME = 'campus_events_test'; python backend/init_db.py

pytest tests -q
```

150 个用例，跑一遍大概 95 秒，覆盖认证、权限、活动生命周期、并发报名、签到、评论、分类、场地、分页、限流、统计接口和数据库端对象这些场景。测试库和开发库是分开的，每个用例前都会清一次业务数据（并校验当前连接的确实是测试库），中断了也不会抱脏数据。

并发那条用例（`test_no_oversell`）用 `threading.Barrier` 把两个线程卡在同一起跑线，跑 8 轮，每轮断言“状态码正好 `[200, 400]` + 失败原因是名额已满 + 库里只有 1 条有效报名”。它是能真抳 bug 的：把 `_lock_event` 里的 `FOR UPDATE` 临时去掉，第 0 轮就会报 `[200, 200]`。

要看覆盖率就 `pytest tests --cov=app --cov-report=term-missing`，当前 89%。

## 还没做的

- 活动列表的排序里有 `(end_time < NOW())` 这种表达式，用不上 `idx_start_time` 索引。3000 行数据实测 1.14ms，先这样了。
- 用户管理只有列表和改角色，没有禁用 / 删除账号。分类也还没有后台增删改的接口。
- 防超卖靠应用层的事务和行锁，数据库端触发器只做单语句兜底（应用层被绕过时拦得住），不负责并发串行化——触发器里不能对正在写入的同一张表做锁定读（MySQL 1442）。
- 令牌放 localStorage，有 XSS 风险，也还没做 refresh token。这轮只做到登出 / 改密即失效。
- 前端没有自动化测试，只有人工点。

## 其它

- 数据库设计（ER 图、范式论证、索引、示例 SQL、有索引和无索引的实测对比）在 `docs/数据库设计说明.md`。
- 测试的范围、用例分布和覆盖率截图在 `docs/测试报告.md`。
- 提交之前记得把 `.env`、`.venv`、`__pycache__`、`.pytest_cache` 删掉，`.env` 里有真实的数据库密码和签名密钥。

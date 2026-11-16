# docs 索引

本目录只放**交付材料**：写课程报告、做答辩需要的图表与说明。代码、脚本、测试分别在 `backend/`、`scripts/`、`tests/`，运行方式见根目录 [`README.md`](../README.md)。

## 文档清单

| 文件 | 对应报告章节 | 主要内容 | 什么时候看 |
| --- | --- | --- | --- |
| [`数据库设计说明.md`](数据库设计说明.md) | Technical Design / Database Design / Evaluation | 系统结构与 5 个并发控制点、ER 图、Schema 设计决策与 1NF/2NF/3NF 论证、约束一览、索引清单 + 已知局限、6 条示例 SQL、有/无索引的 `EXPLAIN` 与耗时对比 | 写「数据库设计」「性能评估」两章；答辩被问锁、索引、范式 |
| [`测试报告.md`](测试报告.md) | Testing / Evaluation | 测试环境与命令、按模块的测试范围、15 个文件 101 个用例的分布、5 个关键场景、覆盖率 79%、结论与已知缺口 | 写「测试」一章；答辩被问「你怎么证明正确」 |
| [`images/er-diagram.png`](images/er-diagram.png) | Database Design | 7 张表的全部列与类型、PK/FK/UQ/CK 标记、8 条关系连线（含 `cancelled_by`）、图例 | 报告插图、答辩投屏 |
| [`images/coverage.png`](images/coverage.png) | Testing | 早期覆盖率截图（78%），数值以测试报告正文 79% 为准 | 报告插图（建议重生成后再用） |

## 推荐阅读顺序

- **只关心怎么跑起来**：根目录 `README.md` 的「快速开始」→ 本目录不用看。
- **写报告**：`数据库设计说明.md`（§1 结构 → §2 ER → §3 范式 → §4 索引 → §5 实测）→ `测试报告.md`（§3 范围 → §4 分布 → §6 覆盖率）。
- **准备答辩**：`数据库设计说明.md` §1 的并发控制表（不超卖 / 不撞场地 / 状态不被覆盖 / 死锁规避）+ `测试报告.md` §5 的 5 个关键场景。

## 图表维护

| 图 | 生成方式 | 何时重生成 |
| --- | --- | --- |
| `images/er-diagram.png` | `python scripts/er_diagram.py`（Pillow，无需 Graphviz） | 改了 `database/schema.sql` 的表 / 列 / 外键 / 索引 |
| `images/coverage.png` | `python -m pytest tests/ --cov=app --cov-report=html`，截 `htmlcov/index.html` | 用例数或覆盖率变化较大时 |

## 约定

- 文档内的图片一律用**相对路径** `images/xxx.png`，不依赖仓库外文件。
- 章节编号与锚点保持稳定（`## 1.`、`### 3.1` 形式），跨文档引用统一写「§编号」。
- 用例数、覆盖率这类会变的数字，出现时必须标口径（如「101 个用例 / 79% / 2026-11 实测」）。
- 两份文档互相链接，改动其一请顺手检查另一侧的引用是否仍成立。

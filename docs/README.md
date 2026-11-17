# docs

写课程报告和答辩用的材料在这里，代码和运行方式看根目录的 `README.md`。

| 文件 | 内容 |
| --- | --- |
| [数据库设计说明.md](数据库设计说明.md) | 系统结构、并发控制点、ER 图、建表决策、范式论证、约束和索引、6 条示例 SQL、有索引和无索引的实测对比 |
| [测试报告.md](测试报告.md) | 怎么跑测试、测了哪些场景、用例分布、覆盖率、结论和已知缺口 |
| [images/](images) | `er-diagram.png` 由 `scripts/er_diagram.py` 生成，`coverage.png` 是覆盖率页面截图 |

ER 图改了表结构要重新生成：

```bash
python scripts/er_diagram.py
```

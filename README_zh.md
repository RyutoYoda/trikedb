<p align="center">
  <a href="https://github.com/RyutoYoda/trikedb/blob/main/README.md">English</a>
  &nbsp;·&nbsp; <a href="https://github.com/RyutoYoda/trikedb/blob/main/README_jp.md">日本語</a>
  &nbsp;·&nbsp; <b>简体中文</b>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/RyutoYoda/trikedb/main/docs/logo.png" width="260" alt="TrikeDB — 一只把知识图谱驮在头盾上的三角龙" />
</p>

<p align="center">
  <a href="https://github.com/RyutoYoda/trikedb/actions/workflows/test.yml"><img src="https://github.com/RyutoYoda/trikedb/actions/workflows/test.yml/badge.svg" alt="tests" /></a>
  <a href="https://pypi.org/project/trikedb/"><img src="https://img.shields.io/pypi/v/trikedb?style=flat&color=4a6fa5&cacheSeconds=300" /></a>
  <img src="https://img.shields.io/pypi/pyversions/trikedb?style=flat&color=4a6fa5" />
  <img src="https://img.shields.io/badge/license-MIT-4a6fa5?style=flat" />
  <img src="https://img.shields.io/badge/SPARQL%201.1-3D7EBB?style=flat&logo=w3c&logoColor=white" />
  <img src="https://img.shields.io/badge/MCP-191919?style=flat&logo=modelcontextprotocol&logoColor=white" />
</p>

# trikedb

**让智能体读得懂的知识图谱，装在一个你能看懂 diff 的文件里。**

你的智能体已经会读代码了。它读不到的是那些**不在**代码里的东西：哪个任务写入
哪张表、谁在负责、两个长得很像的服务里哪个还活着。于是它开始猜，猜出来的是一个
看着很合理、但并不存在的名字。

trikedb 就是把这些写下来的地方——一个 YAML 文件，放在仓库里，紧挨着它所描述的代码：

```yaml
triples:
  - {s: salesflow-crm, p: PROVIDES, o: crm-sync-job}
  - {s: crm-sync-job, p: INGESTS_TO, o: RAW_CRM_CONTACTS, schedule: hourly}
  - {s: LEGACY_DUMP, p: MIGRATED_TO, o: RAW_CRM_CONTACTS, deprecated: true}
```

这个文件**就是**数据库。没有服务器、没有守护进程、不用部署。它在 git 里像其他
文件一样出 diff，人能读，智能体可以用真正的
[SPARQL 1.1](https://www.w3.org/TR/sparql11-query/) 查询——由
[Oxigraph](https://github.com/oxigraph/oxigraph) 执行，而不是自己写的子集——
或者干脆打开文件直接读。

<p align="center">
  <a href="https://ryutoyoda.github.io/trikedb/workspace.html">
    <img src="https://raw.githubusercontent.com/RyutoYoda/trikedb/main/docs/screenshot.png" alt="trikedb 的 HTML 工作台 — 600 条 Freebase 事实的力导向聚类，右侧打开了节点详情面板" />
  </a>
</p>

<p align="center">
  <b>在线演示</b> —
  <a href="https://ryutoyoda.github.io/trikedb/">用五张图表示一家公司</a>
  &nbsp;·&nbsp; <a href="https://ryutoyoda.github.io/trikedb/pipeline.html">带动作日志的数据平台</a>
  &nbsp;·&nbsp; <a href="https://ryutoyoda.github.io/trikedb/workspace.html">600 条真实事实，可筛选，附浏览器内 SPARQL 控制台</a>
</p>

## 安装

```bash
pip install trikedb          # library + CLI
pip install 'trikedb[mcp]'   # + MCP server, so an agent can use it
pip install 'trikedb[all]'   # + serve, OAuth, SHACL, OWL, semantic search, S3/warehouse graphs
```

所有可选能力都是 extra，所以内核始终只有 PyYAML + rdflib + pyoxigraph。
完整清单见[参考手册](https://github.com/RyutoYoda/trikedb/blob/main/docs/REFERENCE_zh.md#extras)。

## 先写三条事实

不需要模式，也不需要建模会。写下事实，然后看它：

```python
from trikedb import TrikeDB

db = TrikeDB("graph.yaml")               # 文件在第一次写入时创建
db.add("salesflow-crm", "PROVIDES", "crm-sync-job")
db.add("crm-sync-job", "INGESTS_TO", "RAW_CRM_CONTACTS", schedule="hourly")
db.set_node("RAW_CRM_CONTACTS", type="table", pii=True)

db.query(["?vendor PROVIDES ?job", "?job INGESTS_TO ?table"])
db.to_html("graph.html")                 # 一个可以点开看的页面，发给同事
```

从空仓库开始，也可以一行 Python 都不写：

```bash
trikedb init graph.yaml --template agent-memory   # 写出一个有形状的起始图谱
trikedb add graph.yaml salesflow-crm PROVIDES crm-sync-job
trikedb query graph.yaml -w "?vendor PROVIDES ?job"
trikedb ui graph.yaml                             # 在浏览器里打开
```

## 真正会用到的四个

还有别的，但一个站得住脚的图谱，通常就是由这四个搭起来的：

| | |
|---|---|
| `db.add(s, p, o, **attrs)` | 陈述一条事实。任意关键字参数都会变成边属性——值得统一下来的是 `prov=`，这样每条事实都能追回它的来源 |
| `db.act(s, p, o, by=…, state=…)` | 记录**发生过的事**：打上时间、追加到该节点的历史里、并把节点迁移到这次动作留下的状态 |
| `db.find(question, where=…)` | 智能体真正需要的检索：先按语义广撒网，再按属性精确过滤 |
| `db.sparql(query)` | 当模式匹配不够用时，完整的查询语言 |

其余的——推理、SHACL、工作区、S3 与数仓存储、HTTP 服务——需要时就在那里，
不需要时不花任何代价。见[参考手册](https://github.com/RyutoYoda/trikedb/blob/main/docs/REFERENCE_zh.md)。

## 然后，把它锁紧

只有装不进垃圾的图谱才值得读。声明什么话可以说，于是每一条写入路径——你自己的、
CLI 的、智能体的——都要遵守同一套规则。形状检查会在节点类型已知的地方生效，
两个方向都管：

```python
db = TrikeDB("graph.yaml", ontology={
    "PROVIDES":   "SaaS vendor -> ingestion job",
    "INGESTS_TO": {"description": "ingestion job -> warehouse table",
                   "domain": "job", "range": "table"},
})

db.set_node("crm-sync-job", type="job")
db.set_node("RAW_CRM_CONTACTS", type="table")

db.add("crm-sync-job", "OWNS", "anything")                # OntologyError: 未声明的谓词
db.add("RAW_CRM_CONTACTS", "INGESTS_TO", "crm-sync-job")  # OntologyError: 方向写反了
```

动作还可以声明**何时才允许发生**、**谁才有权签署**——这是类型检查够不着的另一半。
一个还没发货就被签收的订单，不违反任何类型；一次没有人批准的调价，类型上完全正确。
在这里两者都会被拒绝：

```python
db.declare_link("DELIVERED_TO", domain="order", range="region",
                requires="SHIPPED_FROM",   # 这件事必须先发生过
                by="courier")              # 而这是有权执行它的人

db.act("ORD-25101", "DELIVERED_TO", "Riverside", by="Kai")   # OntologyError: 从未发货
```

## 交给智能体

把图谱注册成 MCP 服务器，智能体就拿到十一个工具——读取用 `sparql`、`match`、
`search`、`find`、`get_node`、`ontology`、`stats`，写入用 `add_triple`、
`set_node`、`remove_triples`、`import_source`：

```json
{
  "mcpServers": {
    "kg": {
      "command": "uvx",
      "args": ["--from", "trikedb[mcp]", "trikedb", "mcp", "/absolute/path/to/graph.yaml"]
    }
  }
}
```

写入会自动保存回 YAML，所以智能体的产出是一份可评审的 git diff，而它试图临时发明的
谓词会被本体拒绝。这也是对"把文档一股脑丢给它"的回答：**抽取交给智能体，
trikedb 负责那条经过校验的写入路径。** 抽取保持灵活，词汇保持稳固。

没有 MCP 客户端？那么整个集成就是智能体项目说明里的一行字——
*"任何涉及数据管道的任务，先读 `graph.yaml`"*——剩下的交给文件本身。

## 人们往里放什么

- **智能体对你们系统的记忆。** 哪个数仓角色能读什么、哪个采集任务是生效的那个、
  一次改动该在哪个仓库里做。这些都不在代码里，也都是智能体会搞错的地方。
- **服务与归属地图。** 谁调用谁、谁在值班、三个名字相近的服务里哪个已废弃。
- **带前置条件的决策与故障日志。** `act()` 加上 `requires`，意味着没被批准过的东西
  根本写不进"已部署"——这是在写入时强制的，而不是评审清单上的一条。
- **数据治理台账。** 含 PII 的表、谁可以访问、保留多久。`by:` 与 `requires:`
  就是一套能在 pull request 里看 diff 的授权模型。

共同点是：几百到几千条、有人**有意**维护的事实。图谱能成立、而且值得信任的规模就在这里。

## 为什么不直接用一个 Markdown 文件

因为 Markdown 拒绝不了一次错误的写入，往里写的智能体同样拒绝不了。在这里，
无论谁来写，都要过同一道关卡——谓词是否已声明、方向是否正确、前置条件是否满足。
而且一旦事实是结构化的，你就能问出 grep 答不了的问题：距这张表两跳内的一切、
所有没有归属的 PII 字段、三月以来有哪些变化。

它对模型的帮助也是可测量的。在 [WebQSP](https://aclanthology.org/P16-2033/)
（知识图谱问答）上，同一个本地模型**单独作答 42.7%，把 trikedb 图谱作为上下文后
达到 77.7%**——300 题的 Hits@1，配对 McNemar 检验 p = 9e-20，每题 0.59 秒。
方法、注意事项与评分敏感性分析见
[`benchmarks/`](https://github.com/RyutoYoda/trikedb/tree/main/benchmarks)。

## trikedb 不是什么

- **不是抽取流水线。** 它不会把你的 PDF 变成图谱。想要的话就配一个抽取器——
  然后把产出整理干净。被抽取出来的图谱会继承幻觉；这一份应该是你能信的那部分。
- **不是给几百万条三元组用的。** 一切都在内存里，扫描是线性的。几百到几千，
  才是一个人工维护的图谱得以成立的范围。
- **不是自己写的 SPARQL 引擎。** 读取跑在 Oxigraph 上，更新和 OWL/SHACL 跑在
  rdflib 上。将来迁到完整的三元组库是一次导出，不是一次重写。
- **不是 Obsidian 的替代品。** 如果你要的是给人看的笔记，请用那个。这里放的是
  机器必须答对的事实。

## 接下来看哪里

- [docs/REFERENCE_zh.md](https://github.com/RyutoYoda/trikedb/blob/main/docs/REFERENCE_zh.md) — 每个功能、文件格式，以及兼容性与安全性约定 · [English](https://github.com/RyutoYoda/trikedb/blob/main/docs/REFERENCE.md) · [日本語](https://github.com/RyutoYoda/trikedb/blob/main/docs/REFERENCE_jp.md)
- [docs/ARCHITECTURE_zh.md](https://github.com/RyutoYoda/trikedb/blob/main/docs/ARCHITECTURE_zh.md) — 分层结构，以及新代码该放在哪里
- [docs/SCALING.md](https://github.com/RyutoYoda/trikedb/blob/main/docs/SCALING.md) — 1k / 10k / 100k 三元组下的实测边界
- [examples/](https://github.com/RyutoYoda/trikedb/tree/main/examples) — 演示背后的图谱，以及一个[可运行的 notebook](https://github.com/RyutoYoda/trikedb/blob/main/examples/trikedb_quickstart.ipynb)
- [CONTRIBUTING.md](https://github.com/RyutoYoda/trikedb/blob/main/CONTRIBUTING.md) — 如何跑测试，以及一个好的 pull request 长什么样

## 许可证

MIT. Copyright (c) 2026 Ryuto Yoda.

### 随附数据

随附的第三方数据集只有一个，另一个没有随附：

- **Freebase** — `examples/freebase_*.yaml` 是 Freebase 转储的一小段摘录，
  采用 [CC BY 2.5](https://creativecommons.org/licenses/by/2.5/) 许可。
  它留在仓库里，是为了让演示页面能从源数据重新生成。
- **WebQSP** — 基准测试的问题与标准答案来自
  [The Value of Semantic Parse Labeling for KBQA](https://aclanthology.org/P16-2033/)
  (Yih et al., 2016)，经由 `rmanluo/RoG-webqsp` 的重新打包版本使用。
  数据集内容不在本仓库中：`benchmarks/webqsp_bench.py prepare` 会在运行时下载测试集。
  仓库里跟踪的是 `benchmarks/*_data.json` —— 图表和上面那个数字所读取的评分结果。

两者都不是使用 trikedb 的前提。

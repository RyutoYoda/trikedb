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

把图谱注册成 MCP 服务器，智能体就拿到十六个工具——读取用 `sparql`、`match`、
`search`、`find`、`get_node`、`history`、`ontology`、`stats`，写入用 `add_triple`、
`act`、`set_node`、`remove_triples`、`import_source`，还有把文档变成事实而不必
猜测词汇的 `extraction_prompt`、`preview_triples`、`add_triples`：

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

## 把一份文档丢进去

模型你已经有了。trikedb 负责写提示词、评判回答；中间那次调用是你的，所以没有
SDK 要装，也没有密钥要交出去。提示词是**从要写入的那张图谱本身**组出来的——它
声明过的谓词，它已有的节点名。所以模型不会在 `WORKS_AT` 旁边临时造一个
`EMPLOYED_BY`，也不会给文件里已经存在的公司再开一个节点：

```python
rows = db.extract(open("press-release.md").read(), llm=my_model)

for f in db.preview(rows):          # 此刻什么都还没写
    print(f["verdict"], f["triple"], f["detail"])

# new       Acme BASED_IN Osaka
# new       Sato WORKS_AT Acme
# conflict  Tanaka WORKS_AT Globex
#           └ WORKS_AT is declared functional and Tanaka already holds 'Acme'
```

`llm` 就是任何接收提示词、返回文本的可调用对象——把你在用的 SDK 包三行即可，
[examples/extract_providers.py](https://github.com/RyutoYoda/trikedb/blob/main/examples/extract_providers.py)
里写好了五个。

也可以完全不碰 API，让一个人或一个聊天窗口站在中间，从命令行分两半跑：

```bash
trikedb extract graph.yaml report.docx > prompt.txt # 贴到任何地方
trikedb import graph.yaml answer.md --dry-run       # 它会做什么
trikedb import graph.yaml answer.md                 # 它做了什么
```

Word 文件直接丢进来就行：`.docx` 本质是一个装着 XML 文档的 zip，读它不需要任何依赖。
Google Docs 可以直接导出 Markdown（文件 → 下载 → Markdown），那种本来就能读。

`--dry-run` 本身就值得拥有，而且对任何来源都有效——CSV、Markdown、另一张图谱。
每一行都会带着理由回来，标为 `new`、`same`、`update`、`rejected` 或 `conflict`，
在你读完之前什么都不会写。`conflict` 不是猜的：被声明为 `functional` 的谓词，
每个主语只能持有一个宾语，所以第二个就是图谱能够证明的矛盾。

那条带约束的提示词到底有多大用？跑一遍就知道——案例、标准答案、评分器，以及
用来对照的无约束基线，都在
[evals/](https://github.com/RyutoYoda/trikedb/tree/main/evals)。那里没有提交任何
分数，因为一个被提交的分数只是某个模型在某一天的数字。

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

- **不是抽取流水线。** 它不会调用语言模型、不保管你的密钥、也不解析你的 PDF。它做
  的是从你的本体写出提示词，并在写入之前拿它去评判每一行——模型和判断都还是你的。
  被抽取出来的图谱会继承幻觉；这一份是让幻觉在落地之前先被看见的那部分。trikedb
  自己会跑的模型只有一个：可选的 `[semantic]` 搜索背后那个小的嵌入模型，首次取回
  之后就在本地跑。
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
- [evals/](https://github.com/RyutoYoda/trikedb/tree/main/evals) — 抽取案例、评分器，以及用来对照的基线
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

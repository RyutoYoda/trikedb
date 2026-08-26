<p align="center">
  <a href="https://github.com/RyutoYoda/trikedb/blob/main/README.md">English</a>
  &nbsp;·&nbsp; <a href="https://github.com/RyutoYoda/trikedb/blob/main/README_jp.md">日本語</a>
  &nbsp;·&nbsp; <b>简体中文</b>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/RyutoYoda/trikedb/main/docs/logo.png" width="260" alt="TrikeDB — 一只在头盾上驮着知识图谱的三角龙">
</p>

<p align="center">
  <a href="https://pypi.org/project/trikedb/"><img src="https://img.shields.io/pypi/v/trikedb?style=flat&color=4a6fa5&cacheSeconds=300" /></a>
  <img src="https://img.shields.io/pypi/pyversions/trikedb?style=flat&color=4a6fa5" />
  <img src="https://img.shields.io/badge/license-MIT-4a6fa5?style=flat" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/SPARQL%201.1-3D7EBB?style=flat&logo=w3c&logoColor=white" />
  <img src="https://img.shields.io/badge/RDF-0C479C?style=flat&logo=w3c&logoColor=white" />
  <img src="https://img.shields.io/badge/MCP-191919?style=flat&logo=modelcontextprotocol&logoColor=white" />
</p>

<p align="center">
  <b><a href="https://ryutoyoda.github.io/trikedb/">🦕 在线演示</a></b> — 600 条真实的 Freebase 事实，可以点击浏览，也能在浏览器里跑 SPARQL
  &nbsp;·&nbsp; <a href="https://ryutoyoda.github.io/trikedb/workspace.html">工作区演示</a> — 同一批事实拆成 6 个领域图谱，平铺展示并可筛选
  &nbsp;·&nbsp; <a href="https://pypi.org/project/trikedb/">PyPI</a>
</p>

# trikedb

**面向 AI 智能体的单文件知识图谱。** 一个图谱就是你仓库里的一个 YAML 文件 — 完整的 SPARQL 1.1，读*和*写都支持，智能体的写入要经过本体护栏，而每一次改动都以 diff 的形式抵达。

```yaml
triples:
  - {s: salesflow-crm, p: PROVIDES, o: crm-sync-job}
  - {s: crm-sync-job, p: INGESTS_TO, o: RAW_CRM_CONTACTS, schedule: hourly}
  - {s: LEGACY_DUMP, p: MIGRATED_TO, o: RAW_CRM_CONTACTS, deprecated: true}
```

这个文件**就是**数据库。没有服务器，没有守护进程，不需要云端部署。它在 git 里能干净地 diff，能和代码放在同一个仓库里长期存活 — 而且这正是 trikedb 真正围绕设计的一点 — **LLM 智能体可以直接 `Read` 它，在你的领域上做推理而不会凭空编造实体名。**

它还能渲染成一个可交互的工作台（[在线演示](https://ryutoyoda.github.io/trikedb/) — 600 条真实的 Freebase 事实）：

<p align="center">
  <a href="https://ryutoyoda.github.io/trikedb/">
    <img src="https://raw.githubusercontent.com/RyutoYoda/trikedb/main/docs/screenshot.png" alt="trikedb 的 HTML 工作台 — 600 条 Freebase 事实以力导向聚类展示，右侧打开了节点详情面板">
  </a>
</p>

## 为什么做这个

RDF 图数据库强大、严谨 — 也很重。SPARQL 端点、OWL 推理机、企业级语义层：规模上很能打，但如果你要的只是一份几百条事实的、经过整理、能让 AI 智能体（和同事）信任的地图，那就是杀鸡用牛刀。

trikedb 保留了大系统的*接口* — 真正的 SPARQL 1.1，由 [Oxigraph](https://github.com/oxigraph/oxigraph) 执行，而不是自己手写的子集 — 同时把*机械装置*缩到一个嵌入式库，跑在一个你能读、能 diff、能提交的文件之上：

|  | 完整的三元组存储部署 | trikedb |
|---|---|---|
| 存储 | 服务器 / 云服务 | 一个 YAML 文件 |
| 查询 | SPARQL 1.1 | SPARQL 1.1（同一种语言，Oxigraph 的 Rust 引擎） |
| 图模型 | 通常只能选一个：RDF *或*属性图（两套系统） | **一个文件同时给你两个** — SPARQL/RDF（`to_rdflib`）与属性图（`to_networkx`，经由 `[networkx]`） |
| 写入 | SPARQL Update | SPARQL Update — 直接持久化回 YAML |
| 模式 | OWL + 推理机 | 一份谓词白名单，另有经 `[shacl]` 的 SHACL shapes |
| 推理 | DL 推理引擎 | 经 `[owl]` 的 OWL-RL 物化 — 推导出的事实落进 YAML，可审阅 |
| 智能体集成 | 一个需要运维的服务 | 智能体直接读文件、`trikedb mcp`（stdio）、或 `trikedb serve`（远程 MCP + UI + REST） |
| 搭建时间 | 一个下午（或一个迭代） | `pip install trikedb` |

如果你需要规模化的完整 OWL-DL 推理、命名图和多租户治理，那你要的是一套完整的企业语义平台。如果你想**今天就有一个知识图谱，放在文件里，放在 git 里** — 那就是 trikedb。而且因为它的存储能干净地映射到 RDF，日后升级到更大的系统是一次导出，而不是重写：每个团队保有自己的 YAML 图谱，把它们缝在一起（或者整体迁走）不过是合并三元组。

### 以整理为先，而不是以抽取为先

大多数「AI 知识图谱」工具用 LLM 从文本里抽取三元组。这对冷启动很好，但抽取出来的图谱会继承幻觉。trikedb 采取相反的立场：**图谱是经过整理的数据**（由人，或者由你监督的智能体），本体约束了什么话可以说，而 LLM 是*消费*图谱而不是发明它。当一个智能体读到

```yaml
- {s: crm-sync-job, p: INGESTS_TO, o: RAW_CRM_CONTACTS}
```

整个流程里不存在任何一步可以让表名被编造出来。

## 安装

从 [PyPI](https://pypi.org/project/trikedb/)：

```bash
pip install trikedb             # 库 + CLI（PyYAML、rdflib、pyoxigraph）
pip install 'trikedb[all]'      # 下面全部，一次装好

pip install 'trikedb[mcp]'      # + 面向 AI 智能体的 MCP 服务器（stdio）
pip install 'trikedb[serve]'    # + UI / REST / 基于 HTTP 的远程 MCP
pip install 'trikedb[oauth]'    # + 面向 claude.ai / ChatGPT 界面的 OAuth 2.1
pip install 'trikedb[remote]'   # + s3:// gs:// 图谱
pip install 'trikedb[snowflake]' # + snowflake:// 图谱（数仓即存储）
pip install 'trikedb[bigquery]' # + bigquery:// 图谱（同上，在 BigQuery 上）
pip install 'trikedb[shacl]'    # + SHACL 校验
pip install 'trikedb[owl]'      # + OWL-RL 推理
pip install 'trikedb[semantic]' # + 语义检索（numpy + model2vec，不需要 torch）
pip install 'trikedb[networkx]' # + 属性图投影（to_networkx）

```

## 快速上手（Python）

```python
from trikedb import TrikeDB

# 一个住在单个 YAML 文件里的、带类型的知识图谱。你声明的谓词就是模式 —
# 这份白名单会在写入时拦住拼写错误和垃圾数据。
db = TrikeDB("pipeline.yaml", ontology={
    "PROVIDES":   "SaaS vendor -> ingestion job",
    "INGESTS_TO": "ingestion job -> warehouse table",
    "MIGRATED_TO": "deprecated table -> its replacement",
})

# 添加事实。任意关键字都会变成边属性 — 而 `prov` 是最该统一使用的那个：
# 标注每条事实的来源，图谱才能一直保持可验证。
db.add("salesflow-crm", "PROVIDES", "crm-sync-job")
db.add("crm-sync-job", "INGESTS_TO", "RAW_CRM_CONTACTS",
       schedule="hourly", prov="https://runbook.example/crm#sync")
db.add("LEGACY_DUMP", "MIGRATED_TO", "RAW_CRM_CONTACTS", deprecated=True)

# 本体是护栏：db.add("crm-sync-job", "OWNS", "x") 会抛出 OntologyError —
# 'OWNS' 不是已声明的谓词，所以这个拼写错误根本落不了地。

# 描述节点：`type` 会给图着色，并且可查询；其他任何东西都可以挂上去。
db.set_node("RAW_CRM_CONTACTS", type="table", pii=True,
            url="https://catalog.example/raw_crm_contacts")

# 提问 — 零依赖地连接模式 ……
db.query(["?vendor PROVIDES ?job", "?job INGESTS_TO ?table"])
# [{'vendor': 'salesflow-crm', 'job': 'crm-sync-job', 'table': 'RAW_CRM_CONTACTS'}]

# …… 或者完整的 SPARQL 1.1（FILTER、OPTIONAL、聚合 — 由 Oxigraph 执行，t: 已预先绑定）
db.sparql('SELECT ?t WHERE { ?t t:type "table" ; t:pii true }')   # 所有含 PII 的表
db.sparql('SELECT ?s ?o WHERE { ?st rdf:subject ?s ; rdf:object ?o ; t:schedule "hourly" }')  # 边属性也一样

# 让图谱给自己分类 — 声明 RDFS/OWL 语义，并把由此推出的内容物化
#（pip install 'trikedb[owl]'）。推导出的事实落进 YAML，可以审阅。
db.declare("INGESTS_TO", "domain:job")    # INGESTS_TO 的主语是 job
db.declare("INGESTS_TO", "range:table")   # 宾语是 table
db.infer(apply=True)   # -> crm-sync-job 是 job，RAW_CRM_CONTACTS 是 table（标记 inferred: true）

# 在信任之前先检查 — 用 SHACL shapes 校验（pip install 'trikedb[shacl]'）
ok, report = db.validate('''@prefix sh: <http://www.w3.org/ns/shacl#> . @prefix t: <urn:trikedb:> .
  t:IngestShape a sh:NodeShape ; sh:targetObjectsOf t:INGESTS_TO ;
    sh:property [ sh:path t:type ; sh:minCount 1 ] .''')   # 每张落地的表都声明了 type 吗？

# 按含义而不是按拼写找事实（pip install 'trikedb[semantic]'）
db.search("what syncs the CRM?", k=5)

# 面向智能体的混合检索 — 语义召回加上一道硬性结构过滤，一次调用完成：
# 先按含义撒一张大网，然后只留下精确匹配的部分。
db.find("where is the customer CRM data?", where={"type": "table", "pii": True})
# -> [{'node': 'RAW_CRM_CONTACTS', 'props': {'type': 'table', 'pii': True, ...}, 'facts': [...]}]

# 写入也走 SPARQL，并直接自动保存回 YAML
db.sparql("INSERT DATA { t:figly t:PROVIDES t:figly-export-job }")

# 自动保存会为每次改动重写整个文件：几条事实正合适，批量导入则是二次复杂度。
# 把它们包进一次保存里。
with db.batch():
    for s, p, o in rows:          # 数万条：不这样要几分钟，这样只要几秒
        db.add(s, p, o)

# 交付一个自包含的 HTML 文件，团队真的可以点进去看
db.to_html("pipeline.html")     # 可搜索的图 + 节点详情 + 浏览器内的 SPARQL 控制台
db.to_rdflib(); db.to_jsonld()  # RDF/SPARQL 视图 — 或者升级到任何 RDF 工具
db.to_networkx()                # 属性图视图：在同一个文件上跑 networkx 算法
                                #（最短路径、中心性）— 需要 'trikedb[networkx]'
```

## 快速上手（CLI）

```bash
trikedb add pipeline.yaml salesflow-crm PROVIDES crm-sync-job
# `prov` 只是一个边属性，但是最该统一使用的那个：标注每条事实的来源。
trikedb add pipeline.yaml crm-sync-job INGESTS_TO RAW_CRM_CONTACTS -a schedule=hourly -a prov=https://runbook.example/crm#sync

trikedb query pipeline.yaml -w "?vendor PROVIDES ?job" -w "?job INGESTS_TO ?table"
# vendor         job           table
# -------------  ------------  ----------------
# salesflow-crm  crm-sync-job  RAW_CRM_CONTACTS

trikedb sparql pipeline.yaml \
  "SELECT ?v ?t WHERE { ?v t:PROVIDES ?j . ?j t:INGESTS_TO ?t }"

# 更新会直接持久化回文件
trikedb sparql pipeline.yaml \
  "INSERT DATA { t:figly t:PROVIDES t:figly-export-job }"

# 语义检索：按含义而不是拼写（[semantic] 附加项）
trikedb search pipeline.yaml "what syncs the CRM?" -k 5

trikedb stats pipeline.yaml
trikedb html pipeline.yaml -o pipeline.html
trikedb jsonld pipeline.yaml
```

## 从 CSV 和 Markdown 文档导入

存储是那个 YAML 文件，但三元组可以来自你的团队已经在写东西的任何地方：

```bash
# 带 s,p,o 表头的 CSV/TSV — 多出来的列会变成边属性
trikedb import pipeline.yaml new_vendors.csv

# Markdown：只有表头含 s/p/o 列的表格会被采集；
# 正文和其他表格会被忽略。你的设计文档就是数据。
trikedb import pipeline.yaml design_doc.md
```

```markdown
<!-- 在一份普通设计文档里的任何位置： -->
| s                 | p          | o                  | schedule  |
|-------------------|------------|--------------------|-----------|
| clickpath-pa      | PROVIDES   | clickpath-webhook  |           |
| clickpath-webhook | INGESTS_TO | RAW_PRODUCT_EVENTS | streaming |
```

导入是确定性的 — 没有 LLM 抽取，所以不会有东西被编造出来。本体在入口处强制生效，`"true"`/`"false"` 单元格会变成布尔值。参见 [`examples/acme_design_doc.md`](https://github.com/RyutoYoda/trikedb/blob/main/examples/acme_design_doc.md) 和 [`examples/acme_new_vendors.csv`](https://github.com/RyutoYoda/trikedb/blob/main/examples/acme_new_vendors.csv)。

## 校验与推理（SHACL / OWL）

谓词白名单是安全带；当你需要真正的模式校验时，用 SHACL（`pip install 'trikedb[shacl]'` — 委托给 [pySHACL](https://github.com/RDFLib/pySHACL)，不是手写的）：

```python
conforms, report = db.validate("""
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix t:  <urn:trikedb:> .
t:BotShape a sh:NodeShape ;
  sh:targetSubjectsOf t:USES_ROLE ;
  sh:property [ sh:path t:type ; sh:hasValue "bot" ; sh:minCount 1 ] .
""")
```

```bash
trikedb validate graph.yaml shapes.ttl   # 有违规时退出码为 1 — 适合 CI
```

至于推理，在你的谓词（和类）上声明 RDFS/OWL 语义，然后把由此推出的内容物化（`pip install 'trikedb[owl]'`，经 [owlrl](https://github.com/RDFLib/OWL-RL) 的 OWL-RL）：

```python
# OWL 属性特性
db.declare("INHERITS", "transitive")     # 作为一条可审阅的三元组存储
db.add("admin", "INHERITS", "editor")
db.add("editor", "INHERITS", "viewer")
db.infer(apply=True)                     # 添加 (admin, INHERITS, viewer) — 标记 inferred: true

# RDFS 类层次 + 类型标注
db.declare("Cat", "subclass_of:Animal")        # rdfs:subClassOf
db.declare("authored", "domain:Person")        # rdfs:domain  → 主语被赋予类型
db.declare("authored", "range:Book")           # rdfs:range   → 宾语被赋予类型
db.declare("bornIn", "subproperty_of:locatedIn")  # rdfs:subPropertyOf
db.add("felix", "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", "Cat")
db.infer()   # → 经 subClassOf 得到 (felix, rdf:type, Animal)；domain/range 的类型标注；等等
```

`infer()` 会把分类与层次（rdf:type、subClassOf、subPropertyOf）以及 OWL 的边（传递 / 对称 / 逆）呈现出来，同时压掉推理机自身的 rdf/owl 记账噪声。

推理是**物化，不是魔法**：推导出的事实带着 `inferred: true` 标签落进 YAML，所以 git diff 会精确显示推理机得出了什么结论，人可以像审阅其他改动一样审阅它。（临时性的传递闭包往往根本不需要 OWL — 像 `t:INHERITS+` 这样的 SPARQL 属性路径在查询时就已经在走链条了。）

## 图谱住在哪里：存储由你选

文件不必在本地，甚至不必是文件。存储层之上的一切只会索取「一整份文档」，所以目的地可以随意更换而其他什么都不用改 — SPARQL、MCP 工具、SHACL 和 `to_networkx` 在字节位于何处时的行为完全一致。

**对象存储**（`pip install 'trikedb[remote]'`）：

```python
db = TrikeDB("s3://team-bucket/kg/pipeline.yaml")   # 读写皆可
```

```bash
trikedb sparql s3://team-bucket/kg/pipeline.yaml "SELECT ?s WHERE { ?s ?p ?o } LIMIT 5"
trikedb mcp s3://team-bucket/kg/pipeline.yaml       # 全团队的智能体共享同一个图谱
```

认证经由 fsspec/s3fs 委托给标准的 AWS 凭据链（环境变量、`~/.aws/credentials` 里的 profile、SSO、IAM 角色）— trikedb 不存储任何凭据，你的 bucket policy *就是*访问控制：读者拿 `s3:GetObject`，写者拿 `s3:PutObject`，按前缀的策略可以给每个团队一个自己的图谱。`gs://`、`az://` 以及纯 `https://`（只读）在装上对应的 fsspec 后端后走同一套机制。

**数仓里的一张表**（`pip install 'trikedb[snowflake]'` 或 `'trikedb[bigquery]'`）— 给那些治理规定「数据必须住在数仓里」的团队：

```python
db = TrikeDB("snowflake://ANALYTICS.PUBLIC.TRIKE_GRAPHS/sales/crm")
# 或者
db = TrikeDB("bigquery://my-project.analytics.TRIKE_GRAPHS/sales/crm")
```

一个图谱是一行（`name`、`doc`、`version`、`updated_at`），而一张表可以装很多图谱 — 一家公司采用 trikedb 的代价是一张表，不是每个图谱一张。没有本地副本，也没有要同步的东西：那一行*就是*图谱。请先建表（trikedb 不会自作主张在你的数仓里跑 DDL）：

```bash
trikedb sql-init snowflake://ANALYTICS.PUBLIC.TRIKE_GRAPHS/sales/crm --print   # 先看 DDL
trikedb sql-init snowflake://ANALYTICS.PUBLIC.TRIKE_GRAPHS/sales/crm           # 或者直接执行
```

连接设置来自环境（`SNOWFLAKE_ACCOUNT`、`SNOWFLAKE_USER`、`SNOWFLAKE_PRIVATE_KEY_PATH` 或 `SNOWFLAKE_PASSWORD`，以及按需的 role/warehouse/database），或者用 `SNOWFLAKE_CONNECTION_NAME` 指定 `connections.toml` 里的一项，让你现有的 Snowflake 工具链去管它。跟 S3 一样：trikedb 不存储凭据，你的 grant 就是访问控制。

**而且数仓可以把它读回去。** `sql-init` 还会创建四个视图，于是同一个图谱既能从内存回答 SPARQL，也能从数仓回答 SQL — 不需要维护第二份副本：

```sql
-- 图谱还和现实一致吗？
SELECT k.NODE_ID
FROM MYDB.PUBLIC.KG_NODE k
LEFT JOIN MYDB.INFORMATION_SCHEMA.TABLES t ON t.TABLE_NAME = k.NODE_ID
WHERE k.NODE_TYPE = 'table' AND t.TABLE_NAME IS NULL;   -- 声称存在，但已经没了
```

`KG_NODE` 和 `KG_EDGE` 采用 Snowflake 上属性图惯用的节点/边列形状，所以针对该形状编写的 Cortex Analyst 语义模型或查询在这里同样可用；`KG_PREDICATE` 暴露本体，`KG_TRIPLE` 把同样的行以朴素的 s/p/o 呈现。节点属性和边属性留在 VARIANT 列里，所以新增一个谓词永远不需要改 DDL。它们是视图而不是表 — 没有重复存储，没有会漂移的东西，零成本，而且 `AT(TIMESTAMP => …)` 能透过它们读取过去。（那套列形状是有意为之的副产品，不是依赖：没有从任何人那里引入任何东西，SQL 是从 trikedb 自己的模型生成的，并且 trikedb 与 Snowflake 没有关联，也未获其背书。）

**只读，不给写入通道。** 传入 `read_only=True`，任何改动都会抛异常，`reload()` 也一样：

```python
db = TrikeDB("snowflake://DB.SCHEMA.T/sales/crm", read_only=True)
```

当写入属于别的地方时用它 — 比如 git 里一份经过审阅的文件 — 而数仓存在的目的是分发和 SQL 访问。一个只读的应用不该握着一个 bug 就能挥霍掉的权限。

**自带连接。** 有些宿主环境里已经有一个会话，而你没办法再建一个 — 在 Streamlit in Snowflake 里既找不到凭据，也开不出对外连接。把你手上有的传进来：

```python
from snowflake.snowpark.context import get_active_session

db = TrikeDB("snowflake://DB.SCHEMA.T/sales/crm",
             connection=get_active_session(), read_only=True)
```

DB-API 的连接也可以。分派依据是「这个对象能做什么」，而不是某个被 import 的类型，所以两条路径互不要求对方的驱动被安装。

两者的并发写入都是安全的。保存以「存储中的图谱仍然是当初读到的那一份」为条件，所以一个会覆盖别人的写入会被 `ConcurrentWriteError` 拒绝，而不是悄悄获胜 — S3 用 ETag 前置条件，数仓用版本列加受影响行数。十个并发写者在两者上都会落地十条三元组。`gs://`、`az://` 和本地文件没有条件写入，所以仍然是后写者胜：把写入都走同一个 MCP 进程，或者把写入保持为在 git 里审阅过的批次。

新增一个后端只发生在一个地方。一个数仓就是四段 SQL 模板加一个连接函数。

## 工作区：很多图谱，一个视图

真实的团队不止一个图谱 — 财务、数据平台、人力。一个工作区文件把它们并起来：

```yaml
# workspace.yaml
graphs:
  finance:  finance.yaml
  platform: s3://team-bucket/kg/platform.yaml   # 本地和远端可以随意混用
  warehouse: ../infra/ontology/warehouse.yaml
```

每个命令都接受它（`trikedb sparql workspace.yaml ...`、`trikedb html workspace.yaml`、`trikedb serve workspace.yaml`）。在 HTML 视图里每个项目平铺为自己的一簇，并带上按图谱的筛选栏；每条三元组都带一个 `graph:` 属性标明来源。

回报是**自动连接**：因为 RDF 三元组会在共享的名字上合并，财务里的 `(tanaka, OWNS_BUDGET, project-atlas)` 和平台里的 `(project-atlas, USES, ACME_DWH)` 就成了一条可以用 SPARQL 走通的路径 — 不需要外键，不需要就模式谈判。并集是**只读视图**；每个成员图谱仍由它的团队拥有（和授权），写入落到成员文件。成员也可以是数仓里的行，并且会继承连接 — 这正是让并集能在「自己开不出连接的地方」也可用的原因：

```yaml
# workspace.yaml 自己也存成一行
graphs:
  ontology: snowflake://DB.SCHEMA.T/kg/ontology
  skills:   snowflake://DB.SCHEMA.T/kg/skills
```

```python
db = TrikeDB("snowflake://DB.SCHEMA.T/kg/workspace",
             connection=get_active_session(), read_only=True)
```

**让 `TrikeDB` 去构建并集，而不是自己读成员再合并。** 有三个细节决定并集里有什么，而弄错任何一个都是静默的 — 图谱只是比它的来源文件稍微贫瘠了一点：

- **节点属性是按键合并，不是按节点。** 在两个成员里都声明过的节点会保留每个*键*的第一个值，所以只有第二个成员才有的 `description` 依然存活。整个字典取第一个成员的那种做法会把它丢掉，而且哪里都不会报错。
- **本体按谓词合并**，描述由第一个成员胜出。
- **三元组的 `graph` 属性是工作区里的键**，而不是成员的文件名或路径。

`content_hash()` 是最便宜的证明方式：你自己构建的并集和 trikedb 构建的是否一致 — 哈希相同，图谱就相同。

## 速度

图谱住在内存里，所以花时间的是「打开它」和「查询它」。两者都可调，而且都不需要改变你写图谱的方式。

在 40,800 条三元组上用 `benchmarks/backend_bench.py` 测量，三次取中位数，Apple silicon：

| 后端 | 打开 | 1 跳 | 2 跳连接 | 写入 1 条 |
|---|---|---|---|---|
| 本地 `.yaml` | 992 ms | 0.04 ms | 55 ms | 1,957 ms |
| 本地 `.json` | **57 ms** | 0.04 ms | 55 ms | **148 ms** |
| `snowflake://` 行 | 507 ms | 0.04 ms | 56 ms | 2,889 ms |

从这里能得出三件事。**查询根本不在乎图谱住在哪里** — 三者完全一致，因为它们都在内存里跑。**格式比介质更重要**：同一个图谱作为 `.json` 打开比作为 `.yaml` 快 17 倍，而数仓里的行虽然要跨网络，却赢过本地的 YAML 文件，因为它的文档本来就是 JSON。**数仓写入是那个昂贵的操作** — 读取、重写、条件更新 — 所以请用 `autosave=False` 批量处理，而不是把它放进循环里。

再看引擎本身，在同一个已构建好的图谱上：

| | 1 跳 | 2 跳连接 | 全量计数 |
|---|---|---|---|
| rdflib | 0.90 ms | 342 ms | 432 ms |
| oxigraph（默认） | **0.04 ms** | **52 ms** | **11 ms** |

一个旋钮，加一件已经默认开着的事情 — 两者都不改变被存储的内容：

**存 JSON 而不是 YAML**，适用于那种被读取的次数远多于被审阅的图谱 — 把文件命名为 `graph.json`，或者放进数仓的一行里（那本来就是 JSON）。API 一样，SPARQL 一样，打开快约 30 倍。代价正是当初选 YAML 的理由：没人喜欢读 JSON 的 diff。

**那个快的 SPARQL 引擎已经在里面了。** 读查询跑在 [Oxigraph](https://github.com/oxigraph/oxigraph) 上，一个带真正索引的 Rust 引擎；`pyoxigraph` 之所以是核心依赖，是因为在所有测过的图谱规模上它都更快，一直下探到几百条三元组。两者都是 SPARQL 1.1，而测试套件断言它们给出完全相同的答案 — 包括那个锋利的边角，带类型的字面量：`?x t:pii true` 必须匹配布尔值而不是字符串 `"true"`。`TrikeDB(..., sparql_engine="rdflib")` 会固定用旧引擎，当你想在真实查询上比较两者时值得一试。如果 pyoxigraph 不在 — 只 vendored 了部分文件，或者某个还没有 wheel 的解释器 — 读取会自己回落到 rdflib 而不是失败。

更新（`INSERT`/`DELETE`）、OWL 推理和 SHACL 始终使用 rdflib — 这些路径要么改数据，要么把图交给 `owlrl`/`pyshacl`，在那里放第二个实现毫无收益。

**不可调**的是它的形状：打开时读入整份文档，保存时整份重写。这就是「一个能在 diff 里审阅的图谱」的代价，也是为什么实际上限是几 MB 而不是几 GB。

## 让一个不断长大的图谱保持健康

本体会从很多人（和智能体）手里累积事实。两个命令让这件事可持续：

```bash
# CI / pre-commit：图谱能解析吗，导出的 HTML 是最新的吗？
# 生成的 HTML 会嵌入图谱的内容哈希，所以过期是可检测的。
trikedb check graph.yaml --html docs/index.html   # 过期则退出码 1

# 健康问题清单：工作区成员之间的重复三元组、Tokyo 与 tokyo 这类
# 名称冲突、近似重复的自由文本事实、孤立的节点属性、
# 声明了但没用过的谓词
trikedb audit workspace.yaml            # 有错误时退出码 1；--strict 连警告也算失败
```

`audit` 在设计上是确定性的 — 若想做超出这些启发式规则的语义去重，把 `--json` 报告交给一个 LLM 智能体，让它以可审阅的 PR 形式提出合并方案。

**审阅这道关卡取决于图谱住在哪里。** git 里的文件给你最强的叙事：每次改动都是一个 diff，`check` 和 `audit` 在 CI 里跑，历史白送。`s3://` 或 `snowflake://` 的图谱没有 pull request — 写入立即落地 — 所以审阅移到了写入边界上的本体护栏、按计划而不是按每次改动运行的 `audit`，以及后端自身的历史（对象版本、数仓的时间旅行、`updated_at` 列）。有些团队故意两者都跑：git 里那份经过审阅的图谱，加上一份智能体写入的共享图谱，用工作区文件并起来，让整理和累积互不阻塞。

## 一定要手写 YAML 吗？

不用 — YAML 是存储格式，不是创作界面。它是图谱被写下来的样子，之所以这么选是为了让人能读懂 diff。每一条写入路径都产出同一份文档，并通过同一道本体检查：

| | |
|---|---|
| `db.add(s, p, o, **attrs)` | Python — 脚本、notebook、ETL |
| `trikedb add FILE S P O -a k=v` | 从 shell 写一条 |
| `trikedb import FILE data.csv` | 表格或 Markdown 表里已经有那些事实了 |
| `db.sparql("INSERT DATA {...}")` | 你习惯用 SPARQL 思考 |
| MCP 的 `add_triple` / `set_node` | 智能体在写 — 通常就是这种情况 |
| `db.infer(apply=True)` | 把已经成立的内容物化出来 |
| 直接编辑 YAML | 文本编辑器也是一个正当的客户端 |

护栏对它们一律生效，所以「智能体写的」和「人写的」不可能在词汇上分叉。

HTML 工作台是一次*渲染*，而图谱住在哪里从不决定页面去哪里：本地图谱渲染在它自己旁边，远端的渲染到工作目录，`-o` 既接受路径也接受对象 URL（`-o s3://site/kg.html` 就发布了）。它是一个自包含的文件 — 没有构建步骤，没有服务器 — 所以发布就是把它放到某个地方。

## 把图谱服务出去（UI + REST + 远程 MCP）

一个进程，三扇门（`pip install 'trikedb[serve]'`）：

```bash
trikedb serve workspace.yaml --port 8080 --token $SECRET
```

- `/` — 工作台 UI，始终显示当前的图谱
- `/sparql` — 极简 REST：`POST {"query": "..."}` → JSON，给应用用
- `/mcp` — 基于 Streamable HTTP 的 MCP，给任何地方的智能体用：

```bash
claude mcp add kg https://kg.internal:8080/mcp --transport http \
  --header "Authorization: Bearer $SECRET"
```

和 stdio 完全相同的十一个 MCP 工具 — 服务器定义是共享的，只有传输层不同。搭配一个 `s3://` 图谱，服务器就是无状态的 — 随处可跑。

### OAuth 2.1，给 claude.ai 和 ChatGPT 的界面用

静态 token 对脚本够用，但网页界面想要真正的登录。把 trikedb 指向你本来就在运维的 IdP，它就成了一个 OAuth 2.1 资源服务器 — 两个连接器界面都知道怎么跟它对话：

```bash
pip install 'trikedb[serve,oauth]'
trikedb serve graph.yaml --public-url https://kg.example.com \
  --oauth-issuer https://idp.example.com/ --required-scope kg:read
```

然后把 `https://kg.example.com/mcp` 添加为自定义连接器，用你自己的身份登录。trikedb **验证** token；它绝不签发 token。这里没有授权服务器，没有用户表，没有密码 — 只有对你的 issuer 做一次 JWKS 查询，以及检查 token 的签名、过期时间和受众是否正确。你的 IdP 仍然是身份唯一居住的地方，而图谱仍然是一个文件。

有三件事要做对：

- **`--public-url` 必须是客户端真正访问到的那个 HTTPS URL。** token 会以 `<public-url>/mcp` 作为受众被绑定（RFC 8707），所以为另一个服务签发的 token 打不开你的图谱。如果你的 IdP 签发的是一个固定的 API identifier，用 `--oauth-audience` 覆盖。
- **IdP 需要能注册这个连接器。** Dynamic Client Registration 是最顺的路（Auth0、Okta、Keycloak、WorkOS 都支持）；如果你的不支持，claude.ai 也接受 Client ID Metadata Document，或者你手动粘贴的 client ID / secret。
- **它必须通过 HTTPS 公网可达。** 两个界面都连不上 `localhost` — 开发时请用隧道。

发现文档已经替你在 `/.well-known/oauth-protected-resource/mcp` 提供好了，而一个未认证的请求会拿到启动登录流程的 RFC 9728 challenge。

## 文件格式

一个 trikedb 文件就是普通的 YAML，有三个顶层键（只有 `triples` 是必需的）：

```yaml
ontology:            # 可选 — 省略它就是自由形式的谓词
  predicates:
    PROVIDES: "SaaS vendor -> ingestion job"
    AFFECTED_BY: "table -> change event"

nodes:               # 可选 — 自由形式的节点属性
  salesflow-crm: {type: saas, url: "https://salesflow.example", plan: enterprise}
  RAW_CRM_CONTACTS: {type: table, schema: ACME_RAW, pii: true}

triples:
  # 朴素事实用紧凑形式
  - {s: adastra-ads, p: PROVIDES, o: ads-spend-collector}

  # 任何额外的键都会变成边属性
  - s: RAW_AD_SPEND_DAILY
    p: AFFECTED_BY
    o: "2025-04-01 adastra API v3: spend now in micros (was cents)"
```

三个值得借走的惯例（参见 [`examples/acme_pipeline.yaml`](https://github.com/RyutoYoda/trikedb/blob/main/examples/acme_pipeline.yaml)）：

- **把变更事件当作宾语。** 指向带日期的事件字符串的 `AFFECTED_BY` 边给你的图谱一段记忆 — 「这个数字为什么在四月变了？」变成了一个查询。
- 边上的 **`deprecated: true`** 会在 HTML 视图里渲染成虚线，并让智能体能过滤掉死路。
- **`via:` / `schedule:`** 这类属性承载运维细节，而不污染节点集合。
- **节点属性会一直长。** 这就是 RDF 的承诺：挂上 `type`、`url`、`schema`、负责人 — 你的团队需要什么都行 — 不需要模式迁移。`type` 驱动 HTML 视图里的颜色分组，而节点属性在 SPARQL 里可查询（`?x t:type "table"`）。在代码里用 `db.set_node("RAW_CRM_CONTACTS", pii=True)` 设置它们。

## 面向智能体的混合检索

语义检索的召回很好（找到你想说的意思）但精度不行 — 分数没有校准，而且它从不说「没有匹配」。SPARQL 正相反：精确，但前提是你已经知道那些名字。`find()` 把两者合进一次调用 — **语义召回，然后一道硬性结构过滤** — 这正是智能体真正想要的检索：

```python
# 「按含义撒一张大网，然后只留下精确匹配的部分」
db.find("where is the customer CRM data?",
        where={"type": "table", "pii": True})   # 必需节点属性的字典 ……
db.find("customer data", where=lambda name, props: props.get("pii"))  # …… 或者一个谓词函数

# 每个结果都是可以直接用的载荷：节点、它的属性、它的事实
# [{"node": "RAW_CRM_CONTACTS", "props": {"type": "table", "pii": True, ...},
#   "facts": [["INGESTS_TO", ...], ...]}]
```

召回负责撒大网（`search`，跨语言，容忍同义词）；`where` 过滤器毫不含糊地丢掉误报，并拉出精确的结构化事实。用召回阶段拿候选，用过滤阶段保正确 — 永远不要用原始相似度分数来做判定。同样这套两段式动作也以下文的 **`find` MCP 工具**提供给 LLM 智能体，或者当你想完全掌控时，用 `search` + `sparql`/`match` 自己拼。

## 给 AI 智能体的本体层（MCP）

trikedb 是嵌入式的，不是托管式的。对智能体来说，「嵌入式」意味着 stdio 上的 MCP — 图谱在智能体会话内部运行，没有服务器要运维。在任何 MCP 客户端里注册它：

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

智能体拿到读取用的 `sparql`、`match`、`search`、`find`、`get_node`、`ontology`、`stats`，以及写入用的 `add_triple`、`set_node`、`remove_triples`、`import_source`。每次写入都会自动保存到 YAML — 于是智能体的贡献以可审阅的 git diff 形式抵达。

这也是对「直接把文档一股脑丢给它就行了」的回答：**智能体是抽取器，trikedb 是那条经过校验的写入通道。** 把你的智能体指向一堆文档，让它记录事实；它去读（什么格式都行 — 它是 LLM），为每条事实调用 `add_triple`，而本体会拒掉它试图发明的任何谓词。抽取保持灵活，图谱保持干净，然后由人来审阅 diff。

## 和 LLM 智能体一起用（不走 MCP）

零配置的循环：

1. 把 `graph.yaml` 放在你的仓库里，紧挨着它所描述的代码。
2. 只需告诉你的智能体一次（写在它的项目指令 / 系统提示里）：

   > 在任何触及数据管道的任务之前，先读 `pipeline.yaml`。
   > 关于哪个作业供给哪张表，它是唯一的事实来源。
   > 谓词仅限于文件中声明的本体。

3. 智能体以对 YAML 的 diff 形式提出修改 — 像任何其他改动一样可以在 PR 里审阅。本体检查（`trikedb.add` 遇到未知谓词会抛异常）把生成的修改约束在你选定的词汇之内。
4. 人类通过 `trikedb html` 浏览同一个图谱。

一个事实来源，两种投影：给机器的 YAML，给人的 HTML。

## trikedb 不是什么

- **不是自己写的一套 SPARQL 实现。** SPARQL 这一层是刻意*不*手写的 — 你的 YAML 会被投影到真正的引擎里：读取跑在 [Oxigraph](https://github.com/oxigraph/oxigraph) 上，更新和 OWL/SHACL 跑在 [rdflib](https://github.com/RDFLib/rdflib) 上。映射规则：主语/谓词成为 `urn:trikedb:` 下的 URI；含空白的宾语（变更事件、备注）成为字面量。通过 SPARQL 插入的三元组一开始没有边属性；存活下来的三元组保留它们自己的。另外还有更轻的 `query()`/`triples()` API 用于快速模式匹配。
- **不是一条抽取流水线。** 它不会把你的 PDF 变成图谱。想要那个就配一个抽取器 — 然后整理它产出的东西。
- **不适合数百万条三元组。** 一切都在内存里，扫描是线性的。最佳区间是数百到数千 — 在这个规模上，一个经过整理的图谱才是可能的。

## 示例

- [`examples/freebase_sample.yaml`](https://github.com/RyutoYoda/trikedb/blob/main/examples/freebase_sample.yaml) — **真实数据**：来自 Freebase 知识图谱的约 600 条事实（CC BY，从 WebQSP 基准的子图中抽取），围绕 Tupac Shakur、阿加莎·克里斯蒂、尼古拉·特斯拉等。节点类型是从谓词的 domain 推断出来的。在线演示用的就是它。
- [`examples/freebase_workspace.yaml`](https://github.com/RyutoYoda/trikedb/blob/main/examples/freebase_workspace.yaml) — 同一批事实拆成 6 个领域图谱（电影 / 音乐 / 书籍 / 人物 / 地点 / 其他），再作为**工作区**并回来：每个成员渲染成自己的一座岛，带一个筛选标签。工作区演示用的就是它。
- [`examples/acme_pipeline.yaml`](https://github.com/RyutoYoda/trikedb/blob/main/examples/acme_pipeline.yaml) — 一个虚构的数据平台，展示那些运维惯例：本体、废弃标记、变更事件。
- [`examples/python_ecosystem.yaml`](https://github.com/RyutoYoda/trikedb/blob/main/examples/python_ecosystem.yaml) — 自由形式的谓词，没有本体。
- [`examples/trikedb_quickstart.ipynb`](https://github.com/RyutoYoda/trikedb/blob/main/examples/trikedb_quickstart.ipynb) — 可运行的 notebook 快速上手，图谱内联在里面。

**在线演示：** https://ryutoyoda.github.io/trikedb/ · **工作区演示：** https://ryutoyoda.github.io/trikedb/workspace.html

导出的 HTML 是一个小工作台，不只是一张图：点一个节点会打开右侧面板列出它的全部属性（URL 会变成链接），右上角可以搜索节点，打开 **SPARQL 控制台**就能在浏览器里跑真正的 SPARQL 1.1 — 由编译成 WASM 的 [Oxigraph](https://github.com/oxigraph/oxigraph) 驱动，首次使用时从 CDN 加载。变更事件渲染成红色菱形，底部带一条时间轴；初始布局会随图谱形状自适应（`--layout flow|free|auto`）。用节点类型的复选框筛选视图（带**全选 / 全不选**快捷方式）— 类型多起来时图例会横向滚动 — 在工作区里也可以用同样的方式切换成员图谱。

## 基准测试

在 [WebQSP](https://aclanthology.org/P16-2033/)（知识图谱问答）上，同一个本地模型**单独作答 42.7%，而以 trikedb 图谱作为上下文时是 77.7%** — 测试集 300 个问题上的 Hits@1，相差 35 个百分点，配对 McNemar 检验 p = 9e-20。检索在其中 89.3% 的问题上把答案摆到了模型面前，每题耗时 0.59 秒。脚本、精度与延迟的取舍，以及一份诚实的评分敏感性分析都在 [`benchmarks/`](https://github.com/RyutoYoda/trikedb/blob/main/benchmarks/README_zh.md)。

## 文档

- [docs/REFERENCE.md](https://github.com/RyutoYoda/trikedb/blob/main/docs/REFERENCE.md)（英文） — 每个功能及其用法（CLI、Python API、MCP、serve、附加项）· [日本語版](https://github.com/RyutoYoda/trikedb/blob/main/docs/REFERENCE_jp.md)
- [docs/ARCHITECTURE.md](https://github.com/RyutoYoda/trikedb/blob/main/docs/ARCHITECTURE_zh.md) — 分层结构，以及新代码该放在哪里
- [docs/SCALING.md](https://github.com/RyutoYoda/trikedb/blob/main/docs/SCALING.md) — 在 1k/10k/100k 三元组上测出的极限，以及何时该从整文件读取转向一个被服务出去的图谱
- [benchmarks/](https://github.com/RyutoYoda/trikedb/blob/main/benchmarks/README_zh.md) — WebQSP 的方法与结论

## 开发

使用 [uv](https://docs.astral.sh/uv/)：

```bash
uv sync --extra dev
uv run pytest
```

## 许可证

MIT

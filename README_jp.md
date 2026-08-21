<p align="center">
  <a href="https://github.com/RyutoYoda/trikedb/blob/main/README.md">English</a>
  &nbsp;·&nbsp; <b>日本語</b>
  &nbsp;·&nbsp; <a href="https://github.com/RyutoYoda/trikedb/blob/main/README_zh.md">简体中文</a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/RyutoYoda/trikedb/main/docs/logo.png" width="260" alt="TrikeDB — 襟に知識グラフを載せたトリケラトプス">
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
  <b><a href="https://ryutoyoda.github.io/trikedb/">🦕 ライブデモ</a></b> — 実際のFreebaseの事実600件。クリックして回れて、ブラウザ上でSPARQLも実行できます
  &nbsp;·&nbsp; <a href="https://ryutoyoda.github.io/trikedb/workspace.html">ワークスペースのデモ</a> — 同じ事実を6つのドメイングラフに分けて、タイル表示＋絞り込み
  &nbsp;·&nbsp; <a href="https://pypi.org/project/trikedb/">PyPI</a>
</p>

# trikedb

**1ファイルのグラフデータベース。** 本物のトリプルストアと同じように問い合わせられます — SPARQL 1.1 のフル対応、読み取り*も*書き込みも。その下にあるのは YAML 1つ。LLMエージェントのために作られています。

```yaml
triples:
  - {s: salesflow-crm, p: PROVIDES, o: crm-sync-job}
  - {s: crm-sync-job, p: INGESTS_TO, o: RAW_CRM_CONTACTS, schedule: hourly}
  - {s: LEGACY_DUMP, p: MIGRATED_TO, o: RAW_CRM_CONTACTS, deprecated: true}
```

このファイル**が**データベースです。サーバもデーモンもクラウドへのデプロイもありません。git で綺麗に diff が取れ、コードの隣のリポジトリで生き続け、そして — trikedb が本当に狙って設計されている点ですが — **LLMエージェントが直接 `Read` して、エンティティ名を捏造せずにあなたのドメインを推論できます。**

しかもインタラクティブなワークベンチとして描画されます（[ライブデモ](https://ryutoyoda.github.io/trikedb/) — 実際のFreebaseの事実600件）:

<p align="center">
  <a href="https://ryutoyoda.github.io/trikedb/">
    <img src="https://raw.githubusercontent.com/RyutoYoda/trikedb/main/docs/screenshot.png" alt="trikedb の HTML ワークベンチ — Freebaseの事実600件を力学配置のクラスタとして表示、ノード詳細パネルを開いた状態">
  </a>
</p>

## なぜ作ったか

RDF のグラフデータベースは強力で、正しく — そして重い。SPARQLエンドポイント、OWL推論器、エンタープライズのセマンティックレイヤー。規模には強いですが、必要なのが「AIエージェント（と同僚）が信頼できる、厳選された数百件の事実の地図」なら過剰です。

trikedb は大きなシステムの*インターフェース*を保ちつつ — 自作のサブセットではなく、[Oxigraph](https://github.com/oxigraph/oxigraph) が実行する本物の SPARQL 1.1 — *機械装置*の側を、読めて diff が取れてコミットできる1ファイルの上の組み込みライブラリまで縮めたものです:

|  | フルのトリプルストア構成 | trikedb |
|---|---|---|
| 保存 | サーバ / クラウドサービス | YAML 1ファイル |
| クエリ | SPARQL 1.1 | SPARQL 1.1（同じ言語、Oxigraph の Rust エンジン） |
| グラフモデル | 通常はどちらかを選ぶ: RDF *か* プロパティグラフ（2システム） | **1ファイルから両方** — SPARQL/RDF（`to_rdflib`）とプロパティグラフ（`to_networkx`、`[networkx]` 経由） |
| 書き込み | SPARQL Update | SPARQL Update — YAML に書き戻して永続化 |
| スキーマ | OWL + 推論器 | 述語のホワイトリスト、加えて `[shacl]` による SHACL シェイプ |
| 推論 | DL推論エンジン | `[owl]` による OWL-RL の実体化 — 導出された事実は YAML に落ち、レビュー可能 |
| エージェント連携 | 運用すべきサービス | エージェントがファイルを読む、`trikedb mcp`（stdio）、`trikedb serve`（リモートMCP + UI + REST） |
| 導入時間 | 半日（あるいは1スプリント） | `pip install trikedb` |

規模のあるフル OWL-DL 推論、名前付きグラフ、マルチテナントのガバナンスが必要なら、フルのエンタープライズ・セマンティックプラットフォームを使ってください。**今日、ファイルで、git の中に**知識グラフが欲しいなら trikedb です。保存形式が RDF に素直に対応しているので、後で大きなシステムに卒業するのは書き直しではなくエクスポートで済みます。各チームが自分の YAML グラフを持ち、それらを繋ぎ合わせる（あるいは丸ごと移行する）のはトリプルをマージするだけです。

### 抽出ファーストではなく、キュレーションファースト

「AI知識グラフ」ツールの多くは、LLM でテキストからトリプルを抽出します。立ち上げには良いのですが、抽出されたグラフはハルシネーションを受け継ぎます。trikedb は逆の立場を取ります: **グラフはキュレーションされたデータ**（人間、あるいは監督下のエージェントによる）であり、オントロジーが言えることを制約し、LLM はグラフを*作る*のではなく*消費*します。エージェントが

```yaml
- {s: crm-sync-job, p: INGESTS_TO, o: RAW_CRM_CONTACTS}
```

を読むとき、テーブル名を作り上げられる工程はどこにもありません。

## インストール

[PyPI](https://pypi.org/project/trikedb/) から:

```bash
pip install trikedb             # ライブラリ + CLI（PyYAML, rdflib, pyoxigraph）
pip install 'trikedb[all]'      # 以下すべてを一度に

pip install 'trikedb[mcp]'      # + AIエージェント向け MCP サーバ（stdio）
pip install 'trikedb[serve]'    # + UI / REST / HTTP 経由のリモート MCP
pip install 'trikedb[oauth]'    # + claude.ai / ChatGPT の UI 向け OAuth 2.1
pip install 'trikedb[remote]'   # + s3:// gs:// のグラフ
pip install 'trikedb[snowflake]' # + snowflake:// のグラフ（ウェアハウスが保存先）
pip install 'trikedb[bigquery]' # + bigquery:// のグラフ（同じことを BigQuery で）
pip install 'trikedb[shacl]'    # + SHACL 検証
pip install 'trikedb[owl]'      # + OWL-RL 推論
pip install 'trikedb[semantic]' # + 意味検索（numpy + model2vec、torch 不要）
pip install 'trikedb[networkx]' # + プロパティグラフ投影（to_networkx）

```

## クイックスタート（Python）

```python
from trikedb import TrikeDB

# YAML 1ファイルに住む、型付きの知識グラフ。宣言した述語がスキーマになり、
# そのホワイトリストが書き込み時にタイポやゴミを捕まえる。
db = TrikeDB("pipeline.yaml", ontology={
    "PROVIDES":   "SaaS vendor -> ingestion job",
    "INGESTS_TO": "ingestion job -> warehouse table",
    "MIGRATED_TO": "deprecated table -> its replacement",
})

# 事実を追加する。任意のキーワードがエッジ属性になる — そして `prov` こそ
# 標準化すべきもの。各事実の出所を書いておけばグラフは検証可能なままでいられる。
db.add("salesflow-crm", "PROVIDES", "crm-sync-job")
db.add("crm-sync-job", "INGESTS_TO", "RAW_CRM_CONTACTS",
       schedule="hourly", prov="https://runbook.example/crm#sync")
db.add("LEGACY_DUMP", "MIGRATED_TO", "RAW_CRM_CONTACTS", deprecated=True)

# オントロジーはガードレール: db.add("crm-sync-job", "OWNS", "x") は
# OntologyError を投げる — 'OWNS' は宣言された述語ではないので、タイポは着地しない。

# ノードを説明する: `type` はグラフに色を付け、クエリもできる。他は何でも付けられる。
db.set_node("RAW_CRM_CONTACTS", type="table", pii=True,
            url="https://catalog.example/raw_crm_contacts")

# 質問する — 依存ゼロでパターンを結合するか …
db.query(["?vendor PROVIDES ?job", "?job INGESTS_TO ?table"])
# [{'vendor': 'salesflow-crm', 'job': 'crm-sync-job', 'table': 'RAW_CRM_CONTACTS'}]

# … フルの SPARQL 1.1（FILTER, OPTIONAL, 集約 — Oxigraph が実行、t: は事前バインド済み）
db.sparql('SELECT ?t WHERE { ?t t:type "table" ; t:pii true }')   # PII を含む全テーブル
db.sparql('SELECT ?s ?o WHERE { ?st rdf:subject ?s ; rdf:object ?o ; t:schedule "hourly" }')  # エッジ属性も

# グラフに自分を分類させる — RDFS/OWL の意味論を宣言して、そこから従うものを
# 実体化する（pip install 'trikedb[owl]'）。導出された事実は YAML に落ち、レビューできる。
db.declare("INGESTS_TO", "domain:job")    # INGESTS_TO の主語は job
db.declare("INGESTS_TO", "range:table")   # 目的語は table
db.infer(apply=True)   # -> crm-sync-job は job、RAW_CRM_CONTACTS は table（inferred: true が付く）

# 信じる前に確かめる — SHACL シェイプで検証（pip install 'trikedb[shacl]'）
ok, report = db.validate('''@prefix sh: <http://www.w3.org/ns/shacl#> . @prefix t: <urn:trikedb:> .
  t:IngestShape a sh:NodeShape ; sh:targetObjectsOf t:INGESTS_TO ;
    sh:property [ sh:path t:type ; sh:minCount 1 ] .''')   # 着地した全テーブルが type を宣言しているか？

# 綴りではなく意味で事実を探す（pip install 'trikedb[semantic]'）
db.search("what syncs the CRM?", k=5)

# エージェント向けハイブリッド検索 — 意味による再現と厳密な構造フィルタを1呼び出しで。
# 意味で広く網を張り、そこから正確に一致するものだけを残す。
db.find("where is the customer CRM data?", where={"type": "table", "pii": True})
# -> [{'node': 'RAW_CRM_CONTACTS', 'props': {'type': 'table', 'pii': True, ...}, 'facts': [...]}]

# 書き込みも SPARQL を通り、そのまま YAML に自動保存される
db.sparql("INSERT DATA { t:figly t:PROVIDES t:figly-export-job }")

# チームが実際にクリックして回れる、自己完結した HTML を1つ出す
db.to_html("pipeline.html")     # 検索可能なグラフ + ノード詳細 + ブラウザ内 SPARQL コンソール
db.to_rdflib(); db.to_jsonld()  # RDF/SPARQL のビュー — あるいは任意の RDF ツールへ卒業
db.to_networkx()                # プロパティグラフのビュー: 同じファイルに networkx の
                                # アルゴリズムを走らせる（最短経路、中心性）— 'trikedb[networkx]'
```

## クイックスタート（CLI）

```bash
trikedb add pipeline.yaml salesflow-crm PROVIDES crm-sync-job
# `prov` は単なるエッジ属性だが、標準化すべきもの。各事実の出所を書く。
trikedb add pipeline.yaml crm-sync-job INGESTS_TO RAW_CRM_CONTACTS -a schedule=hourly -a prov=https://runbook.example/crm#sync

trikedb query pipeline.yaml -w "?vendor PROVIDES ?job" -w "?job INGESTS_TO ?table"
# vendor         job           table
# -------------  ------------  ----------------
# salesflow-crm  crm-sync-job  RAW_CRM_CONTACTS

trikedb sparql pipeline.yaml \
  "SELECT ?v ?t WHERE { ?v t:PROVIDES ?j . ?j t:INGESTS_TO ?t }"

# 更新はそのままファイルに永続化される
trikedb sparql pipeline.yaml \
  "INSERT DATA { t:figly t:PROVIDES t:figly-export-job }"

# 意味検索: 綴りではなく意味で（[semantic] エクストラ）
trikedb search pipeline.yaml "what syncs the CRM?" -k 5

trikedb stats pipeline.yaml
trikedb html pipeline.yaml -o pipeline.html
trikedb jsonld pipeline.yaml
```

## CSV と Markdown ドキュメントからの取り込み

保存先は YAML ファイルですが、トリプルはチームが既に書いている場所から来られます:

```bash
# s,p,o のヘッダを持つ CSV/TSV — 余分な列はエッジ属性になる
trikedb import pipeline.yaml new_vendors.csv

# Markdown: ヘッダに s/p/o 列を持つ表だけが拾われる。
# 散文や他の表は無視される。設計ドキュメントがそのままデータになる。
trikedb import pipeline.yaml design_doc.md
```

```markdown
<!-- ごく普通の設計ドキュメントの、どこにでも: -->
| s                 | p          | o                  | schedule  |
|-------------------|------------|--------------------|-----------|
| clickpath-pa      | PROVIDES   | clickpath-webhook  |           |
| clickpath-webhook | INGESTS_TO | RAW_PRODUCT_EVENTS | streaming |
```

取り込みは決定的です — LLM による抽出がないので、何も捏造されません。オントロジーは入口で強制され、`"true"`/`"false"` のセルは真偽値になります。[`examples/acme_design_doc.md`](https://github.com/RyutoYoda/trikedb/blob/main/examples/acme_design_doc.md) と [`examples/acme_new_vendors.csv`](https://github.com/RyutoYoda/trikedb/blob/main/examples/acme_new_vendors.csv) を参照してください。

## 検証と推論（SHACL / OWL）

述語のホワイトリストはシートベルトです。本物のスキーマ検証が欲しくなったら SHACL を使ってください（`pip install 'trikedb[shacl]'` — 自作ではなく [pySHACL](https://github.com/RDFLib/pySHACL) に委譲）:

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
trikedb validate graph.yaml shapes.ttl   # 違反があれば終了コード 1 — CI に向く
```

推論は、述語（とクラス）に RDFS/OWL の意味論を宣言して、そこから従うものを実体化します（`pip install 'trikedb[owl]'`、[owlrl](https://github.com/RDFLib/OWL-RL) 経由の OWL-RL）:

```python
# OWL のプロパティ特性
db.declare("INHERITS", "transitive")     # レビュー可能なトリプルとして保存される
db.add("admin", "INHERITS", "editor")
db.add("editor", "INHERITS", "viewer")
db.infer(apply=True)                     # (admin, INHERITS, viewer) を追加 — inferred: true が付く

# RDFS のクラス階層 + 型付け
db.declare("Cat", "subclass_of:Animal")        # rdfs:subClassOf
db.declare("authored", "domain:Person")        # rdfs:domain  → 主語に型が付く
db.declare("authored", "range:Book")           # rdfs:range   → 目的語に型が付く
db.declare("bornIn", "subproperty_of:locatedIn")  # rdfs:subPropertyOf
db.add("felix", "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", "Cat")
db.infer()   # → subClassOf 経由で (felix, rdf:type, Animal)、domain/range の型付け、など
```

`infer()` は分類と階層（rdf:type, subClassOf, subPropertyOf）に加えて OWL のエッジ（推移的 / 対称的 / 逆）を表に出し、推論器の rdf/owl 内部記録のノイズは抑えます。

推論は**魔法ではなく実体化**です。導出された事実は `inferred: true` のタグ付きで YAML に落ちるので、git の diff が推論器の結論をそのまま見せ、人間が他の変更と同じようにレビューできます。（その場限りの推移性なら OWL は要らないことも多いです — `t:INHERITS+` のような SPARQL のプロパティパスが、クエリ時に既に連鎖を辿ります。）

## グラフの置き場所: 保存先はあなたが選ぶ

ファイルはローカルでなくてよく、そもそもファイルでなくてもよいのです。ストレージより上の層は「文書1つ丸ごと」しか要求しないので、行き先を差し替えても他は何も変わりません — SPARQL、MCP ツール、SHACL、`to_networkx` は、バイトがどこにあっても同じように振る舞います。

**オブジェクトストレージ**（`pip install 'trikedb[remote]'`）:

```python
db = TrikeDB("s3://team-bucket/kg/pipeline.yaml")   # 読み書き両方
```

```bash
trikedb sparql s3://team-bucket/kg/pipeline.yaml "SELECT ?s WHERE { ?s ?p ?o } LIMIT 5"
trikedb mcp s3://team-bucket/kg/pipeline.yaml       # チーム全員のエージェントが1つのグラフを共有
```

認証は fsspec/s3fs 経由で標準の AWS 認証情報チェーン（環境変数、`~/.aws/credentials` のプロファイル、SSO、IAM ロール）に委譲されます。trikedb は認証情報を一切保存せず、バケットポリシー*が*アクセス制御そのものです — 読み手には `s3:GetObject`、書き手には `s3:PutObject`、プレフィックス単位のポリシーで各チームに専用グラフを与えられます。`gs://`、`az://`、素の `https://`（読み取り専用）も、対応する fsspec バックエンドを入れれば同じ仕組みで動きます。

**ウェアハウスのテーブル**（`pip install 'trikedb[snowflake]'` または `'trikedb[bigquery]'`）— ガバナンス上データはウェアハウスに置くと決まっているチームのために:

```python
db = TrikeDB("snowflake://ANALYTICS.PUBLIC.TRIKE_GRAPHS/sales/crm")
# あるいは
db = TrikeDB("bigquery://my-project.analytics.TRIKE_GRAPHS/sales/crm")
```

1グラフが1行（`name`, `doc`, `version`, `updated_at`）で、1テーブルが多数のグラフを持ちます — trikedb の採用に会社が払うのはテーブル1つで、グラフごとに1つではありません。ローカルのコピーは無く、同期するものもありません: その行*が*グラフです。先にテーブルを作ってください（trikedb が勝手にあなたのウェアハウスで DDL を走らせることはしません）:

```bash
trikedb sql-init snowflake://ANALYTICS.PUBLIC.TRIKE_GRAPHS/sales/crm --print   # DDL を確認する
trikedb sql-init snowflake://ANALYTICS.PUBLIC.TRIKE_GRAPHS/sales/crm           # そのまま実行する
```

接続設定は環境から来ます（`SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PRIVATE_KEY_PATH` または `SNOWFLAKE_PASSWORD`、必要に応じて role/warehouse/database）。あるいは `SNOWFLAKE_CONNECTION_NAME` で `connections.toml` のエントリを指定して、既存の Snowflake ツーリングに任せることもできます。S3 と同じで、trikedb は認証情報を保存せず、あなたの grant がアクセス制御です。

**そしてウェアハウス側から読み返せます。** `sql-init` はビューを4つ作るので、同じグラフがメモリからは SPARQL に、ウェアハウスからは SQL に答えます — 歩調を合わせるべき第二のコピーなしに:

```sql
-- グラフはまだ現実と一致しているか？
SELECT k.NODE_ID
FROM MYDB.PUBLIC.KG_NODE k
LEFT JOIN MYDB.INFORMATION_SCHEMA.TABLES t ON t.TABLE_NAME = k.NODE_ID
WHERE k.NODE_TYPE = 'table' AND t.TABLE_NAME IS NULL;   -- 主張されているが、もう無い
```

`KG_NODE` と `KG_EDGE` は Snowflake 上のプロパティグラフで慣習的に使われるノード/エッジの列形状を持つので、その形状に対して書かれた Cortex Analyst のセマンティックモデルやクエリはここでも動きます。`KG_PREDICATE` はオントロジーを、`KG_TRIPLE` は同じ行を素の s/p/o として公開します。ノードのプロパティとエッジ属性は VARIANT 列に留まるので、述語を1つ増やすのに DDL 変更は要りません。これらはテーブルではなくビューです — 二重に保存されるものは無く、ずれるものも無く、コストはゼロで、`AT(TIMESTAMP => …)` は過去をそれ越しに読みます。（この列形状は意図した副産物であって依存ではありません: 誰からも何も取り込んでおらず、SQL は trikedb 自身のモデルから生成され、trikedb は Snowflake と提携しておらず、その承認も受けていません。）

**書き込み経路を持たずに読む。** `read_only=True` を渡すと、あらゆる変更が例外になります。`reload()` も含めて:

```python
db = TrikeDB("snowflake://DB.SCHEMA.T/sales/crm", read_only=True)
```

書き込みが別の場所に属するとき — 例えば git のレビュー済みファイル — に使ってください。ウェアハウスは配布と SQL アクセスのために置くわけです。読むだけのアプリが、バグで使い果たせる権限を握っているべきではありません。

**自分の接続を持ち込む。** ホスト側にセッションがあって、別のを作る術がないことがあります — Streamlit in Snowflake の中では、見つけられる認証情報も、開ける外向き接続もありません。手元にあるものを渡してください:

```python
from snowflake.snowpark.context import get_active_session

db = TrikeDB("snowflake://DB.SCHEMA.T/sales/crm",
             connection=get_active_session(), read_only=True)
```

DB-API の接続でも動きます。振り分けは import された型ではなく「そのオブジェクトが何をできるか」で決まるので、片方の経路のためにもう片方のドライバを入れる必要はありません。

同時書き込みはどちらでも安全です。保存は「保存されているグラフが、読んだときのものとまだ同じであること」を条件にするので、他人を踏み潰す書き込みは静かに勝つのではなく `ConcurrentWriteError` で拒否されます — S3 は ETag の事前条件で、ウェアハウスはバージョン列と影響行数で。10並列の書き手が、どちらでも10件のトリプルを着地させます。`gs://`、`az://`、ローカルファイルには条件付き書き込みがないので last-write-wins のままです: 書き手を1つの MCP プロセスに通すか、書き込みを git でレビューするバッチに留めてください。

バックエンドの追加は1箇所で済みます。ウェアハウス1つが、SQL テンプレート4つと接続関数1つです。

## ワークスペース: 多数のグラフを1つのビューに

現実のチームはグラフを複数持っています — 財務、データ基盤、人事。ワークスペースファイルがそれらを統合します:

```yaml
# workspace.yaml
graphs:
  finance:  finance.yaml
  platform: s3://team-bucket/kg/platform.yaml   # ローカルとリモートは自由に混ぜられる
  warehouse: ../infra/ontology/warehouse.yaml
```

すべてのコマンドが受け取ります（`trikedb sparql workspace.yaml ...`、`trikedb html workspace.yaml`、`trikedb serve workspace.yaml`）。HTML ビューでは各プロジェクトが自分のクラスタとしてタイル表示され、グラフ単位のフィルタバーが付きます。すべてのトリプルは出所を示す `graph:` 属性を持ちます。

見返りは**自動的な結合**です。RDF のトリプルは共有された名前でマージされるので、財務の `(tanaka, OWNS_BUDGET, project-atlas)` と基盤の `(project-atlas, USES, ACME_DWH)` が、SPARQL で辿れる1本の経路になります — 外部キーもスキーマの折衝もなしに。統合は**読み取り専用のビュー**です。各メンバーグラフはそのチームが所有（と権限管理）し続け、書き込みはメンバーのファイルに行きます。メンバーはウェアハウスの行でもよく、その場合は接続を継承します — これが、自分では接続を開けない場所でも統合を使える理由です:

```yaml
# workspace.yaml 自身も行として保存されている
graphs:
  ontology: snowflake://DB.SCHEMA.T/kg/ontology
  skills:   snowflake://DB.SCHEMA.T/kg/skills
```

```python
db = TrikeDB("snowflake://DB.SCHEMA.T/kg/workspace",
             connection=get_active_session(), read_only=True)
```

**メンバーを自分で読んでマージするのではなく、`TrikeDB` に統合を作らせてください。** 統合の内容を決める細部が3つあり、どれか1つを間違えると静かに壊れます — グラフが、元のファイルより少し貧しくなって出てくるだけなので:

- **ノードのプロパティはノード単位ではなくキー単位でマージされます。** 2つのメンバーで宣言されたノードは各*キー*の最初の値を保つので、2番目のメンバーだけが持つ `description` も生き残ります。最初のメンバーから辞書ごと取ると、どこにもエラーを出さずにそれを落とします。
- **オントロジーは述語単位でマージ**され、説明は最初のメンバーが勝ちます。
- **トリプルの `graph` 属性はワークスペースのキー**であり、メンバーのファイル名やパスではありません。

`content_hash()` は、自分で作った統合が trikedb の作るものと一致するかを安く証明する方法です: ハッシュが同じなら、同じグラフです。

## 速度

グラフはメモリに載るので、時間を食うのは「開くこと」と「問い合わせること」です。どちらも調整でき、どちらもグラフの書き方を変える必要はありません。

40,800トリプルで `benchmarks/backend_bench.py` により測定、3回の中央値、Apple silicon:

| バックエンド | 開く | 1ホップ | 2ホップ結合 | 1件書き込み |
|---|---|---|---|---|
| ローカル `.yaml` | 992 ms | 0.04 ms | 55 ms | 1,957 ms |
| ローカル `.json` | **57 ms** | 0.04 ms | 55 ms | **148 ms** |
| `snowflake://` の行 | 507 ms | 0.04 ms | 56 ms | 2,889 ms |

ここから3つのことが出てきます。**クエリはグラフの置き場所を気にしません** — 3つとも同一で、メモリ内で走るからです。**媒体より形式の方が効きます**: 同じグラフが `.yaml` より `.json` で17倍速く開き、ウェアハウスの行はネットワークを越えるのにローカルの YAML ファイルに勝ちます。その文書が既に JSON だからです。**ウェアハウスへの書き込みが高価な操作**です — 読んで、書き直して、条件付き更新 — なのでループに入れるのではなく `autosave=False` でまとめてください。

そしてエンジンの側、同じグラフを一度構築した後で:

| | 1ホップ | 2ホップ結合 | 全件カウント |
|---|---|---|---|
| rdflib | 0.90 ms | 342 ms | 432 ms |
| oxigraph（既定） | **0.04 ms** | **52 ms** | **11 ms** |

つまみが1つと、既に入っているものが1つ。どちらも保存されるものを変えません:

**YAML ではなく JSON で保存する** — レビューされるよりずっと頻繁に読まれるグラフに。ファイル名を `graph.json` にするか、ウェアハウスの行に置く（そちらは既に JSON）。API も SPARQL も同じで、開く速度が約30倍。代償は YAML を選んだ理由そのものです: JSON の diff を読んで楽しい人はいません。

**速い SPARQL エンジンは既に入っています。** 読み取りクエリは [Oxigraph](https://github.com/oxigraph/oxigraph) — 本物のインデックスを持つ Rust のエンジン — で走ります。`pyoxigraph` がコア依存なのは、測定したすべてのグラフサイズで、数百トリプルまで下げても速かったからです。両方とも SPARQL 1.1 で、テストスイートが「同じ答えを返すこと」を主張します — 鋭い縁である型付きリテラル、`?x t:pii true` が文字列 `"true"` ではなく真偽値に一致しなければならない点も含めて。`TrikeDB(..., sparql_engine="rdflib")` で古いエンジンを固定できます。実際のクエリで両者を比べたくなったときには価値があります。pyoxigraph が無い環境なら — ファイルの一部だけをベンダリングした場合や、まだ wheel が無いインタプリタなど — 読み取りは失敗せずに自分で rdflib に落ちます。

更新（`INSERT`/`DELETE`）、OWL 推論、SHACL は常に rdflib を使います。これらの経路はデータを変えるか、グラフを `owlrl`/`pyshacl` に渡すもので、そこに2つ目の実装があっても何も得られません。

調整**できない**のは形そのものです: 開くときに文書全体を読み、保存するときに全体を書き直します。それが「diff でレビューできるグラフ」の代金であり、実用上の上限が数GBではなく数MBである理由です。

## 育つグラフを健全に保つ

オントロジーは多くの手（とエージェント）から事実を積み上げます。2つのコマンドがそれを持続可能にします:

```bash
# CI / pre-commit: グラフはパースできるか、エクスポートした HTML は最新か？
# 生成された HTML はグラフのコンテンツハッシュを埋め込むので、古さが検出できる。
trikedb check graph.yaml --html docs/index.html   # 古ければ終了コード 1

# 健全性の指摘: ワークスペースメンバー間の重複トリプル、Tokyo と tokyo の
# 名前衝突、ほぼ重複の自由文の事実、孤立したノードプロパティ、
# 宣言されているが使われていない述語
trikedb audit workspace.yaml            # エラーで終了コード 1、--strict は警告でも失敗
```

`audit` は設計上決定的です — このヒューリスティクスを超える意味的な重複排除がしたければ、`--json` のレポートを LLM エージェントに渡して、レビュー可能な PR としてマージを提案させてください。

**レビューの門は、グラフがどこに住むかで変わります。** git の中のファイルが最も強い物語をくれます: すべての変更が diff で、`check` と `audit` が CI で走り、履歴は無料で付いてきます。`s3://` や `snowflake://` のグラフにはプルリクエストがありません — 書き込みは即座に着地します — なのでレビューは、書き込み境界のオントロジーガード、変更ごとではなく定期実行の `audit`、そしてバックエンド自身の履歴（オブジェクトのバージョン、ウェアハウスのタイムトラベル、`updated_at` 列）に移ります。両方を意図的に走らせるチームもあります: git のレビュー済みグラフと、エージェントが書き込む共有グラフを、ワークスペースファイルで統合して、キュレーションと蓄積が互いをブロックしないようにします。

## YAML を手で書かなければいけない？

いいえ — YAML は保存形式であって、執筆インターフェースではありません。グラフが何として書き下されるかであり、人間が diff を読めるように選ばれています。どの書き込み経路も同じ文書を作り、同じオントロジーチェックを通ります:

| | |
|---|---|
| `db.add(s, p, o, **attrs)` | Python — スクリプト、ノートブック、ETL |
| `trikedb add FILE S P O -a k=v` | シェルから1件 |
| `trikedb import FILE data.csv` | スプレッドシートや Markdown の表に、既に事実がある |
| `db.sparql("INSERT DATA {...}")` | SPARQL で考える人 |
| MCP の `add_triple` / `set_node` | エージェントが書いている — 通常はこれ |
| `db.infer(apply=True)` | 既に従っているものを実体化する |
| YAML を直接編集 | テキストエディタも正当なクライアント |

ガードはすべてに等しく適用されるので、「エージェントが書いた」と「人間が書いた」が語彙で乖離することはありません。

HTML のワークベンチは*描画*であり、グラフの住所がページの行き先を決めることはありません: ローカルのグラフは自分の隣に、リモートのものは作業ディレクトリに描画され、`-o` はパスでもオブジェクト URL でも取ります（`-o s3://site/kg.html` で公開されます）。自己完結した1ファイルなので — ビルド工程もサーバも無し — 公開はどこかに置くだけです。

## グラフを配る（UI + REST + リモート MCP）

1プロセス、3つの扉（`pip install 'trikedb[serve]'`）:

```bash
trikedb serve workspace.yaml --port 8080 --token $SECRET
```

- `/` — ワークベンチ UI。常に現在のグラフを表示
- `/sparql` — 最小の REST: `POST {"query": "..."}` → JSON。アプリ向け
- `/mcp` — Streamable HTTP 上の MCP。どこにいるエージェントにも:

```bash
claude mcp add kg https://kg.internal:8080/mcp --transport http \
  --header "Authorization: Bearer $SECRET"
```

stdio と同じ11個の MCP ツールです — サーバ定義は共有で、違うのはトランスポートだけ。`s3://` のグラフと組めばサーバはステートレスになり、どこでも動かせます。

### OAuth 2.1 — claude.ai と ChatGPT の UI 向け

静的なトークンはスクリプトには十分ですが、Web の UI は本物のログインを求めます。既に運用している IdP に trikedb を向けると、OAuth 2.1 のリソースサーバになります — 両方のコネクタ UI が話し方を知っている相手です:

```bash
pip install 'trikedb[serve,oauth]'
trikedb serve graph.yaml --public-url https://kg.example.com \
  --oauth-issuer https://idp.example.com/ --required-scope kg:read
```

あとは `https://kg.example.com/mcp` をカスタムコネクタとして追加し、自分としてログインするだけです。trikedb はトークンを**検証**します。発行は決してしません。ここには認可サーバもユーザテーブルもパスワードもありません — あなたの issuer に対する JWKS の参照と、トークンの署名・有効期限・オーディエンスが正しいかの確認だけです。IdP が身元の住む唯一の場所であり続け、グラフはファイルであり続けます。

正しくすべきことが3つ:

- **`--public-url` はクライアントが実際に到達する HTTPS の URL であること。** トークンは `<public-url>/mcp` をオーディエンスとして束縛されるので（RFC 8707）、別のサービス向けに発行されたトークンであなたのグラフは開けません。IdP が固定の API 識別子を発行するなら `--oauth-audience` で上書きしてください。
- **IdP がコネクタを登録できる必要があります。** Dynamic Client Registration が滑らかな道です（Auth0、Okta、Keycloak、WorkOS はいずれも対応）。対応していない場合、claude.ai は Client ID Metadata Document か、貼り付ける client ID / secret も受け付けます。
- **HTTPS で公開到達可能である必要があります。** どちらの UI も `localhost` には繋げません — 開発中はトンネルを使ってください。

ディスカバリは `/.well-known/oauth-protected-resource/mcp` で配られ、未認証のリクエストにはログインフローを始める RFC 9728 のチャレンジが返ります。

## ファイル形式

trikedb のファイルは、トップレベルのキーが3つある普通の YAML です（必須なのは `triples` だけ）:

```yaml
ontology:            # 任意 — 省略すれば述語は自由形式
  predicates:
    PROVIDES: "SaaS vendor -> ingestion job"
    AFFECTED_BY: "table -> change event"

nodes:               # 任意 — 自由形式のノードプロパティ
  salesflow-crm: {type: saas, url: "https://salesflow.example", plan: enterprise}
  RAW_CRM_CONTACTS: {type: table, schema: ACME_RAW, pii: true}

triples:
  # 素の事実にはコンパクト形式
  - {s: adastra-ads, p: PROVIDES, o: ads-spend-collector}

  # 余分なキーはエッジ属性になる
  - s: RAW_AD_SPEND_DAILY
    p: AFFECTED_BY
    o: "2025-04-01 adastra API v3: spend now in micros (was cents)"
```

盗む価値のある慣習が3つ（[`examples/acme_pipeline.yaml`](https://github.com/RyutoYoda/trikedb/blob/main/examples/acme_pipeline.yaml) を参照）:

- **変更イベントを目的語にする。** 日付入りのイベント文字列を指す `AFFECTED_BY` のエッジは、グラフに記憶を与えます — 「なぜこの数字は4月に変わったのか？」がクエリになります。
- エッジの **`deprecated: true`** は HTML ビューで破線として描画され、エージェントが死んだ経路を除外できるようにします。
- **`via:` / `schedule:`** 属性は、ノード集合を汚さずに運用上の詳細を運びます。
- **ノードプロパティは増え続けます。** それが RDF の約束です: `type`、`url`、`schema`、オーナー — チームが必要とするものを何でも — スキーマ移行なしに付けられます。`type` は HTML ビューで色分けを駆動し、ノードプロパティは SPARQL でクエリできます（`?x t:type "table"`）。コードからは `db.set_node("RAW_CRM_CONTACTS", pii=True)` で設定します。

## エージェント向けハイブリッド検索

意味検索は再現（意味で探す）に強いが精度には弱い — スコアは校正されておらず、「一致なし」とは決して言いません。SPARQL は逆で、正確だが名前を既に知っている場合だけ。`find()` は両者を1呼び出しで組み合わせます — **意味による再現、そして厳密な構造フィルタ** — これがエージェントが実際に欲しい検索です:

```python
# 「意味で広く網を張り、そこから正確に一致するものだけを残す」
db.find("where is the customer CRM data?",
        where={"type": "table", "pii": True})   # 必須ノードプロパティの辞書、あるいは …
db.find("customer data", where=lambda name, props: props.get("pii"))  # … 述語関数

# 各結果はそのまま使えるペイロード: ノード、そのプロパティ、その事実
# [{"node": "RAW_CRM_CONTACTS", "props": {"type": "table", "pii": True, ...},
#   "facts": [["INGESTS_TO", ...], ...]}]
```

再現が広く網を張り（`search`、言語をまたぎ、同義語に寛容）、`where` フィルタが偽陽性をぼかしなく落として、正確な構造化された事実を引き出します。再現段は候補のために、フィルタは正しさのために使ってください — 生の類似度スコアで判定してはいけません。同じ2段構えは、下記の **`find` MCP ツール**として LLM エージェントにも提供されており、完全に制御したいときは `search` + `sparql`/`match` で手組みもできます。

## AIエージェントのためのオントロジー層（MCP）

trikedb は組み込みで、ホスト型ではありません。エージェントにとって「組み込み」とは stdio 上の MCP を意味します — グラフはエージェントのセッションの中で走り、運用するサーバはありません。任意の MCP クライアントに登録してください:

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

エージェントは読み取りに `sparql`、`match`、`search`、`find`、`get_node`、`ontology`、`stats` を、書き込みに `add_triple`、`set_node`、`remove_triples`、`import_source` を得ます。すべての書き込みが YAML に自動保存されるので、エージェントの貢献はレビュー可能な git の diff として届きます。

これは「とりあえずドキュメントを投げ込めばいい」への答えでもあります: **エージェントが抽出器であり、trikedb が検証された書き込み経路です。** ドキュメントの山にエージェントを向けて事実を記録させてください。エージェントはそれらを読み（形式は何でも — LLM ですから）、事実ごとに `add_triple` を呼び、オントロジーが捏造しようとした述語を却下します。抽出は柔軟なまま、グラフは綺麗なまま、そして人間が diff をレビューします。

## LLMエージェントと使う（MCP なし）

準備ゼロのループ:

1. `graph.yaml` を、それが説明するコードの隣、リポジトリの中に置く。
2. エージェントに一度だけ伝える（プロジェクト指示 / システムプロンプトで）:

   > データパイプラインに触るタスクの前に、必ず `pipeline.yaml` を読むこと。
   > どのジョブがどのテーブルに供給しているかの真実の源はこれである。
   > 述語はファイル内で宣言されたオントロジーに限られる。

3. エージェントは YAML への diff として編集を提案します — 他の変更と同じように PR でレビューできます。オントロジーチェック（`trikedb.add` は未知の述語で例外を投げる）が、生成された編集をあなたが選んだ語彙の内側に留めます。
4. 人間は同じグラフを `trikedb html` で眺めます。

真実の源は1つ、投影は2つ: 機械には YAML、人間には HTML。

## trikedb でないもの

- **独自の SPARQL 実装ではありません。** SPARQL の表面は意図的に自作していません — あなたの YAML は本物のエンジンに投影されます: 読み取りは [Oxigraph](https://github.com/oxigraph/oxigraph)、更新と OWL/SHACL は [rdflib](https://github.com/RDFLib/rdflib)。対応規則: 主語と述語は `urn:trikedb:` 配下の URI になり、空白を含む目的語（変更イベント、メモ）はリテラルになります。SPARQL 経由で挿入されたトリプルはエッジ属性なしで始まり、生き残ったトリプルは自分の属性を保ちます。手軽なパターンマッチ用に軽量な `query()`/`triples()` API もあります。
- **抽出パイプラインではありません。** PDF をグラフに変えてはくれません。それが欲しければ抽出器と組み合わせて、出てきたものをキュレーションしてください。
- **数百万トリプル向けではありません。** すべてメモリ上で、走査は線形です。スイートスポットは数百〜数千の範囲 — キュレーションされたグラフが成立しうる規模です。

## 例

- [`examples/freebase_sample.yaml`](https://github.com/RyutoYoda/trikedb/blob/main/examples/freebase_sample.yaml) — **実データ**: Freebase 知識グラフからの約600件の事実（CC BY、WebQSP ベンチマークのサブグラフから抽出）。2Pac、アガサ・クリスティ、ニコラ・テスラなど。ノードの型は述語のドメインから推論されています。ライブデモの中身です。
- [`examples/freebase_workspace.yaml`](https://github.com/RyutoYoda/trikedb/blob/main/examples/freebase_workspace.yaml) — 同じ事実を6つのドメイングラフ（映画 / 音楽 / 書籍 / 人物 / 場所 / その他）に分け、**ワークスペース**として統合し直したもの: 各メンバーがフィルタチップ付きの島として描画されます。ワークスペースのデモの中身です。
- [`examples/acme_pipeline.yaml`](https://github.com/RyutoYoda/trikedb/blob/main/examples/acme_pipeline.yaml) — 架空のデータ基盤で運用上の慣習を示したもの: オントロジー、廃止、変更イベント。
- [`examples/python_ecosystem.yaml`](https://github.com/RyutoYoda/trikedb/blob/main/examples/python_ecosystem.yaml) — 自由形式の述語、オントロジーなし。
- [`examples/trikedb_quickstart.ipynb`](https://github.com/RyutoYoda/trikedb/blob/main/examples/trikedb_quickstart.ipynb) — インラインのグラフで動く、実行可能なノートブック版クイックスタート。

**ライブデモ:** https://ryutoyoda.github.io/trikedb/ · **ワークスペースのデモ:** https://ryutoyoda.github.io/trikedb/workspace.html

エクスポートされる HTML は単なる絵ではなく小さなワークベンチです: ノードをクリックすると全プロパティを載せた右パネルが出て（URL はリンクになります）、右上でノードを検索でき、**SPARQL コンソール**を開けばブラウザ内で本物の SPARQL 1.1 を実行できます — WASM にコンパイルされた [Oxigraph](https://github.com/oxigraph/oxigraph) が、初回利用時に CDN から読み込まれます。変更イベントは赤い菱形として描画され、下部にタイムラインバーが付きます。初期レイアウトはグラフの形に適応します（`--layout flow|free|auto`）。ノード型のチェックボックスで表示を絞り込めます（**全選択 / 全解除**のショートカット付き）— 型が増えると凡例は横スクロールします — ワークスペースならメンバーグラフも同じように切り替えられます。

## ベンチマーク

[WebQSP](https://aclanthology.org/P16-2033/)（知識グラフQA）で、同じローカルモデルが**単体では 42.7%、trikedb のグラフを文脈として与えると 77.7%** 正解します — テスト分割の300問に対する Hits@1、+35ポイントの差、対応のある McNemar 検定で p = 9e-20。検索はそのうち 89.3% でモデルの目の前に正解を置いており、1問あたり 0.59 秒です。スクリプト、精度対レイテンシのトレードオフ、そして誠実な採点感度の分析は [`benchmarks/`](https://github.com/RyutoYoda/trikedb/blob/main/benchmarks/README_jp.md) にあります。

## ドキュメント

- [docs/REFERENCE_jp.md](https://github.com/RyutoYoda/trikedb/blob/main/docs/REFERENCE_jp.md) — 全機能と使い方（CLI、Python API、MCP、serve、エクストラ）· [English](https://github.com/RyutoYoda/trikedb/blob/main/docs/REFERENCE.md)
- [docs/ARCHITECTURE.md](https://github.com/RyutoYoda/trikedb/blob/main/docs/ARCHITECTURE_jp.md) — レイヤー構成と、新しいコードをどこに置くか
- [docs/SCALING.md](https://github.com/RyutoYoda/trikedb/blob/main/docs/SCALING.md) — 1k/10k/100k トリプルでの測定された限界と、ファイル全体読み込みから配信されるグラフに移る時期
- [benchmarks/](https://github.com/RyutoYoda/trikedb/blob/main/benchmarks/README_jp.md) — WebQSP の手法と結果

## 開発

[uv](https://docs.astral.sh/uv/) を使います:

```bash
uv sync --extra dev
uv run pytest
```

## ライセンス

MIT

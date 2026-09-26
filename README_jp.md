<p align="center">
  <a href="https://github.com/RyutoYoda/trikedb/blob/main/README.md">English</a>
  &nbsp;·&nbsp; <b>日本語</b>
  &nbsp;·&nbsp; <a href="https://github.com/RyutoYoda/trikedb/blob/main/README_zh.md">简体中文</a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/RyutoYoda/trikedb/main/docs/logo.png" width="260" alt="TrikeDB — ナレッジグラフをフリルに載せたトリケラトプス">
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

**エージェントが読めるナレッジグラフを、差分が読める1ファイルに。**

エージェントはコードなら読める。読めないのは、コードに書かれていないほうだ
——どのジョブがどのテーブルを作るのか、誰が持ち主なのか、よく似た2つの
サービスのどちらが生きているのか。だから推測する。そして出てくるのは、
それらしい名前の、存在しないものだ。

trikedb はそれを書き留めておく場所。YAML 1ファイルを、それが説明している
コードの隣、同じリポジトリに置く:

```yaml
triples:
  - {s: salesflow-crm, p: PROVIDES, o: crm-sync-job}
  - {s: crm-sync-job, p: INGESTS_TO, o: RAW_CRM_CONTACTS, schedule: hourly}
  - {s: LEGACY_DUMP, p: MIGRATED_TO, o: RAW_CRM_CONTACTS, deprecated: true}
```

このファイル**が**データベース。サーバーもデーモンもデプロイも要らない。
git で普通に差分が出て、人間が読めて、エージェントは本物の
[SPARQL 1.1](https://www.w3.org/TR/sparql11-query/) で問い合わせられる
——自前のサブセットではなく [Oxigraph](https://github.com/oxigraph/oxigraph)
が実行する——か、単にファイルを開いて読めばいい。

<p align="center">
  <a href="https://ryutoyoda.github.io/trikedb/workspace.html">
    <img src="https://raw.githubusercontent.com/RyutoYoda/trikedb/main/docs/screenshot.png" alt="trikedb の HTML ワークベンチ — 600件の Freebase 事実をクラスタ表示し、ノード詳細パネルを開いたところ" />
  </a>
</p>

<p align="center">
  <b>ライブデモ</b> —
  <a href="https://ryutoyoda.github.io/trikedb/">会社を5つのグラフで表したもの</a>
  &nbsp;·&nbsp; <a href="https://ryutoyoda.github.io/trikedb/pipeline.html">アクションログ付きのデータ基盤</a>
  &nbsp;·&nbsp; <a href="https://ryutoyoda.github.io/trikedb/workspace.html">実データ600件・フィルタ可能・ブラウザ内 SPARQL コンソール付き</a>
</p>

## インストール

```bash
pip install trikedb          # library + CLI
pip install 'trikedb[mcp]'   # + MCP server, so an agent can use it
pip install 'trikedb[all]'   # + serve, OAuth, SHACL, OWL, semantic search, S3/warehouse graphs
```

オプション機能はすべて extra なので、コアは PyYAML + rdflib + pyoxigraph のまま。
全一覧は[リファレンス](https://github.com/RyutoYoda/trikedb/blob/main/docs/REFERENCE_jp.md)にある。

## まず3つの事実から

スキーマもモデリング会議も要らない。事実を書いて、見る:

```python
from trikedb import TrikeDB

db = TrikeDB("graph.yaml")               # ファイルは最初の書き込みで作られる
db.add("salesflow-crm", "PROVIDES", "crm-sync-job")
db.add("crm-sync-job", "INGESTS_TO", "RAW_CRM_CONTACTS", schedule="hourly")
db.set_node("RAW_CRM_CONTACTS", type="table", pii=True)

db.query(["?vendor PROVIDES ?job", "?job INGESTS_TO ?table"])
db.to_html("graph.html")                 # チームに渡せるクリック可能なページ
```

空のリポジトリからなら、Python を1行も書かずに:

```bash
trikedb init graph.yaml --template agent-memory   # 形のある初期グラフを書き出す
trikedb add graph.yaml salesflow-crm PROVIDES crm-sync-job
trikedb query graph.yaml -w "?vendor PROVIDES ?job"
trikedb ui graph.yaml                             # ブラウザで開く
```

## 実際に使うのはこの4つ

他にもあるが、役に立っているグラフはたいていこの4つで組み上がっている:

| | |
|---|---|
| `db.add(s, p, o, **attrs)` | 事実を書く。キーワード引数はすべてエッジ属性になる。揃えておく価値があるのは `prov=` で、どの事実もどこから来たか辿れるようになる |
| `db.act(s, p, o, by=…, state=…)` | **起きたこと**を記録する。時刻が打たれ、ノードの履歴に追記され、そのアクションが残した状態へノードが移る |
| `db.find(question, where=…)` | エージェントが欲しい検索。意味で広く拾ってから、プロパティの厳密一致で絞る |
| `db.sparql(query)` | パターンでは足りないときの、本物のクエリ言語 |

残り——推論、SHACL、ワークスペース、S3 やウェアハウス保存、HTTP サーバー——は
必要になったときそこにあり、それまでは何のコストにもならない。
[リファレンス](https://github.com/RyutoYoda/trikedb/blob/main/docs/REFERENCE_jp.md)参照。

## それから、締める

読む価値のあるグラフは、ゴミが混ざらないグラフだけだ。何を言ってよいかを
宣言すれば、すべての書き込み経路——自分、CLI、エージェント——が同じ規則に従う。
形の検査はノードの型が分かっているところで、どちらの向きにも効く:

```python
db = TrikeDB("graph.yaml", ontology={
    "PROVIDES":   "SaaS vendor -> ingestion job",
    "INGESTS_TO": {"description": "ingestion job -> warehouse table",
                   "domain": "job", "range": "table"},
})

db.set_node("crm-sync-job", type="job")
db.set_node("RAW_CRM_CONTACTS", type="table")

db.add("crm-sync-job", "OWNS", "anything")                # OntologyError: 未宣言の述語
db.add("RAW_CRM_CONTACTS", "INGESTS_TO", "crm-sync-job")  # OntologyError: 向きが逆
```

アクションは**いつ実行してよいか**と**誰が署名できるか**も宣言できる——型検査
では届かないほうの半分だ。出荷される前に配達された注文は、どの型にも違反しない。
誰にも承認されていない価格変更は、型としては正しい。ここではどちらも拒否される:

```python
db.declare_link("DELIVERED_TO", domain="order", range="region",
                requires="SHIPPED_FROM",   # これが先に起きている必要がある
                by="courier")              # そしてこれが実行してよい者

db.act("ORD-25101", "DELIVERED_TO", "Riverside", by="Kai")   # OntologyError: 未出荷
```

## エージェントに渡す

グラフを MCP サーバーとして登録すると、エージェントは16個のツールを得る——
読み取りが `sparql` / `match` / `search` / `find` / `get_node` / `history` / `ontology` / `stats`、
書き込みが `add_triple` / `act` / `set_node` / `remove_triples` / `import_source`、
そして語彙を当て推量せずに文書を事実に変えるための
`extraction_prompt` / `preview_triples` / `add_triples`:

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

書き込みは YAML に自動保存されるので、エージェントの貢献はレビュー可能な git 差分
として届き、でっち上げようとした述語はオントロジーが弾く。これが「とりあえず
ドキュメントを全部投げ込む」への答えになる——**抽出するのはエージェント、
trikedb は検証された書き込み経路**。抽出は柔軟なまま、語彙は固い。

MCP クライアントが無い? なら統合はエージェントのプロジェクト指示の1行で済む
——*「パイプラインに触る作業の前に `graph.yaml` を読むこと」*——あとはファイルが働く。

## 文書を放り込む

モデルはもう持っているはずだ。trikedb はプロンプトを書き、返ってきた答えを裁く。
あいだの呼び出しはあなたのもので、だから SDK を入れる必要も鍵を預ける必要もない。
プロンプトは**書き込み先のグラフそのものから**組まれる——宣言済みの述語と、すでに
ある ノード名。だからモデルは `WORKS_AT` の横に `EMPLOYED_BY` をでっち上げないし、
ファイルにすでにいる会社にもう一つノードを開いたりしない:

```python
rows = db.extract(open("press-release.md").read(), llm=my_model)

for f in db.preview(rows):          # まだ何も書かれていない
    print(f["verdict"], f["triple"], f["detail"])

# new       Acme BASED_IN Osaka
# new       Sato WORKS_AT Acme
# conflict  Tanaka WORKS_AT Globex
#           └ WORKS_AT is declared functional and Tanaka already holds 'Acme'
```

`llm` はプロンプトを受け取ってテキストを返すだけの callable——使っている SDK を
3行で包めば済む。5つの実例が
[examples/extract_providers.py](https://github.com/RyutoYoda/trikedb/blob/main/examples/extract_providers.py)
にある。

API を使わず、あいだに人やチャット窓を挟んで、シェルから二つに分けてもいい:

```bash
trikedb extract graph.yaml report.docx > prompt.txt # どこに貼ってもいい
trikedb import graph.yaml answer.md --dry-run       # 何が起きるか
trikedb import graph.yaml answer.md                 # 何が起きたか
```

Word ファイルはそのまま入る: `.docx` の正体は XML を収めた zip なので、読むのに
依存は要らない。Google ドキュメントは Markdown で直接書き出せる
(ファイル → ダウンロード → Markdown)ので、そちらは元から読める。

`--dry-run` はそれ単体で価値があり、どのソースにも効く——CSV でも Markdown でも
別のグラフでも。各行が `new` / `same` / `update` / `rejected` / `conflict` のどれかと
その理由つきで返り、読み終わるまで何も書かれない。`conflict` は当て推量ではない:
`functional` と宣言された述語は主語ごとに目的語を一つしか持てないので、二つ目は
グラフが証明できる矛盾になる。

制約つきプロンプトは実際どれくらい効くのか? 回して確かめてほしい——題材も模範解答も
採点器も、比較用の無制約ベースラインも
[evals/](https://github.com/RyutoYoda/trikedb/tree/main/evals) にある。
スコアはコミットしていない。コミットされたスコアは、あるモデルのある日の数字に
しかならないからだ。

## 何を入れているか

- **エージェントにとっての、システムの記憶。** どのウェアハウスロールが何を読めるか、
  どの取り込みジョブが生きているか、変更はどのリポジトリでやるべきか。どれもコード
  には書いておらず、どれもエージェントが間違えるところだ。
- **サービスと持ち主の地図。** 誰が誰を呼ぶか、誰がオンコールか、似た名前の3つの
  サービスのどれが非推奨か。
- **前提条件つきの意思決定・障害ログ。** `act()` と `requires` があれば、承認されて
  いないものに「デプロイ済み」は記録できない——レビューのチェックリストではなく、
  書き込み時に強制される。
- **データガバナンス台帳。** PII を含むテーブル、アクセスしてよい者、保持期間。
  `by:` と `requires:` は、プルリクエストで差分が読める権限モデルそのものだ。

共通しているのは、誰かが意図して手入れした数百〜数千件という規模。グラフが成立し、
かつ信頼する価値がある大きさはそこにある。

## Markdown ファイルではだめなのか

Markdown は不正な書き込みを拒否できないし、そこへ書くエージェントも拒否できない
からだ。ここでは誰が書いても同じ検査を通る——述語が宣言されているか、向きが正しいか、
前提が満たされているか。そして構造化されていれば、grep では答えられない問いが出せる:
このテーブルから2ホップにあるもの全部、持ち主のいない PII カラム全部、3月から何が変わったか。

モデルの正答率にも測れる差が出る。[WebQSP](https://aclanthology.org/P16-2033/)
（ナレッジグラフQA）で、同じローカルモデルが**単体で 42.7%、trikedb のグラフを
文脈として与えると 77.7%**——300問の Hits@1、対応ありマクネマー検定 p = 9e-20、
1問あたり 0.59 秒。手法・注意点・スコアの感度分析は
[`benchmarks/`](https://github.com/RyutoYoda/trikedb/tree/main/benchmarks) に。

## trikedb ではないもの

- **抽出パイプラインではない。** モデルを呼ばないし、鍵も預からないし、PDF も読まない。
  やるのは、あなたのオントロジーからプロンプトを書くことと、書き込みの前に全行を
  それに照らして裁くこと。モデルも判断もあなたのものだ。抽出したグラフは
  ハルシネーションを受け継ぐ。こちらは、それが着地する前に見えるようにする側だ。
- **数百万トリプル向けではない。** すべてメモリ上にあり、走査は線形。数百〜数千が、
  手入れされたグラフが成立する範囲。
- **自前の SPARQL エンジンではない。** 読み取りは Oxigraph、更新と OWL/SHACL は
  rdflib が実行する。後から本格的なトリプルストアへ移るのは書き直しではなく export。
- **Obsidian の代わりではない。** 人間のためのノートが欲しいならそちら。これは
  機械が間違えては困る事実のためのものだ。

## 次に読むもの

- [docs/REFERENCE_jp.md](https://github.com/RyutoYoda/trikedb/blob/main/docs/REFERENCE_jp.md) — 全機能、ファイル形式、互換性と安全性の契約 · [English](https://github.com/RyutoYoda/trikedb/blob/main/docs/REFERENCE.md) · [简体中文](https://github.com/RyutoYoda/trikedb/blob/main/docs/REFERENCE_zh.md)
- [docs/ARCHITECTURE_jp.md](https://github.com/RyutoYoda/trikedb/blob/main/docs/ARCHITECTURE_jp.md) — レイヤ構成と、新しいコードをどこに置くか
- [docs/SCALING.md](https://github.com/RyutoYoda/trikedb/blob/main/docs/SCALING.md) — 1k / 10k / 100k トリプルでの実測限界
- [examples/](https://github.com/RyutoYoda/trikedb/tree/main/examples) — デモの裏にあるグラフと、[実行できるノートブック](https://github.com/RyutoYoda/trikedb/blob/main/examples/trikedb_quickstart.ipynb)
- [evals/](https://github.com/RyutoYoda/trikedb/tree/main/evals) — 抽出の題材・採点器・比較用ベースライン
- [CONTRIBUTING.md](https://github.com/RyutoYoda/trikedb/blob/main/CONTRIBUTING.md) — テストの回し方と、良いプルリクエストの形

## ライセンス

MIT. Copyright (c) 2026 Ryuto Yoda.

### 同梱データ

同梱してある第三者データセットは1つ、してないものが1つある:

- **Freebase** — `examples/freebase_*.yaml` は Freebase ダンプからの小さな抜粋で、
  [CC BY 2.5](https://creativecommons.org/licenses/by/2.5/) ライセンス。デモページを
  元データから作り直せるように、リポジトリに入れてある。
- **WebQSP** — ベンチマークの質問と正解は
  [The Value of Semantic Parse Labeling for KBQA](https://aclanthology.org/P16-2033/)
  (Yih et al., 2016) より、`rmanluo/RoG-webqsp` の再配布版を経由して使っている。
  データセットの中身はここには置いていない。`benchmarks/webqsp_bench.py prepare` が
  実行時にテストスプリットをダウンロードする。リポジトリにあるのは
  `benchmarks/*_data.json` — 上の数字とグラフが読んでいる採点結果のほうだ。

どちらも trikedb を使うのに必要ではない。

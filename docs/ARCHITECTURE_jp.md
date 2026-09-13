<b>日本語</b> · [English](ARCHITECTURE.md) · [日本語](ARCHITECTURE_jp.md) · [简体中文](ARCHITECTURE_zh.md)

# アーキテクチャ

1グラフは1つのYAMLまたはJSON文書です。ストレージはバイト列とversion token、コアは事実とメタデータ、アダプターはPython・CLI・MCP・HTTPを担当します。小さな組み込みグラフライブラリで、トランザクション付きRDF datasetサーバーではありません。

```mermaid
flowchart TB
    LA["<b>層1</b><br/>インターフェース — 書き込み"]
    LG[" "]
    LB["<b>層2</b><br/>コア — ちょうど1つ"]
    LC["<b>層3</b><br/>ストレージ — 1つを選ぶ"]
    LD["<b>層4</b><br/>投影 — 保存しない"]
    LE["<b>層1</b><br/>インターフェース — 読み取り"]
    LA ~~~ LG ~~~ LB ~~~ LC ~~~ LD ~~~ LE

    WA("エージェント<br/>MCP")
    WC("アプリ<br/>REST · Python")
    WI("一括import<br/>CSV · Markdown · YAML")
    WP("プログラム<br/>SPARQL UPDATE")
    G{{"宣言・書き込みガード<br/>語彙 · domain → range · requires · by<br/>型変更は既存edgeを再検査 · batchは原子的に確定"}}
    C("<b>1つの文書</b><br/>triples · nodes · 述語の宣言")
    subgraph pick["グラフはこのうち1つに存在 — 2つには存在しない"]
        direction LR
        SF("ファイル<br/>graph.yaml · graph.json")
        SO("オブジェクト<br/>s3:// · gs:// · az://")
        SW("テーブル行<br/>snowflake:// · bigquery://")
    end
    PO("oxigraph<br/>すべてのread query")
    PR("rdflib.Graph<br/>更新 · owlrl · pyshacl · export")
    PN("networkx<br/>グラフアルゴリズム")
    PV("SQL view<br/>warehouse rowの上")
    PD("エンジンなし<br/>JSON-LD · ページ内の文書")
    Q("クエリ・検索<br/>導出されるview · 保存しない")
    QE("厳密検索<br/>SPARQL · pattern query")
    QS("意味検索<br/>クエリ時に遅延embedding<br/>文単位でcache")
    QF("find<br/>意味でrecall → 構造でfilter")
    RQ("agent MCP · CLI · REST · Python · HTML<br/>グラフを読むすべての入口")
    RG("プログラム<br/>Python")
    RS("SQL<br/>BI · dbt · notebook")

    WA --> G
    WC --> G
    WI --> G
    WP --> G
    G --> C
    C <--> SF
    C <--> SO
    C <--> SW
    SF ~~~ PO
    SF ~~~ PR
    SO ~~~ PN
    SW -.-> PV
    SW ~~~ PD
    C -.-> PO
    C -.-> PR
    C -.-> PN
    C -.-> PD
    C -.-> Q
    Q --> QE
    Q --> QS
    Q --> QF
    QE --> RQ
    QS --> RQ
    QF --> RQ
    PO --> RQ
    PR --> RQ
    PN --> RG
    PV --> RS
    PD --> RQ

    style pick fill:none,stroke:#9aa4b3,stroke-width:1px,stroke-dasharray:4 6,color:#8d97a6
    classDef lbl fill:none,stroke:none,color:#4b5563
    classDef iface fill:#eef1f6,stroke:#8d9aad,color:#1f2937,rx:10,ry:10
    classDef core fill:#fbf1d8,stroke:#b07d17,color:#5a4409,rx:10,ry:10
    classDef store fill:#e3f3f4,stroke:#2b8a9c,color:#0c454f,rx:10,ry:10
    classDef proj fill:#efe9fb,stroke:#8055e6,color:#3a2568,rx:10,ry:10
    class LA,LG,LB,LC,LD,LE lbl
    class WA,WC,WI,WP,RQ,RG,RS iface
    class C,G core
    class SF,SO,SW store
    class PO,PR,PN,PV,PD,Q,QE,QS,QF proj
```

図は上から下へ読みます。コアは1つの文書、ストレージは選んだ保存先1つ、
投影は追加コピーではなく導出されたviewです。実際に文書を運ぶ矢印は実線、
必要なときだけ作るものは点線です。ガードは対応するAPI書き込みを守りますが、
手編集ファイルとrawな`load`/`save`は文書の形だけを検証します。

## データと投影

`Triple`はs/p/o・edge属性・任意の`rdf_terms`を保存します。既存文書は従来どおり、名前を`urn:trikedb:`配下のIRIにし（http/https/urnは絶対値）、空白入りobjectはliteralにします。明示RDF termはIRI・blank node・literalのdatatype/languageを保持します。空白入りエンティティ名にはobjectを明示IRIにしてください。

`_statements()`がRDF投影を定義し、rdflib・Oxigraph・JSON-LDが共有します。node属性はliteral、edge属性は生成blank nodeのstatementに付きます。合成メタデータはUPDATE WHEREで読めますが、SPARQLでは削除できません。NetworkXとSQL viewは文書から独立に文字列表現のproperty graphを作り、無損失RDF datasetではありません。KG_NODEはメタデータだけのnodeと全edge端点を含みます。

## 更新と失敗

ontologyが空でない場合、add・import・SPARQL INSERTは述語を検査します。HTTP(S)の絶対述語はRDF/OWL語彙用の例外です。手編集やload/saveはホワイトリストを強制せず、loadは文書の形を検証します。reloadは保存文書からontologyを再構築します。

APIが返すTriple・属性は独立したコピーです。変更はAPIを通してキャッシュを無効化してください。nodes_meta・ontology・内部フィールドの直接変更はキャッシュ整合性のある更新として未対応です。batchは本体や最終saveの失敗時に事実・属性・ontologyを戻し、入れ子にも対応します。分散トランザクションではなく、内部で明示saveした内容や外部副作用は取り消せません。

## 永続化と競合

ローカルsaveは同じディレクトリの一時ファイルをwrite/fsync後にreplaceします。既存権限とsymlink先を保ち、新規ファイルは0600です。replace前の失敗では旧内容を保持します。ディレクトリfsyncを含む停電耐性や複数プロセスCASの保証はなく、別ローカルwriterはlast-write-winsです。

S3は条件付き単一PUT（ETag/If-Matchまたは存在しない場合の作成）、SQLはversion条件と更新行数を使います。成功したwrite自身のcommit tokenを返し、保存後HEADで別writerのtokenを採用しません。S3の条件付きmultipartは未対応。他のfsspec backendにはCAS保証がありません。

1つのserve内のREST/MCPは同じTrikeDBを共有し、再入可能lockで操作を直列化します。MCPは条件付き保存の競合時にreloadして操作を再適用します。別プロセスはメモリを共有しません。Python呼出側は自分で同期し、外部編集はreloadしてください。read_onlyは公開APIを保護し、任意のPythonメモリ操作までは制限しません。

## モジュールと層

`model` は「事実とは何か」。`rules` / `rdf` / `reasoning` が文書の意味を、`storage` / `persistence` が入出力を、`audit` が出来上がった文書の読み取りを担当します。`db` はそれらを束ねたストア — メソッドは各モジュールへの委譲で、モジュール側はストアを第一引数で受け取り、`db` を import し返しません。`html` / `importers` / `embeddings` はコアの**上**に置いています: グラフが、それを描くページや、そこから組み立てられるファイル形式や、入っているとは限らない埋め込みモデルに依存してはいけないからです。`cli` / `mcp_server` / `serve` がその上の入口です。

import は上の層から厳密に下の層へ、一方向だけ。関数内 import は任意アダプタを任意のままにする手段なので依存には数えません（`db.to_html()` は呼ばれたときに `html` を import します）。`tests/test_architecture.py` が層を宣言し、コードが合わなくなればビルドが落ちます — 層を決めずに新しいモジュールを足した場合も含めて。**宣言し、それを強制する**、このライブラリがオントロジーについて主張しているのと同じことを、リポジトリ自身にも適用しています。

## クエリと対応範囲

SELECT/ASKは通常Oxigraph、CONSTRUCT/DESCRIBE・fallback・更新・OWL/SHACLはrdflibです。pattern queryは独自のマッチングです。SPARQLの曖昧な先頭はパーサーで判定し、PREFIXやコメントにも対応します。

`search()`は意味検索の投影です。現在のtripleとnode属性を文にし、クエリされたときだけembeddingを遅延生成し、グラフ文書の外に文単位の交換可能なcacheとして保持します。`find()`は広い意味検索のrecallと厳密な構造filterを組み合わせます。どちらも保存された事実を変更しません。

更新は単一default graphのINSERT/DELETEとCLEAR/DROP DEFAULTに対応します。named graph更新、WITH/USING、LOAD/CREATE/COPY/MOVE/ADDは保存前に拒否します。合成メタデータの削除には属性APIを使ってください。SPARQLの戻り値は文字列で、型付きresults protocolではありません。型付きRDFはto_rdflib/to_jsonldで取得できます。

API更新後はクエリキャッシュを再構築します。意味検索は文ごとにembeddingをキャッシュし、変更分を再計算します。保存は文書全体を書き直します。過去の速度図は記録当時の版・環境の観測で、現行版の速度保証ではありません。

## HTMLと検証

配布物はHTML1個ですがvis-networkとOxigraph WASMをCDNから取得するため、完全オフラインではありません。グラフはscript-safe JSONと文脈別DOMエスケープで出力します。描画内部は数値ID、表示は元の名前を使い、特殊名との衝突を避けます。非有限数は文字列として表示します。

tests/test_review_regressions.pyは監査での不具合とRDF・保存境界、tests/browser_smoke.pyは通常・悪意ある入力を新規ブラウザで検証します。公開前の検証はsdistと依存下限も対象にします。fake storageテストはプロトコルの検証で、実クラウド耐久性の証明ではありません。[API](REFERENCE_jp.md)と[測定条件](../benchmarks/README_jp.md)も参照してください。

### 書き込みガードが通すもの・弾くもの

ガードは自然文をLLMが読んで「もっともらしいか」を推測するものではなく、宣言に
基づく書き込み検証です。宣言は説明だけ（許可する語彙）にも、`domain`・`range`・
`requires`・`by`を持つルール（強制する制約）にもできます。事実と宣言は同じ文書と
diffに入ります。

```yaml
ontology:
  SHIPPED_FROM: {domain: order, range: warehouse}
  DELIVERED_TO:
    domain: order
    range: region
    requires: SHIPPED_FROM
    by: courier
```

```python
db.add("ORD-1", "SHIPPED_FROM", "WH-1")       # 型が合えば通る
db.add("ORD-1", "DELIVERED_TO", "Tokyo",       # byがなく弾く
       at="2026-09-14")
db.act("ORD-1", "DELIVERED_TO", "Tokyo",        # shipping後なら通る
       by="Courier-7", at="2026-09-14")
db.add("ORD-1", "DELIVER_TO", "Tokyo")          # 未宣言なので弾く
```

未宣言の述語は保存前に拒否します。端点の型が分かっていれば、逆向き・不適合な
edgeも拒否します。`by`は実行者を必須にし、分かっている型も検査します。`requires`
は時刻と、actionのどちらかの端点に必要な過去の事実を要求します。
`?order PLACED_BY ?s` と `?order CONTAINS ?o` のような複数段の前提も厳密に照合します。
形式が壊れた`requires`は、実行時ではなく宣言時に弾きます。

importも同じ`add()`経路を通ります。`batch()`や一括import中に後から証拠が届き得る
前提は保留し、batch終了時に再検査します。それでも失敗すれば全体をrollbackします。
`set_node()`で後から型を付けた場合も既存edgeを再検査します。まだ型が不明なら推測で
拒否せず、`audit()`が未解決として報告します。

境界も意図的です。APIの`add`・`act`、import、対応するSPARQL insertは該当する検証を
強制します。一方、手編集YAMLとrawな`load()` / `save()`は形と構文だけを検証し、
述語ホワイトリストは実行しません。

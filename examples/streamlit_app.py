"""A curation UI for a trikedb graph, aimed at people who do not write code.

trikedb ships no write UI on purpose: what a curation screen should look
like depends on who is curating. This is the recipe, not a product — copy it
and change the wording to match your graph and your colleagues.

Two things here are worth copying:

1. **There is no validation code.** Every write goes through the same
   ontology guard the CLI and the MCP server go through, so an undeclared
   predicate, an edge written backwards, and an action whose precondition
   never happened all come back as OntologyError and the form just prints it.
   The library is the form validation.

2. **The examples come out of the graph itself.** Rather than teaching
   somebody the words "subject" and "predicate", the form shows three
   sentences already in their graph and lets them copy the shape. A graph
   that is already curated teaches its own vocabulary.

Run it:

    uv run --with streamlit --with 'trikedb[all]' \
        streamlit run examples/streamlit_app.py

Point it at your own graph with TRIKEDB_GRAPH — a path, or any URL trikedb
stores a graph at. The screen is the same either way; only the last section
differs, because where the graph lives decides where review happens:

* **A file in a git repo** — `TRIKEDB_GRAPH=ontology/graph.yaml`. What you
  wrote shows up as a diff and you commit it, so review is a pull request
  and nothing is true until somebody approves it.

* **A row in a warehouse** — `TRIKEDB_GRAPH=snowflake://DB.SCHEMA.T/sales/crm`.
  There is no working tree here, so this screen cannot offer a commit and
  does not pretend to: writes are live the moment the guard accepts them,
  and the last section just shows what you changed. Review moves out of the
  screen — see `examples/export_to_git.py`, which turns a day of writing
  into one pull request. That is the trade: people who will never open git
  get a write surface, and the graph still ends up reviewed, later.

Running inside Streamlit in Snowflake, the warehouse connection is the
session you are already in — no token, no network rule, no secret. The graph
is reached with the same URL and access control is the grants on the table.

On pushing (the file case): run this on your own machine and `git push` uses
the git credentials you already have — there is no token to implement. You
only need a bot account and a personal access token if you *deploy* this
somewhere, and at that point the question stops being "how do I push" and
becomes "whose name is on the commit", which is worth answering deliberately.
If you do deploy it, bind it to localhost or put it behind auth: this page
writes.
"""

import difflib
import os
import subprocess
from pathlib import Path

import streamlit as st

from trikedb import OntologyError, TrikeDB
from trikedb import storage

TARGET = os.environ.get("TRIKEDB_GRAPH", "examples/acme_pipeline.yaml")

#: A URL means the graph is a row in a warehouse or an object in a bucket.
#: The only thing that follows from it here is that there is no working tree
#: to diff and no file to commit, so the review section changes. Everything
#: above it — the form, the guard, the examples — is identical.
IS_URL = "://" in TARGET
GRAPH = None if IS_URL else Path(TARGET)
LABEL = TARGET.rsplit("/", 1)[-1] or TARGET

NEW = ""            # stable sentinels, so switching language cannot invalidate
NEW_TYPE = "\x00+"  # a selectbox that is holding the old language's label

# A form, not a dashboard: a fixed, centred column that cannot outgrow the
# window beats one that stretches to whatever width the screen happens to be.
# "auto" collapses the sidebar in a centred layout, which hides the language
# switch behind a hamburger on arrival — so it is opened explicitly.
st.set_page_config(page_title="trikedb", page_icon="🦕", layout="centered",
                   initial_sidebar_state="expanded")


# ---------------------------------------------------------------- glossary

# **This is the part you replace.**
#
# A predicate is an identifier — INGESTS_TO is what is stored, and it stays
# that way in every language. What a reader actually needs is your words for
# it, and a graph written by an English-speaking team does not have those.
# trikedb stores exactly one description per predicate, so a second language
# lives here, next to the UI that renders it, rather than in the file.
#
# Leave a predicate out and the graph's own description is used instead, so
# you can fill this in a row at a time.
GLOSSARY = {
    "日本語": {
        "predicates": {
            "PROVIDES":    "このSaaSが、この取り込みジョブにデータを提供している",
            "INGESTS_TO":  "この取り込みジョブが、このテーブルにデータを入れている",
            "AFFECTED_BY": "このテーブルが、この変更の影響を受けた",
            "RESTARTED":   "このジョブに対して、運用担当がこれをやった",
            "SUPPLEMENTS": "このテーブルが、こちらのテーブルの欠けを埋めている",
            "MIGRATED_TO": "この古いテーブルが、こちらへ移行された",
        },
        "types": {
            "saas": "SaaS", "job": "取り込みジョブ", "table": "テーブル",
        },
    },
}


# ---------------------------------------------------------------- language

# Only the chrome is translated. Node names, predicates, their descriptions
# and the guard's own error messages come from the graph and the library —
# they are data, not decoration, so they stay as they are.
STRINGS = {
    "English": {
        "title": "Add to the knowledge graph",
        "lede": "Write down one thing that is true. You do not have to know how "
                "the file is stored — if you write something the graph does not "
                "allow, it will tell you why and nothing will be saved.",
        "triples": "facts", "nodes": "objects",
        "declared": "What you are allowed to say",
        "declared_note": "Only these relationships exist in this graph. "
                         "Anything else is refused.",
        "freeform": "Anything goes — this graph has no rules declared yet.",
        "new": "— a new object —", "none": "— not set —", "add_type": "— a new kind —",
        "type_new": "…or type a new name",
        "tab_review": "Save & share",
        "fact_help": "Two objects and how they relate. "
                     "*“This vendor provides this job.”*",
        "review_help": "The graph is one file. Everything you added is shown "
                       "below as changes — read them, then save.",
        "subject": "Object (from)", "predicate": "How they relate",
        "object": "Object (to)",
        "s_tech": "the subject", "p_tech": "the predicate", "o_tech": "the object",
        "prov": "Where did you learn this?",
        "prov_ph": "a link, a document, a person — so the next person can check",
        "extra": "Anything else worth recording",
        "extra_ph": "one per line, like:\nschedule=hourly\ndeprecated=true",
        "add_fact": "Add this fact", "record": "Record this",
        "by": "Who did it", "by_ph": "a name",
        "state": "What state does it leave it in", "state_ph": "e.g. shipped, approved",
        "state_is": "now", "history": "Recently, on this object",
        "kind": "Kind",
        "added": "Added", "recorded": "Recorded",
        "after": "only after", "by_word": "done by", "any": "anything",
        "preview": "You are about to say:",
        "pick_all": "Fill in all three boxes above.",
        "examples": "Examples already in this graph",
        "examples_note": "These are real entries. Copy one to see the shape.",
        "use": "Use this shape",
        "no_examples": "This graph is empty — you are writing the first entry.",
        "no_repo": "is not a git repository, so there is nothing to save to. "
                   "Your changes are already written to the file.",
        "clean": "Nothing to save — everything you added is already committed.",
        "msg": "Describe your changes", "commit": "Save", "commit_push": "Save & share",
        "pushed": "Shared. Your teammates will see it.",
        "committed": "Saved locally.", "failed": "failed",
        "rel_new_opt": "— a new relationship —",
        "rel_type_new": "…or type a new relationship name",
        "rel_updated": "Updated",
        "rel_edit": "Change what this relationship allows",
        "rel_save": "Save these rules",
        "rel_help": "This relationship does not exist yet. Say what it means. "
                    "The rules below are optional — they are what lets the graph "
                    "refuse a sentence written backwards. Once written, it is in "
                    "the dropdown.",
        "rel_name_help": "Letters, numbers and _ . This is the identifier that "
                         "gets stored, so pick it once and keep it.",
        "rel_desc": "Say what it means, in your own words",
        "rel_desc_ph": "e.g. this table was approved by this person",
        "rel_domain": "What kinds may be on the left",
        "rel_range": "What kinds may be on the right",
        "rel_side_help": "Leave empty to allow anything. Filling this in is what "
                         "lets the graph catch a relationship written backwards.",
        "rel_more": "Stricter conditions (optional)",
        "rel_requires": "Must have happened first",
        "rel_nothing_first": "nothing has to happen first",
        "rel_requires_help": "Only for things that happen in an order — "
                             "nothing can be delivered before it shipped.",
        "rel_by": "Only these kinds may do it",
        "rel_kinds_extra": "Other kinds, comma separated",
        "rel_restates": "A declaration is the whole shape, not a patch: anything "
                        "you leave empty is withdrawn. Existing entries are "
                        "re-checked against it, so if something already in the "
                        "graph would break the new rule, nothing is saved.",
        "more": "Add more (optional)",
        "becomes_action": "Fill in any of these and it stops being a standing "
                          "fact and becomes something that *happened*: it is "
                          "stamped with a date and appended to the history.",
        "when": "When",
        "when_ph": "today, if you leave it empty",
        "kind_help": "This is a name the graph has not seen before. Saying "
                     "what kind of object it is lets the graph catch "
                     "relationships written the wrong way round.",
        "kind_ph": "table, job, person…",
        "no_graph": "No graph at {p}. Set TRIKEDB_GRAPH, or run `trikedb init {p}` first.",
        "no_table": "The table behind {p} does not exist yet. Someone with "
                    "rights on the warehouse runs "
                    "`trikedb sql-init <url> --print` and applies the SQL.",
        "no_store": "Cannot reach {p}. This is a connection or a permission "
                    "problem, not something to fix on this screen — show "
                    "whoever set the graph up:",
        "tab_written": "What you wrote",
        "written_help": "This graph is a row in a warehouse, so there is "
                        "nothing to save — every line below is already "
                        "stored. It goes to review in one batch later, as a "
                        "pull request somebody reads.",
        "diff_before": "when you opened this page",
        "diff_now": "now",
        "nothing_yet": "You have not changed anything yet.",
        "busy": "Somebody else saved while you were writing, so nothing was "
                "written. The graph below is theirs — check it still says "
                "what you meant, then add it again.",
    },
    "日本語": {
        "title": "ナレッジグラフに書き込む",
        "lede": "「事実」をひとつ書くだけです。ファイルの中身を知っている必要はありません。"
                "このグラフで許されていないことを書こうとすると、理由を表示して、"
                "何も保存しません。",
        "triples": "事実", "nodes": "オブジェクト",
        "declared": "書いていいことの一覧",
        "declared_note": "このグラフにはこの関係しかありません。それ以外は拒否されます。",
        "freeform": "制限なし — このグラフにはまだルールが宣言されていません。",
        "new": "— 新しいオブジェクト —", "none": "— 未設定 —", "add_type": "— 新しい種類 —",
        "type_new": "…または新しい名前を入力",
        "tab_review": "保存して共有する",
        "fact_help": "オブジェクトとオブジェクトが、どう関係しているか。"
                     "*「このベンダーが、このジョブを提供している」* のような一文です。",
        "review_help": "グラフはファイル1つです。書き加えた内容が下に変更点として"
                       "出ます。目で確認してから保存してください。",
        "subject": "オブジェクト（元）", "predicate": "どう関係しているか",
        "object": "オブジェクト（先）",
        "s_tech": "主語", "p_tech": "述語", "o_tech": "目的語",
        "prov": "どこで知りましたか",
        "prov_ph": "リンク、ドキュメント、人の名前 — 次の人が裏を取れるように",
        "extra": "ほかに記録しておきたいこと",
        "extra_ph": "1行に1つ。例:\nschedule=hourly\ndeprecated=true",
        "add_fact": "この事実を追加", "record": "これを記録する",
        "by": "誰がやったか", "by_ph": "名前",
        "state": "どんな状態になったか", "state_ph": "例: 出荷済み、承認済み",
        "state_is": "現在", "history": "このオブジェクトに最近起きたこと",
        "kind": "種類",
        "added": "追加しました", "recorded": "記録しました",
        "after": "が先に必要", "by_word": "実行できるのは", "any": "なんでも",
        "preview": "いま書こうとしている内容:",
        "pick_all": "上の3つを埋めてください。",
        "examples": "このグラフに実際に入っている例",
        "examples_note": "どれも本物の記録です。真似すれば形がわかります。",
        "use": "この形を使う",
        "no_examples": "このグラフは空です — あなたが最初の1件を書きます。",
        "no_repo": "は git リポジトリではないので、共有先がありません。"
                   "変更はファイルには既に書き込まれています。",
        "clean": "保存するものはありません — 追加した内容は既に保存済みです。",
        "msg": "何を変えたか", "commit": "保存", "commit_push": "保存して共有",
        "pushed": "共有しました。チームの人から見えます。",
        "committed": "手元に保存しました。", "failed": "が失敗しました",
        "rel_new_opt": "— 新しい関係 —",
        "rel_type_new": "…または新しい関係の名前を入力",
        "rel_updated": "直しました",
        "rel_edit": "この関係で何を許すかを直す",
        "rel_save": "このルールを保存",
        "rel_help": "この関係はまだありません。どういう意味かを決めてください。"
                    "下のルールは任意です — 逆向きに書かれた文をグラフが拒否できるのは、"
                    "これがあるからです。一度つくれば、以後プルダウンに出てきます。",
        "rel_name_help": "英数字と _ 。これが実際に保存される識別子なので、"
                         "一度決めたら変えない前提で付けてください。",
        "rel_desc": "どういう意味か、あなたの言葉で",
        "rel_desc_ph": "例: このテーブルを、この人が承認した",
        "rel_domain": "左に来ていい種類",
        "rel_range": "右に来ていい種類",
        "rel_side_help": "空にすると何でも許可されます。ここを埋めておくことが、"
                         "関係が逆向きに書かれたのをグラフが捕まえられる理由です。",
        "rel_more": "さらに厳しい条件（任意）",
        "rel_requires": "先に起きていないといけないこと",
        "rel_nothing_first": "先に必要なことはない",
        "rel_requires_help": "順番のあることにだけ使います — 出荷されていないものは"
                             "配達できない、のような。",
        "rel_by": "これをやっていい人の種類",
        "rel_kinds_extra": "ほかの種類（カンマ区切り）",
        "rel_restates": "宣言は「形の全体」であって、部分的な修正ではありません。"
                        "空にした項目は取り下げられます。既にある記録は新しいルールで"
                        "検査し直されるので、いまグラフに入っているものが新ルールに"
                        "反する場合は、何も保存されません。",
        "more": "詳しく書く（任意）",
        "becomes_action": "ここを埋めると、ずっと成り立つ「事実」ではなく *起きたこと* に "
                          "なります。日付が押され、そのオブジェクトの履歴に積まれます。",
        "when": "いつ",
        "when_ph": "空なら今日",
        "kind_help": "グラフがまだ見たことのない名前です。何の種類かを言っておくと、"
                     "関係が逆向きに書かれたときにグラフが捕まえられます。",
        "kind_ph": "テーブル、ジョブ、人…",
        "no_table": "{p} の元になるテーブルがまだありません。"
                    "ウェアハウスの権限を持つ人に "
                    "`trikedb sql-init <url> --print` を実行してもらい、"
                    "出てきたSQLを流してください。",
        "no_store": "{p} に届きません。接続か権限の問題で、この画面で直せる"
                    "ものではありません。グラフを用意した人に下をそのまま"
                    "見せてください。",
        "tab_written": "いま書いたこと",
        "written_help": "このグラフはウェアハウスの行なので、保存する操作は"
                        "ありません。下に出ている分はすべて保存済みです。"
                        "あとでまとめてプルリクエストになり、そこで人が読みます。",
        "diff_before": "この画面を開いたとき",
        "diff_now": "いま",
        "nothing_yet": "まだ何も変えていません。",
        "busy": "書いている間に他の人が保存したので、今回の分は書き込まれて"
                "いません。下のグラフはその人の内容です。言いたいことが"
                "変わっていないか確かめて、もう一度追加してください。",
        "no_graph": "{p} にグラフがありません。TRIKEDB_GRAPH を設定するか、"
                    "先に `trikedb init {p}` を実行してください。",
    },
}


def t(key: str) -> str:
    return STRINGS[st.session_state.get("lang", "English")][key]


# Streamlit identifies a widget by its key alone, so when the language changes
# the boxes keep the labels they were first drawn with — the new ones are sent
# but never shown. Writing a value back marks it changed, which is what makes
# Streamlit re-send it, so on a language switch we touch every box once.
_lang = st.session_state.get("lang", "English")
if st.session_state.get("_lang_shown", _lang) != _lang:
    for _k in [k for k in st.session_state if not k.startswith("_") and k != "lang"]:
        if isinstance(st.session_state[_k], (str, list)):  # not a button
            st.session_state[_k] = st.session_state[_k]
st.session_state["_lang_shown"] = _lang

# An example button cannot write into a box that already exists on screen, so
# it parks the values here and re-runs; they are applied on the way in, before
# anything is drawn. This has to stay above every widget on the page.
for _k, _v in st.session_state.pop("_pending", {}).items():
    st.session_state[_k] = _v


# ---------------------------------------------------------------- helpers

# Streamlit re-runs this whole file on every interaction, so loading the graph
# has to be cached or every click re-parses the YAML.
@st.cache_resource
def connection():
    """The warehouse connection, when the host already holds one.

    Inside Streamlit in Snowflake the session you are running in *is* the
    credential, so there is nothing to configure: no token, no network rule,
    no secret. Anywhere else this returns None and the driver falls back to
    the SNOWFLAKE_* environment variables — which is also what a local run
    against a warehouse graph uses.
    """
    if not IS_URL:
        return None
    try:
        from snowflake.snowpark.context import get_active_session
        return get_active_session()
    except Exception:  # noqa: BLE001 - not in Snowflake, or no snowpark
        return None


def token():
    """Whatever changes when somebody else writes to the same graph.

    For a file that is the mtime; for a warehouse row it is the version token
    the store hands out, which is the same one a conditional write compares
    against. Either way it is the cache key below, so an agent, a git pull or
    a colleague on the next desk is picked up on the next rerun rather than
    quietly ignored. A warehouse read costs a round trip per rerun; a busy
    deployment would cache it for a few seconds, at the price of showing a
    slightly stale graph.
    """
    if IS_URL:
        return storage.version(TARGET, connection=connection())
    return GRAPH.stat().st_mtime if GRAPH.exists() else 0.0


@st.cache_resource
def load(target: str, _token) -> TrikeDB:
    return TrikeDB(target, connection=connection())


def db() -> TrikeDB:
    return load(TARGET, token())


def stored() -> str:
    """The document exactly as the store holds it right now.

    Empty when nothing is stored there yet, which for a warehouse row is an
    ordinary starting point rather than an error.
    """
    try:
        return storage.read_text(TARGET, connection=connection())
    except Exception:  # noqa: BLE001 - not written yet
        return ""


def git(*args: str) -> subprocess.CompletedProcess:
    """Only ever called for a file-backed graph — see the review section."""
    return subprocess.run(
        ["git", "-C", str(GRAPH.resolve().parent), *args],
        capture_output=True, text=True,
    )


def shape(p: str) -> str:
    """The rule the guard will actually enforce, in words."""
    rule = db().predicate_rules.get(p)
    if not rule:
        return ""
    def side(key: str) -> str:
        want = rule.get(key)
        return "|".join(kind_label(w) for w in sorted(want)) if want else t("any")
    out = f"{side('domain')} → {side('range')}"
    if rule.get("requires"):
        out += f"  ·  {'|'.join(sorted(rule['requires']))} {t('after')}"
    if rule.get("by"):
        out += f"  ·  {t('by_word')} {side('by')}"
    return out


def describe(p: str) -> str:
    """Your words for this predicate, else the graph's own description."""
    lang = st.session_state.get("lang", "English")
    return (GLOSSARY.get(lang, {}).get("predicates", {}).get(p)
            or db().ontology.get(p, "") or "")


def kind_label(name: str) -> str:
    """Your word for a node type, else the type as the graph spells it."""
    lang = st.session_state.get("lang", "English")
    return GLOSSARY.get(lang, {}).get("types", {}).get(name, name)


def predicate_picker(key: str) -> str:
    """Pick a declared relationship, or ask for a new one.

    The same shape as the object pickers on either side of it: what exists is
    in the list, and what does not is made on the spot. A relationship needs
    more than a name, so the fields for it are drawn full width below the row
    rather than squeezed into a third of it.
    """
    options = sorted(db().ontology)
    if not options:
        return st.text_input(t("predicate"), key=key)  # free-form graph
    picked = st.selectbox(
        t("predicate"), [NEW, *options], key=key,
        format_func=lambda x: t("rel_new_opt") if x == NEW else (describe(x) or x),
        help=t("p_tech"),
    )
    typed = st.text_input(
        f"{t('predicate')} ({key})", key=f"{key}_new", label_visibility="collapsed",
        placeholder=t("rel_type_new"), help=t("rel_name_help"),
    )
    p = typed.strip() or ("" if picked == NEW else picked)
    if p in db().ontology and shape(p):
        st.caption(shape(p))
    return p


def kinds_field(label: str, key: str, preset, help: str = "") -> list:
    """A node-type constraint: pick from the kinds the graph already uses, or
    name kinds that do not exist yet."""
    kinds = sorted({v.get("type") for v in db().nodes_meta.values() if v.get("type")})
    picked = st.multiselect(label, kinds, key=key, help=help or None,
                            default=[k for k in (preset or []) if k in kinds],
                            placeholder=t("any"), format_func=kind_label)
    typed = st.text_input(t("rel_kinds_extra"), key=f"{key}_x",
                          value=",".join(k for k in (preset or []) if k not in kinds),
                          label_visibility="collapsed",
                          placeholder=t("rel_kinds_extra"))
    return picked + [w.strip() for w in typed.split(",") if w.strip()]


def link_fields(key: str, rule: dict, desc_value: str) -> dict:
    """The rules a relationship carries, as declare_link() keyword arguments.

    Everything here is optional. Left empty a relationship simply means what
    its description says; filled in, it is what lets the graph refuse a
    sentence written backwards, or an action whose precondition never happened.
    """
    desc = st.text_input(t("rel_desc"), value=desc_value, key=f"{key}_desc",
                         placeholder=t("rel_desc_ph"))
    c1, c2 = st.columns(2)
    with c1:
        dom = kinds_field(t("rel_domain"), f"{key}_dom", rule.get("domain"),
                          t("rel_side_help"))
    with c2:
        rng = kinds_field(t("rel_range"), f"{key}_rng", rule.get("range"),
                          t("rel_side_help"))
    with st.expander(t("rel_more")):
        declared = sorted(db().ontology)
        req = st.multiselect(t("rel_requires"), declared, key=f"{key}_req",
                             default=[x for x in (rule.get("requires") or [])
                                      if x in declared],
                             help=t("rel_requires_help"),
                             placeholder=t("rel_nothing_first"),
                             format_func=lambda x: describe(x) or x)
        who = kinds_field(t("rel_by"), f"{key}_by", rule.get("by"))
    return {"description": desc or None, "domain": dom or None, "range": rng or None,
            "requires": req or None, "by": who or None}


def node_picker(label: str, key: str, help: str = "") -> str:
    """Pick something already in the graph, or type a new name."""
    picked = st.selectbox(
        label, [NEW, *sorted(db().nodes())], key=key, help=help or None,
        format_func=lambda x: t("new") if x == NEW else x,
    )
    typed = st.text_input(
        f"{label} ({key})", key=f"{key}_new", label_visibility="collapsed",
        placeholder=t("type_new"),
    )
    return typed.strip() or ("" if picked == NEW else picked)


def kind_picker(key: str, name: str) -> str:
    """Asked only for a name the graph has not seen before.

    An object's kind is the one property that does real work — it is what lets
    the guard catch a relationship written backwards — and the only moment it
    is worth interrupting somebody for is when they have just invented a name.
    Anything already in the graph has its kind already.
    """
    if not name or name in db().nodes():
        return ""
    kinds = sorted({v.get("type") for v in db().nodes_meta.values() if v.get("type")})
    kind = st.selectbox(
        t("kind"), [NEW, *kinds, NEW_TYPE], key=f"{key}_kind",
        format_func=lambda x: {NEW: t("none"), NEW_TYPE: t("add_type")}.get(
            x, kind_label(x)),
        help=t("kind_help"),
    )
    if kind == NEW_TYPE:
        kind = st.text_input(t("kind"), key=f"{key}_kind_new",
                             label_visibility="collapsed", placeholder=t("kind_ph"))
    return "" if kind in (NEW, NEW_TYPE) else kind.strip()


def attrs_from(raw: str) -> dict:
    """`key=value`, one per line."""
    out = {}
    for line in raw.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def ran(fn, ok: str) -> None:
    """Every write path is guarded, so this is the entire error handling."""
    try:
        fn()
    except OntologyError as e:
        st.error(str(e))          # "not in the ontology" / "written backwards"
    except storage.ConcurrentWriteError:
        # Two people on one graph. Nothing was written, and the copy in
        # memory is built on bytes that no longer exist — so drop it rather
        # than leave a screen showing a change the store never took.
        load.clear()
        st.warning(t("busy"))
    except Exception as e:        # noqa: BLE001 - a UI should not crash on a bad field
        st.error(f"{type(e).__name__}: {e}")
    else:
        st.success(ok)
        st.rerun()


def sentence(s: str, p: str, o: str) -> str:
    kinds = {n: db().node(n).get("type") for n in (s, o) if n in db().nodes()}
    def tag(n: str) -> str:
        return f"**{n}**" + (f" ({kind_label(kinds[n])})" if kinds.get(n) else "")
    return f"{tag(s)} &nbsp;⟶&nbsp; {tag(o)}"


def preview(s: str, p: str, o: str) -> None:
    with st.container(border=True):
        st.caption(t("preview"))
        st.markdown(sentence(s, p, o))
        if describe(p):
            st.markdown(f"**{describe(p)}**")
        st.caption(f"`{p}`")


def fill(**kv) -> None:
    """Park an example and re-run; it is applied at the top of the next run."""
    st.session_state["_pending"] = kv
    st.rerun()


def example_block(prefix: str, keep=None, object_is_text: bool = False) -> None:
    """Three real entries from this graph, as something to copy.

    The examples are not hardcoded: they are read back out of the graph, so
    they are always in the reader's own vocabulary, and a graph that has been
    curated once teaches the next person what it expects.
    """
    st.divider()
    st.caption(f"**{t('examples')}** — {t('examples_note')}")
    seen, shown = set(), 0
    for tr in db().triples():
        if tr.p in seen or (keep and not keep(tr)):
            continue
        seen.add(tr.p)
        shown += 1
        c1, c2 = st.columns([4, 1.4], vertical_alignment="center")
        if describe(tr.p):
            c1.markdown(f"**{describe(tr.p)}**")
        c1.markdown(sentence(tr.s, tr.p, tr.o))
        c1.caption(f"`{tr.p}`")
        obj = ({f"{prefix}_o": tr.o} if object_is_text
               else {f"{prefix}_o": NEW, f"{prefix}_o_new": tr.o})
        if c2.button(t("use"), key=f"{prefix}_ex_{tr.p}", width="stretch"):
            fill(**{f"{prefix}_s": NEW, f"{prefix}_s_new": tr.s,
                    f"{prefix}_p": tr.p, **obj})
        if shown == 3:
            break
    if not shown:
        st.caption(t("no_examples"))


# ---------------------------------------------------------------- sidebar

with st.sidebar:
    st.subheader("🦕 trikedb")
    st.radio("Language / 言語", list(STRINGS), key="lang", horizontal=True)

# Missing means two different things. A file that is not there is a mistake
# — you meant another path, or the graph was never created. A warehouse row
# that is not there is an ordinary empty graph, and the first person to write
# creates it; what cannot be recovered from is the *table* missing, because
# creating one in a company's warehouse is not this screen's call to make.
if IS_URL:
    try:
        storage.exists(TARGET, connection=connection())
    except Exception as exc:  # noqa: BLE001 - TableMissing, auth, network
        # Two different problems wearing one traceback: the table is not
        # there (somebody has to create it) versus we cannot reach the
        # warehouse at all (credentials, grants, network). Telling a user to
        # run sql-init when the real problem is a missing password sends
        # them to the wrong person, so the cause is named.
        if type(exc).__name__ == "TableMissing":
            st.error(t("no_table").format(p=TARGET))
        else:
            st.error(t("no_store").format(p=TARGET))
        st.code(str(exc), language=None, wrap_lines=True)
        st.stop()
elif not GRAPH.exists():
    st.error(t("no_graph").format(p=GRAPH))
    st.stop()

# Read before anything on this page can write, so "what you changed" below
# means this sitting at the screen, not the whole history of the graph.
if "baseline" not in st.session_state:
    st.session_state.baseline = stored()

with st.sidebar:
    c1, c2 = st.columns(2)
    c1.metric(t("triples"), len(db()))
    c2.metric(t("nodes"), len(db().nodes()))
    st.caption(f"`{LABEL}`")

    st.divider()
    st.caption(f"**{t('declared')}**")
    st.caption(t("declared_note"))
    if db().ontology:
        for p in sorted(db().ontology):
            st.markdown(describe(p) or f"`{p}`")
            st.caption(f"`{p}`" + (f" · {shape(p)}" if shape(p) else ""))
    else:
        st.caption(t("freeform"))

# ---------------------------------------------------------------- main

st.title(t("title"))
st.caption(t("lede"))

# ------------------------------------------------------------ the one form
#
# There is only one thing to write here: a sentence. `add()` and `act()` take
# the same three words — the difference is whether you also say *when* and
# *who*, and the form decides that from whether those boxes are filled rather
# than making somebody choose between two screens. Properties are not a fourth
# thing either: they belong to the words in the sentence, so they are asked
# for right under the word, at the moment a new name is typed.

st.markdown(t("fact_help"))

c1, c2, c3 = st.columns(3)
with c1:
    s_ = node_picker(t("subject"), "w_s", t("s_tech"))
    s_kind = kind_picker("w_s", s_)
with c2:
    p_ = predicate_picker("w_p")
with c3:
    o_ = node_picker(t("object"), "w_o", t("o_tech"))
    o_kind = kind_picker("w_o", o_)

# A relationship is the same choice as the objects beside it — take the one
# that exists, or make it here. It needs more than a name, so its fields get
# the full width under the row instead of a third of it.
p_decl = None
if p_ and p_ not in db().ontology:
    st.caption(t("rel_help"))
    p_decl = link_fields("w_p_new", {}, "")
elif p_ and p_ in db().ontology:
    # Restating a declaration replaces it whole, so editing is the same call
    # as creating — it just starts from what is already there.
    with st.expander(t("rel_edit")):
        st.caption(t("rel_restates"))
        kw = link_fields(f"w_p_edit_{p_}", db().predicate_rules.get(p_, {}),
                         db().ontology.get(p_, ""))
        if st.button(t("rel_save"), key=f"rel_save_{p_}"):
            ran(lambda: db().declare_link(p_, **kw), f"{t('rel_updated')}: {p_}")

if s_ and p_ and o_:
    preview(s_, p_, o_)
else:
    st.caption(t("pick_all"))

with st.expander(t("more")):
    prov = st.text_input(t("prov"), placeholder=t("prov_ph"), key="w_prov")
    st.caption(t("becomes_action"))
    d1, d2, d3 = st.columns(3)
    at = d1.text_input(t("when"), placeholder=t("when_ph"), key="w_at")
    by = d2.text_input(t("by"), placeholder=t("by_ph"), key="w_by")
    state = d3.text_input(t("state"), placeholder=t("state_ph"), key="w_state")
    extra = st.text_area(t("extra"), placeholder=t("extra_ph"), height=90,
                         key="w_extra")

happened = bool(at or by or state)


def write() -> None:
    """One button, because it is one sentence. The declaration and the kinds go
    in first, so the guard has something to check the sentence against."""
    if p_decl is not None:
        db().declare_link(p_, **p_decl)
    for name, kind in ((s_, s_kind), (o_, o_kind)):
        if kind:
            db().set_node(name, type=kind)
    attrs = {**({"prov": prov} if prov else {}), **attrs_from(extra)}
    if happened:
        db().act(s_, p_, o_, by=by or None, state=state or None, at=at or None,
                 **attrs)
    else:
        db().add(s_, p_, o_, **attrs)


if st.button(t("record") if happened else t("add_fact"), key="w_go",
             type="primary", disabled=not (s_ and p_ and o_)):
    ran(write, f"{t('recorded') if happened else t('added')}: {s_} {p_} {o_}")

if s_ and s_ in db().nodes() and db().history(s_):
    st.caption(f"**{t('history')}** — {t('state_is')}: `{db().state(s_) or '—'}`")
    for h in db().history(s_)[:3]:
        st.caption(f"`{h.attrs.get('at', '?')}`  {describe(h.p) or h.p} → {h.o}")

example_block("w")


# ----------------------------------------------------------- saving what you wrote
#
# Nothing else is left. Objects and relationships are both made inside the
# sentence that needs them, at the moment a name is typed, so a screen that
# offered a separate place to create either of them was offering the same
# thing twice — and two ways to do one thing is the part people freeze on.
#
# What is left is showing the person what they did, and that is where the two
# homes for a graph stop agreeing. A file in a repo has a baseline to diff
# against and a commit to make, so review fits on this screen. A warehouse row
# has neither: the write already landed. Offering a "save" button there would
# be a lie, so the section below states plainly that the work is saved and
# what will happen to it — see examples/export_to_git.py for the other half.

st.divider()
if IS_URL:
    st.subheader(t("tab_written"))
    st.markdown(t("written_help"))
    diff = "\n".join(difflib.unified_diff(
        st.session_state.baseline.splitlines(), stored().splitlines(),
        fromfile=t("diff_before"), tofile=t("diff_now"), lineterm="",
    ))
    if not diff.strip():
        st.info(t("nothing_yet"))
    else:
        st.code(diff, language="diff", wrap_lines=True)
    st.stop()

st.subheader(t("tab_review"))
st.markdown(t("review_help"))
if git("rev-parse", "--is-inside-work-tree").returncode != 0:
    st.info(f"`{GRAPH.parent}` {t('no_repo')}")
else:
    diff = git("diff", "--", str(GRAPH.resolve())).stdout
    if not diff.strip():
        st.success(t("clean"))
    else:
        st.code(diff, language="diff", wrap_lines=True)
        msg = st.text_input(t("msg"), value=f"graph: update {GRAPH.name}")
        c1, c2 = st.columns(2)
        # Explicit keys: two buttons can end up with the same label in one
        # language and not another, and Streamlit derives a button's id from
        # its label when it has no key.
        commit = c1.button(t("commit"), key="git_commit", disabled=not msg)
        push = c2.button(t("commit_push"), key="git_push", type="primary",
                         disabled=not msg)
        if commit or push:
            steps = [("add", str(GRAPH.resolve())), ("commit", "-m", msg)]
            # Locally, push uses the credentials git already has. Deployed,
            # this is where a bot account and a PAT would go instead.
            if push:
                steps.append(("push",))
            for step in steps:
                r = git(*step)
                if r.returncode != 0:
                    st.error(f"`git {step[0]}` {t('failed')}:\n\n"
                             f"```\n{r.stderr or r.stdout}\n```")
                    break
            else:
                st.success(t("pushed") if push else t("committed"))
                st.rerun()

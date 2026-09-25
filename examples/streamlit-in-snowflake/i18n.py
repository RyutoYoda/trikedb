"""English and Japanese for every word on the screen.

This is deliberately the smallest thing that works -- a dict and a lookup,
no gettext, no .po files, no build step. A curation screen has on the order
of a hundred strings, and the people who will edit them are the same people
who edit the screen.

Three decisions here are worth copying:

1. **Keys are slugs, not English text.** Keying on the English string is the
   obvious shortcut and it breaks quietly: the day somebody improves an
   English sentence, the Japanese silently disappears and English is shown
   to Japanese readers -- which looks like a translation nobody got round
   to, not like a bug.

2. **A missing key is loud, not silent.** `t()` returns the key wrapped in
   brackets rather than falling back to English, and
   `tests/test_i18n.py` fails if any key is missing a language. A silent
   fallback means an untranslated screen ships and nobody finds out until a
   reader mentions it.

3. **The choice lives in `st.session_state`, not in a module global.** A
   Streamlit server runs every session in one process, so a module-level
   "current language" is shared by everyone looking at the app: one person
   switching to Japanese switches it for everybody. Session state is
   per-viewer, which is what "my language" has to mean.

Widget `key=` values are **not** translated, anywhere. They are identifiers,
and translating them would make switching language throw away everything
already typed into the form -- which is exactly when somebody switches.
`tests/test_i18n.py` pins that too.
"""
from __future__ import annotations

from contextlib import contextmanager

import streamlit as st

#: Code -> what to show in the picker.
LANGUAGES = {"en": "English", "ja": "日本語"}

DEFAULT_LANGUAGE = "en"

#: Where the choice is stored. Same namespace as the form's widget keys, so
#: it carries the same prefix to keep them apart.
_KEY = "kg_lang"

#: Only used when there is no Streamlit runtime at all -- unit tests, or
#: importing this module from a shell. Never written by the app; `using()`
#: is the one thing that touches it. If this were the app's storage it
#: would be shared across viewers (see the docstring).
_no_runtime_default = DEFAULT_LANGUAGE


def language() -> str:
    """The current viewer's language."""
    try:
        return st.session_state.get(_KEY) or _no_runtime_default
    except Exception:  # noqa: BLE001 - no Streamlit runtime (tests, imports)
        return _no_runtime_default


@contextmanager
def using(lang: str):
    """Force a language. **For tests**, and for nothing else.

    It sets the process-wide fallback, so calling it from the app would
    change the language for every viewer at once.
    """
    global _no_runtime_default
    before = _no_runtime_default
    _no_runtime_default = lang
    try:
        yield
    finally:
        _no_runtime_default = before


def t(key: str, **fmt) -> str:
    """Look up `key` in the current language and fill in `{placeholders}`.

    An unknown key comes back as `⟦key⟧` rather than raising. A screen that
    is half-drawn because one string is missing is worse than a screen with
    one odd-looking label -- but it still has to be visible, hence the
    brackets.
    """
    entry = TEXT.get(key)
    if entry is None:
        return f"⟦{key}⟧"
    text = entry.get(language()) or entry.get(DEFAULT_LANGUAGE) or f"⟦{key}⟧"
    return text.format(**fmt) if fmt else text


def picker(container=None) -> None:
    """Draw the language switch.

    A radio rather than a selectbox: there are two options and both should
    be readable without opening anything. Each label is written in its own
    language -- somebody who cannot read the current language still has to
    be able to find their way out of it.

    Streamlit reruns the script when the radio changes, so nothing else has
    to be done to redraw the page in the new language.

    Cut `LANGUAGES` down to one entry and nothing is drawn at all -- a
    switch with one position is furniture that asks to be clicked and then
    does nothing.
    """
    codes = list(LANGUAGES)
    if len(codes) < 2:
        return
    where = container if container is not None else st
    current = language()
    where.radio(
        "Language / 言語",
        codes,
        index=codes.index(current) if current in codes else 0,
        key=_KEY,
        format_func=lambda c: LANGUAGES[c],
        horizontal=True,
        label_visibility="collapsed",
    )


# ---------------------------------------------------------------------------
# The strings. Grouped by where they appear, in roughly the order a person
# meets them.
#
# Japanese is not a word-for-word translation of the English. Some of these
# sentences explain a rule rather than name a field, and a sentence that
# explains has to sound like it was written in the language, or people stop
# reading it -- which defeats the point of having written it.
# ---------------------------------------------------------------------------

TEXT: dict[str, dict[str, str]] = {

    # ------------------------------------------------------------- the shell
    "app.title": {
        "en": "Graph curation",
        "ja": "ナレッジグラフの整備",
    },
    "side.graph": {"en": "Knowledge graph", "ja": "ナレッジグラフ"},
    "side.triples": {"en": "Triples", "ja": "トリプル"},
    "side.nodes": {"en": "Nodes", "ja": "ノード"},
    "side.predicates": {"en": "Predicates: {names} …", "ja": "述語: {names} …"},
    "side.content_hash": {
        "en": "content_hash: {value}",
        "ja": "content_hash: {value}",
    },
    "side.engine": {
        "en": "Engine: trikedb — real SPARQL and pattern queries, no egress",
        "ja": "エンジン: trikedb — SPARQL とパターン検索を外部通信なしで実行",
    },
    "side.reading_table": {
        "en": "Reading from: {table} (read only)",
        "ja": "参照元: {table}（読み取りのみ）",
    },
    "side.reading_staged": {
        "en": "Reading from: staged YAML (fallback)",
        "ja": "参照元: 同梱された YAML（フォールバック）",
    },
    "side.source_of_truth": {
        "en": "Source of truth: {repo} — the YAML in git",
        "ja": "正本: {repo} — git にある YAML",
    },
    "err.no_graph": {
        "en": "Could not load the knowledge graph. Stage the YAML files into "
              "./kg/ (see README.md) or run this from a checkout.",
        "ja": "ナレッジグラフを読み込めませんでした。YAML を ./kg/ に"
              "同梱する（README.md 参照）か、チェックアウトから起動してください。",
    },
    "warn.table_unreadable": {
        "en": "Could not read {table}, so this is running on the YAML staged "
              "with the app (a copy from deploy time): {error}",
        "ja": "{table} を読めなかったので、アプリに同梱された YAML"
              "（デプロイ時点のコピー）で動いています: {error}",
    },
    "warn.stale": {
        "en": "The table ({live}) and the YAML staged with this app "
              "({staged}) differ. Answers come from the table. The staged "
              "YAML is a copy from when this app started, so suspect that "
              "first right after a deploy — reloading the app clears it. If "
              "it persists, the table is behind and needs to be pushed again.",
        "ja": "テーブル（{live}）と同梱 YAML（{staged}）が食い違っています。"
              "表示はテーブル側の内容です。同梱 YAML はアプリ起動時点のコピー"
              "なので、デプロイ直後ならまずこちらを疑ってください（アプリを"
              "再読み込みすれば解消します）。解消しない場合はテーブルが古い"
              "ので、入れ直しが必要です。",
    },

    # ---------------------------------------------------------- the top line
    "intro.caption": {
        "en": "Propose a fact you want in the graph. **This screen does not "
              "modify the graph** — your proposal becomes a pull request "
              "against the source repository, and a person decides whether "
              "it is true before it lands.",
        "ja": "グラフに入れたい事実を提案します。**この画面はグラフを書き換え"
              "ません** — 提案は正本リポジトリへのプルリクエストになり、"
              "本当かどうかは人が見てから入ります。",
    },
    "err.no_session": {
        "en": "No Snowflake session, so nothing can be proposed (running "
              "against the bundled YAML).",
        "ja": "Snowflake のセッションが無いので提案できません"
              "（同梱 YAML で動作中）。",
    },
    "err.no_identity": {
        "en": "**Could not work out who you are.** Proposing needs a name: "
              "it decides whose proposal this is queued as, and whose "
              "credential opens the PR. Reload the page; if it keeps "
              "happening, tell whoever runs this app.",
        "ja": "**あなたが誰か判定できませんでした。** 提案には名前が要ります "
              "— 誰の提案として積むか、誰の資格でPRを出すかがそれで決まります。"
              "ページを再読み込みしてください。直らない場合はこのアプリの"
              "管理者に連絡してください。",
    },
    "err.no_identity_detail": {
        "en": "Queueing without a name leaves proposals that belong to "
              "nobody, and any token stored under that name can never be "
              "read back. That happened once, so now it stops here instead.",
        "ja": "名前が無いまま積むと、誰のものでもない提案が残り、その名前で"
              "登録したトークンは二度と読み出せなくなります。実際に起きたので、"
              "ここで止めています。",
    },

    # -------------------------------------------------- the GitHub credential
    "gh.revoked": {
        "en": "Revoked here. Remember to revoke the token on GitHub too.",
        "ja": "ここからは削除しました。GitHub 側でもトークンを失効させて"
              "ください。",
    },
    "gh.registered_as": {
        "en": "Registered as **{login}**. From now on your proposals are "
              "committed under your name.",
        "ja": "**{login}** として登録しました。これ以降、あなたの提案は"
              "あなた名義でコミットされます。",
    },
    "gh.status": {
        "en": "GitHub: **{login}** (ending `{last4}`)",
        "ja": "GitHub: **{login}**（末尾 `{last4}`）",
    },
    "gh.last_error": {
        "en": "Last write with this token failed: {error}",
        "ja": "このトークンでの直近の書き込みが失敗しています: {error}",
    },
    "gh.last_used": {"en": "Last used {when}", "ja": "最終利用 {when}"},
    "gh.none_registered": {
        "en": "**No GitHub credential registered.** You can still queue "
              "proposals, but they will not become a PR. (Nothing is lost — "
              "register below, press the button again, and they go in.)",
        "ja": "**GitHub の資格情報が未登録です。** 提案を積むことはできますが、"
              "PRにはなりません。（消えはしません — 下で登録してもう一度"
              "ボタンを押せば、そのまま載ります。）",
    },
    "gh.expander_replace": {
        "en": "Replace GitHub credential",
        "ja": "GitHub の資格情報を入れ替える",
    },
    "gh.expander_register": {
        "en": "Register GitHub credential",
        "ja": "GitHub の資格情報を登録する",
    },
    "gh.howto": {
        "en": """So that commits are yours, this stores one **GitHub personal
access token** of yours.

1. [Create a fine-grained token](https://github.com/settings/personal-access-tokens/new)
2. **Repository access** → *Only select repositories* → `{repo}` and nothing else
3. **Permissions** → *Contents: Read and write* and *Pull requests: Read and write*
4. Pick a **short expiry** (90 days, say). When it expires you will see
   "last write with this token failed" here and can swap it on this screen.

Do not use a classic token scoped to all of `repo`. What this needs is
write access to one repository.""",
        "ja": """コミットをあなた名義にするため、あなたの
**GitHub パーソナルアクセストークン**を1つ預かります。

1. [fine-grained トークンを作る](https://github.com/settings/personal-access-tokens/new)
2. **Repository access** → *Only select repositories* → `{repo}` だけ
3. **Permissions** → *Contents: Read and write* と *Pull requests: Read and write*
4. **有効期限は短く**（90日程度）。切れたらここに「直近の書き込みが失敗」と
   出るので、この画面で入れ替えてください。

`repo` 全体を対象にした classic トークンは使わないでください。必要なのは
リポジトリ1つへの書き込み権限だけです。""",
    },
    "gh.username": {"en": "GitHub username", "ja": "GitHub のユーザー名"},
    "gh.username_registered_help": {
        "en": "Already registered. To swap only the token, leave this alone.",
        "ja": "登録済みです。トークンだけ入れ替えるなら触らなくて構いません。",
    },
    "gh.use_other_name": {
        "en": "Use a different name",
        "ja": "別の名前を使う",
    },
    "gh.other_name_placeholder": {
        "en": "type a different name (currently {login})",
        "ja": "別の名前を入力（現在は {login}）",
    },
    "gh.username_help": {
        "en": "Used as the commit author. Leave blank and your Snowflake "
              "username is used instead.",
        "ja": "コミットの作成者として使われます。空欄なら Snowflake の"
              "ユーザー名が使われます。",
    },
    "gh.token": {"en": "Token", "ja": "トークン"},
    "gh.token_help": {
        "en": "Once saved, only the last four characters are shown.",
        "ja": "保存後は末尾4文字だけが表示されます。",
    },
    "gh.submit_replace": {"en": "Replace token", "ja": "トークンを入れ替える"},
    "gh.submit_register": {"en": "Register", "ja": "登録する"},
    "gh.token_empty": {
        "en": "The token is empty. (The name you typed has been kept.)",
        "ja": "トークンが空です。（入力した名前は消していません。）",
    },
    "gh.storage_note": {
        "en": "Tokens are stored in a table that only this screen can read. "
              "Query it from a worksheet and no rows come back, and the "
              "token column reads `***` (confirmed, including as "
              "ACCOUNTADMIN). That said, **someone can always remove the "
              "policy**, so keep the token scoped to one repository with a "
              "short expiry as described above.",
        "ja": "トークンはこの画面からしか読めないテーブルに入ります。"
              "ワークシートから引いても行は返らず、トークン列は `***` に"
              "なります（ACCOUNTADMIN でも同じであることを確認済み）。"
              "ただし**ポリシーは誰かが外せる**ので、上のとおり対象を"
              "リポジトリ1つに絞り、期限も短くしておいてください。",
    },
    "gh.revoke": {"en": "Revoke", "ja": "削除する"},

    # --------------------------------------------------------------- the form
    "field.subject": {"en": "Subject (from)", "ja": "主語（から）"},
    "field.object": {"en": "Object (to)", "ja": "目的語（へ）"},
    "field.relationship": {"en": "Relationship", "ja": "関係（述語）"},
    "ph.pick_or_new_name": {
        "en": "pick one, or type a new name",
        "ja": "一覧から選ぶか、新しい名前を入力",
    },
    "ph.pick_or_new_pred": {
        "en": "pick one, or type a new UPPER_SNAKE name",
        "ja": "一覧から選ぶか、UPPER_SNAKE の新しい名前を入力",
    },
    "field.pred_meaning": {
        "en": "What this predicate means (required if new)",
        "ja": "この述語の意味（新規なら必須）",
    },
    "ph.pred_meaning": {
        "en": "what it connects, and in what sense",
        "ja": "何と何を、どういう意味でつなぐか",
    },
    "hint.pred_known": {"en": "`{name}` — {meaning}", "ja": "`{name}` — {meaning}"},
    "hint.pred_naming": {
        "en": "New predicates are `UPPER_SNAKE_CASE` (e.g. `USES_ROLE`). "
              "Match the existing shape, or you end up with the same "
              "meaning spelled two ways.",
        "ja": "新しい述語は `UPPER_SNAKE_CASE` です（例: `USES_ROLE`）。"
              "既存の形に合わせてください。揃っていないと、同じ意味が"
              "2通りの綴りで並ぶことになります。",
    },
    "expander.attrs": {
        "en": "Add attributes (optional)",
        "ja": "属性を足す（任意）",
    },
    "hint.attrs": {
        "en": "Labels on a node: `owner` is `team-x`, `freshness` is "
              "`daily`, that sort of pair. Skip it if you don't need it.",
        "ja": "ノードに付ける情報です。`owner` は `team-x`、`freshness` は "
              "`daily` のような組。不要なら飛ばして構いません。",
    },
    "field.subject_attrs": {"en": "Subject attributes", "ja": "主語の属性"},
    "field.object_attrs": {"en": "Object attributes", "ja": "目的語の属性"},
    "field.attr_name": {"en": "name", "ja": "名前"},
    "field.attr_value": {"en": "value", "ja": "値"},
    "ph.attr_name": {"en": "owner", "ja": "owner"},
    "ph.attr_value": {"en": "team-x", "ja": "team-x"},
    "expander.event": {
        "en": "Record as an event (optional)",
        "ja": "出来事として記録する（任意）",
    },
    "hint.event": {
        "en": "Permanent changes — a deploy, a spec change, an incident — "
              "belong in the graph as a dated **event**. Fill in a date and "
              "the object is registered as an event (`type: event`) and the "
              "relationship is dated.\n\n"
              "Name the object `<subject>-<YYYY-MM-DD>-<what changed>` and "
              "pick `AFFECTED_BY` as the relationship. **Why** goes in the "
              "field below — *what* you did is in the PR, but *why* exists "
              "only in the graph.",
        "ja": "デプロイ・仕様変更・障害のような恒久的な変更は、日付のついた"
              "**出来事**としてグラフに残します。日付を入れると、目的語が"
              "出来事（`type: event`）として登録され、関係にも日付が付きます。"
              "\n\n"
              "目的語の名前は `<主語>-<YYYY-MM-DD>-<何が変わったか>`、関係は "
              "`AFFECTED_BY` を選んでください。**なぜ**は下の欄に書きます — "
              "*何をしたか*はPRに残りますが、*なぜ*はグラフにしか残りません。",
    },
    "field.when": {"en": "When", "ja": "いつ"},
    "help.when": {
        "en": "Leave blank if this is not an event.",
        "ja": "出来事でなければ空欄のままにしてください。",
    },
    "field.which_yaml": {"en": "Which YAML file", "ja": "どの YAML に入れるか"},
    "ph.which_yaml": {
        "en": "pick one, or type a new file name (e.g. cost.yaml)",
        "ja": "一覧から選ぶか、新しいファイル名を入力（例: cost.yaml）",
    },
    "help.which_yaml": {
        "en": "Type a name that isn't listed and it gets created. The same "
              "PR registers it in workspace.yaml, so it is visible from the "
              "union view the moment it merges.",
        "ja": "一覧に無い名前を入力すると新しく作られます。同じPRで "
              "workspace.yaml にも登録されるので、マージされた時点で"
              "統合ビューから見えるようになります。",
    },
    "field.note": {"en": "Why (required)", "ja": "なぜ（必須）"},
    "ph.note": {
        "en": "why you believe this. this is the valuable part",
        "ja": "なぜそう言えるのか。ここが一番価値のある部分です",
    },
    "help.note": {
        "en": "What changed is in the PR diff. Why it changed exists only "
              "in the graph.",
        "ja": "何が変わったかはPRの差分に残ります。なぜ変わったかは"
              "グラフにしか残りません。",
    },
    "field.prov": {"en": "Source (required)", "ja": "出典（必須）"},
    "ph.prov": {
        "en": "PR URL / chat link / document name",
        "ja": "PRのURL / チャットのリンク / 資料名",
    },
    "btn.propose": {
        "en": "Propose and open a PR",
        "ja": "提案してPRを出す",
    },
    "foot.caption": {
        "en": "Every field takes a new name if the list doesn't have one "
              "(for a YAML file, the PR registers it in `workspace.yaml` as "
              "well). Leave the relationship blank and fill in only the "
              "attributes to propose labels on a node. A new predicate "
              "appears at the top of the PR under its own heading, as a "
              "proposal to extend the vocabulary — so it gets read more "
              "carefully than a fact does.",
        "ja": "どの欄も、一覧に無い名前をそのまま入力できます（YAML の場合は "
              "`workspace.yaml` への登録も同じPRに入ります）。関係を空欄に"
              "して属性だけ埋めれば、ノードに情報を足す提案になります。"
              "新しい述語はPRの先頭に別見出しで出ます — 語彙を増やす提案は、"
              "事実を足す提案より丁寧に読まれるべきだからです。",
    },

    # ------------------------------------------------------------- refusals
    "err.note_and_prov": {
        "en": "Why and Source are both required. A fact with neither is not "
              "accepted.",
        "ja": "「なぜ」と「出典」は両方必須です。どちらも無い事実は"
              "受け付けません。",
    },
    "err.guard": {
        "en": "The ontology did not accept this: {why}",
        "ja": "オントロジーが受け付けませんでした: {why}",
    },
    "err.pick_yaml": {
        "en": "Pick which YAML file this goes in (or type a name to create "
              "one).",
        "ja": "どの YAML に入れるか選んでください（新しい名前を入力すれば"
              "作られます）。",
    },
    "info.will_be_created": {
        "en": "`{name}` will be created. This PR registers it in "
              "workspace.yaml too.",
        "ja": "`{name}` は新しく作られます。同じPRで workspace.yaml にも"
              "登録されます。",
    },
    "err.new_pred_needs_desc": {
        "en": "A new predicate needs a description (what it connects, and "
              "in what sense).",
        "ja": "新しい述語には説明が必要です（何と何を、どういう意味で"
              "つなぐか）。",
    },
    "err.rel_needs_both": {
        "en": "A relationship needs both a subject and an object.",
        "ja": "関係には主語と目的語の両方が必要です。",
    },
    "err.date_alone": {
        "en": "A date on its own is not an event. Connect what was affected "
              "(subject) to the name of the event (object) with a "
              "relationship.",
        "ja": "日付だけでは出来事になりません。影響を受けたもの（主語）と"
              "出来事の名前（目的語）を、関係でつないでください。",
    },
    "err.nothing_filled": {
        "en": "Nothing was filled in.",
        "ja": "何も入力されていません。",
    },
    "err.attr_no_name": {
        "en": "{where} row {row} has a value but no name: {value}",
        "ja": "{where}の{row}行目に、値だけあって名前がありません: {value}",
    },
    "err.attr_no_value": {
        "en": "{where} row {row} has a name but no value: {name}",
        "ja": "{where}の{row}行目に、名前だけあって値がありません: {name}",
    },
    "field.attrs_generic": {"en": "attributes", "ja": "属性"},
    # Singular, because these name the thing the row belongs to rather than
    # the field. `field.subject_attrs` labels the field itself.
    "err.where_subject": {"en": "Subject attribute", "ja": "主語の属性"},
    "err.where_object": {"en": "Object attribute", "ja": "目的語の属性"},

    # --------------------------------------------------------- after pressing
    "spinner.building": {
        "en": "Building the pull request…",
        "ja": "プルリクエストを作っています…",
    },
    "warn.pr_failed": {
        "en": "Your proposal was accepted ({target}) but the PR could not be "
              "opened: {error}\n\nNothing was lost. Press \"{button}\" "
              "again, or re-register your GitHub credential.",
        "ja": "提案は受け付けました（{target}）が、PRを出せませんでした: "
              "{error}\n\n消えてはいません。もう一度「{button}」を押すか、"
              "GitHub の資格情報を登録し直してください。",
    },
    "info.new_file": {
        "en": "`{name}` is a new file, so the same PR registers it in "
              "`workspace.yaml`. It will not appear in the union view (the "
              "graph this screen reads) until that merges.",
        "ja": "`{name}` は新しいファイルなので、同じPRで `workspace.yaml` "
              "にも登録されます。統合ビュー（この画面が読んでいるグラフ）に"
              "出るのはマージ後です。",
    },
    "ok.added_to_pr": {
        "en": "Accepted and added to a PR ({target}).",
        "ja": "受け付けて、PRに載せました（{target}）。",
    },
    "link.open_pr": {
        "en": "### → [Open the pull request]({url})",
        "ja": "### → [プルリクエストを開く]({url})",
    },
    "info.accepted": {
        "en": "Accepted ({target}). {message}",
        "ja": "受け付けました（{target}）。{message}",
    },
    "defer.ours": {
        "en": "{count} of your proposals are still deferred because you have "
              "no GitHub credential yet. Register above, press again, and "
              "they go in as they are.",
        "ja": "あなたの提案 {count} 件が保留のままです（GitHub の資格情報が"
              "未登録のため）。上で登録してもう一度押せば、そのまま載ります。",
    },
    "defer.theirs": {
        "en": "{count} proposals from other people are still deferred "
              "because they have no GitHub credential.",
        "ja": "他の人の提案 {count} 件が保留のままです"
              "（その人の GitHub 資格情報が未登録のため）。",
    },

    # ------------------------------------------------------------- history
    "hist.title": {"en": "Your proposals", "ja": "あなたの提案"},
    "hist.legend": {
        "en": "`pending` = waiting for the next PR / `queued` = in a PR / "
              "`refused` = the guard did not accept it",
        "ja": "`pending` = 次のPR待ち / `queued` = PRに載った / "
              "`refused` = ガードが受け付けなかった",
    },
    "hist.see_pr": {
        "en": "[See the pull request]({url})",
        "ja": "[プルリクエストを見る]({url})",
    },
}

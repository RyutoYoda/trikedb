"""The same comparison, inside a real agent: CLAUDE.md against a trikedb MCP.

`memory_bench.py` measures a raw model behind one HTTP call, which is the
clean way to isolate delivery from everything else. It is not how anyone
actually ships project knowledge. In a coding agent the knowledge file is
`CLAUDE.md` or `AGENTS.md` — read at startup and carried in the system prompt
of **every request of every turn** — and the alternative is a graph the agent
queries with a tool.

So this runs the identical questions and the identical corpora through
Claude Code itself, and reads the token counts the harness reports rather
than estimating them:

- ``md``     the corpus is the workspace's `CLAUDE.md`. Nothing else.
- ``graph``  the corpus is `corpus.yaml`, served over `trikedb mcp`, and
             `CLAUDE.md` is three lines telling the agent to query it.
- ``none``   an empty `CLAUDE.md`, no MCP. The harness's own floor — a
             system prompt and a tool list — which is what has to be
             subtracted before the two arms can be compared to each other
             rather than to the harness.

What is measured
----------------
`total_cost_usd` and every token the harness reports: fresh input, cache
writes, cache reads, output. The graph arm takes more turns — a tool call and
then an answer — and each turn re-sends the system prompt, so it is not
obviously cheaper and the number is the point. Reporting only `input_tokens`
would hide most of it, because nearly everything in a warmed agent request is
a cache read.

Usage
-----
    python benchmarks/agent_bench.py run bench_out/memory/d250 \\
        --condition graph --n 30 --out bench_out/memory/d250/agent_graph.jsonl
    python benchmarks/agent_bench.py score bench_out/memory/d250

Costs real money against whatever credentials `claude` is logged in with.
`--n` is small by default for that reason.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import webqsp_bench as wq  # noqa: E402  — the metrics, unmodified

REPO = Path(__file__).resolve().parent.parent

#: ``graph_oneshot`` exists because the other two arms do not take the same
#: number of turns, and turns are most of the bill.
#:
#: A knowledge file is already in the system prompt, so the agent answers in
#: one request. An MCP server is not: the agent spends one request deciding
#: to query and another using what came back, and **every** request re-sends
#: the whole system prompt. Measured, the graph arm's token count is almost
#: exactly turns x prefix — 1 turn 30,845, 2 turns 80,670, 4 turns 128,807 —
#: so comparing it against a one-turn file arm prices the agent loop and
#: calls the result a property of graphs.
#:
#: ``graph_oneshot`` retrieves with trikedb *before* the agent is invoked and
#: puts the result in the prompt. One turn, no tool call, same reader, same
#: instruction — the turn-matched arm, and a real deployment besides: it is
#: what a context hook or a RAG preprocessor does.
CONDITIONS = ("none", "md", "graph", "graph_oneshot")

#: The instruction both arms share, and the reason they need one.
#:
#: Without it the agent does not consult the project at all. Measured on the
#: obfuscated corpus, where every gold answer is an invented name: the graph
#: arm scored 0.0% and took one turn per question, never calling a tool — it
#: recognised "who were the children of king solomon", answered "Rehoboam"
#: from pretraining, and was wrong because in *this* project the answer is
#: `Rhundask-37882`. A benchmark of two delivery mechanisms cannot measure
#: either one while the model is bypassing both.
#:
#: So both files carry the same rule, and it is the rule any real knowledge
#: file is written under: what the project says wins. The arms differ in
#: exactly one thing — whether the facts follow, or a pointer to them does.
_AUTHORITY = """Answer questions about this project only from the project's
own facts, never from general knowledge. The project's names are what they
are even when they look unfamiliar; do not substitute a name you recognise.
"""

#: Both files then have to say *look before you give up*, and for the same
#: reason. Told only that the facts exist, the agent answered "I don't know"
#: to all 30 questions of the obfuscated d0 tier, 19 of them without calling
#: a single tool — the escape hatch in the prompt is free and consulting the
#: project is not, so a cheap model takes the hatch. trikedb's own retrieval
#: answers those questions: `search("who were the children of king solomon")`
#: returns both gold facts as its top two hits. The arm was scoring the
#: agent's willingness to look, not the graph's ability to answer.
#:
#: Wording this as an obligation is not a thumb on the scale. It is what a
#: real knowledge file says — "pull the graph before guessing" is the first
#: rule in the repository this benchmark was written for — and the md arm is
#: given the identical obligation against its own file.
_LOOK_FIRST = """Never answer "I don't know" until you have actually looked.
"""

GRAPH_CLAUDE_MD = f"""# Project knowledge

{_AUTHORITY}
Those facts are in a trikedb knowledge graph, not in this file. Before
answering any question about this project you must query it: call
`mcp__trikedb__search` with the question text, and `mcp__trikedb__match` when
you already know the subject or the predicate. An answer given without
querying the graph is wrong even when it sounds right.

{_LOOK_FIRST}"""

MD_CLAUDE_MD_HEADER = f"""# Project knowledge

{_AUTHORITY}
Those facts are listed below, one section per subject. Before answering any
question about this project you must find the relevant section and read it.
An answer given without reading the facts is wrong even when it sounds right.

{_LOOK_FIRST}"""


#: `memory_bench` hands the model its context in the same message as the
#: question, so "here are facts, now answer" needs no framing. An agent's
#: knowledge is somewhere else — a file it was given at startup, or a tool it
#: has to decide to call — and a bare question does not send it looking.
#:
#: Measured: with `memory_bench`'s prompt verbatim, the agent answered "who
#: were the children of king solomon" with "Rehoboam" in one turn, having
#: called no tool and read no file, on a corpus where the answer was
#: `Rhundask-37882`. Naming the project in the question is what makes it a
#: question about the project. Both arms get the identical wording, so it
#: cannot favour either.
_PROMPT = """Answer the question below about this project, using this
project's own facts rather than anything you already know.
Answer with only the answer itself — no explanation.
If there are several correct answers, put one per line.
If this project's facts do not answer it, reply exactly: I don't know
{facts}
Question: {question}
Answer:"""

#: The one-shot arm's payload: what trikedb returned, in the prompt, before
#: the agent ran. Deliberately the same `(s, p, o)` rendering `memory_bench`
#: uses, so the two experiments differ in the harness around the reader and
#: not in how a retrieved fact looks.
_FACTS_BLOCK = """
Facts retrieved from this project's knowledge graph:
{triples}
"""


def _mcp_config(corpus: Path) -> str:
    """A trikedb stdio server over one corpus file.

    The repository's own checkout rather than a published wheel: this
    benchmark has to measure the code in the tree it ships with, and a
    `uvx trikedb` here would silently benchmark whatever is on PyPI today.
    """
    return json.dumps({"mcpServers": {"trikedb": {
        "command": str(REPO / ".venv" / "bin" / "trikedb"),
        "args": ["mcp", str(corpus.resolve())],
    }}})


def _workspace(bench_dir: Path, condition: str, root: Path,
               harness: str = "claude") -> Path:
    """A throwaway project directory holding exactly one condition's setup.

    The knowledge file is named for the harness that reads it — `CLAUDE.md`
    for Claude Code, `AGENTS.md` for Codex — and only one of them is written.
    Writing both would hand Claude Code the corpus twice, since recent
    versions read `AGENTS.md` as well, and the arm would be charged double
    for the same facts.
    """
    workspace = root / condition
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    memo = workspace / ("AGENTS.md" if harness == "codex" else "CLAUDE.md")
    if condition == "md":
        # The corpus file's own "# Project knowledge" heading is dropped: the
        # header replaces it, so the md arm carries the authority rule once
        # and not twice.
        body = (bench_dir / "AGENTS.md").read_text().split("\n", 3)[-1]
        memo.write_text(MD_CLAUDE_MD_HEADER + "\n" + body)
    elif condition == "graph":
        memo.write_text(GRAPH_CLAUDE_MD)
        shutil.copy(bench_dir / "corpus.yaml", workspace / "corpus.yaml")
    elif condition == "graph_oneshot":
        # No MCP and nothing to look up: the facts arrive in the prompt, so
        # the file only has to say that the project's facts win.
        memo.write_text(f"# Project knowledge\n\n{_AUTHORITY}")
    else:
        # The floor carries the rule too, with no facts to apply it to. Its
        # score is then "what the model says when the project is silent",
        # which is the baseline the other two are measured against — a floor
        # measured under a different instruction would not be one.
        memo.write_text(f"# Project knowledge\n\n{_AUTHORITY}")
    return workspace


def _codex_mcp_args(corpus: Path) -> list:
    """`-c` overrides that attach a trikedb stdio server to one `codex exec`.

    Codex takes MCP servers from `~/.codex/config.toml`, so they go in as
    dotted overrides rather than a JSON blob. Passing them per invocation
    keeps the user's own configured servers out of the measurement, which is
    the same reason the Claude arm passes `--strict-mcp-config`.
    """
    return [
        "-c", f'mcp_servers.trikedb.command="{REPO / ".venv" / "bin" / "trikedb"}"',
        "-c", f'mcp_servers.trikedb.args=["mcp","{corpus.resolve()}"]',
    ]


def _ask_codex(workspace: Path, question: str, model: str, condition: str,
               facts: str = "", resume: bool = False,
               timeout: int = 600) -> dict:
    """One `codex exec`, normalised into the same record the Claude arm writes.

    Codex reads `AGENTS.md` from the working directory, which is the file this
    benchmark's corpora already render — so the md arm here is the literal
    thing the condition is named after, with no adaptation.

    Its usage accounting differs from Claude's and has to be normalised, not
    copied: `input_tokens` is already the total *including* what was served
    from cache, where Claude reports fresh input and cache traffic as three
    separate numbers that have to be added. Treating the two as the same
    field would undercount Claude by roughly the size of its system prompt on
    every question.
    """
    prompt = _PROMPT.format(question=question, facts=facts)
    command = ["codex", "exec", "--json", "--skip-git-repo-check",
               "--dangerously-bypass-approvals-and-sandbox"]
    if model:
        command += ["-m", model]
    if condition == "graph":
        command += _codex_mcp_args(workspace / "corpus.yaml")
    command.append(prompt)
    started = time.perf_counter()
    proc = subprocess.run(command, cwd=workspace, capture_output=True,
                          text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    elapsed = time.perf_counter() - started

    usage, messages, tool_calls, failure = {}, [], 0, None
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        kind = event.get("type")
        if kind == "turn.completed":
            usage = event.get("usage", {})
        elif kind in ("turn.failed", "error"):
            failure = json.dumps(event.get("error") or event)[:400]
        elif kind == "item.completed":
            item = event.get("item", {})
            if item.get("type") == "agent_message":
                messages.append(item.get("text", ""))
            elif item.get("type") in ("mcp_tool_call", "command_execution"):
                tool_calls += 1
    if not usage and not messages:
        return {"error": failure or (proc.stderr or proc.stdout)[-400:],
                "secs": round(elapsed, 2)}
    total = usage.get("input_tokens", 0)
    read = usage.get("cached_input_tokens", 0)
    write = usage.get("cache_write_input_tokens", 0)
    return {
        "answer": messages[-1] if messages else "",
        "error": failure,
        "secs": round(elapsed, 2),
        # One `codex exec` is one turn plus one model request per tool call,
        # which is the same quantity Claude's `num_turns` reports.
        "turns": 1 + tool_calls,
        "fresh_input_tokens": max(total - read - write, 0),
        "cache_write_tokens": write,
        "cache_read_tokens": read,
        "output_tokens": (usage.get("output_tokens", 0)
                          + usage.get("reasoning_output_tokens", 0)),
        "total_input_tokens": total,
    }


def _prefetch(db, question: str, cap: int, retrieval: str) -> str:
    """trikedb's answer to the question, rendered for the prompt.

    Runs in this process, before `claude` is started, and is timed separately
    from it — the retrieval is milliseconds and burying it inside the agent's
    wall clock would hide which part of the latency is whose.
    """
    import memory_bench as mb

    entities = mb.entities_from_question(db, question)
    triples = mb.graph_context(db, question, entities, cap, retrieval)
    if not triples:
        return ""
    return _FACTS_BLOCK.format(
        triples="\n".join(f"({t.s}, {t.p}, {t.o})" for t in triples))


def _ask(workspace: Path, question: str, model: str, condition: str,
         facts: str = "", resume: bool = False, timeout: int = 600,
         harness: str = "claude") -> dict:
    """One `claude -p` run, returning the harness's own result object.

    MCP is passed explicitly and strictly in every arm, so the user's own
    configured servers never leak into the measurement — half a dozen
    unrelated tool schemas in the system prompt would be counted as the cost
    of the condition.

    ``ANTHROPIC_API_KEY`` is cleared in both the environment and the settings
    the child reads, because a stale key in either does not fall back to the
    interactive login — it fails every question with a 401. Clearing the
    environment variable is not enough on its own: `~/.claude/settings.json`
    can pin one, and a key from there wins over the logged-in session.

    ``resume`` continues the workspace's previous conversation instead of
    starting a new one, which is the only way to price a knowledge file
    honestly. A fresh `claude -p` must write the whole file into the cache
    before it can answer, at the 1.25-2x write rate; a session that is
    already running wrote it once and reads it back at 0.1x. Those two are
    different products and reporting either alone is a half-truth.
    """
    if harness == "codex":
        return _ask_codex(workspace, question, model, condition, facts,
                          resume, timeout)
    prompt = _PROMPT.format(question=question, facts=facts)
    mcp = _mcp_config(workspace / "corpus.yaml") if condition == "graph" \
        else json.dumps({"mcpServers": {}})
    command = [
        "claude", "-p", prompt, "--output-format", "json",
        "--model", model, "--strict-mcp-config", "--mcp-config", mcp,
        "--settings", json.dumps({"env": {"ANTHROPIC_API_KEY": ""}}),
        "--permission-mode", "bypassPermissions",
    ] + (["--continue"] if resume else [])
    environment = {k: v for k, v in os.environ.items()
                   if k not in ("ANTHROPIC_API_KEY", "CLAUDECODE",
                                "CLAUDE_CODE_ENTRYPOINT")}
    started = time.perf_counter()
    proc = subprocess.run(command, cwd=workspace, env=environment,
                          capture_output=True, text=True, timeout=timeout)
    elapsed = time.perf_counter() - started
    text = proc.stdout[proc.stdout.find("["):] if "[" in proc.stdout else ""
    try:
        messages = json.loads(text)
        result = [m for m in messages if m.get("type") == "result"][-1]
    except Exception:                                       # noqa: BLE001
        return {"error": (proc.stderr or proc.stdout)[-400:], "secs": elapsed}
    usage = result.get("usage", {})
    fresh = usage.get("input_tokens", 0)
    write = usage.get("cache_creation_input_tokens", 0)
    read = usage.get("cache_read_input_tokens", 0)
    return {
        "answer": result.get("result", "") if not result.get("is_error") else "",
        "error": result.get("result") if result.get("is_error") else None,
        "secs": round(elapsed, 2),
        "turns": result.get("num_turns", 0),
        "cost_usd": result.get("total_cost_usd", 0),
        "fresh_input_tokens": fresh,
        "cache_write_tokens": write,
        "cache_read_tokens": read,
        "output_tokens": usage.get("output_tokens", 0),
        # Summed here rather than in the scorer, because the other harness
        # reports a total that already includes its cache traffic. One field
        # meaning one thing in both is what makes them comparable at all.
        "total_input_tokens": fresh + write + read,
    }


def run(bench_dir: Path, condition: str, model: str, out: Path, n: int,
        workers: int = 3, workspace_root: Path = None,
        cap: int = 15, retrieval: str = None, session: str = "fresh",
        harness: str = "claude") -> None:
    """Answer the first ``n`` questions of a tier through Claude Code.

    ``session="continue"`` asks them all down one conversation, in order, one
    at a time — a session, as opposed to `n` unrelated tasks. It forces
    ``workers=1``, because a conversation has no parallel version, and it is
    the condition under which a cached knowledge file stops being re-written.
    Read it with the caveat it carries: the conversation also accumulates,
    so later questions sit behind a longer prefix and can see earlier
    answers.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    eval_set = json.load(open(bench_dir / "eval_set.json"))[:n]
    root = workspace_root or (out.parent / f"_ws_{bench_dir.name}")
    db = None
    if condition == "graph_oneshot":
        import memory_bench as mb
        from trikedb import TrikeDB

        retrieval = retrieval or mb.DEFAULT_RETRIEVAL
        db = TrikeDB(bench_dir / "corpus.yaml", autosave=False)
        db.search("warm up the index", k=1)   # pay it before anything is timed
    done = set()
    if out.exists():
        done = {json.loads(l)["id"] for l in out.read_text().splitlines() if l.strip()}
        print(f"resuming: {len(done)} already answered", file=sys.stderr)
    todo = [e for e in eval_set if e["id"] not in done]
    if not todo:
        print("nothing to do", file=sys.stderr)
        return

    # One workspace per worker: `claude` writes session state into the
    # directory it runs in, and several at once in the same one is a race
    # that shows up as an occasional lost answer rather than an error.
    if session == "continue":
        workers = 1
    pool_dirs = [_workspace(bench_dir, condition, root / f"w{i}", harness)
                 for i in range(max(workers, 1))]
    free = list(pool_dirs)
    out.parent.mkdir(parents=True, exist_ok=True)
    log, lock, state = out.open("a"), threading.Lock(), {"n": 0, "failed": 0}

    def answer(item):
        with lock:
            workspace = free.pop()
        retrieval_secs = 0.0
        facts = ""
        if db is not None:
            started = time.perf_counter()
            facts = _prefetch(db, item["question"], cap, retrieval)
            retrieval_secs = time.perf_counter() - started
        try:
            with lock:
                # Position in the conversation, captured before the call: the
                # whole point of `continue` is that question 1 pays the cache
                # write and question 5 does not, and an unordered record
                # cannot show that.
                seq = state["n"]
                resume = session == "continue" and bool(seq)
            record = _ask(workspace, item["question"], model, condition, facts,
                          resume=resume, harness=harness)
        except Exception as exc:                            # noqa: BLE001
            record = {"error": f"{type(exc).__name__}: {exc}"}
        finally:
            with lock:
                free.append(workspace)
        with lock:
            if record.get("error") and not record.get("answer"):
                state["failed"] += 1
                print(f"  {item['id']}: {record['error'][:120]}",
                      file=sys.stderr, flush=True)
                return                      # never recorded — a rerun retries it
            log.write(json.dumps(dict(record, id=item["id"], condition=condition,
                                      model=model,
                                      retrieval_secs=round(retrieval_secs, 4),
                                      retrieval=retrieval or "",
                                      session=session, seq=seq,
                                      harness=harness),
                                  ensure_ascii=False) + "\n")
            log.flush()
            state["n"] += 1
            spent = state.get("cost", 0) + record.get("cost_usd", 0)
            state["cost"] = spent
            print(f"  {len(done) + state['n']}/{len(eval_set)}  ${spent:.2f}",
                  file=sys.stderr, flush=True)

    with ThreadPoolExecutor(max_workers=max(workers, 1)) as executor:
        list(executor.map(answer, todo))
    log.close()
    print(f"wrote {out} — ${state.get('cost', 0):.2f}"
          + (f", {state['failed']} left for a rerun" if state["failed"] else ""),
          file=sys.stderr)


def score(bench_dir: Path, out_json: Path = None) -> None:
    """One row per condition, in tokens.

    Tokens and not dollars. The harness reports both, and the dollar figure
    is the less honest of the two here: cost depends on which cache band each
    token lands in, a cache write costs 12x a cache read, and whether the
    file was already cached depends on session lifetime — none of which this
    benchmark controls. Token counts are measured directly and mean the same
    thing in every arm.

    ``turns`` is in the table for the same reason. Every turn re-sends the
    whole prefix, so an arm that queries a tool and then answers processes
    the prefix twice; without the column the reader would read that as the
    cost of the graph rather than the cost of the loop around it.
    """
    import statistics

    def usage(rec):
        """(fresh, cache write, cache read, total) for any record.

        Absorbs two shapes: Claude reports fresh input and cache traffic
        separately and the total is their sum, Codex reports a total that
        already contains the cache reads. Records written before the fields
        were unified are read through their old names.
        """
        fresh = rec.get("fresh_input_tokens", rec.get("input_tokens", 0))
        write = rec.get("cache_write_tokens", rec.get("cache_creation_tokens", 0))
        read = rec.get("cache_read_tokens", 0)
        return fresh, write, read, rec.get("total_input_tokens") or fresh + write + read

    gold = {e["id"]: e["answers"] for e in json.load(open(bench_dir / "eval_set.json"))}
    meta = json.loads((bench_dir / "corpus_meta.json").read_text())
    print(f"corpus: {meta['corpus_triples']} triples, "
          f"~{meta['document_chars'] // 4:,} tokens as markdown\n")
    print(f"{'condition':<15}{'Hits@1':>8}{'F1':>7}{'n':>5}{'turns':>7}"
          f"{'cache wr':>10}{'cache rd':>10}{'out':>7}"
          f"{'total in':>10}{'secs':>7}{'retr ms':>9}")
    rows = []
    for path in sorted(bench_dir.glob("agent_*.jsonl")):
        recs = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        recs = [r for r in recs if r["id"] in gold]
        if not recs:
            continue
        n = len(recs)
        med = lambda key: statistics.median(r.get(key, 0) for r in recs)  # noqa: E731
        # Everything the model had to look at, cached or not. `input_tokens`
        # alone is near zero in a warm agent and would say the file is free.
        total_in = statistics.median(usage(r)[3] for r in recs)
        # The harness is part of the row's identity, not a footnote: the two
        # report different absolute numbers for the same condition because
        # their system prompts differ, and a table that mixed them under one
        # label would invite subtracting one from the other.
        harness = recs[0].get("harness", "claude")
        row = {
            "condition": (recs[0]["condition"] if harness == "claude"
                          else f"{recs[0]['condition']}*"), "n": n,
            "hits_at_1": round(100 * sum(
                wq.hits_at_1(r["answer"], gold[r["id"]]) for r in recs) / n, 1),
            "f1": round(100 * sum(
                wq.f1(r["answer"], gold[r["id"]]) for r in recs) / n, 1),
            "median_turns": med("turns"),
            "harness": recs[0].get("harness", "claude"),
            "median_cache_write_tokens": int(statistics.median(
                usage(r)[1] for r in recs)),
            "median_cache_read_tokens": int(statistics.median(
                usage(r)[2] for r in recs)),
            "median_output_tokens": int(med("output_tokens")),
            "median_total_input_tokens": int(total_in),
            "median_secs": round(med("secs"), 1),
            "median_retrieval_secs": round(med("retrieval_secs"), 4),
            "retrieval": recs[0].get("retrieval", ""),
            "session": recs[0].get("session", "fresh"),
            "corpus_triples": meta["corpus_triples"],
            "file_tokens": meta["document_chars"] // 4,
        }
        print(f"{row['condition']:<15}{row['hits_at_1']:>7.1f}%{row['f1']:>6.1f}%"
              f"{n:>5}{row['median_turns']:>7.0f}"
              f"{row['median_cache_write_tokens']:>10,}"
              f"{row['median_cache_read_tokens']:>10,}"
              f"{row['median_output_tokens']:>7,}"
              f"{row['median_total_input_tokens']:>10,}"
              f"{row['median_secs']:>7.1f}"
              f"{1000 * row['median_retrieval_secs']:>8.0f}ms")
        rows.append(row)
    if out_json:
        out_json.write_text(json.dumps(rows, indent=1) + "\n")
        print(f"\nwrote {out_json}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("bench_dir", type=Path)
    r.add_argument("--condition", choices=CONDITIONS, required=True)
    r.add_argument("--harness", choices=("claude", "codex"), default="claude",
                   help="which agent CLI to drive")
    r.add_argument("--model", default="",
                   help="harness default when omitted")
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--n", type=int, default=30)
    r.add_argument("--workers", type=int, default=3)
    r.add_argument("--cap", type=int, default=15,
                   help="triples the one-shot arm retrieves per question")
    r.add_argument("--retrieval", default=None,
                   help="which trikedb retrieval the one-shot arm uses")
    r.add_argument("--workspace-root", type=Path, default=None,
                   dest="workspace_root",
                   help="where the throwaway project directories go. Put them "
                        "outside any git repository: both harnesses walk up "
                        "from the working directory looking for a knowledge "
                        "file, and an unrelated CLAUDE.md two levels up is "
                        "then measured as part of the condition")
    r.add_argument("--session", choices=("fresh", "continue"), default="fresh",
                   help="continue asks every question down one conversation, "
                        "so a cached knowledge file is written only once")
    s = sub.add_parser("score")
    s.add_argument("bench_dir", type=Path)
    s.add_argument("--json", type=Path, dest="out_json")
    args = ap.parse_args()
    if args.cmd == "run":
        run(args.bench_dir, args.condition, args.model, args.out, args.n,
            args.workers, args.workspace_root, args.cap, args.retrieval,
            args.session, args.harness)
    else:
        score(args.bench_dir, args.out_json)


if __name__ == "__main__":
    main()

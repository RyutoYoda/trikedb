"""Render agent_data.json — the same corpus inside two real agent CLIs.

    python benchmarks/agent_bench.py score bench_out/memory/d0 --json ...
    python benchmarks/agent_chart.py             # -> benchmarks/agent.png

`memory_chart.py` plots a raw model behind one HTTP call. This plots the same
corpora through Claude Code and Codex, where the knowledge file is loaded from
disk into the system prompt and the graph is a tool the harness calls.

Only the turn-matched pair is drawn: the whole file against pre-retrieved
graph context, both answering in one request. The arm where the agent queries
the MCP server itself takes three or four turns and re-sends the prefix on
each, so putting it on the same axis would price the agent loop and read as a
property of graphs; its numbers are in the table in README.md instead.

Needs plotly and kaleido:  pip install plotly kaleido
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_MUTED = "#52514e"
GRID = "#e6e5e1"

#: Hue carries the delivery — blue the file, orange the graph, as everywhere
#: else in this directory — and the dash carries the harness. That way the
#: figure's subject stays "file against graph" and the two CLIs read as two
#: samples of it rather than as four unrelated products.
MD = "#2a78d6"
GRAPH = "#eb6834"
SERIES = [
    ("claude", "md", MD, "solid"),
    ("claude", "graph_oneshot", GRAPH, "solid"),
    ("codex", "md", MD, "dot"),
    ("codex", "graph_oneshot", GRAPH, "dot"),
]

TEXT = {
    "en": {
        "title": "Agent input tokens and local answer-match rate",
        "sub": ("WebQSP · 30 questions · claude-haiku-4.5 and Codex · file/graph turns vary · tokens as each harness reports them"),
        "x": "facts in the project's knowledge",
        "y1": "tokens processed per question", "y2": "Local answer match",
        "claude md": "Claude Code · CLAUDE.md",
        "claude graph_oneshot": "Claude Code · pre-retrieved trikedb",
        "codex md": "Codex · AGENTS.md",
        "codex graph_oneshot": "Codex · pre-retrieved trikedb",
    },
    "jp": {
        "title": "エージェントの入力トークンと独自採点の比較",
        "sub": ("WebQSP · 30問 · claude-haiku-4.5 と Codex · 全文条件は1〜3ターン · "
                "各ハーネスが報告したトークン数"),
        "x": "プロジェクトの知識に入っている事実の数",
        "y1": "1問あたりの処理トークン", "y2": "Local answer match",
        "claude md": "Claude Code · CLAUDE.md",
        "claude graph_oneshot": "Claude Code · pre-retrieved trikedb",
        "codex md": "Codex · AGENTS.md",
        "codex graph_oneshot": "Codex · pre-retrieved trikedb",
    },
    "zh": {
        "title": "智能体输入token与本地答案匹配率",
        "sub": ("WebQSP · 30 题 · claude-haiku-4.5 与 Codex · 全文条件为1至3轮 · "
                "各 harness 自己报告的 token 数"),
        "x": "项目知识中的事实条数",
        "y1": "每题处理的 token 数", "y2": "Local answer match",
        "claude md": "Claude Code · CLAUDE.md",
        "claude graph_oneshot": "Claude Code · pre-retrieved trikedb",
        "codex md": "Codex · AGENTS.md",
        "codex graph_oneshot": "Codex · pre-retrieved trikedb",
    },
}


def main(lang: str = "en") -> None:
    words = TEXT[lang]
    rows = json.loads((HERE / "agent_data.json").read_text())

    def pick(harness, condition):
        # Codex rows carry a trailing marker on the condition so a mixed table
        # cannot silently average the two harnesses; strip it to match.
        return sorted((r for r in rows if r.get("harness") == harness
                       and r["condition"].rstrip("*") == condition),
                      key=lambda r: r["corpus_triples"])

    figure = make_subplots(rows=2, cols=1, shared_xaxes=True,
                           vertical_spacing=0.08, row_heights=[0.54, 0.46])
    sizes = sorted({r["corpus_triples"] for r in rows})

    for harness, condition, color, dash in SERIES:
        points = pick(harness, condition)
        if not points:
            continue
        label = words[f"{harness} {condition}"]
        x = [r["corpus_triples"] for r in points]
        figure.add_trace(go.Scatter(
            x=x, y=[r["median_total_input_tokens"] for r in points],
            mode="lines+markers", name=label,
            line=dict(color=color, width=3, dash=dash),
            marker=dict(size=9, color=color),
            hovertemplate=f"{label}<br>%{{x:,}} facts<br>%{{y:,}} tokens<extra></extra>",
        ), row=1, col=1)
        figure.add_trace(go.Scatter(
            x=x, y=[r["hits_at_1"] for r in points], mode="lines+markers",
            name=label, showlegend=False,
            line=dict(color=color, width=3, dash=dash),
            marker=dict(size=9, color=color),
            hovertemplate=f"{label}<br>%{{x:,}} facts<br>%{{y:.1f}}%<extra></extra>",
        ), row=2, col=1)

    figure.update_layout(
        title=dict(
            text=(f"{words['title']}<br>"
                  f"<span style='font-size:13px;color:{INK_MUTED}'>"
                  f"{words['sub']}</span>"),
            font=dict(size=21, color=INK), x=0.01, xanchor="left", y=0.955),
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(family="Helvetica, Arial, sans-serif", color=INK, size=14),
        legend=dict(orientation="h", y=-0.14, x=0, font=dict(size=12),
                    entrywidth=0.5, entrywidthmode="fraction"),
        margin=dict(l=82, r=34, t=112, b=110), width=1100, height=700,
    )
    figure.update_xaxes(type="log", showgrid=False, zeroline=False,
                        linecolor=GRID)
    figure.update_xaxes(tickvals=sizes, ticktext=[f"{s:,}" for s in sizes],
                        title=dict(text=words["x"], font=dict(size=14)),
                        row=2, col=1)
    figure.update_yaxes(title=dict(text=words["y1"], font=dict(size=14)),
                        type="linear", gridcolor=GRID, zeroline=False,
                        range=[0, 130_000],
                        # Explicit ticks: the range spans barely one decade, so
                        # plotly falls back to minor ticks and labels the axis
                        # "4 5 6 7 8 9 100k", which reads as single digits.
                        tickvals=[0, 30_000, 60_000, 90_000, 120_000],
                        ticktext=["0", "30k", "60k", "90k", "120k"],
                        row=1, col=1)
    figure.update_yaxes(title=dict(text=words["y2"], font=dict(size=14)),
                        range=[0, 100], ticksuffix="%", gridcolor=GRID,
                        zeroline=False, row=2, col=1)
    out = HERE / ("agent.png" if lang == "en" else f"agent_{lang}.png")
    figure.write_image(out, scale=2)
    print(f"wrote {out}")


if __name__ == "__main__":
    import sys

    for language in (sys.argv[1:] or TEXT):
        main(language)

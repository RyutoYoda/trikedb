"""Render memory_data.json as one line: tokens per question, as knowledge grows.

    python benchmarks/memory_bench.py sweep bench_out/memory \
        --json benchmarks/memory_data.json
    python benchmarks/memory_chart.py            # -> benchmarks/memory.png

Two series, one axis pair, a number printed on every point. Nothing else.

Two earlier versions tried to carry tokens and accuracy in one figure — first
as stacked panels, then as a token-quality scatter — and both failed the test
that matters, which is whether a reader who is not the author can say what
they are looking at within a few seconds. The scatter failed in a specific
way worth recording: the series had different numbers of points (three sizes
for the file, five for the graph), the graph's five landed within 35 tokens of
each other and so read as one blob, and only the file's points carried
labels. Every one of those was defensible and together they were unreadable.

The axis is tokens, and the wording stays tokens. Tokens are not cost: a
token's price depends on which cache band it lands in, and the same count can
differ severalfold in money. This benchmark counts tokens and does not measure
money, so calling the axis "cost" would be claiming something it cannot show.

So this figure answers one question — **does the token count grow with the
project?** — and the accuracy numbers live in the table in README.md, where a
reader is already reading numbers. `md_grep` is left out for the same reason:
it settles a different question (is it the retrieval or the graph) and the
table settles it in two numbers.

Needs plotly and kaleido:  pip install plotly kaleido
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import plotly.graph_objects as go

HERE = Path(__file__).resolve().parent

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_MUTED = "#52514e"
GRID = "#e6e5e1"
RULE = "#c9c7c0"

#: Blue is the file, orange the graph — the same meanings these hues carry in
#: every other figure in this directory.
MD = "#2a78d6"
GRAPH = "#eb6834"

TEXT = {
    "en": {
        "title": "The file's tokens grow with the project. The graph's do not.",
        "sub": ("WebQSP · 100 questions · qwen3:8b · one corpus, written out "
                "both ways · prompt tokens the server actually counted<br>"
                "<b>Hits@1</b> · whole file 82%→71% · 15 facts 77%→72% — the "
                "file leads at the smallest corpus and falls below the graph "
                "as the project grows"),
        "x": "facts in the project's knowledge",
        "y": "prompt tokens per question",
        "md": "the whole CLAUDE.md / AGENTS.md",
        "graph": "trikedb, 15 facts returned",
        "stop": "past here the file no longer<br>fits the model's context window",
    },
    "jp": {
        "title": "ファイルのトークンは知識量に比例する。グラフはしない。",
        "sub": ("WebQSP · 100問 · qwen3:8b · 同一コーパスを両方の形で書き出した · "
                "サーバが実際に数えたプロンプトトークン<br>"
                "<b>Hits@1</b> · 全文 82%→71% · 15件 77%→72% — "
                "最小コーパスでは全文が上、知識が育つと全文が下回る"),
        "x": "プロジェクトの知識に入っている事実の数",
        "y": "1問あたりのプロンプトトークン",
        "md": "CLAUDE.md / AGENTS.md 全文",
        "graph": "trikedb、15件返す",
        "stop": "これ以上はファイルが<br>モデルの文脈窓に入らない",
    },
    "zh": {
        "title": "文件的 token 随项目增长，图谱的不会。",
        "sub": ("WebQSP · 100 题 · qwen3:8b · 同一份语料写成两种形态 · "
                "服务端实际统计的提示词 token<br>"
                "<b>Hits@1</b> · 全文 82%→71% · 返回 15 条 77%→72% —— "
                "语料最小时全文更高，语料变大后全文反而更低"),
        "x": "项目知识中的事实条数",
        "y": "每题的提示词 token 数",
        "md": "整份 CLAUDE.md / AGENTS.md",
        "graph": "trikedb，返回 15 条",
        "stop": "再大文件就装不进<br>模型的上下文窗口",
    },
}


def main(lang: str = "en") -> None:
    words = TEXT[lang]
    rows = json.loads((HERE / "memory_data.json").read_text())
    warm = [r for r in rows if "/cold" not in r["condition"]]

    def series(name):
        return sorted((r for r in warm if r["condition"] == name),
                      key=lambda r: r["corpus_triples"])

    figure = go.Figure()
    for name, color, side in (("md", MD, "top center"),
                              ("graph", GRAPH, "bottom center")):
        points = series(name)
        figure.add_trace(go.Scatter(
            x=[r["corpus_triples"] for r in points],
            y=[r["median_prompt_tokens"] for r in points],
            mode="lines+markers+text", name=words[name],
            # Every point, not just the ends. Five numbers along a flat line
            # is exactly the message — they are all the same number — and a
            # reader who has to trust an annotation for that will not.
            text=[f"{r['median_prompt_tokens']:,}" for r in points],
            textposition=side, cliponaxis=False,
            textfont=dict(size=13, color=color),
            line=dict(color=color, width=3),
            marker=dict(size=11, color=color,
                        line=dict(color=SURFACE, width=1.5)),
            hovertemplate=(f"{words[name]}<br>%{{x:,}} facts"
                           "<br>%{y:,} tokens<extra></extra>"),
        ))

    sizes = sorted({r["corpus_triples"] for r in warm
                    if r["condition"] != "none"})
    md_points = series("md")
    if md_points and md_points[-1]["corpus_triples"] < max(sizes):
        # Why the blue line stops. Without it the reader's first guess is that
        # the measurement is missing, when in fact the configuration is: the
        # rendered file is larger than the window the model has.
        figure.add_vline(x=md_points[-1]["corpus_triples"],
                         line=dict(color=RULE, width=1, dash="dash"))
        figure.add_annotation(
            x=math.log10(md_points[-1]["corpus_triples"]), xshift=12,
            y=math.log10(md_points[-1]["median_prompt_tokens"]), yshift=-30,
            xanchor="left", text=words["stop"], showarrow=False,
            align="left", font=dict(size=12, color=INK_MUTED))

    figure.update_layout(
        title=dict(
            text=(f"{words['title']}<br>"
                  f"<span style='font-size:13px;color:{INK_MUTED}'>"
                  f"{words['sub']}</span>"),
            font=dict(size=22, color=INK), x=0.01, xanchor="left", y=0.95),
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(family="Helvetica, Arial, sans-serif", color=INK, size=14),
        legend=dict(orientation="h", y=-0.18, x=0, font=dict(size=14)),
        xaxis=dict(type="log", showgrid=False, zeroline=False, linecolor=RULE,
                   tickvals=sizes, ticktext=[f"{s:,}" for s in sizes],
                   title=dict(text=words["x"], font=dict(size=14))),
        yaxis=dict(type="log", gridcolor=GRID, zeroline=False,
                   title=dict(text=words["y"], font=dict(size=14)),
                   # Explicit ticks: across two decades plotly labels the minor
                   # ones too, and the axis reads "5 2 5 2" instead of numbers.
                   tickvals=[300, 1_000, 3_000, 10_000, 30_000],
                   ticktext=["300", "1k", "3k", "10k", "30k"],
                   range=[math.log10(250), math.log10(60_000)]),
        margin=dict(l=84, r=44, t=132, b=96), width=1000, height=580,
    )
    out = HERE / ("memory.png" if lang == "en" else f"memory_{lang}.png")
    figure.write_image(out, scale=2)
    print(f"wrote {out}")


if __name__ == "__main__":
    import sys

    for language in (sys.argv[1:] or TEXT):
        main(language)

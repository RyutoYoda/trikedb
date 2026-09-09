"""Render retrieval_methods_data.json — how each way of asking finds an answer.

    python benchmarks/memory_bench.py methods bench_out/memory --cap 15 \
        --json benchmarks/retrieval_methods_data.json
    python benchmarks/retrieval_methods_chart.py   # -> retrieval_methods.png

No model is involved in this figure, which is why it is the one to read
first: it is whether the gold answer ended up in the context, at a fixed
budget, not a bound on downstream accuracy. The x axis is how much project
knowledge exists, because that is what separates the methods — at 500 facts
several of them look fine, and the spread only opens up as the corpus grows.

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

#: Orange is the method the benchmark ends up using, blue the text baseline
#: it has to beat, and the rest are grey — they are context, not contenders,
#: and colouring six lines would ask the eye to compare things the figure is
#: not about. Direct labels on all three coloured lines, since a legend of
#: seven entries is a lookup table.
HIGHLIGHT = {
    "hybrid (entity + semantic)": "#eb6834",
    "AGENTS.md, matching lines": "#2a78d6",
    "semantic search": "#1baf7a",
}
MUTED = "#b9b7b0"

TEXT = {
    "en": {
        "title": "How you ask the graph decides what you get",
        "sub": ("WebQSP · 100 questions · 15 triples of budget · no answer-generating model "
                "involved — whether a gold answer reached the context"),
        "x": "facts in the project's knowledge",
        "y": "answer reached the context",
        "hybrid (entity + semantic)": "trikedb, hybrid",
        "semantic search": "trikedb, semantic only",
        "AGENTS.md, matching lines": "AGENTS.md, matching lines",
    },
    "jp": {
        "title": "グラフの引き方で結果が変わる",
        "sub": ("WebQSP · 100問 · 予算15トリプル · 回答生成モデル不使用 — "
                "正解が文脈に入ったかどうか"),
        "x": "プロジェクトの知識に入っている事実の数",
        "y": "正解が文脈に入った割合",
        "hybrid (entity + semantic)": "trikedb, hybrid",
        "semantic search": "trikedb, 意味検索のみ",
        "AGENTS.md, matching lines": "AGENTS.md の該当行",
    },
    "zh": {
        "title": "怎么查图谱，决定了你能拿到什么",
        "sub": ("WebQSP · 100 题 · 预算 15 条三元组 · 不调用回答生成模型 — "
                "标准答案是否进入了上下文"),
        "x": "项目知识中的事实条数",
        "y": "答案进入上下文的比例",
        "hybrid (entity + semantic)": "trikedb, hybrid",
        "semantic search": "trikedb, 仅语义检索",
        "AGENTS.md, matching lines": "AGENTS.md 匹配行",
    },
}


def main(lang: str = "en") -> None:
    words = TEXT[lang]
    rows = json.loads((HERE / "retrieval_methods_data.json").read_text())
    by_method: dict = {}
    for row in rows:
        by_method.setdefault(row["method"], []).append(row)

    figure = go.Figure()
    # Muted first so the three that carry the story draw over them.
    for method in sorted(by_method, key=lambda m: m in HIGHLIGHT):
        points = sorted(by_method[method], key=lambda r: r["corpus_triples"])
        color = HIGHLIGHT.get(method, MUTED)
        figure.add_trace(go.Scatter(
            x=[r["corpus_triples"] for r in points],
            y=[r["reached_pct"] for r in points],
            mode="lines+markers", name=method,
            line=dict(color=color, width=3 if method in HIGHLIGHT else 1.6),
            marker=dict(size=8 if method in HIGHLIGHT else 5, color=color),
            hovertemplate=f"{method}<br>%{{x:,}} facts<br>%{{y:.0f}}%<extra></extra>",
        ))
        if method not in HIGHLIGHT:
            # Unlabelled on purpose. Four of the six methods converge within
            # two points of each other at the largest corpus, so labelling
            # them all stacks four strings on one gridline and none of them
            # can be read. Their numbers are in the table in README.md, where
            # a reader who wants them is already reading numbers.
            continue
        # log10, because the x axis is logarithmic and an annotation takes the
        # axis's own units while a trace takes data values. Passing 3,998
        # here puts the label thousands of decades off-canvas, where it is
        # simply absent — the figure renders, with no labels and no error.
        figure.add_annotation(
            x=math.log10(points[-1]["corpus_triples"]),
            y=points[-1]["reached_pct"],
            text=words.get(method, method), showarrow=False,
            xanchor="left", xshift=10, font=dict(size=13, color=color))

    sizes = sorted({r["corpus_triples"] for r in rows})
    figure.update_layout(
        title=dict(
            text=(f"{words['title']}<br>"
                  f"<span style='font-size:13px;color:{INK_MUTED}'>"
                  f"{words['sub']}</span>"),
            font=dict(size=21, color=INK), x=0.01, xanchor="left", y=0.93),
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(family="Helvetica, Arial, sans-serif", color=INK, size=14),
        showlegend=True,
        legend=dict(orientation="h", y=-0.3, entrywidth=0.5, entrywidthmode="fraction", font_size=11),
        xaxis=dict(type="log", tickvals=sizes,
                   ticktext=[f"{s:,}" for s in sizes], showgrid=False,
                   zeroline=False, linecolor=GRID,
                   title=dict(text=words["x"], font=dict(size=14))),
        yaxis=dict(range=[0, 100], ticksuffix="%", gridcolor=GRID,
                   zeroline=False,
                   title=dict(text=words["y"], font=dict(size=14))),
        margin=dict(l=76, r=210, t=100, b=180), width=1100, height=620,
    )
    out = HERE / ("retrieval_methods.png" if lang == "en"
                  else f"retrieval_methods_{lang}.png")
    figure.write_image(out, scale=2)
    print(f"wrote {out}")


if __name__ == "__main__":
    import sys

    for language in (sys.argv[1:] or TEXT):
        main(language)

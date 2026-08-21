"""Render accuracy_data.json as the one bar chart the benchmark exists for.

    python benchmarks/webqsp_bench.py score bench_out/hybrid/eval_set.json \
        bench_out/ans_*.jsonl --json benchmarks/accuracy_data.json
    python benchmarks/accuracy_chart.py        # -> benchmarks/accuracy.png

Deliberately austere. An earlier version carried both metrics, a sub-label per
row, a reference line for retrieval reach, a legend and an axis — every item
defensible on its own, and together they buried the finding. This one shows
four bars, four labels and two deltas. F1, n and reach live in the tables in
README.md, where a reader who wants them is already reading numbers.

Needs plotly and kaleido:  pip install plotly kaleido
"""

from __future__ import annotations

import json
from pathlib import Path

import plotly.graph_objects as go

HERE = Path(__file__).resolve().parent

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_MUTED = "#52514e"

#: Two hues, because the two conditions are what this figure compares — a light
#: and a dark tint of one hue read as "more of the same thing" and the eye has
#: to measure the bars to see which is which. Blue is the baseline, orange is
#: with a graph, and orange is always the taller bar.
#:
#: Validated on this surface: CVD dE 24.7 (protan), normal-vision dE 33.6, both
#: above 3:1 against the surface. Note these two carry *condition* here, not a
#: metric — this figure plots one metric, so the hue is free for something else.
WITHOUT_GRAPH = "#2a78d6"
WITH_GRAPH = "#eb6834"

#: filename -> (label, has a graph). Bottom to top, paired by model so each
#: model's before/after sits adjacent — interleaving the conditions put the two
#: halves of the comparison four rows apart, and a jump you have to hunt for is
#: a jump nobody sees.
#: Stages, not competitors. 89.3% and 77.7% are the same 300 questions at two
#: points in one pipeline — what trikedb put in front of the model, and what
#: the model then said. Drawing them as rival bars is what made an earlier
#: version of this figure unreadable; drawing them as stages is what makes the
#: loss legible, because the gap between the top two bars is the reader
#: dropping answers it was handed.
#:
#: The bottom bar is the same reader with no graph. Every bar is over all 300
#: questions with nothing excluded, which is the only reason they can share an
#: axis at all.
REACH = 89.3
ROWS = [
    ("ans_nograph_27b.jsonl", "alone_27b", "without"),
    ("ans_hybrid_grounded_27b.jsonl", "graph_27b", "with"),
    ("ans_nograph_8b.jsonl", "alone_8b", "without"),
    ("ans_hybrid_grounded_8b.jsonl", "graph_8b", "with"),
    (None, "reach", "trikedb"),
]

#: A translated doc deserves a translated figure — a reader who chose 日本語
#: should not have to read the one image in English. Only the words move; every
#: number and every colour is the same file of data.
TEXT = {
    "en": {
        "title": "trikedb finds the answer for 89.3% of questions",
        "sub": "WebQSP · every bar is the same 300 questions",
        "reach": "<b>trikedb found it</b>",
        "graph_8b": "qwen3:8b + graph", "alone_8b": "qwen3:8b alone",
        "graph_27b": "qwen3.8:27b + graph", "alone_27b": "qwen3.8:27b alone",
        "delta": "{d:+.0f} points from the graph",
        "loss": "−{d:.1f}: the reader dropped what it was handed",
    },
    "jp": {
        "title": "trikedb は89.3%の質問で正解を見つける",
        "sub": "WebQSP · どの棒も同じ300問",
        "reach": "<b>trikedb が見つけた</b>",
        "graph_8b": "qwen3:8b + グラフ", "alone_8b": "qwen3:8b 単体",
        "graph_27b": "qwen3.8:27b + グラフ", "alone_27b": "qwen3.8:27b 単体",
        "delta": "グラフで {d:+.0f} ポイント",
        "loss": "−{d:.1f}：渡したのにリーダーが落とした",
    },
    "zh": {
        "title": "trikedb 在 89.3% 的题目上找到了答案",
        "sub": "WebQSP · 每根柱子都是同一批 300 题",
        "reach": "<b>trikedb 找到了它</b>",
        "graph_8b": "qwen3:8b + 图谱", "alone_8b": "qwen3:8b 单独",
        "graph_27b": "qwen3.8:27b + 图谱", "alone_27b": "qwen3.8:27b 单独",
        "delta": "图谱带来 {d:+.0f} 个百分点",
        "loss": "−{d:.1f}：递到手上却被阅读模型丢掉",
    },
}

#: trikedb's bar is a different *stage*, not a rival reader, so it gets its own
#: darker treatment. Reader bars stay blue/orange for without/with a graph.
TRIKEDB_BAR = "#1a4f8f"

#: Two gaps, and they mean opposite things: what the graph added, and what the
#: reader then lost. Both are differences a reader will not compute by eye.


def main(lang: str = "en") -> None:
    words = TEXT[lang]
    scored = {r["answers"]: r for r in json.loads((HERE / "accuracy_data.json").read_text())}

    COLOR = {"trikedb": TRIKEDB_BAR, "with": WITH_GRAPH, "without": WITHOUT_GRAPH}
    values = [(words[key], REACH if name is None else scored[name]["hits_at_1"], kind)
              for name, key, kind in ROWS]

    figure = go.Figure(go.Bar(
        y=[label for label, _, _ in values],
        x=[value for _, value, _ in values],
        orientation="h",
        marker=dict(color=[COLOR[kind] for _, _, kind in values],
                    line=dict(color=SURFACE, width=2)),
        text=[f"{value:.1f}%" for _, value, _ in values],
        textposition="outside", cliponaxis=False,
        textfont=dict(size=16, color=INK),
        hovertemplate="%{y}<br>%{x:.1f}% of 300 questions<extra></extra>",
    ))

    # Row indices, bottom-up as plotly draws them.
    at = {key: i for i, (_, key, _) in enumerate(ROWS)}
    for lower, upper, template, color, size in (
        ("alone_8b", "graph_8b", words["delta"], WITH_GRAPH, 16),
        ("alone_27b", "graph_27b", words["delta"], WITH_GRAPH, 16),
    ):
        gain = values[at[upper]][1] - values[at[lower]][1]
        figure.add_annotation(
            x=values[at[upper]][1], y=(at[lower] + at[upper]) / 2, xshift=150,
            text=f"<b>{template.format(d=gain)}</b>", showarrow=False,
            font=dict(size=size, color=color),
        )
    figure.add_annotation(
        x=REACH, y=(at["graph_8b"] + at["reach"]) / 2, xshift=150,
        text=words["loss"].format(d=REACH - values[at["graph_8b"]][1]),
        showarrow=False, font=dict(size=14, color=INK_MUTED),
    )

    figure.update_layout(
        title=dict(
            text=(f"{words['title']}<br>"
                  f"<span style='font-size:14px;color:{INK_MUTED}'>"
                  f"{words['sub']}</span>"),
            font=dict(size=22, color=INK), x=0.01, xanchor="left", y=0.94,
        ),
        bargap=0.42,
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(family="Helvetica, Arial, sans-serif", color=INK, size=15),
        xaxis=dict(range=[0, 100], showgrid=False, zeroline=False,
                   showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, linecolor=SURFACE),
        showlegend=False,
        margin=dict(l=10, r=330, t=100, b=16), width=1100, height=420,
    )
    out = HERE / ("accuracy.png" if lang == "en" else f"accuracy_{lang}.png")
    figure.write_image(out, scale=2)
    print(f"wrote {out}")


if __name__ == "__main__":
    import sys

    for language in (sys.argv[1:] or TEXT):
        main(language)

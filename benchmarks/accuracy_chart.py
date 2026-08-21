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
    ("ans_nograph_8b.jsonl", "baseline", False),
    ("ans_hybrid_grounded_8b.jsonl", "reader", True),
    (None, "reach", True),
]

#: A translated doc deserves a translated figure — a reader who chose 日本語
#: should not have to read the one image in English. Only the words move; every
#: number and every colour is the same file of data.
TEXT = {
    "en": {
        "title": "trikedb finds the answer for 89.3% of questions",
        "sub": "300 WebQSP questions · the same 300 at every bar",
        "reach": "trikedb found it<br>and put it in the context",
        "reader": "the 8B reader<br>then said it",
        "baseline": "the same reader<br>with no graph",
        "delta": "{d:+.0f} points from the graph",
        "loss": "−{d:.1f} the reader dropped",
    },
    "jp": {
        "title": "trikedb は89.3%の質問で正解を見つける",
        "sub": "WebQSP 300問 · どの棒も同じ300問",
        "reach": "trikedb が見つけて<br>文脈に入れた",
        "reader": "8Bのリーダーが<br>それを言えた",
        "baseline": "同じリーダー<br>グラフなし",
        "delta": "グラフで {d:+.0f} ポイント",
        "loss": "−{d:.1f} リーダーが落とした",
    },
    "zh": {
        "title": "trikedb 在 89.3% 的题目上找到了答案",
        "sub": "300 道 WebQSP 题 · 每根柱子都是同一批 300 题",
        "reach": "trikedb 找到了它<br>并放进上下文",
        "reader": "8B 阅读模型<br>把它说出来了",
        "baseline": "同一个阅读模型<br>没有图谱",
        "delta": "图谱带来 {d:+.0f} 个百分点",
        "loss": "−{d:.1f} 被阅读模型丢掉",
    },
}

#: Two gaps, and they mean opposite things: what the graph added, and what the
#: reader then lost. Both are differences a reader will not compute by eye.


def main(lang: str = "en") -> None:
    words = TEXT[lang]
    scored = {r["answers"]: r for r in json.loads((HERE / "accuracy_data.json").read_text())}

    values = []
    for name, key, graph in ROWS:
        value = REACH if name is None else scored[name]["hits_at_1"]
        values.append((words[key], value, graph))

    figure = go.Figure(go.Bar(
        y=[label for label, _, _ in values],
        x=[value for _, value, _ in values],
        orientation="h",
        marker=dict(color=[WITH_GRAPH if g else WITHOUT_GRAPH for _, _, g in values],
                    line=dict(color=SURFACE, width=2)),
        text=[f"{value:.1f}%" for _, value, _ in values],
        textposition="outside", cliponaxis=False,
        textfont=dict(size=17, color=INK),
        hovertemplate="%{y}<br>%{x:.1f}% of 300 questions<extra></extra>",
    ))

    reach, reader, baseline = REACH, values[1][1], values[0][1]
    figure.add_annotation(
        x=reader, y=0.5, xshift=132, showarrow=False,
        text=f"<b>{words['delta'].format(d=reader - baseline)}</b>",
        font=dict(size=17, color=WITH_GRAPH),
    )
    figure.add_annotation(
        x=reach, y=1.5, xshift=132, showarrow=False,
        text=words["loss"].format(d=reach - reader),
        font=dict(size=15, color=INK_MUTED),
    )

    figure.update_layout(
        title=dict(
            text=(f"{words['title']}<br>"
                  f"<span style='font-size:14px;color:{INK_MUTED}'>"
                  f"{words['sub']}</span>"),
            font=dict(size=22, color=INK), x=0.01, xanchor="left", y=0.93,
        ),
        bargap=0.5,
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(family="Helvetica, Arial, sans-serif", color=INK, size=15),
        xaxis=dict(range=[0, 100], showgrid=False, zeroline=False,
                   showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, linecolor=SURFACE),
        showlegend=False,
        margin=dict(l=10, r=290, t=100, b=16), width=1020, height=340,
    )
    out = HERE / ("accuracy.png" if lang == "en" else f"accuracy_{lang}.png")
    figure.write_image(out, scale=2)
    print(f"wrote {out}")


if __name__ == "__main__":
    import sys

    for language in (sys.argv[1:] or TEXT):
        main(language)

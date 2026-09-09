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
# Gold answer-string presence is a separate retrieval statistic.
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
        "title": "Gold strings appear in 89.3% of retrieved contexts",
        "sub": "WebQSP · n shown per bar · graph + grounding instructions",
        "reach": "<b>Answer-string presence</b>",
        "graph_8b": "qwen3:8b + graph", "alone_8b": "qwen3:8b alone",
        "graph_27b": "qwen3.8:27b + graph", "alone_27b": "qwen3.8:27b alone",
        "delta": "{d:+.0f} points: graph + grounding",
        "loss": "−{d:.1f}: the reader dropped what it was handed",
    },
    "jp": {
        "title": "89.3%の検索文脈に正解文字列がある",
        "sub": "WebQSP · 棒ごとにnを表示 · グラフ＋grounding指示",
        "reach": "<b>文脈中の正解文字列</b>",
        "graph_8b": "qwen3:8b + グラフ", "alone_8b": "qwen3:8b 単体",
        "graph_27b": "qwen3.8:27b + グラフ", "alone_27b": "qwen3.8:27b 単体",
        "delta": "グラフ＋指示で {d:+.0f} pt",
        "loss": "−{d:.1f}：渡したのにリーダーが落とした",
    },
    "zh": {
        "title": "89.3%的检索上下文包含答案字符串",
        "sub": "WebQSP · 每柱标明n · 图谱＋grounding指令",
        "reach": "<b>上下文包含答案字符串</b>",
        "graph_8b": "qwen3:8b + 图谱", "alone_8b": "qwen3:8b 单独",
        "graph_27b": "qwen3.8:27b + 图谱", "alone_27b": "qwen3.8:27b 单独",
        "delta": "图谱＋指令 {d:+.0f} pp",
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
    values = [(words[key] + f" · n={300 if name is None else scored[name]['n']}", REACH if name is None else scored[name]["hits_at_1"], kind)
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
        hovertemplate="%{y}<br>%{x:.1f}%<extra></extra>",
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
        margin=dict(l=10, r=330, t=100, b=16), width=1250, height=450,
    )
    out = HERE / ("accuracy.png" if lang == "en" else f"accuracy_{lang}.png")
    figure.write_image(out, scale=2)
    print(f"wrote {out}")


if __name__ == "__main__":
    import sys

    for language in (sys.argv[1:] or TEXT):
        main(language)

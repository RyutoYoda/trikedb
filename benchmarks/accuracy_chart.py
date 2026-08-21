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

#: One measure, so one hue — the blue Hits@1 wears in every figure here. The
#: pale tint is the same hue lightened, not a second colour: rows without a
#: graph are the baseline, and the eye should land on the rows with one.
WITH_GRAPH = "#2a78d6"
WITHOUT_GRAPH = "#a9c8ec"

#: filename -> (label, has a graph). Bottom to top, paired by model so each
#: model's before/after sits adjacent — interleaving the conditions put the two
#: halves of the comparison four rows apart, and a jump you have to hunt for is
#: a jump nobody sees.
ROWS = [
    ("ans_hybrid_grounded_27b.jsonl", "qwen3.8:27b + graph", True),
    ("ans_nograph_27b.jsonl", "qwen3.8:27b alone", False),
    ("ans_hybrid_grounded_8b.jsonl", "qwen3:8b + graph", True),
    ("ans_nograph_8b.jsonl", "qwen3:8b alone", False),
]

#: (lower row, upper row) whose gap gets a delta callout. The number this
#: benchmark exists to produce is a *difference*, and a difference the reader
#: has to compute by eye is one they will not compute.
DELTAS = [("ans_nograph_8b.jsonl", "ans_hybrid_grounded_8b.jsonl"),
          ("ans_nograph_27b.jsonl", "ans_hybrid_grounded_27b.jsonl")]


def main() -> None:
    scored = {r["answers"]: r for r in json.loads((HERE / "accuracy_data.json").read_text())}
    rows = [(label, graph, scored[name]) for name, label, graph in ROWS if name in scored]
    if not rows:
        raise SystemExit("no rows matched accuracy_data.json — check ROWS")

    figure = go.Figure(go.Bar(
        y=[label for label, _, _ in rows],
        x=[r["hits_at_1"] for _, _, r in rows],
        orientation="h",
        marker=dict(color=[WITH_GRAPH if g else WITHOUT_GRAPH for _, g, _ in rows],
                    line=dict(color=SURFACE, width=2)),
        text=[f"{r['hits_at_1']:.1f}%" for _, _, r in rows],
        textposition="outside", cliponaxis=False,
        textfont=dict(size=16, color=INK),
        hovertemplate="%{y}<br>Hits@1 %{x:.1f}%<extra></extra>",
    ))

    index = {name: i for i, (name, _, _) in enumerate(ROWS) if name in scored}
    for low, high in DELTAS:
        if low in index and high in index:
            gain = scored[high]["hits_at_1"] - scored[low]["hits_at_1"]
            figure.add_annotation(
                x=scored[high]["hits_at_1"], y=(index[low] + index[high]) / 2,
                text=f"<b>{gain:+.0f} points</b>", showarrow=False, xshift=112,
                font=dict(size=18, color=WITH_GRAPH),
            )

    figure.update_layout(
        title=dict(
            text=("A knowledge graph beats 3.4x the parameters<br>"
                  f"<span style='font-size:14px;color:{INK_MUTED}'>WebQSP · "
                  "Hits@1</span>"),
            font=dict(size=22, color=INK), x=0.01, xanchor="left", y=0.93,
        ),
        bargap=0.44,
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(family="Helvetica, Arial, sans-serif", color=INK, size=16),
        xaxis=dict(range=[0, 100], showgrid=False, zeroline=False,
                   showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, linecolor=SURFACE),
        showlegend=False,
        margin=dict(l=10, r=210, t=100, b=16), width=960, height=360,
    )
    out = HERE / "accuracy.png"
    figure.write_image(out, scale=2)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()

"""Render accuracy_data.json as a grouped bar chart.

    python benchmarks/webqsp_bench.py score bench_out/hybrid/eval_set.json \
        bench_out/ans_*.jsonl --json benchmarks/accuracy_data.json
    python benchmarks/accuracy_chart.py        # -> benchmarks/accuracy.png

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
GRID = "#e6e5e1"
RULE = "#c9c7c0"

#: Two slots, in fixed order. Validated on the light surface: worst adjacent
#: CVD dE 24.7 (protan), normal-vision dE 33.6, both above 3:1 against the
#: surface. Same pair the ceiling chart uses, so the two figures in this
#: directory do not disagree about what blue and orange mean.
HITS = "#2a78d6"
F1 = "#eb6834"

#: filename -> (row label, sub-label). Order here is the order of the chart,
#: bottom to top, so the story reads upward: no graph, then the graph as it
#: was, then the graph with the retrieval this benchmark ended up choosing.
ROWS = [
    ("ans_nograph_8b.jsonl", "no graph", "the model alone"),
    ("ans_1hopcvt_plain_8b.jsonl", "graph · 1-hop + CVT", "250 triples"),
    ("ans_hybrid_grounded_8b.jsonl", "graph · hybrid retrieval", "250 triples, grounded answers"),
]

#: Answer-in-context for the retrieval the top row uses, on the same 300
#: questions. It shares the axis with the bars because it is also a
#: percentage-of-questions, but it is a *different quantity* — what retrieval
#: put in front of the model, not what the model got right — and reading it as
#: a taller bar is the mistake the line invites. Hence the wording: "reached",
#: not a percentage score. The gap between it and the top bar is 38 questions
#: whose answer was in the context and did not come out of the model.
CEILING = 89.3
CEILING_LABEL = "retrieval reached the answer for 89.3% of questions"


def main() -> None:
    scored = {r["answers"]: r for r in json.loads((HERE / "accuracy_data.json").read_text())}
    rows = [(label, sub, scored[name]) for name, label, sub in ROWS if name in scored]
    if not rows:
        raise SystemExit("no rows matched accuracy_data.json — check the filenames in ROWS")

    # n per row, not one figure for the whole chart: a run stopped early is a
    # smaller n, and hiding that behind a single number would overstate it.
    y = [f"{label}<br><span style='font-size:11px;color:{INK_MUTED}'>{sub} · n={r['n']}</span>"
         for label, sub, r in rows]
    figure = go.Figure()
    figure.add_vline(x=CEILING, line=dict(color=RULE, width=2, dash="dot"))
    figure.add_annotation(
        x=CEILING, y=1.015, xref="x", yref="paper",
        text=CEILING_LABEL,
        showarrow=False, font=dict(size=11, color=INK_MUTED),
        xanchor="right", xshift=-6, yshift=1,
    )
    for key, name, color in (("hits_at_1", "Hits@1", HITS), ("f1", "F1", F1)):
        values = [r[key] for _, _, r in rows]
        figure.add_trace(go.Bar(
            y=y, x=values, name=name, orientation="h",
            marker=dict(color=color, line=dict(color=SURFACE, width=2)),
            text=[f"{v:.1f}" for v in values], textposition="outside",
            textfont=dict(size=12, color=INK_MUTED), cliponaxis=False,
            hovertemplate="%{y}<br>" + name + " %{x:.1f}%<extra></extra>",
        ))

    figure.update_layout(
        title=dict(
            text=("Does a knowledge graph help the model answer?<br>"
                  f"<span style='font-size:13px;color:{INK_MUTED}'>WebQSP test split · "
                  f"qwen3:8b, temperature 0 · Hits@1 and F1 per the RoG reference "
                  f"implementation</span>"),
            font=dict(size=19, color=INK), x=0.008, xanchor="left", y=0.955,
        ),
        barmode="group", bargap=0.34, bargroupgap=0.12,
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(family="Helvetica, Arial, sans-serif", color=INK_MUTED, size=12),
        xaxis=dict(range=[0, 100], gridcolor=GRID,
                   zeroline=False, linecolor=GRID, ticksuffix="%"),
        yaxis=dict(gridcolor=SURFACE, zeroline=False, linecolor=GRID),
        legend=dict(orientation="h", y=-0.16, x=0, bgcolor="rgba(0,0,0,0)",
                    font=dict(size=12)),
        margin=dict(l=10, r=64, t=104, b=52), width=1000, height=104 + 92 * len(rows),
    )
    out = HERE / "accuracy.png"
    figure.write_image(out, scale=2)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()

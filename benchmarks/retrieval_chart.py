"""Render retrieval_data.json as reach against context budget.

The one figure that says what retrieval selection is worth. Same 300 questions,
same everything above the retrieval layer — the only variable is which triples
get picked, and how many are allowed. What the plot shows is that the *method*
moves the line far more than the budget does, and that two of the three methods
sit on top of each other.

    python benchmarks/retrieval_chart.py     # -> benchmarks/retrieval.png

Reads benchmarks/retrieval_data.json: a list of {"method", "cap", "reach"}.

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

#: Categorical slots in fixed order, from the same theme the other figures in
#: this directory use. Validated on this surface: worst adjacent CVD dE 9.2
#: (deutan), worst normal-vision dE 27.6. The green sits at 2.74:1 against the
#: surface, under the 3:1 line, so the relief the validator requires is
#: mandatory rather than optional — hence a direct value label on every series
#: and the same numbers as a table in README.md.
#:
#: The last item is the y-offset for that label. The top two lines land 0.6pt
#: apart at 250 and their labels collided; pushing one up and one down is the
#: fix, and the collision is itself the finding.
SERIES = [
    ("hybrid", "hybrid — entity anchor + semantic", "#2a78d6", 11),
    ("semantic", "semantic search alone", "#eb6834", -11),
    ("1-hop + CVT", "1-hop + CVT (graph structure only)", "#1baf7a", 0),
]


def main() -> None:
    rows = json.loads((HERE / "retrieval_data.json").read_text())

    figure = go.Figure()
    for key, label, color, yshift in SERIES:
        points = sorted((r for r in rows if r["method"] == key), key=lambda r: r["cap"])
        if not points:
            continue
        single = len(points) == 1
        figure.add_trace(go.Scatter(
            x=[p["cap"] for p in points], y=[p["reach"] for p in points],
            name=label, mode="markers" if single else "lines+markers",
            line=dict(color=color, width=2),
            marker=dict(size=11, color=color, symbol="diamond" if single else "circle",
                        line=dict(color=SURFACE, width=2)),  # 2px surface ring
            hovertemplate=(label + "<br>%{x} triples → %{y:.1f}% reach<extra></extra>"),
        ))
        # Direct-label the end of each line so identity is never colour-alone.
        last = points[-1]
        figure.add_annotation(
            x=last["cap"], y=last["reach"], text=f"<b>{last['reach']:.1f}%</b>",
            showarrow=False, xshift=34, yshift=yshift,
            font=dict(size=12, color=INK_MUTED),
        )

    figure.update_layout(
        title=dict(
            text=("What is the retrieval method worth?<br>"
                  f"<span style='font-size:13px;color:{INK_MUTED}'>share of 300 "
                  "WebQSP questions whose gold answer is inside the retrieved "
                  "context · same questions, same budget</span>"),
            font=dict(size=19, color=INK), x=0.008, xanchor="left", y=0.94,
        ),
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(family="Helvetica, Arial, sans-serif", color=INK_MUTED, size=12),
        xaxis=dict(title="context budget (triples)", gridcolor=GRID, zeroline=False,
                   linecolor=GRID, range=[60, 290], dtick=50),
        yaxis=dict(title="answer present in context", range=[60, 100],
                   gridcolor=GRID, zeroline=False, linecolor=GRID, ticksuffix="%"),
        legend=dict(orientation="h", y=-0.22, x=0, bgcolor="rgba(0,0,0,0)",
                    font=dict(size=12)),
        margin=dict(l=10, r=64, t=104, b=88), width=1000, height=540,
    )
    out = HERE / "retrieval.png"
    figure.write_image(out, scale=2)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()

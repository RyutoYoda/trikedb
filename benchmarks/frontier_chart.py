"""Render frontier_data.json as accuracy against seconds per question.

Two numbers decide whether a graph is worth attaching to a model: how much
more often it is right, and how much longer it takes. Plotting them against
each other says what a bar chart of either alone cannot — whether the accuracy
is worth the latency, and where the trade stops paying.

    python benchmarks/frontier_chart.py     # -> benchmarks/frontier.png

Reads benchmarks/frontier_data.json: a list of
{"label", "sub", "secs", "hits_at_1", "f1", "n"}.

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

#: Same two slots as accuracy_chart.py and ceiling_chart.py, so blue and orange
#: mean the same thing in every figure in this directory. Validated on this
#: surface: worst adjacent CVD dE 24.7 (protan), normal-vision dE 33.6, both
#: above 3:1 against the surface.
HITS = "#2a78d6"
F1 = "#eb6834"


def main() -> None:
    rows = json.loads((HERE / "frontier_data.json").read_text())
    rows.sort(key=lambda r: r["secs"])

    figure = go.Figure()
    for key, name, color in (("hits_at_1", "Hits@1", HITS), ("f1", "F1", F1)):
        figure.add_trace(go.Scatter(
            x=[r["secs"] for r in rows], y=[r[key] for r in rows],
            name=name, mode="lines+markers",
            line=dict(color=color, width=2),
            marker=dict(size=11, color=color,
                        line=dict(color=SURFACE, width=2)),  # 2px surface ring
            hovertemplate=("%{customdata}<br>" + name +
                           " %{y:.1f}%<br>%{x:.1f} s per question<extra></extra>"),
            customdata=[r["label"] for r in rows],
        ))

    # One direct label per point, on the Hits@1 series only — labelling both
    # series doubles the text for no information, since a point's identity is
    # its x position.
    for r in rows:
        figure.add_annotation(
            x=r["secs"], y=r["hits_at_1"],
            text=f"<b>{r['label']}</b><br>{r['sub']}",
            showarrow=False, yshift=34, font=dict(size=11, color=INK_MUTED),
            bgcolor=SURFACE, borderpad=2,
        )

    figure.update_layout(
        title=dict(
            text=("Is the graph worth the latency it costs?<br>"
                  f"<span style='font-size:13px;color:{INK_MUTED}'>WebQSP test "
                  "split, 300 questions · qwen3:8b, temperature 0 · Hits@1 and "
                  "F1 per the RoG reference implementation</span>"),
            font=dict(size=19, color=INK), x=0.008, xanchor="left", y=0.94,
        ),
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(family="Helvetica, Arial, sans-serif", color=INK_MUTED, size=12),
        xaxis=dict(title="seconds per question", gridcolor=GRID, zeroline=False,
                   linecolor=GRID, rangemode="tozero"),
        yaxis=dict(title="percent", range=[0, 100], gridcolor=GRID,
                   zeroline=False, linecolor=GRID, ticksuffix="%"),
        legend=dict(orientation="h", y=-0.2, x=0, bgcolor="rgba(0,0,0,0)",
                    font=dict(size=12)),
        margin=dict(l=10, r=40, t=110, b=76), width=1000, height=560,
    )
    out = HERE / "frontier.png"
    figure.write_image(out, scale=2)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()

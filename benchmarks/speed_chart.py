"""Render where the time goes in one answered question.

    python benchmarks/speed_chart.py          # -> benchmarks/speed.png

One stacked bar. The point is a ratio, and a ratio is the one thing a stacked
bar says better than a table: of the 22.5 s a graph-grounded answer costs,
trikedb spends 0.59 s finding the facts and the reader spends the rest reading
them. Numbers come from `webqsp_bench.py latency` and from timing the retrieval
directly; both are medians on an idle machine.

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

TRIKEDB = "#2a78d6"
READER = "#c9d9ee"


def main() -> None:
    data = json.loads((HERE / "speed_data.json").read_text())
    total = data["trikedb_secs"] + data["reader_secs"]

    figure = go.Figure()
    for name, secs, color, label in (
        ("trikedb", data["trikedb_secs"], TRIKEDB,
         f"<b>trikedb {data['trikedb_secs']:.2f} s</b><br>load the graph, retrieve the facts"),
        (data["reader"], data["reader_secs"], READER,
         f"<b>{data['reader']} {data['reader_secs']:.1f} s</b><br>read the context, write the answer"),
    ):
        figure.add_trace(go.Bar(
            x=[secs], y=["one question"], orientation="h", name=name,
            marker=dict(color=color, line=dict(color=SURFACE, width=2)),
            hovertemplate=name + " %{x:.2f} s<extra></extra>",
        ))
        # trikedb's slice is 3% of the width, so its label cannot sit inside
        # it or centre on it without running off the left edge. Point at it.
        if name == "trikedb":
            figure.add_annotation(
                x=secs / 2, y=0, text=label, font=dict(size=15, color=TRIKEDB),
                showarrow=True, arrowhead=0, arrowwidth=1.5, arrowcolor=TRIKEDB,
                ax=90, ay=72, xanchor="left", align="left",
            )
        else:
            figure.add_annotation(
                x=data["trikedb_secs"] + secs / 2, y=0, text=label,
                showarrow=False, font=dict(size=15, color=INK), align="center",
            )

    figure.update_layout(
        title=dict(
            text=("trikedb is 3% of the time an answer takes<br>"
                  f"<span style='font-size:14px;color:{INK_MUTED}'>median seconds "
                  f"for one WebQSP question, 250 triples of context</span>"),
            font=dict(size=22, color=INK), x=0.01, xanchor="left", y=0.9,
        ),
        barmode="stack", bargap=0.7,
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(family="Helvetica, Arial, sans-serif", color=INK, size=15),
        xaxis=dict(range=[0, total * 1.02], showgrid=False, zeroline=False,
                   ticksuffix=" s", tickfont=dict(color=INK_MUTED)),
        yaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
        showlegend=False,
        margin=dict(l=16, r=16, t=104, b=112), width=960, height=300,
    )
    out = HERE / "speed.png"
    figure.write_image(out, scale=2)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()

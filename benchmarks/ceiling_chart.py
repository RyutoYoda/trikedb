"""Render ceiling_data.json as a line chart.

    python benchmarks/ceiling_bench.py > benchmarks/ceiling_data.json
    python benchmarks/ceiling_chart.py            # -> benchmarks/ceiling.png

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
RULE = "#c9c7c0"        # reference lines: darker than the grid, still recessive

#: Categorical slots 1-5, in fixed order. Validated for the adjacent pairlist:
#: worst CVD dE 9.1, worst normal-vision dE 19.6. Three of the five sit below
#: 3:1 against the surface, so the relief rule applies — hence the direct
#: labels on every line, and the table in README.md.
#: `label_it` picks which lines get a direct label. Five series with five
#: labels collided — the two middle curves sit on top of each other — and the
#: guidance caps direct labels at four anyway, so only the three that carry the
#: story are labelled. The legend still names all five.
SERIES = [
    ("open_json", "open a .json graph", "#2a78d6", True),
    ("sparql_2hop", "SPARQL, 2-hop join", "#eb6834", True),
    ("open_yaml", "open the same graph as .yaml", "#1baf7a", False),
    ("to_html", "generate the HTML workbench", "#eda100", False),
    ("search", "semantic search()", "#e87ba4", True),
]


def main() -> None:
    rows = json.loads((HERE / "ceiling_data.json").read_text())
    x = [r["triples"] for r in rows]

    figure = go.Figure()

    # Reference bands first, so the data draws on top of them. One second is
    # where an operation stops feeling immediate; ten is where people stop
    # waiting for it.
    for y, label in ((1_000, "1s — no longer instant"),
                     (10_000, "10s — nobody waits")):
        figure.add_hline(y=y, line=dict(color=RULE, width=2, dash="dot"))
        # Placed by hand rather than with annotation_position, which put the
        # text outside the plot area where it was clipped away.
        figure.add_annotation(
            x=math.log10(1_100), y=math.log10(y), text=label,
            xanchor="left", yanchor="bottom", yshift=4, showarrow=False,
            font=dict(size=11, color=INK_MUTED), bgcolor=SURFACE, borderpad=2,
        )

    for key, label, color, label_it in SERIES:
        ys = [r[key] for r in rows]
        if any(v is None for v in ys):
            continue
        figure.add_trace(go.Scatter(
            x=x, y=ys, name=label, mode="lines+markers",
            line=dict(color=color, width=2),
            marker=dict(size=8, color=color,
                        line=dict(color=SURFACE, width=2)),  # 2px surface ring
            hovertemplate="%{x:,} triples<br>%{y:.0f} ms<extra>" + label + "</extra>",
        ))
        if label_it:
            # Direct label at the right end: identity is never colour alone,
            # and it is the relief the contrast WARN requires.
            figure.add_annotation(
                x=math.log10(x[-1]), y=math.log10(ys[-1]),
                text=label, xanchor="left", xshift=12, showarrow=False,
                font=dict(size=12, color=INK_MUTED),
            )

    figure.update_layout(
        title=dict(
            text="Each operation hits its own ceiling<br>"
                 "<span style='font-size:13px;color:%s'>trikedb · one synthetic "
                 "graph, six sizes · median of three</span>" % INK_MUTED,
            font=dict(size=19, color=INK), x=0.008, xanchor="left",
            y=0.97, yanchor="top",
        ),
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(family="Helvetica, Arial, sans-serif", color=INK_MUTED, size=12),
        xaxis=dict(
            type="log", title="triples in the graph",
            gridcolor=GRID, zeroline=False, linecolor=GRID,
            tickvals=[1_000, 3_000, 10_000, 30_000, 100_000, 300_000],
            ticktext=["1k", "3k", "10k", "30k", "100k", "300k"],
            range=[math.log10(600), math.log10(260_000)],
        ),
        yaxis=dict(
            type="log", title="milliseconds",
            gridcolor=GRID, zeroline=False, linecolor=GRID,
            tickvals=[1, 10, 100, 1_000, 10_000, 100_000],
            ticktext=["1ms", "10ms", "100ms", "1s", "10s", "100s"],
        ),
        legend=dict(orientation="h", yanchor="top", y=-0.16, x=0.008,
                    bgcolor="rgba(0,0,0,0)", font=dict(size=12)),
        margin=dict(l=78, r=210, t=96, b=104),
        width=1020, height=600,
    )

    out = HERE / "ceiling.png"
    figure.write_image(out, scale=2)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()

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
    ("open_json", "#2a78d6", True),
    ("sparql_2hop", "#eb6834", True),
    ("open_yaml", "#1baf7a", False),
    ("to_html", "#eda100", False),
    ("search", "#e87ba4", True),
]

#: A translated doc deserves a translated figure. Only the words move; the
#: data, the colours and which lines get a direct label are identical.
TEXT = {
    "en": {
        "title": "Each operation hits its own ceiling",
        "sub": "trikedb · one synthetic graph, six sizes · median of three",
        "x": "triples in the graph", "y": "milliseconds",
        "open_json": "open a .json graph", "sparql_2hop": "SPARQL, 2-hop join",
        "open_yaml": "open the same graph as .yaml",
        "to_html": "generate the HTML workbench", "band_1s": "1s — no longer instant", "band_10s": "10s — nobody waits",
        "search": "semantic search()",
    },
    "jp": {
        "title": "機能ごとに天井が違う",
        "sub": "trikedb · 合成グラフ1つを6サイズ · 3回の中央値",
        "x": "グラフのトリプル数", "y": "ミリ秒",
        "open_json": ".json のグラフを開く", "sparql_2hop": "SPARQL 2ホップ結合",
        "open_yaml": "同じグラフを .yaml で開く",
        "to_html": "HTML ワークベンチを生成", "band_1s": "1秒 — もう即時ではない", "band_10s": "10秒 — 誰も待たない",
        "search": "意味検索 search()",
    },
    "zh": {
        "title": "每个操作都有自己的天花板",
        "sub": "trikedb · 一个合成图谱的六种规模 · 三次取中位数",
        "x": "图谱中的三元组数", "y": "毫秒",
        "open_json": "打开 .json 图谱", "sparql_2hop": "SPARQL 两跳连接",
        "open_yaml": "以 .yaml 打开同一个图谱",
        "to_html": "生成 HTML 工作台", "band_1s": "1 秒 — 不再是瞬时", "band_10s": "10 秒 — 没人会等",
        "search": "语义检索 search()",
    },
}


def main(lang: str = "en") -> None:
    words = TEXT[lang]
    rows = json.loads((HERE / "ceiling_data.json").read_text())
    x = [r["triples"] for r in rows]

    figure = go.Figure()

    # Reference bands first, so the data draws on top of them. One second is
    # where an operation stops feeling immediate; ten is where people stop
    # waiting for it.
    for y, label in ((1_000, words["band_1s"]), (10_000, words["band_10s"])):
        figure.add_hline(y=y, line=dict(color=RULE, width=2, dash="dot"))
        # Placed by hand rather than with annotation_position, which put the
        # text outside the plot area where it was clipped away.
        figure.add_annotation(
            x=math.log10(1_100), y=math.log10(y), text=label,
            xanchor="left", yanchor="bottom", yshift=4, showarrow=False,
            font=dict(size=11, color=INK_MUTED), bgcolor=SURFACE, borderpad=2,
        )

    for key, color, label_it in SERIES:
        label = words[key]
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
            text=f"{words['title']}<br>"
                 f"<span style='font-size:13px;color:{INK_MUTED}'>"
                 f"{words['sub']}</span>",
            font=dict(size=19, color=INK), x=0.008, xanchor="left",
            y=0.97, yanchor="top",
        ),
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(family="Helvetica, Arial, sans-serif", color=INK_MUTED, size=12),
        xaxis=dict(
            type="log", title=words["x"],
            gridcolor=GRID, zeroline=False, linecolor=GRID,
            tickvals=[1_000, 3_000, 10_000, 30_000, 100_000, 300_000],
            ticktext=["1k", "3k", "10k", "30k", "100k", "300k"],
            range=[math.log10(600), math.log10(260_000)],
        ),
        yaxis=dict(
            type="log", title=words["y"],
            gridcolor=GRID, zeroline=False, linecolor=GRID,
            tickvals=[1, 10, 100, 1_000, 10_000, 100_000],
            ticktext=["1ms", "10ms", "100ms", "1s", "10s", "100s"],
        ),
        legend=dict(orientation="h", yanchor="top", y=-0.16, x=0.008,
                    bgcolor="rgba(0,0,0,0)", font=dict(size=12)),
        margin=dict(l=78, r=210, t=96, b=104),
        width=1020, height=600,
    )

    out = HERE / ("ceiling.png" if lang == "en" else f"ceiling_{lang}.png")
    figure.write_image(out, scale=2)
    print(f"wrote {out}")


if __name__ == "__main__":
    import sys

    for language in (sys.argv[1:] or TEXT):
        main(language)

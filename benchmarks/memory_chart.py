"""Render memory_data.json as a cost-quality plot: tokens against accuracy.

    python benchmarks/memory_bench.py sweep bench_out/memory \
        --json benchmarks/memory_data.json
    python benchmarks/memory_chart.py            # -> benchmarks/memory.png

One panel, not two. An earlier version stacked tokens over accuracy on a
shared x axis of corpus size, and it asked the reader to hold a point in the
top panel against the point below it and do the division — which is the whole
finding, performed in the reader's head. Here both quantities are position:
tokens across, accuracy up, so **up and to the left is better** and "the same
answers for fewer tokens" becomes a place on the page rather than arithmetic.

It also separates what the line chart merged. Plotted against corpus size the
grep control sat within a few hundred tokens of the graph and the two curves
overlapped; plotted against accuracy they are far apart vertically, which is
the difference that actually matters.

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
RULE = "#c9c7c0"

#: Blue is the file, orange the graph, green the text-retrieval control — the
#: same meanings these hues carry in every other figure in this directory.
MD = "#2a78d6"
GRAPH = "#eb6834"
MD_GREP = "#1baf7a"

TEXT = {
    "en": {
        "title": "Up and to the left is better: fewer tokens, better answers",
        "sub": ("WebQSP · 100 questions · qwen3:8b · one corpus delivered as a "
                "CLAUDE.md / AGENTS.md and as a trikedb graph · each point is "
                "one corpus size, 492 to 3,998 facts"),
        "x": "prompt tokens per question", "y": "Hits@1",
        "md": "the whole CLAUDE.md / AGENTS.md",
        "graph": "trikedb, 15 facts returned",
        "md_grep": "grep the file, 15 lines",
        "tuned": "trikedb at 492 facts,<br>returning more",
        "none": "no context at all — {floor:.0f}%",
        "grow": "the file grows →",
        "flat": "every corpus size, 492 to 3,998 facts,<br>lands in this one spot",
    },
    "jp": {
        "title": "左上が良い：トークンは少なく、精度は高い",
        "sub": ("WebQSP · 100問 · qwen3:8b · 同一コーパスを CLAUDE.md / AGENTS.md "
                "と trikedb グラフで渡した · 点1つがコーパスサイズ1つ、492〜3,998件"),
        "x": "1問あたりのプロンプトトークン", "y": "Hits@1",
        "md": "CLAUDE.md / AGENTS.md 全文",
        "graph": "trikedb、15件返す",
        "md_grep": "ファイルを grep、15行",
        "tuned": "492件のとき<br>返す件数を増やす",
        "none": "文脈なし — {floor:.0f}%",
        "grow": "ファイルは育つ →",
        "flat": "492〜3,998件、どのサイズも<br>この一点に集まる",
    },
    "zh": {
        "title": "越靠左上越好：token 更少，答得更准",
        "sub": ("WebQSP · 100 题 · qwen3:8b · 同一份语料分别以 CLAUDE.md / "
                "AGENTS.md 和 trikedb 图谱交付 · 每个点是一种语料规模，492〜3,998 条"),
        "x": "每题的提示词 token 数", "y": "Hits@1",
        "md": "整份 CLAUDE.md / AGENTS.md",
        "graph": "trikedb，返回 15 条",
        "md_grep": "grep 文件，15 行",
        "tuned": "492 条语料下<br>增加返回条数",
        "none": "没有任何上下文 — {floor:.0f}%",
        "grow": "文件不断变大 →",
        "flat": "492〜3,998 条，任何规模<br>都落在这一个位置",
    },
}


def main(lang: str = "en") -> None:
    rows = json.loads((HERE / "memory_data.json").read_text())
    warm = [r for r in rows if "/cold" not in r["condition"]]
    floor = next((r["hits_at_1"] for r in warm if r["condition"] == "none"), 0)
    words = {k: v.format(floor=floor) if "{floor" in v else v
             for k, v in TEXT[lang].items()}

    def series(name):
        return sorted((r for r in warm if r["condition"] == name),
                      key=lambda r: r["corpus_triples"])

    figure = go.Figure()

    # Each condition is a path through the plane as the corpus grows. The
    # file's runs down and to the right — dearer *and* worse — and the graph's
    # barely moves, which is the finding stated as a shape rather than a ratio.
    for name, color, label in (
        ("md_grep", MD_GREP, lambda r, i, n: ""),
        ("md", MD, lambda r, i, n: f"{r['corpus_triples']:,}"),
        ("graph", GRAPH, lambda r, i, n: ""),
    ):
        points = series(name)
        if not points:
            continue
        figure.add_trace(go.Scatter(
            x=[r["median_prompt_tokens"] for r in points],
            y=[r["hits_at_1"] for r in points],
            mode="lines+markers+text", name=words[name],
            legendrank={"md": 1, "graph": 2, "md_grep": 3}[name],
            text=[label(r, i, len(points)) for i, r in enumerate(points)],
            textposition="bottom center", cliponaxis=False,
            textfont=dict(size=12, color=color),
            line=dict(color=color, width=2),
            marker=dict(size=13, color=color,
                        line=dict(color=SURFACE, width=1.5)),
            customdata=[r["corpus_triples"] for r in points],
            hovertemplate=(f"{words[name]}<br>%{{customdata:,}} facts"
                           "<br>%{x:,} tokens<br>%{y:.1f}%<extra></extra>"),
        ))

    # The knob, drawn only where it was measured. Returning more facts buys
    # accuracy the file cannot buy at any price — it is already sending
    # everything — and these points sit above *and* left of the file's best,
    # which is the one comparison in the figure that is unambiguous.
    tuned = sorted((r for r in warm if r["condition"].startswith("graph@")
                    and r["corpus_triples"] == 492),
                   key=lambda r: r["median_prompt_tokens"])
    base = next((r for r in series("graph") if r["corpus_triples"] == 492), None)
    if tuned and base:
        chain = [base] + tuned
        figure.add_trace(go.Scatter(
            x=[r["median_prompt_tokens"] for r in chain],
            y=[r["hits_at_1"] for r in chain],
            mode="lines+markers", showlegend=False,
            line=dict(color=GRAPH, width=1.5, dash="dot"),
            marker=dict(size=13, color=SURFACE,
                        line=dict(color=GRAPH, width=2.5)),
            hovertemplate=("492 facts<br>%{x:,} tokens"
                           "<br>%{y:.1f}%<extra></extra>"),
        ))
        figure.add_annotation(
            x=math.log10(tuned[-1]["median_prompt_tokens"]),
            y=tuned[-1]["hits_at_1"], yshift=30,
            text=words["tuned"], showarrow=False,
            font=dict(size=12, color=GRAPH))

    figure.add_hline(y=floor, line=dict(color=RULE, width=1, dash="dot"))
    figure.add_annotation(x=0.995, xref="x domain", y=floor, yshift=12,
                          text=words["none"], showarrow=False,
                          xanchor="right", font=dict(size=12, color=INK_MUTED))

    md_points = series("md")
    if len(md_points) > 1:
        figure.add_annotation(
            x=math.log10(md_points[-1]["median_prompt_tokens"]),
            y=md_points[-1]["hits_at_1"], yshift=-2, xshift=12,
            xanchor="left", text=words["grow"], showarrow=False,
            font=dict(size=12, color=MD))
    graph_points = series("graph")
    if graph_points:
        # Drawn with an arrow, because the grep control clusters in the same
        # corner: a floating caption there could be read as belonging to
        # either series, which is the one thing this figure must not be
        # ambiguous about.
        figure.add_annotation(
            x=math.log10(sum(r["median_prompt_tokens"] for r in graph_points)
                         / len(graph_points)),
            y=sum(r["hits_at_1"] for r in graph_points) / len(graph_points),
            text=words["flat"], showarrow=True, arrowhead=0, arrowwidth=1.2,
            arrowcolor=GRAPH, ax=64, ay=76, xanchor="left",
            font=dict(size=12, color=GRAPH))

    priced = [r for r in warm if r["condition"] != "none"]
    figure.update_layout(
        title=dict(
            text=(f"{words['title']}<br>"
                  f"<span style='font-size:13px;color:{INK_MUTED}'>"
                  f"{words['sub']}</span>"),
            font=dict(size=21, color=INK), x=0.01, xanchor="left", y=0.94),
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(family="Helvetica, Arial, sans-serif", color=INK, size=14),
        legend=dict(orientation="h", y=-0.17, x=0, font=dict(size=13)),
        xaxis=dict(
            type="log", gridcolor=GRID, zeroline=False,
            title=dict(text=words["x"], font=dict(size=14)),
            # Explicit ticks: across two decades plotly labels the minor ones
            # too, and the axis reads "5 2 5 2" instead of round numbers.
            tickvals=[300, 1_000, 3_000, 10_000, 30_000],
            ticktext=["300", "1k", "3k", "10k", "30k"],
            range=[math.log10(0.62 * min(r["median_prompt_tokens"] for r in priced)),
                   math.log10(2.6 * max(r["median_prompt_tokens"] for r in priced))],
        ),
        yaxis=dict(gridcolor=GRID, zeroline=False, ticksuffix="%",
                   title=dict(text=words["y"], font=dict(size=14)),
                   range=[floor - 4, 95]),
        margin=dict(l=78, r=40, t=110, b=96), width=1000, height=620,
    )
    out = HERE / ("memory.png" if lang == "en" else f"memory_{lang}.png")
    figure.write_image(out, scale=2)
    print(f"wrote {out}")


if __name__ == "__main__":
    import sys

    for language in (sys.argv[1:] or TEXT):
        main(language)

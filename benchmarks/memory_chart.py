"""Render memory_data.json as one line: tokens per question, as knowledge grows.

    python benchmarks/memory_bench.py sweep bench_out/memory \
        --json benchmarks/memory_data.json
    python benchmarks/memory_chart.py            # -> benchmarks/memory.png

Two series, one axis pair, a number printed on every point. Nothing else.

Two earlier versions tried to carry tokens and accuracy in one figure — first
as stacked panels, then as a token-quality scatter — and both failed the test
that matters, which is whether a reader who is not the author can say what
they are looking at within a few seconds. The scatter failed in a specific
way worth recording: the series had different numbers of points (three sizes
for the file, five for the graph), the graph's five landed within 35 tokens of
each other and so read as one blob, and only the file's points carried
labels. Every one of those was defensible and together they were unreadable.

The axis is tokens, and the wording stays tokens. Tokens are not cost: a
token's price depends on which cache band it lands in, and the same count can
differ severalfold in money. This benchmark counts tokens and does not measure
money, so calling the axis "cost" would be claiming something it cannot show.

So this figure answers one question — **does the token count grow with the
project?** — and the accuracy numbers live in the table in README.md, where a
reader is already reading numbers. `md_grep` is left out for the same reason:
it settles a different question (is it the retrieval or the graph) and the
table settles it in two numbers.

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

#: Blue is the file, orange the graph — the same meanings these hues carry in
#: every other figure in this directory.
MD = "#2a78d6"
GRAPH = "#eb6834"

TEXT = {
 "en": {"title":"Prompt tokens: full file versus up to 15 retrieved facts", "sub":"Historical qwen3:8b · 100 gold-curated questions · medians · both axes logarithmic", "x":"facts in corpus", "y":"prompt tokens per question", "md":"whole file (unflagged samples)", "graph":"trikedb, up to 15 facts", "stop":"Larger file runs flagged for<br>possible truncation; excluded"},
 "jp": {"title":"全文と最大15件の検索結果：入力トークンの比較", "sub":"過去のqwen3:8b · 正解を使って構成した100問 · 中央値 · 両軸は対数", "x":"コーパスの事実数", "y":"1問の入力トークン", "md":"全文（切詰め疑いなし）", "graph":"trikedb、最大15件", "stop":"これより大きい全文は<br>切詰めの疑いがあるため除外"},
 "zh": {"title":"全文与最多15条检索事实的输入token比较", "sub":"历史qwen3:8b · 使用答案构建的100题 · 中位数 · 双对数轴", "x":"语料事实数", "y":"每题输入token", "md":"全文（未标记疑似截断）", "graph":"trikedb，最多15条", "stop":"更大的全文疑似截断<br>已从图中排除"},
}


def main(lang: str = "en") -> None:
    words = TEXT[lang]
    rows = json.loads((HERE / "memory_data.json").read_text())
    warm = [r for r in rows if "/cold" not in r["condition"]]

    def series(name):
        return sorted((r for r in warm if r["condition"] == name and not r.get("truncated")),
                      key=lambda r: r["corpus_triples"])

    figure = go.Figure()
    for name, color, side in (("md", MD, "top center"),
                              ("graph", GRAPH, "bottom center")):
        points = series(name)
        figure.add_trace(go.Scatter(
            x=[r["corpus_triples"] for r in points],
            y=[r["median_prompt_tokens"] for r in points],
            mode="lines+markers+text", name=words[name],
            # Every point, not just the ends. Five numbers along a flat line
            # is exactly the message — they are all the same number — and a
            # reader who has to trust an annotation for that will not.
            text=[f"{r['median_prompt_tokens']:,}" for r in points],
            textposition=side, cliponaxis=False,
            textfont=dict(size=13, color=color),
            line=dict(color=color, width=3),
            marker=dict(size=11, color=color,
                        line=dict(color=SURFACE, width=1.5)),
            hovertemplate=(f"{words[name]}<br>%{{x:,}} facts"
                           "<br>%{y:,} tokens<extra></extra>"),
        ))

    sizes = sorted({r["corpus_triples"] for r in warm
                    if r["condition"] != "none"})
    md_points = series("md")
    if md_points and md_points[-1]["corpus_triples"] < max(sizes):
        # Why the blue line stops. Without it the reader's first guess is that
        # the measurement is missing, when in fact the configuration is: the
        # rendered file is larger than the window the model has.
        figure.add_vline(x=md_points[-1]["corpus_triples"],
                         line=dict(color=RULE, width=1, dash="dash"))
        figure.add_annotation(
            x=math.log10(md_points[-1]["corpus_triples"]), xshift=12,
            y=math.log10(md_points[-1]["median_prompt_tokens"]), yshift=-30,
            xanchor="left", text=words["stop"], showarrow=False,
            align="left", font=dict(size=12, color=INK_MUTED))

    figure.update_layout(
        title=dict(
            text=(f"{words['title']}<br>"
                  f"<span style='font-size:13px;color:{INK_MUTED}'>"
                  f"{words['sub']}</span>"),
            font=dict(size=22, color=INK), x=0.01, xanchor="left", y=0.95),
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(family="Helvetica, Arial, sans-serif", color=INK, size=14),
        legend=dict(orientation="h", y=-0.18, x=0, font=dict(size=14)),
        xaxis=dict(type="log", showgrid=False, zeroline=False, linecolor=RULE,
                   tickvals=sizes, ticktext=[f"{s:,}" for s in sizes],
                   title=dict(text=words["x"], font=dict(size=14))),
        yaxis=dict(type="log", gridcolor=GRID, zeroline=False,
                   title=dict(text=words["y"], font=dict(size=14)),
                   # Explicit ticks: across two decades plotly labels the minor
                   # ones too, and the axis reads "5 2 5 2" instead of numbers.
                   tickvals=[300, 1_000, 3_000, 10_000, 30_000],
                   ticktext=["300", "1k", "3k", "10k", "30k"],
                   range=[math.log10(250), math.log10(60_000)]),
        margin=dict(l=84, r=44, t=132, b=96), width=1000, height=580,
    )
    out = HERE / ("memory.png" if lang == "en" else f"memory_{lang}.png")
    figure.write_image(out, scale=2)
    print(f"wrote {out}")


if __name__ == "__main__":
    import sys

    for language in (sys.argv[1:] or TEXT):
        main(language)

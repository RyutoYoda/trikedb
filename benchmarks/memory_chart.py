"""Render memory_data.json as the two panels the comparison comes down to.

    python benchmarks/memory_bench.py sweep bench_out/memory \
        --json benchmarks/memory_data.json
    python benchmarks/memory_chart.py            # -> benchmarks/memory.png

Tokens on top, accuracy underneath, one shared x axis — the size of the
project's knowledge. That order is the argument: the panels answer "what does
each question cost" and then "did the cheap one give up any accuracy for it",
and reversing them turns a result into a pair of unrelated charts. The token
axis is logarithmic because the gap is multiplicative and a linear axis draws
the graph's line flat against zero, which reads as "no data".

Needs plotly and kaleido:  pip install plotly kaleido
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_MUTED = "#52514e"
GRID = "#e6e5e1"
RULE = "#c9c7c0"

#: The same two hues the accuracy chart uses for the same meaning — blue is
#: the condition without a graph, orange is the one with. `md_grep` is the
#: honest middle (retrieval, but over text) and gets a third hue rather than a
#: tint of either, because reading it as "a lighter kind of markdown" is
#: exactly the wrong reading: it is the control that isolates what the *graph*
#: contributes on top of retrieving at all.
MD = "#2a78d6"
GRAPH = "#eb6834"
MD_GREP = "#1baf7a"

#: Two lines, not three. `md_grep` is a control and its numbers matter, but on
#: this figure it sits within a few hundred tokens of the graph's line, so the
#: top panel showed two curves where the legend promised three and the reader
#: had to work out which was missing. It lives in the table in README.md.
SERIES = [("md", MD, "top center"), ("graph", GRAPH, "bottom center")]
PLOTTED = ("md", "graph", "md_grep")

#: A translated doc deserves a translated figure. Only the words move; every
#: number and every colour is the same file of data.
TEXT = {
    "en": {
        "title": "The file's cost grows with the project. The graph's does not.",
        "sub": ("WebQSP · 100 questions · qwen3:8b · the identical corpus "
                "delivered as a CLAUDE.md / AGENTS.md and as a trikedb graph"),
        "x": "facts in the project's knowledge",
        "y1": "prompt tokens per question", "y2": "Hits@1",
        "md": "the whole CLAUDE.md / AGENTS.md in the prompt",
        "md_grep": "matching lines of AGENTS.md",
        "graph": "trikedb retrieval, 15 facts",
        "none": "no context at all",
        "gap": "<b>{cut:.1f}% fewer</b> tokens<br>at 15 facts returned",
        "window": "↑ past here the file no longer fits the window",
    },
    "jp": {
        "title": "ファイルのコストはプロジェクトと共に増える。グラフは増えない。",
        "sub": ("WebQSP · 100問 · qwen3:8b · 同一のコーパスを "
                "CLAUDE.md / AGENTS.md と trikedb グラフの両方で渡した"),
        "x": "プロジェクトの知識に入っている事実の数",
        "y1": "1問あたりのプロンプトトークン", "y2": "Hits@1",
        "md": "CLAUDE.md / AGENTS.md 全文をプロンプトに",
        "md_grep": "AGENTS.md の該当行だけ",
        "graph": "trikedb で検索、15件",
        "none": "文脈なし",
        "gap": "トークン <b>{cut:.1f}% 削減</b><br>（15件返した場合）",
        "window": "↑ これ以上はファイルが窓に入らない",
    },
    "zh": {
        "title": "文件的成本随项目增长，图谱的不会。",
        "sub": ("WebQSP · 100 题 · qwen3:8b · 同一份语料分别以 "
                "CLAUDE.md / AGENTS.md 和 trikedb 图谱交付"),
        "x": "项目知识中的事实条数",
        "y1": "每题的提示词 token 数", "y2": "Hits@1",
        "md": "把整个 CLAUDE.md / AGENTS.md 放进提示",
        "md_grep": "只放 AGENTS.md 中匹配的行",
        "graph": "trikedb 检索，15 条",
        "none": "没有任何上下文",
        "gap": "token <b>减少 {cut:.1f}%</b><br>（返回 15 条时）",
        "window": "↑ 再大文件就装不进上下文窗口",
    },
}


def main(lang: str = "en") -> None:
    rows = json.loads((HERE / "memory_data.json").read_text())
    warm = [r for r in rows if "/cold" not in r["condition"]]
    floor = next((r["hits_at_1"] for r in warm if r["condition"] == "none"), None)
    by = {name: sorted((r for r in warm if r["condition"] == name),
                       key=lambda r: r["corpus_triples"])
          for name in PLOTTED}

    # The bracket's ratio is raw tokens at a fixed retrieval size, taken at
    # the largest corpus where the file still fits the window. It is not a
    # like-for-like saving and the title no longer claims it is: at the
    # smallest corpus this retrieval size scores five points below the file,
    # so the same ratio there would be comparing a cheap wrong answer against
    # an expensive right one. README.md carries the accuracy-matched table.
    fitting = [r for r in by["md"] if not r["truncated"]] or by["md"]
    biggest = fitting[-1]
    paired = next(r for r in by["graph"]
                  if r["corpus_triples"] == biggest["corpus_triples"])
    ratio = biggest["median_prompt_tokens"] / paired["median_prompt_tokens"]
    # A percentage, because "78x" makes the reader work out which direction is
    # cheaper. "98.7% fewer" does not.
    cut = 100 * (1 - paired["median_prompt_tokens"]
                 / biggest["median_prompt_tokens"])
    words = {k: v.format(ratio=ratio, cut=cut) if "{" in v else v
             for k, v in TEXT[lang].items()}

    # Every size any condition reached, not just the file arm's. The file
    # stops before the graph does — that is the finding — and taking the
    # ticks from it leaves the last two corpus sizes unlabelled.
    sizes = sorted({r["corpus_triples"] for r in warm})

    figure = make_subplots(rows=2, cols=1, shared_xaxes=True,
                           vertical_spacing=0.08, row_heights=[0.52, 0.48])

    for name, color, side in SERIES:
        points = by[name]
        if not points:
            continue
        x = [r["corpus_triples"] for r in points]

        def ends(values, fmt):
            """The value written on the first and last point, nothing between.

            Labelling every point stacks five numbers along a line that is
            almost flat; labelling none makes the reader decode a log axis to
            learn that 409 and 375 are the same number twice.
            """
            return [fmt(v) if i in (0, len(values) - 1) else ""
                    for i, v in enumerate(values)]

        tokens = [r["median_prompt_tokens"] for r in points]
        figure.add_trace(go.Scatter(
            x=x, y=tokens, mode="lines+markers+text", name=words[name],
            legendgroup=name, text=ends(tokens, lambda v: f"{v:,}"),
            textposition=side, textfont=dict(size=13, color=color),
            cliponaxis=False,
            line=dict(color=color, width=3), marker=dict(size=9, color=color),
            hovertemplate="%{x:,} facts<br>%{y:,} prompt tokens<extra></extra>",
        ), row=1, col=1)
        # A truncated prompt is drawn hollow. It is still the real score of a
        # real configuration — a file that outgrew the window — but it is a
        # different failure from getting lost in a file that fit, and one
        # marker for both would merge them.
        hits = [r["hits_at_1"] for r in points]
        figure.add_trace(go.Scatter(
            x=x, y=hits, mode="lines+markers+text",
            name=words[name], legendgroup=name, showlegend=False,
            text=ends(hits, lambda v: f"{v:.0f}%"),
            textposition=side, textfont=dict(size=13, color=color),
            cliponaxis=False,
            line=dict(color=color, width=3),
            marker=dict(size=11, color=[SURFACE if r["truncated"] else color
                                        for r in points],
                        line=dict(color=color, width=3)),
            hovertemplate="%{x:,} facts<br>%{y:.1f}% Hits@1<extra></extra>",
        ), row=2, col=1)

    # The gap itself, drawn as a bracket between the two lines at the widest
    # point that still fits. A reader will not divide two log-axis positions
    # by eye, and that division is the entire result.
    # On a log axis these two take different units, which is not a thing you
    # find out from the rendering: a shape is placed from the data value, an
    # annotation from its log10. Give both the same number and one of them
    # lands somewhere the eye reads as "the code did not run".
    low, high = (paired["median_prompt_tokens"], biggest["median_prompt_tokens"])
    figure.add_shape(type="line", x0=biggest["corpus_triples"],
                     x1=biggest["corpus_triples"], y0=low, y1=high,
                     line=dict(color=INK_MUTED, width=1.5), row=1, col=1)
    figure.add_annotation(
        x=math.log10(biggest["corpus_triples"]), xshift=10,
        y=(math.log10(low) + math.log10(high)) / 2,
        text=words["gap"], showarrow=False, xanchor="left",
        font=dict(size=19, color=INK), row=1, col=1)

    if floor is not None:
        figure.add_hline(y=floor, row=2, col=1,
                         line=dict(color=RULE, width=1, dash="dot"))
        figure.add_annotation(x=0.995, xref="x domain", y=floor, yshift=11,
                              text=f"{words['none']} — {floor:.0f}%",
                              showarrow=False, xanchor="right",
                              font=dict(size=13, color=INK_MUTED), row=2, col=1)

    # Where the file arm stops. It is not missing data: past this size the
    # rendered file no longer fits the reader's context window, and the arm
    # cannot be run at all rather than merely running worse.
    if biggest["corpus_triples"] < max(sizes):
        figure.add_annotation(
            x=math.log10(biggest["corpus_triples"]), xshift=14,
            y=math.log10(biggest["median_prompt_tokens"]), yshift=-2,
            text=words["window"], showarrow=False, xanchor="left",
            font=dict(size=12, color=MD), row=1, col=1)

    figure.update_layout(
        title=dict(
            text=(f"{words['title']}<br>"
                  f"<span style='font-size:13px;color:{INK_MUTED}'>"
                  f"{words['sub']}</span>"),
            font=dict(size=22, color=INK), x=0.01, xanchor="left", y=0.955,
        ),
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(family="Helvetica, Arial, sans-serif", color=INK, size=14),
        legend=dict(orientation="h", y=-0.13, x=0, font=dict(size=14)),
        margin=dict(l=78, r=30, t=112, b=68), width=1000, height=700,
    )
    # A log x axis, because the tiers are multiplicative (495, 1195, 1647,
    # 2282, 4113) and on a linear axis the first three crowd into the left
    # quarter — which is where the whole comparison happens.
    #
    # Applied to *both* rows, not just the labelled one. `shared_xaxes` links
    # the two axes' ranges but not their scale type, so setting it on row 2
    # alone leaves row 1 linear: the panels then plot the same corpus sizes at
    # different horizontal positions, and the two halves of one finding stop
    # lining up — visible only if you notice the leftmost markers disagree.
    figure.update_xaxes(type="log", showgrid=False, zeroline=False,
                        linecolor=RULE)
    figure.update_xaxes(tickvals=sizes, ticktext=[f"{s:,}" for s in sizes],
                        title=dict(text=words["x"], font=dict(size=14)),
                        row=2, col=1)
    # Clamped to the data. Left to itself the axis runs down to 5 tokens to
    # reach a round decade, and three quarters of the panel is then empty
    # space under the flat line.
    # Explicit ticks. Left alone across two and a half decades plotly labels
    # the minor ticks too, so the axis reads "5 2 5 2 5 2" between the
    # decades and every number on it has to be decoded.
    figure.update_yaxes(title=dict(text=words["y1"], font=dict(size=13)),
                        type="log", gridcolor=GRID, zeroline=False,
                        range=[math.log10(230), math.log10(90_000)],
                        tickvals=[300, 1_000, 3_000, 10_000, 30_000],
                        ticktext=["300", "1k", "3k", "10k", "30k"],
                        row=1, col=1)
    figure.update_yaxes(title=dict(text=words["y2"], font=dict(size=13)),
                        range=[0, 100], ticksuffix="%", gridcolor=GRID,
                        zeroline=False, row=2, col=1)
    out = HERE / ("memory.png" if lang == "en" else f"memory_{lang}.png")
    figure.write_image(out, scale=2)
    print(f"wrote {out}")


if __name__ == "__main__":
    import sys

    for language in (sys.argv[1:] or TEXT):
        main(language)

"""Historical independent latency measurements; never subtract medians."""

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

#: A translated doc deserves a translated figure. Only the words move.
TEXT = {
 "en": {"title": "Retrieval and model request time, measured separately", "sub": "Historical medians · retrieval n=30; model requests n=20 · not an end-to-end breakdown", "trikedb": "Graph load + retrieval", "reader": "qwen3:8b HTTP request", "unit": " s"},
 "jp": {"title": "検索とモデル応答の時間を別々に測定", "sub": "過去の中央値 · 検索30問、モデル20問 · 合計時間の内訳ではありません", "trikedb": "グラフ読込＋検索", "reader": "qwen3:8b HTTP応答", "unit": " 秒"},
 "zh": {"title": "分别测量检索与模型请求时间", "sub": "历史中位数 · 检索30题，模型20题 · 不是端到端时间分解", "trikedb": "图谱载入＋检索", "reader": "qwen3:8b HTTP请求", "unit": " 秒"},
}


def main(lang: str = "en") -> None:
    words = TEXT[lang]
    data = json.loads((HERE / "speed_data.json").read_text())
    values = [data["reader_secs"], data["trikedb_secs"]]
    figure = go.Figure(go.Bar(
        x=values, y=[words["reader"], words["trikedb"]], orientation="h",
        marker_color=[READER, TRIKEDB],
        text=[f"{v:.2f}{words['unit']}" for v in values], textposition="outside",
        cliponaxis=False,
    ))
    figure.update_layout(
        title=dict(text=words["title"] + "<br><sup>" + words["sub"] + "</sup>",
                   x=0.02, font_size=22),
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE, showlegend=False,
        font=dict(family="Arial, sans-serif", size=16, color=INK),
        xaxis=dict(range=[0, max(values)*1.18], ticksuffix=words["unit"]),
        margin=dict(l=235, r=45, t=100, b=55), width=1100, height=370,
    )
    out = HERE / ("speed.png" if lang == "en" else f"speed_{lang}.png")
    figure.write_image(out, scale=2)
    print(f"wrote {out}")


if __name__ == "__main__":
    import sys

    for language in (sys.argv[1:] or TEXT):
        main(language)

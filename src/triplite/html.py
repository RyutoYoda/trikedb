"""Interactive HTML export using vis-network (loaded from CDN)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Union

PALETTE = [
    "#4f8ef7", "#f7784f", "#2fbf71", "#b04ff7", "#f7c34f",
    "#4ff7e3", "#f74f9e", "#8ef74f", "#f74f4f", "#4f6af7",
]

_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>__TITLE__</title>
<script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
<style>
  body { margin: 0; font-family: -apple-system, "Segoe UI", sans-serif; background: #1a1c22; color: #e8e8ea; }
  #graph { width: 100vw; height: 100vh; }
  #panel { position: fixed; top: 12px; left: 12px; background: #24262eE6; border: 1px solid #3a3d47;
           border-radius: 10px; padding: 12px 16px; max-width: 320px; z-index: 10; }
  #panel h1 { font-size: 15px; margin: 0 0 8px; }
  #legend div { font-size: 12px; margin: 3px 0; }
  #legend span { display: inline-block; width: 22px; height: 4px; border-radius: 2px;
                 margin-right: 8px; vertical-align: middle; }
  #search { width: 100%; box-sizing: border-box; margin-top: 8px; padding: 6px 8px; border-radius: 6px;
            border: 1px solid #3a3d47; background: #1a1c22; color: #e8e8ea; }
  #stats { font-size: 11px; color: #9a9daa; margin-top: 8px; }
</style>
</head>
<body>
<div id="panel">
  <h1>__TITLE__</h1>
  <div id="legend"></div>
  <input id="search" placeholder="search nodes...">
  <div id="stats">__STATS__</div>
</div>
<div id="graph"></div>
<script>
const NODES = __NODES__;
const EDGES = __EDGES__;
const PREDICATES = __PREDICATES__;

const legend = document.getElementById("legend");
for (const [p, color] of Object.entries(PREDICATES)) {
  const row = document.createElement("div");
  row.innerHTML = `<span style="background:${color}"></span>${p}`;
  legend.appendChild(row);
}

const nodes = new vis.DataSet(NODES);
const edges = new vis.DataSet(EDGES);
const network = new vis.Network(
  document.getElementById("graph"),
  { nodes, edges },
  {
    physics: { solver: "forceAtlas2Based", stabilization: { iterations: 150 } },
    nodes: { shape: "dot", font: { color: "#e8e8ea", size: 14 },
             borderWidth: 1, color: { border: "#3a3d47", background: "#5a83b8",
             highlight: { border: "#ffffff", background: "#7aa3d8" } } },
    edges: { arrows: "to", font: { color: "#9a9daa", size: 10, strokeWidth: 0 },
             smooth: { type: "continuous" } },
    interaction: { hover: true },
  }
);

document.getElementById("search").addEventListener("input", (e) => {
  const q = e.target.value.toLowerCase();
  const hit = NODES.filter((n) => q && n.id.toLowerCase().includes(q)).map((n) => n.id);
  network.selectNodes(hit);
  if (hit.length) network.focus(hit[0], { scale: 1.2, animation: true });
});
</script>
</body>
</html>
"""


def to_html(db, path: Union[str, Path, None] = None, title: str = "triplite graph") -> str:
    """Render the graph to a self-contained interactive HTML page."""
    predicates = db.predicates()
    colors = {p: PALETTE[i % len(PALETTE)] for i, p in enumerate(predicates)}

    degree: dict = {}
    for t in db:
        degree[t.s] = degree.get(t.s, 0) + 1
        degree[t.o] = degree.get(t.o, 0) + 1

    nodes = [
        {"id": n, "label": n, "value": degree.get(n, 1)}
        for n in db.nodes()
    ]
    edges = []
    for t in db:
        edge = {
            "from": t.s,
            "to": t.o,
            "label": t.p,
            "color": {"color": colors[t.p], "highlight": "#ffffff"},
        }
        if t.attrs:
            edge["title"] = "\n".join(f"{k}: {v}" for k, v in t.attrs.items())
        if t.attrs.get("deprecated"):
            edge["dashes"] = True
        edges.append(edge)

    stats = f"{len(nodes)} nodes · {len(edges)} edges · {len(predicates)} predicates"
    html = (
        _TEMPLATE
        .replace("__TITLE__", title)
        .replace("__STATS__", stats)
        .replace("__NODES__", json.dumps(nodes, ensure_ascii=False))
        .replace("__EDGES__", json.dumps(edges, ensure_ascii=False))
        .replace("__PREDICATES__", json.dumps(colors, ensure_ascii=False))
    )
    if path is not None:
        Path(path).write_text(html, encoding="utf-8")
    return html

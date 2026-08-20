"""Interactive HTML export: vis-network graph + in-browser SPARQL console.

The exported page is a small single-file "workbench" over the graph:
a searchable network view, a right-hand detail panel showing every
property of the clicked node (URLs become links — this is the RDF
promise: keep attaching facts as properties), a bottom bar of change
events, and a SPARQL console powered by Oxigraph compiled to WASM
(loaded from CDN on first use, never hand-rolled).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Union

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
  :root { --bg: #14161b; --panel: #1e2129; --border: #32363f; --text: #e8e8ea; --dim: #9a9daa; }
  body.light { --bg: #f4f5f8; --panel: #ffffff; --border: #d7dae2; --text: #1b1e26; --dim: #646a78; }
  body { margin: 0; font-family: -apple-system, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); overflow: hidden; }
  #graph { position: fixed; inset: 52px 0 46px 0; }

  #header { position: fixed; top: 0; left: 0; right: 0; height: 52px; z-index: 20;
            display: flex; align-items: center; gap: 10px; padding: 0 14px; box-sizing: border-box;
            background: var(--panel); border-bottom: 1px solid var(--border); }
  #header h1 { font-size: 15px; margin: 0; white-space: nowrap; }
  #subtitle { font-size: 11px; color: var(--dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  /* labels slide horizontally when they outgrow the bar instead of vanishing */
  #legend { display: flex; gap: 8px; margin-left: 6px; overflow-x: auto; overflow-y: hidden;
            flex-shrink: 1; min-width: 40px; max-width: 46vw; scrollbar-width: thin; }
  #legend::-webkit-scrollbar { height: 6px; }
  #legend::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
  .lg { font-size: 10px; color: var(--dim); white-space: nowrap; }
  .lg.toggle { cursor: pointer; user-select: none; }
  .lg.off { opacity: .35; }
  .lg b { display: inline-block; width: 16px; height: 3px; border-radius: 2px; vertical-align: middle; margin-right: 4px; }
  .lg i { display: inline-block; width: 10px; height: 10px; border-radius: 3px; border: 2px solid;
          vertical-align: middle; margin-right: 4px; background: var(--bg); font-style: normal;
          font-size: 9px; line-height: 10px; text-align: center; font-weight: 700; }
  #spacer { flex: 1; }
  #search { width: 210px; padding: 6px 9px; border-radius: 7px; border: 1px solid var(--border);
            background: var(--bg); color: var(--text); font-size: 12px; }
  .btn { padding: 6px 11px; border-radius: 7px; border: 1px solid var(--border); background: var(--bg);
         color: var(--text); font-size: 12px; cursor: pointer; white-space: nowrap; }
  .btn:hover { border-color: #5a83b8; }
  .btn.active { background: #2c4a6e; border-color: #5a83b8; }
  body.light .btn.active { background: #dbe6f7; }
  /* compact select-all / clear controls next to a group of toggles */
  .selbtn { font-size: 10px; padding: 3px 7px; border-radius: 6px; border: 1px solid var(--border);
            background: var(--bg); color: var(--dim); cursor: pointer; white-space: nowrap; }
  .selbtn:hover { border-color: #5a83b8; color: var(--text); }
  #legend-ctl { display: none; gap: 6px; flex-shrink: 0; align-items: center; }

  #sparql { position: fixed; top: 52px; left: 0; right: 0; z-index: 19; display: none;
            background: var(--panel); border-bottom: 1px solid var(--border); padding: 10px 14px; }
  #sparql.open { display: block; }
  /* never cover the detail panel (its close button stays visible and unambiguous) */
  body.detail-open #sparql { right: 330px; }
  #sparql textarea { width: 100%; box-sizing: border-box; height: 74px; resize: vertical;
            background: var(--bg); color: var(--text); border: 1px solid var(--border); border-radius: 7px;
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; padding: 8px; }
  #sparql .row { display: flex; gap: 10px; align-items: center; margin-top: 7px; }
  #sparql .hint { font-size: 11px; color: var(--dim); }
  #results { max-height: 200px; overflow: auto; margin-top: 8px; }
  #results table { border-collapse: collapse; font-size: 12px; font-family: ui-monospace, Menlo, monospace; }
  #results th, #results td { border: 1px solid var(--border); padding: 4px 10px; text-align: left; }
  #results th { color: #7aa3d8; }
  #results .err { color: #f7784f; font-size: 12px; white-space: pre-wrap; }

  #detail { position: fixed; top: 52px; right: 0; bottom: 46px; width: 330px; z-index: 18;
            background: var(--panel); border-left: 1px solid var(--border); padding: 14px 16px;
            box-sizing: border-box; overflow-y: auto; display: none; }
  #detail.open { display: block; }
  #detail h2 { font-size: 15px; margin: 0 40px 4px 0; word-break: break-all;
               font-family: ui-monospace, Menlo, monospace; }
  #detail .close { position: absolute; top: 10px; right: 12px; }
  #detail h3 { font-size: 11px; color: var(--dim); text-transform: uppercase; letter-spacing: .06em;
               margin: 16px 0 6px; }
  .rel { padding: 7px 9px; border: 1px solid var(--border); border-radius: 8px; margin: 6px 0;
         font-size: 12px; word-break: break-all; }
  .pred { display: inline-block; padding: 1px 7px; border-radius: 10px; font-size: 10px;
          font-family: ui-monospace, Menlo, monospace; color: #14161b; font-weight: 700; margin-right: 6px; }
  .rel .attr { color: var(--dim); font-size: 11px; margin-top: 4px;
               font-family: ui-monospace, Menlo, monospace; }
  .rel .attr a { color: #7aa3d8; }
  a.nodelink { color: var(--text); cursor: pointer; text-decoration: underline dotted; }
  .deprecated { opacity: .55; }

  #events { position: fixed; bottom: 0; left: 0; right: 0; height: 46px; z-index: 20;
            display: flex; gap: 8px; align-items: center; padding: 0 14px; box-sizing: border-box;
            background: var(--panel); border-top: 1px solid var(--border); overflow-x: auto; }
  #events .tag { font-size: 11px; color: var(--dim); white-space: nowrap; }
  .chip { border: 1px solid #7a4444; color: #f0a0a0; border-radius: 7px; padding: 4px 9px;
          font-size: 11px; white-space: nowrap; cursor: pointer; font-family: ui-monospace, Menlo, monospace; }
  .chip:hover { border-color: #f7784f; }
  .chip b { color: #f7784f; font-weight: 700; margin-right: 6px; }
  body.light .chip { border-color: #d89b9b; color: #a33a30; }
  body.light .chip b { color: #c73e1d; }
  body.light .chip:hover { border-color: #c73e1d; }
</style>
</head>
<body>
<div id="header">
  <h1>&#x1F996; __TITLE__</h1>
  <div id="subtitle">__SUBTITLE__</div>
  <div id="legend"></div>
  <span id="legend-ctl"></span>
  <div id="spacer"></div>
  <input id="search" placeholder="search nodes...">
  <span id="search-count" style="font-size: 11px; color: var(--dim); min-width: 34px;"></span>
  <button class="btn" id="btn-tosparql" title="turn this search into an editable SPARQL query">text2sparql</button>
  <button class="btn" id="btn-sparql">SPARQL</button>
  <button class="btn" id="btn-fit">Fit</button>
  <button class="btn" id="btn-theme" title="toggle light/dark">light</button>
</div>

<div id="graphbar" style="position: fixed; top: 52px; left: 0; right: 0; z-index: 18; display: none;
     gap: 8px; align-items: center; padding: 7px 14px; background: var(--panel);
     border-bottom: 1px solid var(--border); overflow-x: auto;"></div>

<div id="sparql">
  <textarea id="sparql-input" spellcheck="false">SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 20</textarea>
  <div class="row">
    <button class="btn" id="btn-run">Run</button>
    <span class="hint">SPARQL 1.1 via Oxigraph (WASM) &middot; prefixes <code>t:</code> and <code>rdf:</code> are pre-bound &middot; edge attrs are reified (<code>?st rdf:subject ?s ; t:note ?n</code>) &middot; matching nodes get highlighted</span>
  </div>
  <div id="results"></div>
</div>

<div id="detail">
  <button class="btn close" id="btn-close">&times;</button>
  <div id="detail-body"></div>
</div>

<div id="graph"></div>

<div id="events">
  <span class="tag">&#x26A0; events</span>
</div>

<script>
const TRIPLES = __TRIPLES__;
const PREDICATES = __PREDICATES__;
const NODES_META = __NODES_META__;
const NODE_TYPES = __NODE_TYPES__;
const NT = __NT__;
const EVENT_PREDICATES = __EVENT_PREDICATES__;
const GRAPHS = __GRAPHS__;   // workspace: {graph name: color}; {} otherwise
const BASE = "urn:trikedb:";

// which member graph(s) each node belongs to (workspace unions only)
const nodeGraphs = {};
TRIPLES.forEach(t => {
  if (t.graph) {
    (nodeGraphs[t.s] ??= new Set()).add(t.graph);
    (nodeGraphs[t.o] ??= new Set()).add(t.graph);
  }
});
// grid anchors: each member graph gets a cell so projects tile side by side
const gnames = Object.keys(GRAPHS);
const anchors = {};
if (gnames.length > 1) {
  const cols = Math.ceil(Math.sqrt(gnames.length)), CELL = 1900;
  gnames.forEach((g, i) => { anchors[g] = { x: (i % cols) * CELL, y: Math.floor(i / cols) * CELL }; });
}
const jitter = (id, salt) => {
  let h = salt;
  for (const c of id) h = (h * 31 + c.charCodeAt(0)) % 997;
  return h - 498;
};

// ---------------------------------------------------------------- graph
const ids = [...new Set([...TRIPLES.flatMap(t => [t.s, t.o]), ...Object.keys(NODES_META)])];
const degree = {};
TRIPLES.forEach(t => { degree[t.s] = (degree[t.s] || 0) + 1; degree[t.o] = (degree[t.o] || 0) + 1; });
const wrap = (id) => id.length > 14 ? id.replace(/([_\\-])/g, "$1\\n").replace(/\\n$/, "") : id;
const eventNodes = new Set(TRIPLES.filter(t => EVENT_PREDICATES.includes(t.p)).map(t => t.o));
// vis-network requires levels on ALL nodes or NONE — honor explicit level
// props only when every non-event node has one (events go one past the max)
const explicitLevels = ids.filter(id => !eventNodes.has(id)).map(id => (NODES_META[id] || {}).level);
const useLevels = explicitLevels.length > 0 && explicitLevels.every(l => typeof l === "number");
const maxLevel = useLevels ? Math.max(...explicitLevels) : 0;
const nodes = new vis.DataSet(ids.map(id => {
  if (eventNodes.has(id)) {
    const n = { id, label: id.length > 26 ? id.slice(0, 26) + "\\u2026" : id, shape: "diamond", size: 9,
                color: { border: "#f74f4f", background: "#3a1f1f" }, font: { color: "#f0a0a0", size: 10 } };
    if (useLevels) n.level = maxLevel + 1;
    return n;
  }
  const meta = NODES_META[id] || {};
  const n = { id, label: meta.label ? String(meta.label) : wrap(id), value: degree[id] || 1 };
  const tc = NODE_TYPES[meta.type];
  if (tc) n.color = { border: tc, background: "#1e2129",
                      highlight: { border: "#ffffff", background: "#2c4a6e" } };
  if (useLevels) n.level = meta.level;
  const g0 = nodeGraphs[id] ? [...nodeGraphs[id]][0] : null;
  if (g0 && anchors[g0]) {   // seed each project into its grid cell
    n.x = anchors[g0].x + jitter(id, 7) * 1.4;
    n.y = anchors[g0].y + jitter(id, 13) * 1.4;
  }
  return n;
}));
const edges = new vis.DataSet(TRIPLES.map((t, i) => {
  const e = { id: i, from: t.s, to: t.o, label: t.p,
              color: { color: PREDICATES[t.p], highlight: "#ffffff" } };
  const attrs = Object.entries(t).filter(([k]) => !["s", "p", "o"].includes(k));
  if (attrs.length) e.title = attrs.map(([k, v]) => k + ": " + v).join("\\n");
  if (t.deprecated || EVENT_PREDICATES.includes(t.p)) e.dashes = true;
  return e;
}));
const FLOW_OPTS = {
  layout: { hierarchical: { enabled: true, direction: "LR", sortMethod: "directed",
                            levelSeparation: 240, nodeSpacing: 95, treeSpacing: 130 } },
  physics: { enabled: false },
};
const FREE_OPTS = {
  layout: { hierarchical: { enabled: false } },
  physics: { enabled: true, solver: "forceAtlas2Based", stabilization: { iterations: 150 } },
};
let flow = __FLOW_DEFAULT__;
const network = new vis.Network(document.getElementById("graph"), { nodes, edges }, {
  ...(flow ? FLOW_OPTS : FREE_OPTS),
  nodes: { shape: "box", font: { color: "#e8e8ea", size: 12, face: "Menlo, monospace" },
           color: { border: "#5a83b8", background: "#1e2129",
                    highlight: { border: "#ffffff", background: "#2c4a6e" } },
           shapeProperties: { borderRadius: 6 }, margin: 8 },
  edges: { arrows: "to", font: { color: "#9a9daa", size: 9, strokeWidth: 0 },
           smooth: { type: "cubicBezier", forceDirection: "horizontal", roundness: 0.4 } },
  interaction: { hover: true },
});

// ------------------------------------- header legend (click = filter)
const hiddenTypes = new Set();
const hiddenPreds = new Set();
const hiddenGraphs = new Set();
function refreshVisibility() {
  nodes.update(ids.map(id => {
    const meta = NODES_META[id] || {};
    const byType = meta.type && hiddenTypes.has(meta.type);
    const byGraph = nodeGraphs[id] && [...nodeGraphs[id]].every(g => hiddenGraphs.has(g));
    return { id, hidden: !!(byType || byGraph) };
  }));
  edges.update(TRIPLES.map((t, i) => ({
    id: i, hidden: !!(hiddenPreds.has(t.p) || (t.graph && hiddenGraphs.has(t.graph))),
  })));
}
const legend = document.getElementById("legend");
const typeEls = {};
function setTypeHidden(ty, off) {   // reused by per-label clicks and the all/none controls
  off ? hiddenTypes.add(ty) : hiddenTypes.delete(ty);
  const el = typeEls[ty];
  el.classList.toggle("off", off);
  el.querySelector("i").innerHTML = off ? "" : "&#10003;";
}
for (const [ty, color] of Object.entries(NODE_TYPES)) {
  const el = document.createElement("span");
  el.className = "lg toggle";
  el.title = `show/hide ${ty} nodes`;
  el.innerHTML = `<i style="border-color:${color};color:${color}">&#10003;</i>${ty}`;
  el.onclick = () => { setTypeHidden(ty, !hiddenTypes.has(ty)); refreshVisibility(); };
  typeEls[ty] = el;
  legend.appendChild(el);
}
for (const [p, color] of Object.entries(PREDICATES)) {
  const el = document.createElement("span");
  el.className = "lg toggle";
  el.title = `show/hide ${p} edges`;
  el.innerHTML = `<b style="background:${color}"></b>${p}`;
  el.onclick = () => {
    hiddenPreds.has(p) ? hiddenPreds.delete(p) : hiddenPreds.add(p);
    el.classList.toggle("off", hiddenPreds.has(p));
    refreshVisibility();
  };
  legend.appendChild(el);
}
// select-all / clear for the node-type checkboxes above (predicate bars are left alone)
const typeNames = Object.keys(NODE_TYPES);
if (typeNames.length) {
  const ctl = document.getElementById("legend-ctl");
  ctl.style.display = "flex";
  const mk = (label, off, title) => {
    const b = document.createElement("button");
    b.className = "selbtn"; b.textContent = label; b.title = title;
    b.onclick = () => { typeNames.forEach(ty => setTypeHidden(ty, off)); refreshVisibility(); };
    ctl.appendChild(b);
  };
  mk("all", false, "show all node types");
  mk("none", true, "hide all node types");
}
// ------------------------------------------------- workspace graph filter
const graphChips = {};
function setGraphHidden(g, hidden) {   // reused by per-chip clicks and the all/none controls
  hidden ? hiddenGraphs.add(g) : hiddenGraphs.delete(g);
  graphChips[g].classList.toggle("active", !hidden);
}
if (gnames.length > 0) {
  const bar = document.getElementById("graphbar");
  bar.style.display = "flex";
  const tag = document.createElement("span");
  tag.className = "lg"; tag.textContent = "workspace:";
  tag.title = "this view is a workspace: a read-only union of member graphs — click a chip to show/hide one";
  bar.appendChild(tag);
  for (const g of gnames) {
    const chip = document.createElement("button");
    chip.className = "btn active";
    chip.title = `show/hide member graph "${g}"`;
    chip.innerHTML = `<b style="display:inline-block;width:9px;height:9px;border-radius:5px;background:${GRAPHS[g]};margin-right:6px;vertical-align:middle"></b>${g}`;
    chip.onclick = () => { setGraphHidden(g, !hiddenGraphs.has(g)); refreshVisibility(); };
    graphChips[g] = chip;
    bar.appendChild(chip);
  }
  const mk = (label, hidden, title) => {
    const b = document.createElement("button");
    b.className = "selbtn"; b.textContent = label; b.title = title;
    b.style.marginLeft = label === "all" ? "6px" : "0";
    b.onclick = () => { gnames.forEach(g => setGraphHidden(g, hidden)); refreshVisibility(); };
    bar.appendChild(b);
  };
  mk("all", false, "show all member graphs");
  mk("none", true, "hide all member graphs");
  document.getElementById("sparql").style.top = "94px";
}

// ---------------------------------------------------------- theme toggle
const THEMES = {
  dark:  { font: "#e8e8ea", nodeBg: "#1e2129", edgeFont: "#9a9daa", hlBg: "#2c4a6e",
           hlBorder: "#ffffff", edgeHl: "#ffffff", evFont: "#f0a0a0", evBg: "#3a1f1f" },
  light: { font: "#1b1e26", nodeBg: "#ffffff", edgeFont: "#646a78", hlBg: "#dbe6f7",
           hlBorder: "#5a83b8", edgeHl: "#1b1e26", evFont: "#b3261e", evBg: "#fdeaea" },
};
function applyTheme(name) {
  const th = THEMES[name];
  document.body.classList.toggle("light", name === "light");
  // vis caches the style of selected elements: deselect, restyle, reselect
  const sel = network.getSelection();
  network.unselectAll();
  network.setOptions({ nodes: { font: { color: th.font } },
                       edges: { font: { color: th.edgeFont } } });
  nodes.update(nodes.get().map(n => {
    const ev = n.shape === "diamond";
    const c = n.color || {};
    return { id: n.id,
             font: { ...(n.font || {}), color: ev ? th.evFont : th.font },
             color: { ...c, background: ev ? th.evBg : th.nodeBg,
                      highlight: { border: th.hlBorder, background: th.hlBg } } };
  }));
  edges.update(TRIPLES.map((t, i) => ({
    id: i, color: { color: PREDICATES[t.p], highlight: th.edgeHl } })));
  network.setSelection(sel);
  try { localStorage.setItem("trikedb-theme", name); } catch (e) {}
  document.getElementById("btn-theme").textContent = name === "light" ? "dark" : "light";
}
document.getElementById("btn-theme").onclick = () =>
  applyTheme(document.body.classList.contains("light") ? "dark" : "light");
try {
  if (localStorage.getItem("trikedb-theme") === "light") applyTheme("light");
} catch (e) {}

document.getElementById("btn-fit").onclick = () => network.fit({ animation: true });
// full-text search: node ids + labels + node properties + edge attributes
// + free-text objects (attached to their subjects). Enter cycles matches.
const searchIndex = {};
ids.forEach(id => {
  const parts = [id];
  const meta = NODES_META[id];
  if (meta) for (const v of Object.values(meta)) parts.push(String(v));
  searchIndex[id] = parts.join(" ").toLowerCase();
});
TRIPLES.forEach(t => {
  const extra = [];
  for (const [k, v] of Object.entries(t)) {
    if (k !== "s" && k !== "p" && k !== "o") extra.push(String(v));
  }
  if (/\\s/.test(t.o)) extra.push(t.o);   // 自由文オブジェクトは主語からも引けるように
  if (extra.length) {
    const blob = " " + extra.join(" ").toLowerCase();
    searchIndex[t.s] += blob;
    searchIndex[t.o] += blob;
  }
});
const searchBox = document.getElementById("search");
const searchCount = document.getElementById("search-count");
let searchState = { q: "", hits: [], i: -1 };
searchBox.addEventListener("input", (e) => {
  const q = e.target.value.toLowerCase();
  searchState = { q, hits: q ? ids.filter(id => searchIndex[id].includes(q)) : [], i: -1 };
  searchCount.textContent = q ? `${searchState.hits.length}` : "";
});
// bridge: turn the current search into an editable SPARQL query
document.getElementById("btn-tosparql").onclick = () => {
  const q = searchBox.value.trim().toLowerCase().replace(/"/g, '\\"');
  if (!q) return;
  document.getElementById("sparql-input").value =
    `SELECT ?s ?p ?o WHERE { ?s ?p ?o .\n  FILTER(CONTAINS(LCASE(STR(?s)), "${q}")\n      || CONTAINS(LCASE(STR(?p)), "${q}")\n      || CONTAINS(LCASE(STR(?o)), "${q}")) }`;
  document.getElementById("sparql").classList.add("open");
  document.getElementById("btn-sparql").classList.add("active");
  document.getElementById("btn-run").click();
};
searchBox.addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || !searchState.hits.length) {
    if (e.key === "Enter") searchCount.textContent = "0/0";
    return;
  }
  const n = searchState.hits.length;
  searchState.i = (searchState.i + (e.shiftKey ? -1 : 1) + n) % n;
  searchCount.textContent = `${searchState.i + 1}/${n}`;
  network.selectNodes(searchState.hits);       // 全ヒットをハイライト
  const id = searchState.hits[searchState.i];  // 現在のヒットへズーム
  network.focus(id, { scale: 1.1, animation: true });
  showDetail(id);
});

// --------------------------------------------------------- detail panel
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const linkify = (s) => esc(s).replace(/(https?:\\/\\/[^\\s<]+)/g,
  '<a href="$1" target="_blank" rel="noopener">$1</a>');

function relHTML(t, other, arrow) {
  const attrs = Object.entries(t).filter(([k]) => !["s", "p", "o"].includes(k));
  const cls = t.deprecated ? "rel deprecated" : "rel";
  return `<div class="${cls}">
    <span class="pred" style="background:${PREDICATES[t.p]}">${esc(t.p)}</span>${arrow}
    ${ids.includes(other) ? `<a class="nodelink" data-node="${esc(other)}">${esc(other)}</a>` : linkify(other)}
    ${attrs.map(([k, v]) => `<div class="attr">${esc(k)}: ${linkify(v)}</div>`).join("")}
  </div>`;
}

function showDetail(id) {
  const meta = NODES_META[id] || {};
  const out = TRIPLES.filter(t => t.s === id);
  const inc = TRIPLES.filter(t => t.o === id);
  let html = `<h2>${esc(id)}</h2>`;
  if (meta.type) html += `<span class="pred" style="background:${NODE_TYPES[meta.type] || "#5a83b8"}">${esc(meta.type)}</span>`;
  const props = Object.entries(meta).filter(([k]) => k !== "type");
  if (props.length) html += "<h3>properties</h3>" + props.map(([k, v]) =>
    `<div class="rel"><div class="attr">${esc(k)}: ${linkify(v)}</div></div>`).join("");
  if (out.length) html += "<h3>outgoing</h3>" + out.map(t => relHTML(t, t.o, "&rarr; ")).join("");
  if (inc.length) html += "<h3>incoming</h3>" + inc.map(t => relHTML(t, t.s, "&larr; ")).join("");
  document.getElementById("detail-body").innerHTML = html;
  document.getElementById("detail").classList.add("open");
  document.body.classList.add("detail-open");
}
document.getElementById("btn-close").onclick = () => {
  document.getElementById("detail").classList.remove("open");
  document.body.classList.remove("detail-open");
};
document.getElementById("detail").addEventListener("click", (e) => {
  const n = e.target.closest("a.nodelink");
  if (n) focusNode(n.dataset.node);
});
network.on("click", (params) => {
  if (params.nodes.length) showDetail(params.nodes[0]);
});
function focusNode(id) {
  network.selectNodes([id]);
  network.focus(id, { scale: 1.1, animation: true });
  showDetail(id);
}

// ----------------------------------------------------------- events bar
const eventsBar = document.getElementById("events");
const eventTriples = TRIPLES.filter(t => EVENT_PREDICATES.includes(t.p));
if (!eventTriples.length) eventsBar.style.display = "none";
eventTriples.forEach(t => {
  const chip = document.createElement("span");
  chip.className = "chip";
  chip.innerHTML = `<b>${esc(t.s)}</b>${esc(t.o.length > 70 ? t.o.slice(0, 70) + "\\u2026" : t.o)}`;
  chip.onclick = () => focusNode(t.s);
  eventsBar.appendChild(chip);
});

// ------------------------------------------------------- SPARQL console
document.getElementById("btn-sparql").onclick = (e) => {
  document.getElementById("sparql").classList.toggle("open");
  e.target.classList.toggle("active");
};
let store = null;
async function ensureStore() {
  if (store) return store;
  const mod = await import("https://cdn.jsdelivr.net/npm/oxigraph@0.4.11/web.js");
  await mod.default();
  store = new mod.Store();
  try { store.load(NT, { format: "application/n-triples" }); }
  catch (e) { store.load(NT, "application/n-triples"); }
  return store;
}
const shorten = (v) => v && v.startsWith && v.startsWith(BASE)
  ? decodeURIComponent(v.slice(BASE.length)) : v;
document.getElementById("btn-run").onclick = async () => {
  const box = document.getElementById("results");
  box.innerHTML = '<span class="hint">loading engine\\u2026</span>';
  try {
    const s = await ensureStore();
    const result = s.query("PREFIX t: <" + BASE + ">\\nPREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\\n" + document.getElementById("sparql-input").value);
    if (typeof result === "boolean") {
      box.innerHTML = `<table><tr><th>ASK</th></tr><tr><td>${result ? "yes" : "no"}</td></tr></table>`;
      return;
    }
    const rows = [];
    for (const binding of result) {
      const row = {};
      for (const [k, term] of binding) row[k] = shorten(term.value);
      rows.push(row);
    }
    if (!rows.length) { box.innerHTML = '<span class="hint">no matches</span>'; return; }
    const cols = Object.keys(rows[0]);
    box.innerHTML = `<table><tr>${cols.map(c => `<th>?${esc(c)}</th>`).join("")}</tr>` +
      rows.map(r => `<tr>${cols.map(c => `<td>${esc(r[c] ?? "")}</td>`).join("")}</tr>`).join("") +
      "</table>";
    const hits = [...new Set(rows.flatMap(r => Object.values(r)))].filter(v => ids.includes(v));
    if (hits.length) {
      network.selectNodes(hits);
      network.fit({ nodes: hits, animation: true });
    }
  } catch (err) {
    box.innerHTML = `<div class="err">${esc(err.message || err)}</div>`;
  }
};
</script>
<!-- trikedb:hash:__CONTENT_HASH__ -->
</body>
</html>
"""


def to_html(
    db,
    path: Union[str, Path, None] = None,
    title: str = "trikedb knowledge graph",
    event_predicates=None,
    layout: str = "auto",
) -> str:
    """Render the graph to a self-contained interactive HTML workbench.

    event_predicates: which predicates represent change events (red
    diamonds + bottom timeline bar). None uses a heuristic — predicates
    whose objects contain whitespace, i.e. look like free text rather
    than node names. Pass an explicit list (or []) to override it.

    layout: initial layout — "flow" (hierarchical left-to-right, best
    for pipeline-shaped graphs), "free" (force-directed, best for dense
    hub-shaped graphs), or "auto" (flow up to 150 triples, free above).
    A toggle button switches at runtime either way.
    """
    predicates = db.predicates()
    colors = {p: PALETTE[i % len(PALETTE)] for i, p in enumerate(predicates)}
    triples = [t.to_dict() for t in db]
    nodes_meta = dict(getattr(db, "nodes_meta", {}))
    types = sorted({p["type"] for p in nodes_meta.values() if p.get("type")})
    reversed_palette = PALETTE[::-1]
    type_colors = {t: reversed_palette[i % len(reversed_palette)] for i, t in enumerate(types)}
    nt = db.to_rdflib().serialize(format="nt")

    if event_predicates is None:
        event_preds = sorted({t.p for t in db if any(c.isspace() for c in t.o)})
    else:
        event_preds = sorted({str(p) for p in event_predicates})

    graph_names = sorted({t.attrs.get("graph") for t in db if t.attrs.get("graph")})
    graph_colors = {g: PALETTE[(i + 3) % len(PALETTE)] for i, g in enumerate(graph_names)}

    if layout == "auto":
        # workspaces tile projects on a grid, which needs the force layout
        flow_default = len(triples) <= 150 and not graph_names
    else:
        flow_default = layout == "flow"

    n_nodes = len(db.nodes())
    subtitle = (
        f"{len(triples)} triples &middot; {n_nodes} nodes &middot; one YAML file"
    )

    html = (
        _TEMPLATE
        .replace("__TITLE__", title)
        .replace("__SUBTITLE__", subtitle)
        .replace("__TRIPLES__", json.dumps(triples, ensure_ascii=False))
        .replace("__PREDICATES__", json.dumps(colors, ensure_ascii=False))
        .replace("__NODES_META__", json.dumps(nodes_meta, ensure_ascii=False))
        .replace("__NODE_TYPES__", json.dumps(type_colors, ensure_ascii=False))
        .replace("__NT__", json.dumps(nt, ensure_ascii=False))
        .replace("__EVENT_PREDICATES__", json.dumps(event_preds, ensure_ascii=False))
        .replace("__GRAPHS__", json.dumps(graph_colors, ensure_ascii=False))
        .replace("__FLOW_DEFAULT__", "true" if flow_default else "false")
        .replace("__CONTENT_HASH__", db.content_hash())
    )
    if path is not None:
        from . import storage, storage_sql

        if storage_sql.is_sql_url(path):
            # A warehouse row holds a graph. Writing a page into one would
            # replace the graph with HTML the loader cannot read.
            raise ValueError(
                f"{path}: a warehouse row holds a graph, not a page — write "
                "the workbench to a file or an object URL instead"
            )
        # Through the storage layer, so -o s3://bucket/kg/graph.html
        # publishes the workbench instead of failing on a local path that
        # was never going to exist.
        storage.write_text(path, html)
    return html

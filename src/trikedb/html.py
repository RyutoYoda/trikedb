"""Interactive HTML export: vis-network graph + in-browser SPARQL console.

The exported page is a small single-file "workbench" over the graph:
a searchable network view, a right-hand detail panel showing every
property of the clicked node (URLs become links — this is the RDF
promise: keep attaching facts as properties), change events drawn on
the line between the two objects they happened between, and a SPARQL
console powered by Oxigraph compiled to WASM (loaded from CDN on first
use, never hand-rolled).
"""

from __future__ import annotations

import json
import re
from html import escape
from pathlib import Path
from typing import Union

from .model import TIME_ATTRS

PALETTE = [
    "#4f8ef7", "#f7784f", "#2fbf71", "#b04ff7", "#f7c34f",
    "#4ff7e3", "#f74f9e", "#8ef74f", "#f74f4f", "#4f6af7",
]


# An event is a fact that happened *at a time*. Anything without one is a
# plain relation, however wordy its object. The rule this replaces — "the
# object contains whitespace" — called 69 of the 127 predicates in the
# shipped Freebase demo change events, among them people.person.parents
# and book.author.works_written, and redrew 62% of the nodes as red
# diamonds. A relation is not an event just because it is spelled out.
_LEADING_DATE = re.compile(r"^\d{4}[-/]\d{1,2}")


def _is_event(triple) -> bool:
    """Does this triple record something that happened, and say when?

    Either a time attribute (``at:``/``when:``/... — the action-log form,
    which can also carry ``by:``, ``state:`` and the rest), or an object
    that opens with a date (the free-text form the examples have always
    used: ``o: "2025-04-01 adastra API v3: ..."``).
    """
    attrs = getattr(triple, "attrs", None) or {}
    if any(k in attrs for k in TIME_ATTRS):
        return True
    return bool(_LEADING_DATE.match(str(triple.o)))


def _levels(triples: list, nodes_meta: dict) -> dict:
    """A column number per node for the hierarchical ("flow") layout.

    vis-network works these out itself from edge direction, and gets them
    catastrophically wrong as soon as the graph has a cycle. A six-step
    process with one rework edge (review sends work back to build) and one
    shortcut into the same step came out 13,920px wide — 53 columns for 6
    steps, with the first step stranded 12,720px from everything else.
    Loops are not an edge case in a process graph; they are what a process
    graph is for.

    So the columns are computed here, over the DAG left after dropping the
    edges that close a loop: every node keeps a column, the back edge draws
    as an arrow pointing left, and the layout stays as wide as the process
    is long. Explicit `level` node properties still win — that is the
    documented way to pin a column by hand.
    """
    succ: dict = {}
    nodes: list = []
    for t in triples:
        for name in (t["s"], t["o"]):
            if name not in succ:
                succ[name] = []
                nodes.append(name)
        if t["s"] != t["o"]:            # a self-loop is its own back edge
            succ[t["s"]].append(t["o"])
    for name in nodes_meta:
        if name not in succ:
            succ[name] = []
            nodes.append(name)

    # Iterative DFS colouring: grey means "on the current path", so an edge
    # into a grey node is the one closing the loop. Recursion would blow the
    # stack on a long chain, and a graph this file can hold gets long.
    WHITE, GREY, BLACK = 0, 1, 2
    colour = dict.fromkeys(nodes, WHITE)
    back: set = set()
    for root in nodes:
        if colour[root] != WHITE:
            continue
        stack = [(root, iter(succ[root]))]
        colour[root] = GREY
        while stack:
            node, children = stack[-1]
            for child in children:
                if colour[child] == GREY:
                    back.add((node, child))
                elif colour[child] == WHITE:
                    colour[child] = GREY
                    stack.append((child, iter(succ[child])))
                    break
            else:
                colour[node] = BLACK
                stack.pop()

    indegree = dict.fromkeys(nodes, 0)
    for src, dests in succ.items():
        for dest in dests:
            if (src, dest) not in back:
                indegree[dest] += 1
    level = dict.fromkeys(nodes, 1)
    queue = [n for n in nodes if not indegree[n]]
    while queue:
        node = queue.pop(0)
        for dest in succ[node]:
            if (node, dest) in back:
                continue
            level[dest] = max(level[dest], level[node] + 1)
            indegree[dest] -= 1
            if not indegree[dest]:
                queue.append(dest)
    return level

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
  #graph { position: fixed; inset: 52px 0 0 0; }

  /* The action log, as a strip along the bottom. The graph draws an event
     where it happened — on the line between the two objects — which is the
     one thing a list cannot show; the strip puts the same events in time
     order, which is the one thing the graph cannot show. Both readings of
     the same triples, neither a replacement for the other. */
  #strip { position: fixed; left: 0; right: 0; bottom: 0; height: 58px; z-index: 19;
           display: none; align-items: stretch; background: var(--panel);
           border-top: 1px solid var(--border); }
  body.strip-on #strip { display: flex; }
  body.strip-on #graph { inset: 52px 0 58px 0; }
  body.strip-on #detail { bottom: 58px; }
  #strip .striphead { display: flex; flex-direction: column; justify-content: center;
            padding: 0 11px; border-right: 1px solid var(--border); cursor: pointer; min-width: 78px; }
  #strip .striphead:hover .striptitle { color: var(--text); }
  .striptitle { font-size: 10px; color: var(--dim); text-transform: uppercase; letter-spacing: .06em; }
  .stripcount { font-size: 11px; color: var(--text); font-family: ui-monospace, Menlo, monospace; }
  #striprail { display: flex; gap: 6px; align-items: center; overflow-x: auto; overflow-y: hidden;
               padding: 0 10px; flex: 1; scrollbar-width: thin; }
  #striprail::-webkit-scrollbar { height: 6px; }
  #striprail::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
  .tick { flex: 0 0 auto; max-width: 250px; padding: 5px 8px; cursor: pointer;
          border: 1px solid var(--border); border-left: 2px solid #7a4444; border-radius: 7px; }
  .tick:hover { border-color: #f7784f; }
  .tick.on { border-color: #f7784f; background: #2c1d1a; }
  body.light .tick.on { background: #fbe6df; }
  .tick .tickhead { display: flex; gap: 6px; align-items: center; }
  .tick .ticknode { display: flex; gap: 6px; align-items: center; min-width: 0; margin-top: 3px; }
  .tick .ticknode .pred { flex: 0 0 auto; }
  .tick .tickname { font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
                    font-family: ui-monospace, Menlo, monospace; }
  body.light #strip .tick { border-left-color: #d89b9b; }

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

  #detail { position: fixed; top: 52px; right: 0; bottom: 0; width: 330px; z-index: 18;
            background: var(--panel); border-left: 1px solid var(--border); padding: 14px 16px;
            box-sizing: border-box; overflow-y: auto; display: none; }
  #detail.open { display: block; }
  #detail h2 { font-size: 15px; margin: 0 40px 4px 0; word-break: break-all;
               font-family: ui-monospace, Menlo, monospace; }
  /* An id may be broken anywhere; a sentence may not. */
  #detail h2.human { word-break: normal; overflow-wrap: anywhere; font-family: inherit; }
  #detail .close { position: absolute; top: 10px; right: 12px; }
  #detail h3 { font-size: 11px; color: var(--dim); text-transform: uppercase; letter-spacing: .06em;
               margin: 16px 0 6px; }
  .rel { padding: 7px 9px; border: 1px solid var(--border); border-radius: 8px; margin: 6px 0;
         font-size: 12px; overflow-wrap: anywhere; }
  .pred { display: inline-block; padding: 1px 7px; border-radius: 10px; font-size: 10px;
          font-family: ui-monospace, Menlo, monospace; color: #14161b; font-weight: 700; margin-right: 6px; }
  .rel .attr { color: var(--dim); font-size: 11px; margin-top: 4px;
               font-family: ui-monospace, Menlo, monospace; }
  .rel .attr a { color: #7aa3d8; }
  a.nodelink { color: var(--text); cursor: pointer; text-decoration: underline dotted; }
  #detail .nodeid { font-family: ui-monospace, Menlo, monospace; font-size: 11px;
                    color: var(--dim); margin: -4px 0 2px; }
  .deprecated { opacity: .55; }
  /* a predicate chip in the panel opens what that predicate declares */
  .pred[data-pred] { cursor: pointer; }
  .pred[data-pred]:hover { outline: 2px solid var(--text); outline-offset: 1px; }
  .rel .attr code { color: var(--text); word-break: normal; overflow-wrap: anywhere; }
  .rel .attr .rulekey { display: inline-block; min-width: 64px; color: var(--text); font-weight: 700; }
  .rel .attr.rulemore { margin-top: 2px; padding-left: 64px; }
  .rel.rule, .rel.rule .attr { word-break: normal; overflow-wrap: anywhere; }
  .rel .undeclared { color: var(--dim); font-size: 11px; margin-top: 4px; font-style: italic; }

  .state { display: inline-block; border: 1px solid #7a4444; border-radius: 7px; padding: 1px 7px;
           font-size: 10px; color: #f7784f; white-space: nowrap; letter-spacing: .02em;
           font-family: ui-monospace, Menlo, monospace; }
  .when { font-size: 10px; color: var(--dim); white-space: nowrap;
          font-family: ui-monospace, Menlo, monospace; }
  .rel.event { border-left: 2px solid #7a4444; }
  .rel.event[data-node] { cursor: pointer; }
  .rel.event[data-node]:hover { border-color: #f7784f; }
  .rel.event .evhead .nodelink { font-family: ui-monospace, Menlo, monospace; font-size: 11px; }
  .rel.event .evhead { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-bottom: 4px; }
  .rel.event .evwhat { font-size: 12px; }
  body.light .state { border-color: #d89b9b; color: #c73e1d; }
  body.light .rel.event { border-left-color: #d89b9b; }
  body.light .rel.event[data-node]:hover { border-color: #c73e1d; }
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
  <button class="btn" id="btn-events" title="every event in time order, newest first">events</button>
  <button class="btn" id="btn-onto" title="every predicate and what it declares: domain, range, requires, by">ontology</button>
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

<div id="strip">
  <div class="striphead" id="btn-fulllog" title="open the whole log in the panel">
    <span class="striptitle">action log</span>
    <span class="stripcount" id="stripcount"></span>
  </div>
  <div id="striprail"></div>
</div>

<script>
const show = (v) => (v !== null && typeof v === "object") ? JSON.stringify(v) : String(v);
const esc = (s) => show(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
const linkify = (s) => {
  const text = show(s);
  const rx = /https?:\\/\\/[^\\s<>"']+/g;
  let result = "", start = 0;
  for (const match of text.matchAll(rx)) {
    result += esc(text.slice(start, match.index));
    const url = match[0];
    result += '<a href="' + esc(url) + '" target="_blank" rel="noopener">' + esc(url) + '</a>';
    start = match.index + url.length;
  }
  return result + esc(text.slice(start));
};

const TRIPLES = __TRIPLES__;
const PREDICATES = Object.assign(Object.create(null), __PREDICATES__);
const NODES_META = Object.assign(Object.create(null), __NODES_META__);
const NODE_TYPES = Object.assign(Object.create(null), __NODE_TYPES__);
const NT = __NT__;
const EVENT_PREDICATES = __EVENT_PREDICATES__;
const EVENT_NODES = __EVENT_NODES__;      // event objects that are payloads, not nodes
const RULES = __RULES__;                  // what each predicate declares about itself
const RULE_ORDER = ["domain", "range", "requires", "by"];
const RULE_SAYS = {
  domain: "subject must be",
  range: "object must be",
  requires: "must have happened first",
  by: "may only be done by",
};
const GRAPHS = Object.assign(Object.create(null), __GRAPHS__);   // workspace: {graph name: color}; {} otherwise
const LEVELS = Object.assign(Object.create(null), __LEVELS__);   // computed column per node; a `level` prop overrides
const BASE = "urn:trikedb:";

// which member graph(s) each node belongs to (workspace unions only)
const nodeGraphs = Object.create(null);
TRIPLES.forEach(t => {
  if (t.graph) {
    (nodeGraphs[t.s] ??= new Set()).add(t.graph);
    (nodeGraphs[t.o] ??= new Set()).add(t.graph);
  }
});
// grid anchors: each member graph gets a cell so projects tile side by side
const gnames = Object.keys(GRAPHS);
const anchors = Object.create(null);
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
// Never pass user names into the renderer's object-keyed internal indexes.
const nodeIds = new Map(ids.map((name, i) => [name, i]));
const visualIds = names => names.map(name => nodeIds.get(name));
const degree = Object.create(null);
TRIPLES.forEach(t => { degree[t.s] = (degree[t.s] || 0) + 1; degree[t.o] = (degree[t.o] || 0) + 1; });
const wrap = (id) => id.length > 14 ? id.replace(/([_\\-])/g, "$1\\n").replace(/\\n$/, "") : id;
// ------------------------------------------------------- action layer
// An event belongs to the node it happened to: its SUBJECT. That node
// carries the state, so the state is shown on it and its history hangs
// off it. The object is either a node in its own right (a named event,
// a proposal record) or a scrap of free text that exists nowhere else —
// and only the latter is drawn as a payload diamond. Redrawing every
// object of an event triple as a diamond, as this used to, stripped 32
// real entities in the shipped demo of their type, label and column and
// stranded them in a row of their own: an event tied to nothing.
const isEventTriple = (t) => EVENT_PREDICATES.includes(t.p);
const eventTriples = TRIPLES.filter(isEventTriple);
// What an action is written in, on both grounds. Set on the edge itself,
// so the theme's default edge colour does not swallow it.
const EVENT_EDGE_FONT = { dark: "#f7784f", light: "#b3261e" };
const eventNodes = new Set(EVENT_NODES);

const TIME_KEYS = ["at", "when", "date", "time", "timestamp", "occurred", "recorded"];
const STATE_KEYS = ["state", "status"];
const facet = (t, keys) => { for (const k of keys) if (t[k] !== undefined) return String(t[k]); return ""; };
const timeOf = (t) => facet(t, TIME_KEYS) ||
  (String(t.o).match(/^\\d{4}[-/]\\d{1,2}(?:[-/]\\d{1,2})?/) || [""])[0];
const stateOf = (t) => facet(t, STATE_KEYS);

// A sort key, not the string anyone sees: pad every number so 2025/4/1
// lands where 2025-04-01 does, then drop the separators so two spellings
// of the same day compare equal instead of comparing their punctuation.
const timeKey = (t) => timeOf(t).replace(/\\d+/g, (d) => d.padStart(4, "0"))
                                .replace(/\\D/g, "");
// Newest first. Two events can land on the same day, and a stable sort
// then leaves the FIRST one standing as the latest — the opposite of true
// for a log you append to. File order breaks the tie: written later,
// happened later.
const eventOrder = new Map(eventTriples.map((t, i) => [t, i]));
const byTime = (a, b) =>
  timeKey(b).localeCompare(timeKey(a)) || eventOrder.get(b) - eventOrder.get(a);
const eventsOf = Object.create(null);   // node -> its own events, newest first
eventTriples.forEach(t => (eventsOf[t.s] ??= []).push(t));
Object.values(eventsOf).forEach(l => l.sort(byTime));
// ...and the events written from the other node's side. Once an event grows
// its own properties it becomes an object — a price change with a before and
// an after — and then the product is the OBJECT of the event, not its
// subject. Without this fold, promoting an event to an object cuts every
// object it touches off from its own history. Same rule as history() in
// Python: history folds both ways, state does not, because the change is
// what is 'applied' — not the product, and certainly not the approver.
const incomingOf = Object.create(null);
eventTriples.forEach(t => { if (t.o !== t.s) (incomingOf[t.o] ??= []).push(t); });
Object.values(incomingOf).forEach(l => l.sort(byTime));
// The state act() wrote onto the node, if it wrote one; otherwise the state
// the node's last event left it in, which is how a graph hand-written in
// YAML says the same thing. Same rule as TrikeDB.state() in Python.
const currentState = (id) => {
  const stored = (NODES_META[id] || {}).state;
  if (stored !== undefined && stored !== null && stored !== "") return String(stored);
  for (const t of eventsOf[id] || []) { const s = stateOf(t); if (s) return s; }
  return "";
};
// vis-network requires levels on ALL nodes or NONE, and works them out
// itself — badly — when given none: one rework edge and a six-step process
// spread over 53 columns. LEVELS covers every node, and a `level` property
// still overrides it. Events go one past the max.
const levelOf = (id) => {
  const explicit = (NODES_META[id] || {}).level;
  return typeof explicit === "number" ? explicit : LEVELS[id];
};
const nodeLevels = ids.filter(id => !eventNodes.has(id)).map(levelOf);
const useLevels = nodeLevels.length > 0 && nodeLevels.every(l => typeof l === "number");
const maxLevel = useLevels ? Math.max(...nodeLevels) : 0;
const nodes = new vis.DataSet(ids.map(id => {
  if (eventNodes.has(id)) {
    const n = { id: nodeIds.get(id), label: id.length > 26 ? id.slice(0, 26) + "\\u2026" : id, shape: "diamond", size: 9,
                color: { border: "#f74f4f", background: "#3a1f1f" }, font: { color: "#f0a0a0", size: 10 } };
    if (useLevels) n.level = maxLevel + 1;
    return n;
  }
  const meta = NODES_META[id] || {};
  const n = { id: nodeIds.get(id), label: meta.label ? String(meta.label) : wrap(id), value: degree[id] || 1 };
  const evs = eventsOf[id];
  if (evs) {   // this node has a history: read its state off the node itself
    const st = currentState(id);
    n.label += "\\n\\u25B8 " + (st || evs.length + (evs.length > 1 ? " events" : " event"));
    n.borderWidth = 3;
  }
  const tc = NODE_TYPES[meta.type];
  if (tc) n.color = { border: tc, background: "#1e2129",
                      highlight: { border: "#ffffff", background: "#2c4a6e" } };
  if (useLevels) n.level = levelOf(id);
  const g0 = nodeGraphs[id] ? [...nodeGraphs[id]][0] : null;
  if (g0 && anchors[g0]) {   // seed each project into its grid cell
    n.x = anchors[g0].x + jitter(id, 7) * 1.4;
    n.y = anchors[g0].y + jitter(id, 13) * 1.4;
  }
  return n;
}));
// A hub's edges all start at the same point, so their midpoints — where the
// label goes — land on top of each other and a dozen predicates pile into
// one unreadable smear. Hand each edge of a hub a different lane so the fan
// reads as a list. A node with one or two edges keeps lane 0, on the line
// where the label belongs; only a crowd gets spread out. Small graphs have
// no crowd, so they are left alone entirely.
const spreadLabels = TRIPLES.length > 150;
const LANES = [0, -11, 11, -22, 22, -33, 33];
const laneCount = Object.create(null);
const eventEdgeIds = [];
const edges = new vis.DataSet(TRIPLES.map((t, i) => {
  const e = { id: i, from: nodeIds.get(t.s), to: nodeIds.get(t.o), label: t.p,
              color: { color: PREDICATES[t.p], highlight: "#ffffff" } };
  const font = {};
  if (spreadLabels) {
    const hub = (degree[t.s] || 0) >= (degree[t.o] || 0) ? t.s : t.o;
    const k = (laneCount[hub] = (laneCount[hub] || 0) + 1) - 1;
    font.vadjust = LANES[k % LANES.length];
  }
  // An action happens BETWEEN two objects, so that is where it is drawn:
  // on the line, in its own colour, reading when it happened and what
  // state it left behind. Filed away in a strip along the bottom instead,
  // an event stops being part of the graph and becomes a ticker that
  // looks like it belongs to nothing — which is exactly how it read.
  if (isEventTriple(t)) {
    const when = timeOf(t), st = stateOf(t);
    const said = [when, st ? "\\u25B8 " + st : ""].filter(Boolean).join("  ");
    if (said) e.label = said;
    e.width = 2;
    font.color = EVENT_EDGE_FONT.dark;
    eventEdgeIds.push(i);
  }
  if (Object.keys(font).length) e.font = font;
  // the predicate leads the tooltip too: on a busy canvas the label a line
  // belongs to is not always the one nearest the cursor
  const lines = [t.p];
  Object.entries(t).filter(([k]) => !["s", "p", "o"].includes(k))
        .forEach(([k, v]) => lines.push(k + ": " + v));
  e.title = document.createElement("div");
  e.title.textContent = lines.join("\\n");
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
  // The solver's defaults let nodes settle on top of each other, which on a
  // graph of any size reads as one illegible clump. avoidOverlap keeps them
  // apart and the longer spring gives labels room; the extra stabilization
  // steps are what that arrangement needs to actually come to rest.
  physics: { enabled: true, solver: "forceAtlas2Based",
             forceAtlas2Based: { gravitationalConstant: -120, centralGravity: 0.008,
                                 springLength: 190, springConstant: 0.05, avoidOverlap: 1 },
             stabilization: { iterations: Math.min(1200, Math.max(200, ids.length * 12)) } },
};
let flow = __FLOW_DEFAULT__;
const network = new vis.Network(document.getElementById("graph"), { nodes, edges }, {
  ...(flow ? FLOW_OPTS : FREE_OPTS),
  nodes: { shape: "box", font: { color: "#e8e8ea", size: 12, face: "Menlo, monospace" },
           // Do NOT set `scaling` here. vis rewrites any scaling object we
           // pass down, and the label comes out with a NaN font size: every
           // box then measures 0px of text and renders empty at every zoom.
           // The label draw threshold is dealt with after construction.
           color: { border: "#5a83b8", background: "#1e2129",
                    highlight: { border: "#ffffff", background: "#2c4a6e" } },
           shapeProperties: { borderRadius: 6 }, margin: 8 },
  // A label is drawn at the middle of its line, so on a hub every edge
  // of the same length puts its text in the same place and what you read
  // is several predicates written on top of each other. An opaque plate
  // behind the text means the top one stays a word instead of becoming
  // a smear — and six identical labels stacked just look like one.
  edges: { arrows: "to", font: { color: "#9a9daa", size: 9, strokeWidth: 0,
                                 background: "#14161b" },
           smooth: { type: "cubicBezier", forceDirection: "horizontal", roundness: 0.4 } },
  interaction: { hover: true },
});
if (!flow) {
  network.once("stabilizationIterationsDone", function () {
    network.setOptions({ physics: false });
    network.redraw();
  });
}

// vis hides a label once it would render under ~4px, so on a big graph the
// whole thing fits on screen as rows of blank boxes and you have to zoom in
// to find out what anything is. Tiny text still reads as "there is a name
// here", and you can still see which cluster you want. Passing this through
// the options is not an option: vis rewrites any `scaling` we hand it and
// leaves the label with a NaN font size. So reach for the threshold vis
// built itself, and do it every frame — vis rebuilds a node's options
// whenever one is updated (theme switch, type filter), which would put the
// default back.
network.on("beforeDrawing", function () {
  for (const id in network.body.nodes) {
    const o = network.body.nodes[id].options;
    if (o && o.scaling && o.scaling.label) o.scaling.label.drawThreshold = 0;
  }
});
network.redraw();

// ------------------------------------- header legend (click = filter)
const hiddenTypes = new Set();
const hiddenPreds = new Set();
const hiddenGraphs = new Set();
// Which nodes a filter leaves standing. Separate from the update below
// because the *camera* wants the answer too, and asking twice is how the
// two drift apart.
function visibleNodes() {
  return ids.filter(id => {
    const meta = NODES_META[id] || {};
    const byType = meta.type && hiddenTypes.has(meta.type);
    const byGraph = nodeGraphs[id] && [...nodeGraphs[id]].every(g => hiddenGraphs.has(g));
    return !(byType || byGraph);
  });
}
let framed = visibleNodes().join("\\u0000");
function refreshVisibility() {
  const shown = visibleNodes();
  const keep = new Set(shown);
  nodes.update(ids.map(id => ({ id: nodeIds.get(id), hidden: !keep.has(id) })));
  edges.update(TRIPLES.map((t, i) => ({
    id: i, hidden: !!(hiddenPreds.has(t.p) || (t.graph && hiddenGraphs.has(t.graph))),
  })));
  // Frame what is left. Hiding five sixths of a workspace used to leave
  // the remainder as a speck in whichever corner the layout had put it,
  // at the zoom chosen for the whole graph — so the answer to what you
  // just clicked was off screen until you found `Fit`. Moving the camera
  // when nothing moved would be the jarring kind of help, though, and a
  // predicate toggle hides edges only, so the visible set is compared
  // before anything is re-framed.
  const sig = shown.join("\\u0000");
  if (sig !== framed && shown.length) {
    network.fit({ nodes: visualIds(shown), animation: true });
  }
  framed = sig;
}
const legend = document.getElementById("legend");
const typeEls = Object.create(null);
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
  el.innerHTML = `<i style="border-color:${color};color:${color}">&#10003;</i>${esc(ty)}`;
  el.onclick = () => { setTypeHidden(ty, !hiddenTypes.has(ty)); refreshVisibility(); };
  typeEls[ty] = el;
  legend.appendChild(el);
}
for (const [p, color] of Object.entries(PREDICATES)) {
  const el = document.createElement("span");
  el.className = "lg toggle";
  const r = RULES[p] || {};
  const shape = RULE_ORDER.filter(k => (r[k] || []).length)
    .map(k => `${k}: ${r[k].join(", ")}`).join("\\n");
  el.title = `show/hide ${p} edges` + (shape ? `\\n\\n${shape}` : "");
  el.innerHTML = `<b style="background:${color}"></b>${esc(p)}`;
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
const graphChips = Object.create(null);
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
    chip.innerHTML = `<b style="display:inline-block;width:9px;height:9px;border-radius:5px;background:${GRAPHS[g]};margin-right:6px;vertical-align:middle"></b>${esc(g)}`;
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
  dark:  { font: "#e8e8ea", nodeBg: "#1e2129", edgeFont: "#9a9daa", hlBg: "#2c4a6e", bg: "#14161b",
           hlBorder: "#ffffff", edgeHl: "#ffffff", evFont: "#f0a0a0", evBg: "#3a1f1f" },
  light: { font: "#1b1e26", nodeBg: "#ffffff", edgeFont: "#646a78", hlBg: "#dbe6f7", bg: "#f4f5f8",
           hlBorder: "#5a83b8", edgeHl: "#1b1e26", evFont: "#b3261e", evBg: "#fdeaea" },
};
function applyTheme(name, persist = true) {
  const th = THEMES[name];
  document.body.classList.toggle("light", name === "light");
  // vis caches the style of selected elements: deselect, restyle, reselect
  const sel = network.getSelection();
  network.unselectAll();
  network.setOptions({ nodes: { font: { color: th.font } },
                       edges: { font: { color: th.edgeFont, background: th.bg } } });
  // An event edge carries its own font colour, so the options above do not
  // reach it. Merge rather than replace — the lane (vadjust) lives there too.
  if (eventEdgeIds.length) edges.update(eventEdgeIds.map(id => {
    const f = Object.assign({}, edges.get(id).font);
    f.color = EVENT_EDGE_FONT[name];
    return { id, font: f };
  }));
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
  if (persist) { try { localStorage.setItem("trikedb-theme", name); } catch (e) {} }
  document.getElementById("btn-theme").textContent = name === "light" ? "dark" : "light";
}
document.getElementById("btn-theme").onclick = () =>
  applyTheme(document.body.classList.contains("light") ? "dark" : "light");
// ?theme=light|dark lets an embedding page pick the theme without touching
// the visitor's own saved preference.
const urlTheme = new URLSearchParams(location.search).get("theme");
if (urlTheme === "light" || urlTheme === "dark") {
  applyTheme(urlTheme, false);
} else {
  try {
    if (localStorage.getItem("trikedb-theme") === "light") applyTheme("light");
  } catch (e) {}
}

document.getElementById("btn-fit").onclick = () => network.fit({ animation: true });
// full-text search: node ids + labels + node properties + edge attributes
// + free-text objects (attached to their subjects). Enter cycles matches.
const searchIndex = Object.create(null);
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
  network.selectNodes(visualIds(searchState.hits));       // 全ヒットをハイライト
  const id = searchState.hits[searchState.i];  // 現在のヒットへズーム
  network.focus(nodeIds.get(id), { scale: 1.1, animation: true });
  showDetail(id);
});

// A node keeps its id in the drawing — short, stable, and the thing you
// would paste into a query — and says what it is in words wherever there is
// room for words: the panel heading, every link to it, and the log. `name`
// first, then the two other spellings a graph already uses for the same
// thing. A node with none of them is its id, which for a record like
// PC-0007 is the honest answer rather than a missing one.
const HUMAN_KEYS = ["label", "name", "title", "summary"];
// Which property supplied the words, so the panel can show it as the
// heading without also listing it underneath as a property of itself.
const humanKeyOf = (id) => {
  const m = NODES_META[id] || {};
  return HUMAN_KEYS.find(k => m[k] !== undefined && m[k] !== null && String(m[k]).trim()) || "";
};
const nameOf = (id) => {
  const k = humanKeyOf(id);
  return k ? String(NODES_META[id][k]) : "";
};
// A link always carries the id in data-node (that is what gets focused) and
// keeps it in the tooltip when the visible text is the name instead.
function nodeLink(id) {
  const nm = nameOf(id);
  return nm ? `<a class="nodelink" data-node="${esc(id)}" title="${esc(id)}">${esc(nm)}</a>`
            : `<a class="nodelink" data-node="${esc(id)}">${esc(id)}</a>`;
}
const linkOrText = (x) => ids.includes(x) ? nodeLink(x) : linkify(x);

// --------------------------------------------------------- detail panel
// String({}) is "[object Object]", which is what an attribute holding a
// mapping used to render as. Nothing in the graph should hold one, but the
// file is hand-edited, and a stray `attrs: {}` key made every relation in
// the shipped demo read "attrs: [object Object]".

function relHTML(t, other, arrow) {
  const attrs = Object.entries(t).filter(([k]) => !["s", "p", "o"].includes(k));
  const cls = t.deprecated ? "rel deprecated" : "rel";
  return `<div class="${cls}">
    <span class="pred" data-pred="${esc(t.p)}" title="what ${esc(t.p)} declares" style="background:${PREDICATES[t.p]}">${esc(t.p)}</span>${arrow}
    ${linkOrText(other)}
    ${attrs.map(([k, v]) => `<div class="attr">${esc(k)}: ${linkify(v)}</div>`).join("")}
  </div>`;
}

// An event reads as when / what state it left this node in / what happened,
// with the rest of the action log (by, input, result) underneath — the point
// of attaching events to a node is being able to read its state off it.
function eventHTML(t, from) {
  const when = timeOf(t), st = stateOf(t);
  const skip = ["s", "p", "o", ...TIME_KEYS, ...STATE_KEYS];
  const attrs = Object.entries(t).filter(([k]) => !skip.includes(k));
  return `<div class="rel event">
    <div class="evhead">
      ${when ? `<span class="when">${esc(when)}</span>` : ""}
      ${st ? `<span class="state">${esc(st)}</span>` : ""}
      <span class="pred" data-pred="${esc(t.p)}" title="what ${esc(t.p)} declares" style="background:${PREDICATES[t.p]}">${esc(t.p)}</span>
    </div>
    <div class="evwhat">${from ? "&larr; " : ""}${linkOrText(from ? t.s : t.o)}</div>
    ${attrs.map(([k, v]) => `<div class="attr">${esc(k)}: ${linkify(v)}</div>`).join("")}
  </div>`;
}

function showDetail(id) {
  const meta = NODES_META[id] || {};
  const own = eventsOf[id] || [], into = incomingOf[id] || [];
  const evs = own.concat(into).sort(byTime);
  const out = TRIPLES.filter(t => t.s === id && !isEventTriple(t));
  const inc = TRIPLES.filter(t => t.o === id && !isEventTriple(t));
  const nmKey = humanKeyOf(id), nm = nmKey ? String(meta[nmKey]) : "";
  let html = nm ? `<h2 class="human">${esc(nm)}</h2><div class="nodeid">${esc(id)}</div>`
                : `<h2>${esc(id)}</h2>`;
  if (meta.type) html += `<span class="pred" style="background:${NODE_TYPES[meta.type] || "#5a83b8"}">${esc(meta.type)}</span>`;
  const st = currentState(id);
  if (st) html += `<span class="state">${esc(st)}</span>`;
  // nmKey is already the heading; repeating it as a property says the
  // same sentence twice in the space of four lines.
  const props = Object.entries(meta).filter(([k]) => k !== "type" && k !== nmKey);
  if (props.length) html += "<h3>properties</h3>" + props.map(([k, v]) =>
    `<div class="rel"><div class="attr">${esc(k)}: ${linkify(v)}</div></div>`).join("");
  if (evs.length) html += `<h3>events &middot; ${evs.length}</h3>`
    + evs.map(t => eventHTML(t, t.o === id)).join("");
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
  // The chip comes first: inside an event row it sits within the clickable
  // row itself, and asking what a predicate declares must not navigate away
  // from the fact that prompted the question.
  const chip = e.target.closest(".pred[data-pred]");
  if (chip) { showOntology(chip.dataset.pred); return; }
  const n = e.target.closest("a.nodelink") || e.target.closest(".rel.event[data-node]");
  if (n) focusNode(n.dataset.node);
});
// Clicking a line used to do nothing, which on a page where every line is
// a fact is a dead end. An edge answers for its subject — the node the
// relation hangs off, and for an event the node the event happened to, so
// the panel that opens has the rest of that node's history in it.
network.on("click", (params) => {
  if (params.nodes.length) { showDetail(ids[params.nodes[0]]); return; }
  if (params.edges.length) {
    const t = TRIPLES[params.edges[0]];
    if (t) focusNode(t.s);
  }
});
function focusNode(id) {
  network.selectNodes(visualIds([id]));
  network.focus(nodeIds.get(id), { scale: 1.1, animation: true });
  showDetail(id);
}

// ------------------------------------------------------- the action log
// The events themselves live in the graph, on the line between the two
// objects, which is where they happened. Read across every node at once in
// time order they are also a log, and that is the one thing the drawing
// cannot show — so the same events run along the bottom as a strip and open
// in full in the panel. Neither is the events' home; both are readings of it.
const timeline = eventTriples.slice().sort(byTime);
const btnEvents = document.getElementById("btn-events");
if (!timeline.length) btnEvents.style.display = "none";
else btnEvents.textContent = "events \\u00b7 " + timeline.length;
function timelineHTML(t) {
  const when = timeOf(t), st = stateOf(t);
  return `<div class="rel event" data-node="${esc(t.s)}">
    <div class="evhead">
      ${when ? `<span class="when">${esc(when)}</span>` : ""}
      ${st ? `<span class="state">${esc(st)}</span>` : ""}
      <span class="pred" data-pred="${esc(t.p)}" title="what ${esc(t.p)} declares" style="background:${PREDICATES[t.p]}">${esc(t.p)}</span>
      ${nodeLink(t.s)}
    </div>
    <div class="evwhat">&rarr; ${ids.includes(t.o) ? nodeLink(t.o)
      : esc(t.o.length > 90 ? t.o.slice(0, 90) + "\\u2026" : t.o)}</div>
  </div>`;
}
// The strip. Newest first, same order as the panel log and as history():
// a log you append to reads from the top.
const rail = document.getElementById("striprail");
function tickHTML(t, i) {
  const when = timeOf(t), st = stateOf(t);
  return `<div class="tick" data-ev="${i}" data-node="${esc(t.s)}" title="${esc(t.s + " " + t.p + " " + t.o)}">
    <div class="tickhead">
      ${when ? `<span class="when">${esc(when)}</span>` : ""}
      ${st ? `<span class="state">${esc(st)}</span>` : ""}
    </div>
    <div class="ticknode">
      <span class="pred" style="background:${PREDICATES[t.p]}">${esc(t.p)}</span>
      <span class="tickname">${esc(nameOf(t.s) || t.s)}</span>
    </div>
  </div>`;
}
if (timeline.length) {
  document.getElementById("stripcount").textContent = timeline.length + " events";
  rail.innerHTML = timeline.map(tickHTML).join("");
  document.body.classList.add("strip-on");
  btnEvents.classList.add("active");
}
rail.addEventListener("click", (e) => {
  const el = e.target.closest(".tick");
  if (!el) return;
  rail.querySelectorAll(".tick.on").forEach(n => n.classList.remove("on"));
  el.classList.add("on");
  focusNode(el.dataset.node);
});
btnEvents.onclick = () => {
  const on = document.body.classList.toggle("strip-on");
  btnEvents.classList.toggle("active", on);
};
document.getElementById("btn-fulllog").onclick = () => showTimeline();

function showTimeline() {
  document.getElementById("detail-body").innerHTML =
    `<h2>action log</h2><h3>${timeline.length} event${timeline.length === 1 ? "" : "s"} &middot; newest first</h3>`
    + timeline.map(timelineHTML).join("");
  document.getElementById("detail").classList.add("open");
  document.body.classList.add("detail-open");
}

// ------------------------------------------------------ the declarations
// Every line on this page was allowed in by a rule, and the rules were the
// one thing the page never showed. You could read that a courier delivered
// an order and not that DELIVERED_TO refuses to be written at all until
// SHIPPED_FROM has happened, or that only a courier may write it. A
// declaration is part of the graph, so it gets drawn with it: the button
// lists every predicate, and a predicate chip anywhere in the panel opens
// its own declaration next to the fact that raised the question.
const ruleNames = Object.keys(RULES);
const enforced = ruleNames.filter(p => RULE_ORDER.some(k => (RULES[p][k] || []).length));
function ruleHTML(p) {
  const r = RULES[p] || {};
  // domain, range and by name alternatives; requires names steps that
  // must ALL hold. Running either kind together on one line with a
  // separator hides which of the two a reader is looking at.
  const rows = RULE_ORDER.filter(k => (r[k] || []).length).map(k => {
    const vals = r[k].map(v => `<code>${esc(v)}</code>`);
    const head = `<span class="rulekey">${k}</span>${esc(RULE_SAYS[k])}`;
    if (vals.length === 1) return `<div class="attr">${head}: ${vals[0]}</div>`;
    if (k !== "requires") return `<div class="attr">${head} one of: ${vals.join(" &middot; ")}</div>`;
    return `<div class="attr"><span class="rulekey">requires</span>all of these must have happened first:</div>`
      + vals.map(v => `<div class="attr rulemore">${v}</div>`).join("");
  }).join("");
  return `<div class="rel rule">
    <span class="pred" style="background:${PREDICATES[p] || "#5a83b8"}">${esc(p)}</span>
    ${r.n ? `<span class="when">${r.n} triple${r.n === 1 ? "" : "s"}</span>` : ""}
    ${r.description ? `<div class="attr">${esc(r.description)}</div>` : ""}
    ${rows || `<div class="undeclared">nothing declared \\u2014 anything may write this</div>`}
  </div>`;
}
function showOntology(only) {
  const names = only && RULES[only] ? [only] : ruleNames;
  const head = only && RULES[only]
    ? `<h2>${esc(only)}</h2><h3>what this predicate declares</h3>`
    : `<h2>ontology</h2><h3>${ruleNames.length} predicate${ruleNames.length === 1 ? "" : "s"}`
      + ` &middot; ${enforced.length} enforced</h3>`;
  document.getElementById("detail-body").innerHTML = head + names.map(ruleHTML).join("");
  document.getElementById("detail").classList.add("open");
  document.body.classList.add("detail-open");
}
const btnOnto = document.getElementById("btn-onto");
if (!ruleNames.length) btnOnto.style.display = "none";
else {
  btnOnto.textContent = "ontology \\u00b7 " + ruleNames.length;
  btnOnto.onclick = () => showOntology();
}

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
      const row = Object.create(null);
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
      network.selectNodes(visualIds(hits));
      network.fit({ nodes: visualIds(hits), animation: true });
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
    """Render the graph to a single-file interactive HTML workbench (CDN dependencies).

    event_predicates: which predicates carry change events. An event is
    attached to its subject — the node whose state it changed — which
    gets the event's latest `state:` on its label and the full history
    in the detail panel. The event itself is drawn where it happened:
    on the line between the two objects, in the action colour, labelled
    with its date and the state it left behind. The `events` button in
    the header reads the same log across every node in time order.
    None detects them: a predicate is an event predicate when its triples
    carry a time attribute (`at:`, `when:`, `date:`, ...) or their object
    opens with a date. Pass an explicit list (or []) to override it.

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
        event_preds = sorted({t.p for t in db if _is_event(t)})
    else:
        event_preds = sorted({str(p) for p in event_predicates})

    # Which objects of an event triple are payloads rather than nodes in
    # their own right. A name the graph says anything else about — node
    # properties, or an outgoing edge — is an entity, and stays one.
    entity_ids = {t.s for t in db} | set(nodes_meta)
    event_nodes = sorted({t.o for t in db if t.p in set(event_preds)} - entity_ids)

    # What each predicate declares about itself, alongside how often it is
    # actually used. A predicate the ontology never mentions still belongs
    # in this list: "nothing declared" is the fact a reader most needs, and
    # leaving it out would make the page look stricter than the graph is.
    declared = dict(getattr(db, "ontology", {}) or {})
    predicate_rules = dict(getattr(db, "predicate_rules", {}) or {})
    counts: dict = {}
    for t in db:
        counts[t.p] = counts.get(t.p, 0) + 1
    rules_data = {}
    for name in sorted(set(predicates) | set(declared)):
        entry: dict = {}
        desc = declared.get(name) or ""
        if desc:
            entry["description"] = desc
        for key, want in (predicate_rules.get(name) or {}).items():
            entry[key] = list(want)
        if counts.get(name):
            entry["n"] = counts[name]
        rules_data[name] = entry

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

    def json_safe(value):
        # YAML permits nonfinite numbers; JSON.parse does not. Display their
        # spelling as text instead of letting one property break the page.
        import datetime
        import math
        if isinstance(value, float) and not math.isfinite(value):
            return str(value)
        # YAML also parses an unquoted 2025-04-01 into a date, and json
        # cannot serialise one — which is to say the most natural way to
        # write `at:` used to raise TypeError instead of rendering a page.
        if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
            return value.isoformat()
        if isinstance(value, dict):
            return {k: json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [json_safe(v) for v in value]
        return value

    def script_json(value):
        # JSON.parse avoids JavaScript object-literal __proto__ semantics.
        encoded = json.dumps(json.dumps(json_safe(value), ensure_ascii=False,
                                        allow_nan=False), ensure_ascii=False)
        encoded = (encoded.replace("<", "\\u003c").replace(">", "\\u003e")
                   .replace("&", "\\u0026").replace("\u2028", "\\u2028")
                   .replace("\u2029", "\\u2029"))
        return f"JSON.parse({encoded})"

    replacements = {
        "TITLE": escape(str(title), quote=True), "SUBTITLE": subtitle,
        "TRIPLES": script_json(triples), "PREDICATES": script_json(colors),
        "NODES_META": script_json(nodes_meta), "NODE_TYPES": script_json(type_colors),
        "NT": script_json(nt), "EVENT_PREDICATES": script_json(event_preds),
        "EVENT_NODES": script_json(event_nodes),
        "RULES": script_json(rules_data),
        "GRAPHS": script_json(graph_colors),
        "LEVELS": script_json(_levels(triples, nodes_meta)),
        "FLOW_DEFAULT": "true" if flow_default else "false",
        "CONTENT_HASH": db.content_hash(),
    }
    # Replacement values are data, and must never be expanded as templates.
    html = re.sub(r"__([A-Z_]+)__", lambda m: replacements[m[1]], _TEMPLATE)
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

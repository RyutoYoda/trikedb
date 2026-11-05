const $ = (id) => document.getElementById(id);
let state,
  graph,
  selected,
  section = "workflows",
  draft = [],
  draftBaseSha = "",
  previewHash = "",
  editorToken = "";
let language =
  localStorage.getItem("trikedb-review-language") ||
  (navigator.language.startsWith("ja") ? "ja" : "en");
const messages = {
  en: {
    workspace: "Review workspace",
    reload: "Reload",
    review: "Review changes",
    graphContent: "GRAPH CONTENT",
    explore: "Explore and edit",
    search: "Search names or IDs",
    workflows: "Workflows",
    nodesRelations: "Nodes and relations",
    draftNote:
      "Changes stay in this browser until you review them. A draft PR does not change the canonical graph.",
    add: "+ Add",
    hint: "Drag from a blue point to a white point to connect",
    reviewArrow: "Review changes →",
    edit: "EDIT",
    cancel: "Cancel",
    saveDraft: "Save to draft",
    reviewCaps: "REVIEW",
    source: "Source URL or document name",
    sourcePlaceholder: "Example: process guide, section 2",
    reason: "Reason for change (at least 5 characters)",
    reasonPlaceholder: "Why is this change needed?",
    discard: "Discard changes",
    preview: "1. Preview YAML diff",
    publish: "2. Create draft PR",
    processMap: "Process map",
    relationMap: "Relationship map",
    linkNode: "+ Link a node",
    editWorkflow: "Edit workflow details",
    connect: "+ Connect a relationship",
    remove: "Remove",
    noSteps: "No steps yet. Use + Add to create one.",
    noRelations: "This node has no direct relationships.",
    sourceBadge: "local demo",
    githubBadge: "GitHub main",
    name: "Name",
    description: "Description",
    summary: "Summary",
    type: "Type",
    nextSteps: "Next step IDs (comma separated)",
    insertAfter: "Insert after",
    fromNode: "From node",
    toNode: "To node",
    relationship: "Relationship",
    id: "ID",
    loaded: "Canonical YAML loaded.",
    saved:
      "Change saved in this browser. Review the YAML diff before creating a PR.",
    noChanges: "No changes to review.",
    changeCount: "change(s) to",
    addVerb: "Add",
    editVerb: "Edit",
    invalidDraft:
      "Canonical YAML changed. This draft is preserved here but cannot be published. Copy any needed edits, then discard it and edit the current graph.",
    setup: "Connect GitHub",
    setupCaps: "SETUP",
    setupHelp:
      "Register a GitHub App with the minimum repository permissions, install it on one repository, then check the connection.",
    setupToken: "Setup token",
    repo: "Repository (owner/name)",
    graphPath: "Graph YAML path on main",
    ownerType: "App owner",
    org: "Organization",
    personal: "Personal account",
    install: "Install App on the selected repository ↗",
    register: "1. Register App on GitHub",
    checkConnection: "2. Check connection",
    newWorkflow: "+ New workflow",
    deleteItem: "Delete",
    undo: "Undo last change",
  },
  ja: {
    workspace: "レビュー画面",
    reload: "再読込",
    review: "変更を確認",
    graphContent: "グラフの内容",
    explore: "追加・編集",
    search: "名前・IDで検索",
    workflows: "ワークフロー",
    nodesRelations: "ノード・関係",
    draftNote:
      "変更は確認するまでこのブラウザに保存されます。ドラフトPRでは正本は変わりません。",
    add: "＋追加",
    hint: "青い点から白い点へドラッグして接続",
    reviewArrow: "変更を確認 →",
    edit: "編集",
    cancel: "キャンセル",
    saveDraft: "下書きに保存",
    reviewCaps: "レビュー",
    source: "出典URL・資料名",
    sourcePlaceholder: "例：業務手順書の第2章",
    reason: "変更理由（5文字以上）",
    reasonPlaceholder: "なぜ変更が必要か",
    discard: "変更を破棄",
    preview: "① YAML差分を確認",
    publish: "② ドラフトPRを作成",
    processMap: "工程の流れ",
    relationMap: "関係のマップ",
    linkNode: "＋ノードを紐付け",
    editWorkflow: "ワークフローの概要を編集",
    connect: "＋関係を追加",
    remove: "解除",
    noSteps: "工程がありません。＋追加で作成できます。",
    noRelations: "このノードには直接の関係がありません。",
    sourceBadge: "ローカルの例",
    githubBadge: "GitHub正本",
    name: "名前",
    description: "説明",
    summary: "概要",
    type: "種類",
    nextSteps: "次の工程ID（カンマ区切り）",
    insertAfter: "この工程の後に追加",
    fromNode: "接続元",
    toNode: "接続先",
    relationship: "関係の種類",
    id: "ID",
    loaded: "正本YAMLを読み込みました。",
    saved:
      "変更をこのブラウザに保存しました。PRの前にYAML差分を確認してください。",
    noChanges: "確認する変更はありません。",
    changeCount: "件の変更：",
    addVerb: "追加",
    editVerb: "編集",
    invalidDraft:
      "正本YAMLが更新されました。古い下書きは保存されていますが、送信できません。必要な内容を控えて破棄し、最新の正本で編集してください。",
    setup: "GitHubを接続",
    setupCaps: "初期設定",
    setupHelp:
      "必要最小限の権限でGitHub Appを登録し、対象リポジトリへインストールして接続を確認します。",
    setupToken: "セットアップ用トークン",
    repo: "リポジトリ（所有者/名前）",
    graphPath: "main上のグラフYAMLのパス",
    ownerType: "Appの所有者",
    org: "組織",
    personal: "個人アカウント",
    install: "対象リポジトリにAppをインストール ↗",
    register: "① GitHubでAppを登録",
    checkConnection: "② 接続を確認",
    newWorkflow: "＋ワークフローを作成",
    deleteItem: "削除",
    undo: "直前の変更を戻す",
  },
};
function t(key) {
  return messages[language][key] || key;
}
function translatePage() {
  document.documentElement.lang = language;
  for (const element of document.querySelectorAll("[data-i18n]"))
    element.textContent = t(element.dataset.i18n);
  for (const element of document.querySelectorAll("[data-i18n-placeholder]"))
    element.placeholder = t(element.dataset.i18nPlaceholder);
  $("language").textContent = language === "ja" ? "English" : "日本語";
  if (state) render();
}

function status(message) {
  $("status").textContent = message;
}
function item(tag, className, label) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (label !== undefined) element.textContent = label;
  return element;
}
function appendField(
  parent,
  label,
  key,
  value = "",
  options = null,
  multiline = false,
) {
  const wrapper = item("label", "", label);
  const input = options
    ? item("select")
    : item(multiline ? "textarea" : "input");
  input.name = key;
  if (options)
    for (const option of options) {
      const row = item("option", "", option);
      row.value = option;
      input.append(row);
    }
  input.value = value ?? "";
  wrapper.append(input);
  parent.append(wrapper);
}
function view() {
  const result = structuredClone(state.graph);
  if (draftBaseSha && draftBaseSha !== state.sha) return result;
  result.nodes ||= {};
  result.triples ||= [];
  result.workflows ||= {};
  for (const change of draft) {
    if (change.kind === "node") {
      if (change.action === "remove") {
        delete result.nodes[change.id];
        continue;
      }
      result.nodes[change.id] = {
        ...(result.nodes[change.id] || {}),
        type: change.type,
        label: change.label,
        description: change.description,
      };
    } else if (change.kind === "edge") {
      if (change.action === "add")
        result.triples.push({ s: change.s, p: change.p, o: change.o });
      else
        result.triples = result.triples.filter(
          (edge) =>
            !(
              edge.s === change.s &&
              edge.p === change.p &&
              edge.o === change.o
            ),
        );
    } else if (change.kind === "workflow") {
      result.workflows[change.id] = {
        ...(result.workflows[change.id] || {}),
        label: change.label,
        summary: change.summary,
        steps: result.workflows[change.id]?.steps || [],
      };
    } else if (change.kind === "step") {
      const steps = result.workflows[change.workflow]?.steps;
      if (!steps) continue;
      const index = steps.findIndex((step) => step.id === change.id);
      if (change.action === "remove") {
        if (index >= 0) steps.splice(index, 1);
        for (const step of steps)
          step.next = (step.next || []).filter((id) => id !== change.id);
        result.triples = result.triples.filter(
          (edge) => edge.s !== change.id && edge.o !== change.id,
        );
      } else {
        const next = {
          ...(steps[index] || {}),
          id: change.id,
          label: change.label,
          description: change.description,
          next: change.next,
        };
        if (index < 0) {
          const after = steps.find((step) => step.id === change.after);
          if (after) {
            next.next = change.next.length
              ? change.next
              : [...(after.next || [])];
            after.next = [change.id];
          }
          steps.push(next);
        } else steps[index] = next;
      }
    }
  }
  return result;
}
function saveDraft() {
  if (!draft.length || !draftBaseSha) draftBaseSha = state.sha;
  localStorage.setItem(
    "trikedb-review-example",
    JSON.stringify({ sha: draftBaseSha || state.sha, operations: draft }),
  );
  previewHash = "";
  $("change-count").textContent = draft.length;
  $("publish").disabled = true;
  render();
}
function loadDraft() {
  try {
    const saved = JSON.parse(
      localStorage.getItem("trikedb-review-example") || "null",
    );
    if (Array.isArray(saved?.operations)) {
      draft = saved.operations.slice(0, 30);
      draftBaseSha = saved.sha;
    }
  } catch {
    /* ignore malformed browser storage */
  }
  $("change-count").textContent = draft.length;
}
function card(kind, id, label, description, kicker) {
  const element = item("div", "card", "");
  element.tabIndex = 0;
  element.setAttribute("role", "button");
  element.dataset.id = id;
  element.dataset.kind = kind;
  element.append(item("small", "", kicker), item("strong", "", label || id));
  if (description) element.append(item("p", "", description));
  for (const direction of ["in", "out"]) {
    const handle = item("span", `connector ${direction}`);
    handle.dataset.id = id;
    handle.dataset.kind = kind;
    handle.dataset.direction = direction;
    handle.title =
      direction === "out" ? "Drag to connect" : "Drop here to connect";
    element.append(handle);
  }
  element.addEventListener("click", (event) => {
    if (!event.target.closest(".connector")) openEdit(kind, "update", id);
  });
  element.addEventListener("keydown", (event) => {
    if (event.key === "Enter") openEdit(kind, "update", id);
  });
  return element;
}
function drawConnections(row, connections) {
  if (!row.isConnected) return;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.classList.add("connection-layer");
  svg.setAttribute("width", row.scrollWidth);
  svg.setAttribute("height", row.scrollHeight);
  svg.setAttribute("viewBox", `0 0 ${row.scrollWidth} ${row.scrollHeight}`);
  const marker = document.createElementNS(svg.namespaceURI, "marker");
  marker.id = "connection-arrow";
  marker.setAttribute("viewBox", "0 0 10 10");
  marker.setAttribute("refX", "9");
  marker.setAttribute("refY", "5");
  marker.setAttribute("markerWidth", "7");
  marker.setAttribute("markerHeight", "7");
  marker.setAttribute("orient", "auto-start-reverse");
  const tip = document.createElementNS(svg.namespaceURI, "path");
  tip.setAttribute("d", "M 0 0 L 10 5 L 0 10 z");
  tip.setAttribute("fill", "#6b9cdd");
  marker.append(tip);
  const defs = document.createElementNS(svg.namespaceURI, "defs");
  defs.append(marker);
  svg.append(defs);
  const origin = row.getBoundingClientRect();
  function point(id, direction) {
    const handle = [...row.querySelectorAll(`.connector.${direction}`)].find(
      (el) => el.dataset.id === id,
    );
    if (!handle) return null;
    const box = handle.getBoundingClientRect();
    return {
      x: box.left + box.width / 2 - origin.left,
      y: box.top + box.height / 2 - origin.top,
    };
  }
  for (const edge of connections) {
    const from = point(edge.s, "out"),
      to = point(edge.o, "in");
    if (!from || !to) continue;
    const path = document.createElementNS(svg.namespaceURI, "path");
    const bend = Math.max(45, Math.abs(to.x - from.x) / 2);
    path.setAttribute(
      "d",
      `M ${from.x} ${from.y} C ${from.x + bend} ${from.y}, ${to.x - bend} ${to.y}, ${to.x} ${to.y}`,
    );
    path.setAttribute("class", "connection-path");
    path.setAttribute("marker-end", "url(#connection-arrow)");
    svg.append(path);
    const label = document.createElementNS(svg.namespaceURI, "text");
    label.setAttribute("x", (from.x + to.x) / 2);
    label.setAttribute("y", (from.y + to.y) / 2 - 9);
    label.setAttribute("class", "connection-label");
    label.textContent = `${edge.p} ×`;
    label.addEventListener("click", () => {
      if (edge.kind === "step") {
        const step = graph.workflows[selected]?.steps.find(
          (value) => value.id === edge.s,
        );
        if (!step) return;
        draft.push({
          kind: "step",
          action: "update",
          workflow: selected,
          id: step.id,
          label: step.label,
          description: step.description || "",
          next: (step.next || []).filter((id) => id !== edge.o),
        });
      } else
        draft.push({
          kind: "edge",
          action: "remove",
          s: edge.s,
          p: edge.p,
          o: edge.o,
        });
      saveDraft();
    });
    svg.append(label);
  }
  row.prepend(svg);
}
let activeDrag = null;
window.addEventListener("pointerdown", (event) => {
  const handle = event.target.closest?.(".connector.out");
  if (!handle) return;
  event.preventDefault();
  activeDrag = {
    id: handle.dataset.id,
    kind: handle.dataset.kind,
    start: handle.getBoundingClientRect(),
  };
  const overlay = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  overlay.classList.add("drag-layer");
  const line = document.createElementNS(overlay.namespaceURI, "path");
  line.setAttribute("class", "drag-path");
  overlay.append(line);
  document.body.append(overlay);
  activeDrag.overlay = overlay;
  activeDrag.line = line;
});
window.addEventListener("pointermove", (event) => {
  if (!activeDrag) return;
  const box = activeDrag.start;
  const x = box.left + box.width / 2,
    y = box.top + box.height / 2;
  activeDrag.line.setAttribute(
    "d",
    `M ${x} ${y} C ${x + 80} ${y}, ${event.clientX - 80} ${event.clientY}, ${event.clientX} ${event.clientY}`,
  );
});
window.addEventListener("pointerup", (event) => {
  if (!activeDrag) return;
  const source = activeDrag;
  source.overlay.remove();
  activeDrag = null;
  const target = document
    .elementFromPoint(event.clientX, event.clientY)
    ?.closest(".connector.in");
  if (
    !target ||
    target.dataset.kind !== source.kind ||
    target.dataset.id === source.id
  )
    return;
  if (source.kind === "step") {
    const step = graph.workflows[selected]?.steps.find(
      (value) => value.id === source.id,
    );
    if (!step || (step.next || []).includes(target.dataset.id)) return;
    draft.push({
      kind: "step",
      action: "update",
      workflow: selected,
      id: step.id,
      label: step.label,
      description: step.description || "",
      next: [...(step.next || []), target.dataset.id],
    });
    saveDraft();
  } else openEdit("edge", "add", source.id, target.dataset.id);
});
function render() {
  if (!state) return;
  graph = view();
  const workflows = Object.entries(graph.workflows || {});
  const nodes = Object.entries(graph.nodes || {});
  $("workflow-count").textContent = workflows.length;
  $("node-count").textContent = nodes.length;
  $("section-workflows").classList.toggle("active", section === "workflows");
  $("section-nodes").classList.toggle("active", section === "nodes");
  const choices = section === "workflows" ? workflows : nodes;
  const query = $("search").value.toLowerCase().trim();
  const visible = choices.filter(([id, value]) =>
    (id + " " + (value.label || "") + " " + (value.description || ""))
      .toLowerCase()
      .includes(query),
  );
  if (!choices.some(([id]) => id === selected))
    selected = choices[0]?.[0] || null;
  const list = $("list");
  list.replaceChildren();
  for (const [id, value] of visible) {
    const button = item(
      "button",
      "item" + (id === selected ? " active" : ""),
      value.label || id,
    );
    button.append(item("small", "", id));
    button.addEventListener("click", () => {
      selected = id;
      render();
    });
    list.append(button);
  }
  $("crumb").textContent =
    section === "workflows" ? t("workflows") : t("nodesRelations");
  $("map-title").textContent =
    section === "workflows" ? t("processMap") : t("relationMap");
  const current =
    section === "workflows" ? graph.workflows[selected] : graph.nodes[selected];
  $("title").textContent = current?.label || selected || "Nothing selected";
  $("summary").textContent = current?.summary || current?.description || "";
  const canvas = $("canvas");
  canvas.replaceChildren();
  if (!current) {
    canvas.append(item("p", "empty", "Add a workflow or node to start."));
    return;
  }
  if (section === "workflows") {
    const row = item("div", "flow");
    for (const [index, step] of (current.steps || []).entries()) {
      const wrapper = item("div", "step-wrap");
      wrapper.append(
        card(
          "step",
          step.id,
          step.label,
          step.description,
          `STEP ${index + 1}`,
        ),
      );
      const related = (graph.triples || []).filter(
        (edge) => edge.s === step.id && graph.nodes[edge.o],
      );
      for (const edge of related)
        wrapper.append(
          item(
            "small",
            "step-relation",
            `${edge.p} → ${graph.nodes[edge.o].label || edge.o}`,
          ),
        );
      const connect = item("button", "link-button", t("linkNode"));
      connect.addEventListener("click", () => openEdit("edge", "add", step.id));
      wrapper.append(connect);
      row.append(wrapper);
    }
    if (!row.childNodes.length) row.append(item("p", "empty", t("noSteps")));
    canvas.append(row);
    const connections = (current.steps || []).flatMap((step) =>
      (step.next || []).map((next) => ({
        s: step.id,
        p: "NEXT_STEP",
        o: next,
        kind: "step",
      })),
    );
    requestAnimationFrame(() => drawConnections(row, connections));
    const edit = item("button", "secondary", t("editWorkflow"));
    edit.style.marginTop = "22px";
    edit.addEventListener("click", () =>
      openEdit("workflow", "update", selected),
    );
    canvas.append(edit);
  } else {
    const row = item("div", "flow");
    row.append(
      card(
        "node",
        selected,
        current.label,
        current.description,
        current.type || "node",
      ),
    );
    const connected = (graph.triples || []).filter(
      (edge) => edge.s === selected || edge.o === selected,
    );
    const targets = [
      ...new Set([
        ...connected.map((edge) => (edge.s === selected ? edge.o : edge.s)),
        ...Object.keys(graph.nodes || {}).filter((id) => id !== selected),
      ]),
    ]
      .filter((id) => graph.nodes[id])
      .slice(0, 20);
    const neighbors = item("div", "neighbor-grid");
    for (const target of targets) {
      const node = graph.nodes[target];
      neighbors.append(
        card("node", target, node.label, node.description, node.type || "node"),
      );
    }
    row.append(neighbors);
    canvas.append(row);
    requestAnimationFrame(() =>
      drawConnections(
        row,
        connected.filter((edge) => graph.nodes[edge.s] && graph.nodes[edge.o]),
      ),
    );
    const addEdge = item("button", "secondary", t("connect"));
    addEdge.style.marginTop = "22px";
    addEdge.addEventListener("click", () => openEdit("edge", "add", selected));
    canvas.append(addEdge);
  }
}
function openEdit(kind, action, id = "", target = "") {
  const fields = $("fields");
  fields.replaceChildren();
  const value =
    kind === "workflow"
      ? graph.workflows[id]
      : kind === "node"
        ? graph.nodes[id]
        : kind === "step"
          ? graph.workflows[selected]?.steps.find((step) => step.id === id)
          : null;
  $("edit-title").textContent =
    `${action === "create" ? t("addVerb") : t("editVerb")} ${kind}`;
  $("edit-form").dataset.kind = kind;
  $("edit-form").dataset.action = action;
  $("edit-form").dataset.id = id;
  $("delete-item").hidden =
    action === "create" || !["node", "step"].includes(kind);
  if (kind !== "edge") appendField(fields, t("id"), "id", id);
  if (kind === "workflow") {
    appendField(fields, t("name"), "label", value?.label);
    appendField(fields, t("summary"), "summary", value?.summary, null, true);
  } else if (kind === "step") {
    if (action === "create" && value === undefined) {
      const steps = graph.workflows[selected]?.steps || [];
      if (steps.length)
        appendField(
          fields,
          t("insertAfter"),
          "after",
          steps.at(-1).id,
          steps.map((step) => step.id),
        );
    }
    appendField(fields, t("name"), "label", value?.label);
    appendField(
      fields,
      t("description"),
      "description",
      value?.description,
      null,
      true,
    );
    appendField(fields, t("nextSteps"), "next", (value?.next || []).join(", "));
    fields.append(
      item(
        "p",
        "muted",
        "Step connections are checked against the canonical workflow before a PR is created.",
      ),
    );
  } else if (kind === "node") {
    appendField(fields, t("type"), "type", value?.type || "concept");
    appendField(fields, t("name"), "label", value?.label);
    appendField(
      fields,
      t("description"),
      "description",
      value?.description,
      null,
      true,
    );
  } else {
    appendField(fields, t("fromNode"), "s", id);
    const relationTypes = Object.keys(graph.ontology?.predicates || {}).filter(
      (predicate) => !["HAS_STEP", "NEXT_STEP"].includes(predicate),
    );
    appendField(
      fields,
      t("relationship"),
      "p",
      relationTypes[0],
      relationTypes,
    );
    appendField(
      fields,
      t("toNode"),
      "o",
      target,
      Object.keys(graph.nodes || {}),
    );
  }
  $("edit-dialog").showModal();
}
$("edit-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (draft.length >= 30) {
    status("A draft can contain at most 30 changes.");
    return;
  }
  const form = event.currentTarget;
  const values = Object.fromEntries(new FormData(form));
  const kind = form.dataset.kind;
  const change = { kind, action: form.dataset.action, ...values };
  if (kind === "step") {
    change.workflow = selected;
    change.next = values.next
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
  }
  draft.push(change);
  $("edit-dialog").close();
  if (kind === "workflow" || kind === "node") selected = change.id;
  saveDraft();
  status(t("saved"));
});
$("delete-item").addEventListener("click", () => {
  const form = $("edit-form");
  const kind = form.dataset.kind;
  const id = form.dataset.id;
  draft.push({
    kind,
    action: "remove",
    id,
    ...(kind === "step" ? { workflow: selected } : {}),
  });
  $("edit-dialog").close();
  saveDraft();
  status(t("saved"));
});
async function load() {
  try {
    let response = await fetch("/api/state", {
      cache: "no-store",
      headers: editorToken ? { "X-Editor-Token": editorToken } : {},
    });
    if (response.status === 403) {
      editorToken = prompt("Editor token / 編集用トークン:") || "";
      response = await fetch("/api/state", {
        cache: "no-store",
        headers: editorToken ? { "X-Editor-Token": editorToken } : {},
      });
    }
    if (!response.ok)
      throw new Error(`Graph could not be loaded (${response.status})`);
    state = await response.json();
    $("source-badge").textContent =
      `${state.file} · ${state.publishing ? t("githubBadge") : t("sourceBadge")}`;
    draft = [];
    loadDraft();
    render();
    status(
      draft.length && draftBaseSha !== state.sha
        ? t("invalidDraft")
        : t("loaded"),
    );
  } catch (error) {
    status(error.message);
  }
}
async function api(path, body) {
  if (state.publishing && !editorToken)
    editorToken =
      prompt("Editor token (kept only until this tab closes):") || "";
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(editorToken ? { "X-Editor-Token": editorToken } : {}),
    },
    body: JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok)
    throw new Error(result.detail || `Request failed (${response.status})`);
  return result;
}
function proposal() {
  return {
    base_sha: draftBaseSha || state.sha,
    operations: draft,
    source: $("source").value.trim(),
    reason: $("reason").value.trim(),
  };
}
function openReview() {
  $("operations").replaceChildren(
    ...draft.map((change) =>
      item(
        "p",
        "",
        `${change.action} ${change.kind}: ${change.id || `${change.s} ${change.p} ${change.o}`}`,
      ),
    ),
  );
  $("review-intro").textContent = draft.length
    ? `${draft.length} ${t("changeCount")} ${state.file}`
    : t("noChanges");
  const stale = draft.length && draftBaseSha !== state.sha;
  $("preview").disabled = !draft.length || stale;
  $("publish").disabled = !previewHash || !state.publishing;
  $("review-error").textContent = stale ? t("invalidDraft") : "";
  $("review-dialog").showModal();
}
$("preview").addEventListener("click", async () => {
  $("review-error").textContent = "";
  try {
    const result = await api("/api/preview", proposal());
    previewHash = result.preview_hash;
    $("diff").textContent = result.diff;
    $("diff").hidden = false;
    $("publish").disabled = !state.publishing;
    if (!state.publishing)
      $("review-error").textContent =
        "Local demo: configure a GitHub App and editor token to create a draft PR.";
  } catch (error) {
    $("review-error").textContent = error.message;
  }
});
$("publish").addEventListener("click", async () => {
  $("review-error").textContent = "";
  try {
    const result = await api("/api/pr", {
      ...proposal(),
      preview_hash: previewHash,
    });
    $("pr-link").href = result.url;
    $("pr-link").textContent = `Draft PR #${result.number} opened on GitHub ↗`;
    $("pr-link").hidden = false;
    draft = [];
    saveDraft();
  } catch (error) {
    $("review-error").textContent = error.message;
  }
});
$("discard").addEventListener("click", () => {
  draft = [];
  saveDraft();
  $("review-dialog").close();
  status("Draft discarded.");
});
$("undo-change").addEventListener("click", () => {
  if (!draft.length) return;
  draft.pop();
  saveDraft();
  $("review-dialog").close();
  status(t("saved"));
});
for (const name of ["workflows", "nodes"])
  $("section-" + name).addEventListener("click", () => {
    section = name;
    selected = null;
    render();
  });
$("search").addEventListener("input", render);
$("add").addEventListener("click", () => {
  if (section === "nodes") openEdit("node", "create");
  else if (selected) openEdit("step", "create");
  else openEdit("workflow", "create");
});
$("new-workflow").addEventListener("click", () => {
  section = "workflows";
  openEdit("workflow", "create");
});
$("review").addEventListener("click", openReview);
$("review-bottom").addEventListener("click", openReview);
$("reload").addEventListener("click", load);
async function setupStatus() {
  const response = await fetch("/api/setup/status", { cache: "no-store" });
  if (!response.ok) return;
  const result = await response.json();
  $("setup-open").hidden = result.connected;
  $("setup-register").disabled = !result.enabled || result.registered;
  if (!result.enabled)
    $("setup-error").textContent =
      "Set PUBLIC_BASE_URL and a random SETUP_TOKEN of at least 24 characters on the server, then restart the container.";
  $("install-link").hidden = !result.install_url;
  if (result.install_url) $("install-link").href = result.install_url;
  if (new URLSearchParams(location.search).get("setup") === "registered") {
    $("setup-dialog").showModal();
    history.replaceState(null, "", location.pathname);
  }
}
$("setup-open").addEventListener("click", () => $("setup-dialog").showModal());
$("setup-register").addEventListener("click", async () => {
  $("setup-error").textContent = "";
  try {
    const response = await fetch("/api/setup/start", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Setup-Token": $("setup-token").value,
      },
      body: JSON.stringify({
        repository: $("setup-repo").value.trim(),
        graph_path: $("setup-path").value.trim(),
      }),
    });
    const result = await response.json();
    if (!response.ok)
      throw new Error(result.detail || `Setup failed (${response.status})`);
    const form = item("form");
    form.method = "POST";
    form.action =
      $("setup-owner").value === "personal" ? result.personal_url : result.url;
    const manifest = item("input");
    manifest.type = "hidden";
    manifest.name = "manifest";
    manifest.value = JSON.stringify(result.manifest);
    form.append(manifest);
    document.body.append(form);
    form.submit();
  } catch (error) {
    $("setup-error").textContent = error.message;
  }
});
$("setup-finish").addEventListener("click", async () => {
  $("setup-error").textContent = "";
  try {
    const response = await fetch("/api/setup/finish", {
      method: "POST",
      headers: { "X-Setup-Token": $("setup-token").value },
    });
    const result = await response.json();
    if (!response.ok)
      throw new Error(result.detail || `Setup failed (${response.status})`);
    $("setup-dialog").close();
    await load();
    await setupStatus();
  } catch (error) {
    $("setup-error").textContent = error.message;
  }
});
$("language").addEventListener("click", () => {
  language = language === "ja" ? "en" : "ja";
  localStorage.setItem("trikedb-review-language", language);
  translatePage();
});
for (const button of document.querySelectorAll("[data-close]"))
  button.addEventListener("click", () => $(button.dataset.close).close());
translatePage();
load();
setupStatus();

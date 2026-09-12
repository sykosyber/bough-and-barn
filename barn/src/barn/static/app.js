let currentRunId = null;
let currentSnapshot = null;
let selectedAgentId = null;

const $ = (selector) => document.querySelector(selector);
const svgNS = "http://www.w3.org/2000/svg";

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status}: ${body}`);
  }
  return response.json();
}

async function bootstrapDemo() {
  setBusy(true);
  try {
    const payload = await api("/demo/bootstrap", { method: "POST" });
    currentRunId = payload.state.id;
    selectedAgentId = payload.decision.agent_id;
    await refresh();
    await showWhy(selectedAgentId);
    $("#complete").disabled = false;
  } finally {
    setBusy(false);
  }
}

async function completeDemo() {
  if (!currentRunId) return;
  setBusy(true);
  try {
    await api(`/demo/${currentRunId}/complete`, { method: "POST" });
    await refresh();
    if (selectedAgentId) await showWhy(selectedAgentId);
    $("#complete").disabled = true;
  } finally {
    setBusy(false);
  }
}

async function refresh() {
  if (!currentRunId) return;
  currentSnapshot = await api(`/runs/${currentRunId}/snapshot`);
  renderWork(currentSnapshot.state);
  renderCrew(currentSnapshot.state);
  renderEvents(currentSnapshot.events);
  const agents = Object.values(currentSnapshot.state.agents);
  const work = Object.values(currentSnapshot.state.work_items);
  const active = agents.filter((a) => a.status !== "retired").length;
  $("#run-status").textContent = `${currentSnapshot.state.goal} · ${currentRunId}`;
  $("#counts").textContent = `${active}/${agents.length} active crew · ${work.filter(w => w.status === "resolved").length}/${work.length} work resolved`;
}

function setBusy(value) {
  $("#bootstrap").disabled = value;
  if (value) $("#complete").disabled = true;
}

function renderWork(state) {
  const svg = $("#work-graph");
  clear(svg);
  const items = Object.values(state.work_items).sort((a, b) => a.created_seq - b.created_seq);
  const positions = treePositions(items, (item) => item.parent_work_id);
  drawEdges(svg, items, positions, (item) => item.parent_work_id);
  for (const work of items) {
    const { x, y } = positions[work.id];
    const g = el("g", { class: `node ${work.status}`, transform: `translate(${x},${y})` });
    g.appendChild(el("rect", { x: -82, y: -25, width: 164, height: 50, rx: 3 }));
    g.appendChild(text(work.title, 0, -3));
    g.appendChild(text(work.status, 0, 13, "meta"));
    svg.appendChild(g);
  }
}

function renderCrew(state) {
  const svg = $("#crew-graph");
  clear(svg);
  const agents = Object.values(state.agents).sort((a, b) => a.created_seq - b.created_seq);
  const positions = treePositions(agents, (agent) => agent.parent_agent_id);
  drawEdges(svg, agents, positions, (agent) => agent.parent_agent_id);
  for (const agent of agents) {
    const { x, y } = positions[agent.id];
    const g = el("g", { class: `node crew-node ${agent.status}`, transform: `translate(${x},${y})` });
    g.appendChild(el("circle", { cx: 0, cy: 0, r: 31 }));
    g.appendChild(text(agent.role, 0, -3));
    g.appendChild(text(agent.status, 0, 13, "meta"));
    g.addEventListener("click", () => showWhy(agent.id));
    svg.appendChild(g);
  }
}

function treePositions(items, parentOf) {
  const byId = Object.fromEntries(items.map((item) => [item.id, item]));
  const depth = {};
  const getDepth = (item) => {
    if (depth[item.id] !== undefined) return depth[item.id];
    const parent = parentOf(item);
    depth[item.id] = parent && byId[parent] ? getDepth(byId[parent]) + 1 : 0;
    return depth[item.id];
  };
  items.forEach(getDepth);
  const levels = {};
  items.forEach((item) => (levels[depth[item.id]] ||= []).push(item));
  const width = 660;
  const out = {};
  for (const [d, level] of Object.entries(levels)) {
    level.forEach((item, index) => {
      const spacing = width / (level.length + 1);
      out[item.id] = { x: spacing * (index + 1), y: 75 + Number(d) * 125 };
    });
  }
  return out;
}

function drawEdges(svg, items, positions, parentOf) {
  for (const item of items) {
    const parent = parentOf(item);
    if (!parent || !positions[parent]) continue;
    const a = positions[parent];
    const b = positions[item.id];
    svg.appendChild(el("line", { class: "edge", x1: a.x, y1: a.y + 32, x2: b.x, y2: b.y - 32 }));
  }
}

async function showWhy(agentId) {
  if (!currentRunId) return;
  selectedAgentId = agentId;
  const explanation = await api(`/runs/${currentRunId}/agents/${agentId}/why`);
  const list = $("#why-list");
  list.innerHTML = "";
  for (const step of explanation.steps) {
    const li = document.createElement("li");
    const label = document.createElement("strong");
    label.textContent = `${step.kind}: ${step.label}`;
    li.appendChild(label);
    if (step.detail) li.appendChild(document.createTextNode(` — ${step.detail}`));
    list.appendChild(li);
  }
}

function renderEvents(events) {
  const root = $("#events");
  root.innerHTML = "";
  for (const event of [...events].reverse()) {
    const row = document.createElement("div");
    row.className = "event";
    row.innerHTML = `<div class="seq">#${event.seq}</div><div><div class="kind"></div><div class="detail"></div></div>`;
    row.querySelector(".kind").textContent = event.type;
    row.querySelector(".detail").textContent = `${event.actor_agent_id || "system"} · ${event.work_id || "no work"}`;
    root.appendChild(row);
  }
}

function el(name, attrs = {}) {
  const node = document.createElementNS(svgNS, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  return node;
}

function text(value, x, y, cls = "") {
  const node = el("text", { x, y, "text-anchor": "middle", class: cls });
  const clipped = value.length > 25 ? value.slice(0, 22) + "…" : value;
  node.textContent = clipped;
  return node;
}

function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

$("#bootstrap").addEventListener("click", () => bootstrapDemo().catch(showError));
$("#complete").addEventListener("click", () => completeDemo().catch(showError));

function showError(error) {
  $("#run-status").textContent = `Error: ${error.message}`;
  setBusy(false);
}

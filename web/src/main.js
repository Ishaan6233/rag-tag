import * as OBC from "@thatopen/components";
import "./style.css";

const viewport = document.getElementById("viewport");
const statusEl = document.getElementById("status");
const fileNameEl = document.getElementById("fileName");
const reloadBtn = document.getElementById("reloadBtn");
const messagesEl = document.getElementById("messages");
const stepsEl = document.getElementById("steps");
const chatForm = document.getElementById("chatForm");
const chatText = document.getElementById("chatText");
const tabButtons = document.querySelectorAll(".tab[data-tab]");
const panels = document.querySelectorAll(".chat__panel");

let sessionId = localStorage.getItem("ragtag-session") || null;
let currentIfc = null;

const setStatus = (text) => {
  statusEl.textContent = text;
};

const addMessage = (role, text) => {
  const card = document.createElement("div");
  card.className = `message ${role === "user" ? "message--user" : ""}`;

  const roleEl = document.createElement("div");
  roleEl.className = "message__role";
  roleEl.textContent = role === "user" ? "You" : "Assistant";

  const textEl = document.createElement("div");
  textEl.className = "message__text";
  textEl.textContent = text;

  card.append(roleEl, textEl);
  messagesEl.appendChild(card);
  messagesEl.scrollTop = messagesEl.scrollHeight;
};

const renderSteps = (steps) => {
  stepsEl.innerHTML = "";
  if (!steps || steps.length === 0) {
    const empty = document.createElement("div");
    empty.className = "step";
    empty.textContent = "No tool steps recorded yet.";
    stepsEl.appendChild(empty);
    return;
  }

  steps.forEach((entry, index) => {
    const step = document.createElement("div");
    step.className = "step";

    const title = document.createElement("div");
    title.className = "step__title";
    title.textContent = `Step ${index + 1}`;

    const content = document.createElement("div");
    content.textContent = JSON.stringify(entry, null, 2);

    step.append(title, content);
    stepsEl.appendChild(step);
  });
};

tabButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    const target = btn.dataset.tab;
    tabButtons.forEach((b) => b.classList.remove("tab--active"));
    btn.classList.add("tab--active");
    panels.forEach((panel) => {
      panel.classList.toggle(
        "chat__panel--active",
        panel.dataset.panel === target
      );
    });
  });
});

const components = new OBC.Components();
const worlds = components.get(OBC.Worlds);
const world = worlds.create();
world.scene = new OBC.SimpleScene(components);
world.scene.setup();
world.scene.three.background = null;
world.renderer = new OBC.SimpleRenderer(components, viewport);
world.camera = new OBC.OrthoPerspectiveCamera(components);
components.init();
components.get(OBC.Grids).create(world);

await world.camera.controls.setLookAt(78, 20, -2.2, 26, -4, 25);

const ifcLoader = components.get(OBC.IfcLoader);
await ifcLoader.setup({
  autoSetWasm: false,
  wasm: {
    path: "https://unpkg.com/web-ifc@0.0.74/",
    absolute: true,
  },
});

const fragments = components.get(OBC.FragmentsManager);
const workerSource =
  "https://thatopen.github.io/engine_fragment/resources/worker.mjs";
const workerBlob = await (await fetch(workerSource)).blob();
const workerFile = new File([workerBlob], "worker.mjs", {
  type: "text/javascript",
});
const workerUrl = URL.createObjectURL(workerFile);
fragments.init(workerUrl);

world.camera.controls.addEventListener("update", () => {
  fragments.core.update();
});

fragments.list.onItemSet.add(({ value: model }) => {
  model.useCamera(world.camera.three);
  world.scene.three.add(model.object);
  fragments.core.update(true);
});

fragments.core.models.materials.list.onItemSet.add(({ value: material }) => {
  if (!("isLodMaterial" in material && material.isLodMaterial)) {
    material.polygonOffset = true;
    material.polygonOffsetUnits = 1;
    material.polygonOffsetFactor = Math.random();
  }
});

const clearModels = () => {
  for (const model of fragments.list.values()) {
    world.scene.three.remove(model.object);
  }
  if (typeof fragments.list.clear === "function") {
    fragments.list.clear();
  }
};

const fetchDefaultIfc = async () => {
  const res = await fetch("/api/ifc/default");
  if (!res.ok) {
    throw new Error("No IFC file found on the server.");
  }
  const data = await res.json();
  return data.file;
};

const loadIfc = async (fileName) => {
  if (!fileName) {
    return;
  }
  clearModels();
  setStatus("Loading IFC model…");
  const response = await fetch(`/ifc/${fileName}`);
  if (!response.ok) {
    throw new Error(`Failed to load ${fileName}.`);
  }
  const buffer = new Uint8Array(await response.arrayBuffer());
  await ifcLoader.load(buffer, false, fileName, {
    processData: {
      progressCallback: (progress) => {
        const pct = Math.round(progress * 100);
        setStatus(`Parsing IFC… ${pct}%`);
      },
    },
  });
  setStatus("Model ready.");
};

const initViewer = async () => {
  try {
    setStatus("Connecting to server…");
    currentIfc = await fetchDefaultIfc();
    fileNameEl.textContent = currentIfc;
    await loadIfc(currentIfc);
  } catch (err) {
    setStatus("Viewer failed to load.");
    addMessage("assistant", err.message);
  }
};

reloadBtn.addEventListener("click", async () => {
  if (!currentIfc) {
    return;
  }
  await loadIfc(currentIfc);
});

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = chatText.value.trim();
  if (!text) {
    return;
  }
  chatText.value = "";
  addMessage("user", text);

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question: text,
        session_id: sessionId,
        ifc_file: currentIfc,
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Chat request failed.");
    }
    sessionId = data.session_id;
    localStorage.setItem("ragtag-session", sessionId);
    addMessage("assistant", data.answer || "No answer returned.");
    renderSteps(data.tool_history || []);
  } catch (err) {
    addMessage("assistant", err.message);
  }
});

initViewer();

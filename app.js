const DATA_URL = "data/athletes.encrypted.json";
const SAMPLE_URL = "data/athletes.sample.json";

const state = {
  board: null,
  category: "all",
  gradYear: "all",
  position: "all",
  recruitState: "all",
  search: "",
  selectedId: null
};

const els = {
  authScreen: document.querySelector("#authScreen"),
  authForm: document.querySelector("#authForm"),
  passwordInput: document.querySelector("#passwordInput"),
  authError: document.querySelector("#authError"),
  appShell: document.querySelector("#appShell"),
  lockButton: document.querySelector("#lockButton"),
  offerList: document.querySelector("#offerList"),
  detailPanel: document.querySelector("#detailPanel"),
  template: document.querySelector("#offerCardTemplate"),
  categoryButtons: document.querySelector("#categoryButtons"),
  yearFilter: document.querySelector("#yearFilter"),
  positionFilter: document.querySelector("#positionFilter"),
  stateFilter: document.querySelector("#stateFilter"),
  searchInput: document.querySelector("#searchInput"),
  totalCount: document.querySelector("#totalCount"),
  newCount: document.querySelector("#newCount"),
  secMetric: document.querySelector("#secMetric"),
  p4Metric: document.querySelector("#p4Metric"),
  g6Metric: document.querySelector("#g6Metric"),
  hiddenMetric: document.querySelector("#hiddenMetric"),
  syncLabel: document.querySelector("#syncLabel"),
  syncTime: document.querySelector("#syncTime")
};

els.authForm.addEventListener("submit", async event => {
  event.preventDefault();
  await unlock(els.passwordInput.value);
});

els.lockButton.addEventListener("click", () => {
  state.board = null;
  state.selectedId = null;
  els.passwordInput.value = "";
  els.appShell.classList.add("is-locked");
  els.authScreen.classList.remove("is-hidden");
  els.authError.textContent = "";
  els.passwordInput.focus();
});

els.categoryButtons.addEventListener("click", event => {
  const button = event.target.closest("[data-category]");
  if (!button) return;
  state.category = button.dataset.category;
  document.querySelectorAll("[data-category]").forEach(node => node.classList.toggle("is-active", node === button));
  render();
});

els.yearFilter.addEventListener("change", event => {
  state.gradYear = event.target.value;
  render();
});

els.positionFilter.addEventListener("change", event => {
  state.position = event.target.value;
  render();
});

els.stateFilter.addEventListener("change", event => {
  state.recruitState = event.target.value;
  render();
});

els.searchInput.addEventListener("input", event => {
  state.search = event.target.value.trim().toLowerCase();
  render();
});

async function unlock(password) {
  els.authError.textContent = "";
  let encrypted = null;

  try {
    encrypted = await fetchJson(DATA_URL);
  } catch (error) {
    encrypted = null;
  }

  if (encrypted && encrypted.ciphertext !== "placeholder") {
    try {
      state.board = await decryptBoard(encrypted, password);
    } catch {
      els.authError.textContent = "Password was not accepted.";
      return;
    }
  } else {
    try {
      state.board = await fetchJson(SAMPLE_URL);
      els.authError.textContent = "Live encrypted data was not found. Showing sample rows.";
    } catch {
      els.authError.textContent = "The data feed is unavailable.";
      return;
    }
  }

  if (!isBoard(state.board)) {
    els.authError.textContent = "The data feed opened, but it is not in the expected format.";
    return;
  }

  state.selectedId = state.board.athletes[0]?.id ?? null;
  populateFilters();
  els.appShell.classList.remove("is-locked");
  els.authScreen.classList.add("is-hidden");
  render();
}

async function fetchJson(url) {
  const response = await fetch(`${url}?v=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Unable to load ${url}`);
  return response.json();
}

async function decryptBoard(payload, password) {
  if (!payload || payload.version !== 1) throw new Error("Unsupported encrypted payload");
  const enc = new TextEncoder();
  const keyMaterial = await crypto.subtle.importKey("raw", enc.encode(password), "PBKDF2", false, ["deriveKey"]);
  const key = await crypto.subtle.deriveKey(
    {
      name: "PBKDF2",
      salt: base64ToBytes(payload.salt),
      iterations: payload.iterations,
      hash: "SHA-256"
    },
    keyMaterial,
    { name: "AES-GCM", length: 256 },
    false,
    ["decrypt"]
  );
  const plainBuffer = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: base64ToBytes(payload.iv) },
    key,
    base64ToBytes(payload.ciphertext)
  );
  return JSON.parse(new TextDecoder().decode(plainBuffer));
}

function base64ToBytes(value) {
  const binary = atob(value);
  return Uint8Array.from(binary, char => char.charCodeAt(0));
}

function isBoard(board) {
  return board && board.meta && Array.isArray(board.athletes);
}

function populateFilters() {
  const athletes = state.board.athletes;
  fillSelect(els.yearFilter, ["all", ...unique(athletes.map(item => item.gradYear).filter(Boolean)).sort()]);
  fillSelect(els.positionFilter, ["all", ...unique(athletes.map(item => item.position).filter(Boolean)).sort()]);
  fillSelect(els.stateFilter, ["all", ...unique(athletes.map(item => item.state).filter(Boolean)).sort()]);
}

function fillSelect(select, values) {
  const labels = {
    all: "All"
  };
  select.innerHTML = "";
  values.forEach(value => {
    const option = document.createElement("option");
    option.value = String(value);
    option.textContent = labels[value] ?? value;
    select.append(option);
  });
}

function unique(values) {
  return [...new Set(values.map(value => String(value)).filter(Boolean))];
}

function render() {
  if (!state.board) return;
  const athletes = [...state.board.athletes].sort((a, b) => new Date(b.updatedAt || b.lastOfferAt) - new Date(a.updatedAt || a.lastOfferAt));
  const filtered = athletes.filter(matchesFilters);
  const selected = filtered.find(item => item.id === state.selectedId) ?? filtered[0] ?? null;
  state.selectedId = selected?.id ?? null;

  renderMetrics(athletes);
  renderList(filtered);
  renderDetail(selected);

  els.syncLabel.textContent = state.board.meta.status || "Encrypted feed";
  els.syncTime.textContent = state.board.meta.generatedAt ? `Updated ${formatDateTime(state.board.meta.generatedAt)}` : "Updated time unavailable";
}

function matchesFilters(item) {
  if (state.category !== "all" && !(item.categories || []).includes(state.category)) return false;
  if (state.gradYear !== "all" && String(item.gradYear) !== state.gradYear) return false;
  if (state.position !== "all" && String(item.position) !== state.position) return false;
  if (state.recruitState !== "all" && String(item.state) !== state.recruitState) return false;
  if (!state.search) return true;
  const haystack = [
    item.name,
    item.highSchool,
    item.city,
    item.state,
    item.position,
    item.gradYear,
    ...(item.offerSchools || []),
    item.sourceText
  ].join(" ").toLowerCase();
  return haystack.includes(state.search);
}

function renderMetrics(athletes) {
  const count = category => athletes.filter(item => (item.categories || []).includes(category)).length;
  els.totalCount.textContent = athletes.length;
  els.newCount.textContent = athletes.filter(item => item.isNew).length;
  els.secMetric.textContent = count("sec");
  els.p4Metric.textContent = count("p4");
  els.g6Metric.textContent = count("g6-footprint");
  els.hiddenMetric.textContent = count("hidden");
}

function renderList(athletes) {
  els.offerList.innerHTML = "";
  if (!athletes.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.innerHTML = "<strong>No matching offers.</strong><p class=\"muted\">Adjust the filters or wait for the next X scan.</p>";
    els.offerList.append(empty);
    return;
  }

  athletes.forEach(item => {
    const node = els.template.content.firstElementChild.cloneNode(true);
    node.classList.toggle("is-selected", item.id === state.selectedId);
    const button = node.querySelector(".card-button");
    const categoryTag = node.querySelector(".category-tag");
    const yearTag = node.querySelector(".year-tag");
    const title = node.querySelector("h3");
    const score = node.querySelector(".score-pill");
    const meta = node.querySelector(".meta-line");
    const offer = node.querySelector(".offer-line");
    const links = node.querySelector(".link-row");

    const category = primaryCategory(item);
    categoryTag.textContent = category.label;
    categoryTag.classList.add(category.key);
    yearTag.textContent = item.gradYear ? `${item.gradYear}` : "Year TBD";
    title.textContent = item.name || "Unknown Recruit";
    score.textContent = `HG ${item.hiddenGemScore ?? 0}`;
    meta.textContent = [item.position, formatHeight(item.heightInches), item.weightPounds ? `${item.weightPounds} lb` : null, locationLine(item)].filter(Boolean).join(" | ");
    offer.textContent = `Offer: ${(item.offerSchools || ["Unclear"]).join(", ")}`;
    links.append(...linkNodes(item));

    button.addEventListener("click", () => {
      state.selectedId = item.id;
      render();
    });
    els.offerList.append(node);
  });
}

function renderDetail(item) {
  if (!item) {
    els.detailPanel.innerHTML = "<p class=\"eyebrow\">Selected Recruit</p><h3>No result selected</h3><p class=\"muted\">The current filters do not match any offer rows.</p>";
    return;
  }

  const strengths = item.brief?.strengths?.length ? item.brief.strengths : ["Needs staff review after link check."];
  const weaknesses = item.brief?.weaknesses?.length ? item.brief.weaknesses : ["Profile is incomplete until film and verified measurements are reviewed."];
  els.detailPanel.innerHTML = `
    <p class="eyebrow">${primaryCategory(item).label}</p>
    <h3>${escapeHtml(item.name || "Unknown Recruit")}</h3>
    <p class="muted">${escapeHtml([item.highSchool, locationLine(item)].filter(Boolean).join(" | "))}</p>
    <div class="detail-grid">
      <div><small>Grad Year</small><strong>${escapeHtml(item.gradYear || "TBD")}</strong></div>
      <div><small>Position</small><strong>${escapeHtml(item.position || "TBD")}</strong></div>
      <div><small>Frame</small><strong>${escapeHtml([formatHeight(item.heightInches), item.weightPounds ? `${item.weightPounds} lb` : null].filter(Boolean).join(" | ") || "TBD")}</strong></div>
      <div><small>Hidden Score</small><strong>${escapeHtml(item.hiddenGemScore ?? 0)}</strong></div>
    </div>
    <p class="offer-line">Offer: ${escapeHtml((item.offerSchools || ["Unclear"]).join(", "))}</p>
    <h4>Strengths</h4>
    <ul class="brief-list">${strengths.map(text => `<li>${escapeHtml(text)}</li>`).join("")}</ul>
    <h4>Weaknesses</h4>
    <ul class="brief-list">${weaknesses.map(text => `<li>${escapeHtml(text)}</li>`).join("")}</ul>
    <div class="link-row">${linkNodes(item).map(node => node.outerHTML).join("")}</div>
    <p class="muted">Last seen ${escapeHtml(formatDateTime(item.lastOfferAt || item.updatedAt))}. Confidence ${escapeHtml(item.confidence ?? "TBD")}.</p>
  `;
}

function primaryCategory(item) {
  const categories = item.categories || [];
  if (categories.includes("sec")) return { key: "sec", label: "SEC" };
  if (categories.includes("p4")) return { key: "p4", label: "P4" };
  if (categories.includes("g6-footprint")) return { key: "g6-footprint", label: "G6 Footprint" };
  if (categories.includes("hidden")) return { key: "hidden", label: "Hidden Gem" };
  return { key: "watch", label: "Watch" };
}

function linkNodes(item) {
  return [
    ["X", item.xUrl],
    ["Hudl", item.hudlUrl],
    ["UC Report", item.ucReportUrl]
  ]
    .filter(([, href]) => href)
    .map(([label, href]) => {
      const anchor = document.createElement("a");
      anchor.href = href;
      anchor.target = "_blank";
      anchor.rel = "noopener noreferrer";
      anchor.textContent = label;
      return anchor;
    });
}

function locationLine(item) {
  return [item.city, item.state].filter(Boolean).join(", ");
}

function formatHeight(inches) {
  const value = Number(inches);
  if (!value) return "";
  return `${Math.floor(value / 12)}'${value % 12}"`;
}

function formatDateTime(value) {
  if (!value) return "time unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "time unavailable";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit"
  }).format(date);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

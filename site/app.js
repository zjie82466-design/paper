const STORAGE_KEY = "power-paper-digest-filters-v2";
const PERSONAL_STORAGE_KEY = "power-paper-digest-personal-v1";
const SOURCE_LABELS = {
  arxiv: "arXiv",
  ieee: "IEEE",
  elsevier: "Elsevier",
  nature: "Nature",
};

const state = {
  payload: null,
  archivePayload: null,
  viewMode: "latest",
  source: "all",
  journal: "all",
  keywordGroup: "all",
  label: "all",
  personalFilter: "all",
  sort: "score",
  query: "",
  paperState: {},
  activeDialogPaper: null,
};

document.addEventListener("DOMContentLoaded", async () => {
  loadSavedState();

  const sortSelect = document.getElementById("sort-select");
  const searchInput = document.getElementById("search-input");

  sortSelect.value = state.sort;
  searchInput.value = state.query;

  sortSelect.addEventListener("change", (event) => {
    state.sort = event.target.value;
    saveFilterState();
    renderSections();
  });

  searchInput.addEventListener("input", (event) => {
    state.query = event.target.value.trim().toLowerCase();
    saveFilterState();
    renderSections();
  });

  document.getElementById("reset-filters").addEventListener("click", () => {
    state.source = "all";
    state.journal = "all";
    state.keywordGroup = "all";
    state.label = "all";
    state.personalFilter = "all";
    state.sort = "score";
    state.query = "";
    sortSelect.value = state.sort;
    searchInput.value = "";
    saveFilterState();
    renderFrame();
    renderSections();
  });

  document.getElementById("export-reading-list").addEventListener("click", () => {
    downloadText("power-paper-reading-list.md", buildReadingListMarkdown());
  });

  document.getElementById("dialog-close").addEventListener("click", closePaperDialog);
  document.getElementById("paper-dialog").addEventListener("click", (event) => {
    if (event.target.id === "paper-dialog") closePaperDialog();
  });
  document.getElementById("dialog-note").addEventListener("input", (event) => {
    if (!state.activeDialogPaper) return;
    updatePersonalNote(state.activeDialogPaper, event.target.value);
  });
  document.querySelectorAll("[data-view-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      state.viewMode = button.dataset.viewMode || "latest";
      normalizeSavedState();
      saveFilterState();
      renderFrame();
      renderSections();
    });
  });

  try {
    const response = await fetch("./latest.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`latest.json ${response.status}`);
    state.payload = await response.json();
    state.archivePayload = await fetchArchivePayload(state.payload);
    normalizeSavedState();
    renderFrame();
    renderSections();
  } catch (error) {
    renderError(error);
  }
});

async function fetchArchivePayload(fallbackPayload) {
  try {
    const response = await fetch("./archive.json", { cache: "no-store" });
    if (!response.ok) return fallbackPayload;
    return await response.json();
  } catch (error) {
    return fallbackPayload;
  }
}

function renderFrame() {
  const active = activePayload();
  const { meta, papers } = active;
  const latestMeta = state.payload.meta;
  const archiveMeta = (state.archivePayload || state.payload).meta;
  document.getElementById("site-title").textContent = latestMeta.title;
  document.getElementById("site-subtitle").textContent = latestMeta.subtitle;
  document.getElementById("date-window").textContent = `${latestMeta.window_start} 至 ${latestMeta.target_date}`;
  document.getElementById("updated-at").textContent = `生成于 ${formatDateTime(latestMeta.generated_at, latestMeta.timezone)}`;
  document.getElementById("paper-count").textContent =
    `${latestMeta.paper_count} 篇本周 / ${archiveMeta.paper_count || archiveMeta.archive_count || latestMeta.paper_count} 篇留存`;
  renderViewToggle();

  const stats = document.getElementById("stats");
  stats.innerHTML = "";
  [
    ["本周入选", latestMeta.paper_count],
    ["历史留存", archiveMeta.paper_count || archiveMeta.archive_count || latestMeta.paper_count],
    ["来源类型", Object.keys(meta.source_counts || {}).length],
    ["覆盖期刊", Object.keys(meta.journal_counts || {}).length],
  ].forEach(([label, value]) => {
    const card = document.createElement("article");
    card.className = "stat-card";
    card.innerHTML = `<span>${label}</span><strong>${value}</strong>`;
    stats.appendChild(card);
  });

  buildChips(
    document.getElementById("source-filters"),
    [{ value: "all", label: "全部" }].concat(
      Object.entries(meta.source_counts || {}).map(([source, count]) => ({
        value: source,
        label: `${sourceLabel(source)} (${count})`,
      })),
    ),
    state.source,
    (value) => {
      state.source = value;
      saveFilterState();
      renderSections();
    },
  );

  buildChips(
    document.getElementById("journal-filters"),
    [{ value: "all", label: "全部" }].concat(
      Object.entries(meta.journal_counts || {}).map(([journal, count]) => ({
        value: journal,
        label: `${shortJournalName(journal)} (${count})`,
        title: journal,
      })),
    ),
    state.journal,
    (value) => {
      state.journal = value;
      saveFilterState();
      renderSections();
    },
  );

  const groupCounts = buildKeywordGroupCounts(papers);
  buildChips(
    document.getElementById("keyword-filters"),
    [{ value: "all", label: "全部" }].concat(
      Object.entries(groupCounts).map(([group, count]) => ({ value: group, label: `${group} (${count})` })),
    ),
    state.keywordGroup,
    (value) => {
      state.keywordGroup = value;
      saveFilterState();
      renderSections();
    },
  );

  const labelCounts = buildCounts(papers, (paper) => paper.relevance_label || "Background Read");
  buildChips(
    document.getElementById("label-filters"),
    [{ value: "all", label: "全部" }].concat(
      Object.entries(labelCounts).map(([label, count]) => ({ value: label, label: `${label} (${count})` })),
    ),
    state.label,
    (value) => {
      state.label = value;
      saveFilterState();
      renderSections();
    },
  );

  renderPersonalFilters();

  renderSourceNotes(meta.source_notes || {});
  renderRequirementPanel(state.payload.meta);
  renderPersonalSummary();

  const errorBanner = document.getElementById("error-banner");
  if (meta.source_errors && meta.source_errors.length > 0) {
    errorBanner.hidden = false;
    errorBanner.textContent = `部分来源抓取异常：${meta.source_errors.join(" | ")}`;
  } else {
    errorBanner.hidden = true;
    errorBanner.textContent = "";
  }
}

function activePayload() {
  if (state.viewMode === "archive" && state.archivePayload) return state.archivePayload;
  return state.payload;
}

function renderViewToggle() {
  document.querySelectorAll("[data-view-mode]").forEach((button) => {
    const active = button.dataset.viewMode === state.viewMode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function renderSections() {
  if (!state.payload) return;
  const dataset = activePayload();

  const container = document.getElementById("sections");
  container.innerHTML = "";
  const sectionTemplate = document.getElementById("section-template");
  let visibleTotal = 0;

  Object.entries(dataset.sections).forEach(([, section]) => {
    const papers = sortPapers(filterPapers(section.papers));
    visibleTotal += papers.length;

    const fragment = sectionTemplate.content.cloneNode(true);
    fragment.querySelector("h3").textContent = section.title;
    fragment.querySelector(".section-heading p").textContent = section.description;
    fragment.querySelector(".section-heading span").textContent = `${papers.length} 篇`;
    const grid = fragment.querySelector(".paper-grid");

    if (papers.length === 0) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "当前筛选条件下没有论文。";
      grid.appendChild(empty);
    } else {
      papers.forEach((paper) => grid.appendChild(renderPaper(paper)));
    }
    container.appendChild(fragment);
  });

  document.getElementById("visible-count").textContent = `${visibleTotal} 篇论文通过当前筛选`;
}

function renderPaper(paper) {
  const fragment = document.getElementById("paper-template").content.cloneNode(true);
  const personal = getPersonalState(paper);
  const card = fragment.querySelector(".paper-card");
  card.classList.toggle("is-priority", personal.priority);
  card.classList.toggle("is-saved", personal.saved);
  card.classList.toggle("is-read", personal.read);
  fragment.querySelector(".source").textContent = sourceLabel(paper.source);
  fragment.querySelector(".journal").textContent = paper.journal;
  fragment.querySelector(".age").textContent = paper.published_date_local;
  fragment.querySelector(".title").textContent = paper.title;
  fragment.querySelector(".authors").textContent =
    `${(paper.authors || []).slice(0, 6).join(", ") || "Unknown authors"} · ${paper.published_time_local}`;
  fragment.querySelector(".score").textContent = `推荐分 ${Number(paper.final_score).toFixed(1)} / 10`;
  fragment.querySelector(".label").textContent = paper.relevance_label;
  setupPersonalActions(fragment, paper);
  fragment.querySelector(".reason").textContent = paper.score_reason || "";
  fragment.querySelector(".summary").textContent = paper.ai_summary || "";
  fragment.querySelector(".value").textContent = paper.application_value || "";
  fragment.querySelector(".limitations").textContent = paper.limitations || "";

  const keywordContainer = fragment.querySelector(".keywords");
  (paper.matched_keyword_groups || []).forEach((group) => {
    const chip = document.createElement("span");
    chip.textContent = group;
    keywordContainer.appendChild(chip);
  });
  (paper.matched_keywords || []).slice(0, 5).forEach((keyword) => {
    const chip = document.createElement("span");
    chip.className = "keyword";
    chip.textContent = keyword;
    keywordContainer.appendChild(chip);
  });

  fragment.querySelector(".primary-link").href = paper.url;
  if (paper.pdf_url) {
    const pdf = fragment.querySelector(".pdf-link");
    pdf.href = paper.pdf_url;
    pdf.hidden = false;
  }
  if (paper.doi) {
    const doi = fragment.querySelector(".doi-link");
    doi.href = paper.doi_url || `https://doi.org/${paper.doi}`;
    doi.hidden = false;
  }
  if (paper.xplore_url) {
    const journalLink = fragment.querySelector(".journal-link");
    journalLink.href = paper.xplore_url;
    journalLink.hidden = false;
  }

  const status = fragment.querySelector(".copy-status");
  const fallback = fragment.querySelector(".citation-fallback");
  enableCopyButton(fragment.querySelector(".copy-doi"), paper.doi, status, fallback, "DOI 已复制");
  enableCopyButton(fragment.querySelector(".copy-bibtex"), paper.bibtex_entry, status, fallback, "BibTeX 已复制");
  enableCopyButton(fragment.querySelector(".copy-ris"), paper.ris_entry, status, fallback, "RIS 已复制");

  const noteBox = fragment.querySelector(".note-box");
  const noteInput = fragment.querySelector(".note-input");
  noteInput.value = personal.note || "";
  noteBox.open = Boolean(personal.note);
  noteInput.addEventListener("input", (event) => {
    updatePersonalNote(paper, event.target.value);
  });

  return fragment;
}

function filterPapers(papers) {
  return papers.filter((paper) => {
    const sourceMatch = state.source === "all" || paper.source === state.source;
    const journalMatch = state.journal === "all" || paper.journal === state.journal;
    const groupMatch =
      state.keywordGroup === "all" || (paper.matched_keyword_groups || []).includes(state.keywordGroup);
    const labelMatch = state.label === "all" || paper.relevance_label === state.label;
    const personalMatch = matchesPersonalFilter(paper);
    const haystack = [
      paper.title,
      paper.journal,
      paper.doi || "",
      (paper.authors || []).join(" "),
      (paper.matched_keywords || []).join(" "),
      (paper.matched_keyword_groups || []).join(" "),
      paper.score_reason || "",
      paper.ai_summary || "",
      paper.application_value || "",
      paper.limitations || "",
      getPersonalState(paper).note || "",
    ]
      .join(" ")
      .toLowerCase();
    const queryMatch = !state.query || haystack.includes(state.query);
    return sourceMatch && journalMatch && groupMatch && labelMatch && personalMatch && queryMatch;
  });
}

function sortPapers(papers) {
  return [...papers].sort((left, right) => {
    if (state.sort === "latest") {
      return new Date(right.published_at_local) - new Date(left.published_at_local);
    }
    if (state.sort === "journal") {
      return left.journal.localeCompare(right.journal);
    }
    if (state.sort === "personal") {
      return personalRank(right) - personalRank(left) || right.final_score - left.final_score;
    }
    return right.final_score - left.final_score;
  });
}

function buildKeywordGroupCounts(papers) {
  const counts = {};
  papers.forEach((paper) => {
    (paper.matched_keyword_groups || []).forEach((group) => {
      counts[group] = (counts[group] || 0) + 1;
    });
  });
  return Object.fromEntries(Object.entries(counts).sort((a, b) => b[1] - a[1]));
}

function buildCounts(items, readValue) {
  const counts = {};
  items.forEach((item) => {
    const value = readValue(item);
    if (value) counts[value] = (counts[value] || 0) + 1;
  });
  return Object.fromEntries(Object.entries(counts).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])));
}

function buildChips(container, options, active, onClick) {
  container.innerHTML = "";
  options.forEach((option) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `chip${option.value === active ? " is-active" : ""}`;
    button.textContent = option.label;
    if (option.title) button.title = option.title;
    button.addEventListener("click", () => {
      onClick(option.value);
      buildChips(container, options, option.value, onClick);
    });
    container.appendChild(button);
  });
}

function setupPersonalActions(fragment, paper) {
  const detailButton = fragment.querySelector(".detail-button");
  const priorityButton = fragment.querySelector(".priority-button");
  const savedButton = fragment.querySelector(".saved-button");
  const readButton = fragment.querySelector(".read-button");

  detailButton.addEventListener("click", () => openPaperDialog(paper));
  priorityButton.addEventListener("click", () => togglePersonalFlag(paper, "priority"));
  savedButton.addEventListener("click", () => togglePersonalFlag(paper, "saved"));
  readButton.addEventListener("click", () => togglePersonalFlag(paper, "read"));

  syncPersonalButtons(fragment, paper);
}

function syncPersonalButtons(fragment, paper) {
  const personal = getPersonalState(paper);
  const buttonMap = [
    [".priority-button", personal.priority, "重点", "重点中"],
    [".saved-button", personal.saved, "收藏", "已收藏"],
    [".read-button", personal.read, "已读", "已读"],
  ];
  buttonMap.forEach(([selector, active, label, activeLabel]) => {
    const button = fragment.querySelector(selector);
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
    button.textContent = active ? activeLabel : label;
  });
}

function togglePersonalFlag(paper, flag) {
  const key = paperKey(paper);
  const personal = getPersonalState(paper);
  state.paperState[key] = { ...personal, [flag]: !personal[flag] };
  cleanupPersonalState(key);
  savePersonalState();
  renderFrame();
  renderSections();
}

function updatePersonalNote(paper, note) {
  const key = paperKey(paper);
  const personal = getPersonalState(paper);
  state.paperState[key] = { ...personal, note };
  cleanupPersonalState(key);
  savePersonalState();
  renderPersonalSummary();
  renderPersonalFilters();
}

function cleanupPersonalState(key) {
  const personal = state.paperState[key];
  if (!personal) return;
  if (!personal.priority && !personal.saved && !personal.read && !(personal.note || "").trim()) {
    delete state.paperState[key];
  }
}

function getPersonalState(paper) {
  const saved = state.paperState[paperKey(paper)] || {};
  return {
    priority: Boolean(saved.priority),
    saved: Boolean(saved.saved),
    read: Boolean(saved.read),
    note: typeof saved.note === "string" ? saved.note : "",
  };
}

function paperKey(paper) {
  if (paper.doi) return `doi:${paper.doi.toLowerCase()}`;
  if (paper.id) return `id:${paper.id}`;
  return `title:${paper.title}`;
}

function matchesPersonalFilter(paper) {
  const personal = getPersonalState(paper);
  if (state.personalFilter === "priority") return personal.priority;
  if (state.personalFilter === "saved") return personal.saved;
  if (state.personalFilter === "read") return personal.read;
  if (state.personalFilter === "unread") return !personal.read;
  if (state.personalFilter === "notes") return Boolean(personal.note.trim());
  return true;
}

function personalRank(paper) {
  const personal = getPersonalState(paper);
  return (
    (personal.priority ? 100 : 0) +
    (personal.saved ? 40 : 0) +
    (!personal.read ? 10 : 0) +
    (personal.note.trim() ? 5 : 0)
  );
}

function buildPersonalCounts(papers) {
  const counts = { priority: 0, saved: 0, read: 0, unread: 0, notes: 0 };
  papers.forEach((paper) => {
    const personal = getPersonalState(paper);
    if (personal.priority) counts.priority += 1;
    if (personal.saved) counts.saved += 1;
    if (personal.read) counts.read += 1;
    if (!personal.read) counts.unread += 1;
    if (personal.note.trim()) counts.notes += 1;
  });
  return counts;
}

function renderPersonalSummary() {
  if (!state.payload) return;
  const counts = buildPersonalCounts(activePayload().papers || []);
  const container = document.getElementById("personal-summary");
  container.innerHTML = "";
  [
    ["重点", counts.priority],
    ["收藏", counts.saved],
    ["已读", counts.read],
    ["备注", counts.notes],
  ].forEach(([label, value]) => {
    const item = document.createElement("span");
    item.innerHTML = `<strong>${value}</strong>${label}`;
    container.appendChild(item);
  });
}

function renderPersonalFilters() {
  if (!state.payload) return;
  const personalCounts = buildPersonalCounts(activePayload().papers || []);
  buildChips(
    document.getElementById("personal-filters"),
    [
      { value: "all", label: "全部" },
      { value: "priority", label: `重点 (${personalCounts.priority})` },
      { value: "saved", label: `收藏 (${personalCounts.saved})` },
      { value: "unread", label: `未读 (${personalCounts.unread})` },
      { value: "read", label: `已读 (${personalCounts.read})` },
      { value: "notes", label: `有备注 (${personalCounts.notes})` },
    ],
    state.personalFilter,
    (value) => {
      state.personalFilter = value;
      saveFilterState();
      renderSections();
    },
  );
}

function renderSourceNotes(notes) {
  const container = document.getElementById("source-notes");
  container.innerHTML = "";
  Object.entries(notes).forEach(([source, note]) => {
    const paragraph = document.createElement("p");
    const label = document.createElement("strong");
    label.textContent = `${sourceLabel(source)}：`;
    paragraph.append(label, document.createTextNode(note));
    container.appendChild(paragraph);
  });

  const reminder = document.createElement("p");
  reminder.className = "note-muted";
  reminder.textContent = "下载权限仍取决于原始数据库、期刊网站和学校账号；本站主要承担发现、筛选、引用导出和导读功能。";
  container.appendChild(reminder);
}

function renderRequirementPanel(meta) {
  const targets = meta.ieee_targets || [];
  document.getElementById("tracked-target-count").textContent = `${targets.length} 个入口`;

  const targetGrid = document.getElementById("ieee-targets");
  targetGrid.innerHTML = "";
  targets.forEach((target) => {
    const card = document.createElement("article");
    card.className = "target-card";

    const title = document.createElement("h3");
    title.textContent = target.short_title || target.journal;

    const journal = document.createElement("p");
    journal.className = "target-journal";
    journal.textContent = target.journal;

    const count = document.createElement("span");
    count.className = "target-count";
    count.textContent = `本周 ${target.selected_count || 0} / 留存 ${target.archive_count || target.selected_count || 0}`;

    const collection = document.createElement("p");
    collection.className = "target-collection";
    collection.textContent = `Zotero 文件夹：${target.zotero_collection || target.journal}`;

    const links = document.createElement("div");
    links.className = "target-links";
    links.append(
      buildTargetLink(target.xplore_url, "IEEE Xplore"),
      buildTargetLink(target.bibtex_path, "本周 BibTeX"),
      buildTargetLink(target.ris_path, "本周 RIS"),
      buildTargetLink(target.archive_bibtex_path, "历史 BibTeX"),
      buildTargetLink(target.archive_ris_path, "历史 RIS"),
    );

    card.append(title, journal, count, collection, links);
    targetGrid.appendChild(card);
  });

  const topics = document.getElementById("required-topics");
  topics.innerHTML = "";
  (meta.required_topics || []).forEach((topic) => {
    const chip = document.createElement("span");
    chip.textContent = topic;
    topics.appendChild(chip);
  });

  const workflow = document.getElementById("workflow-notes");
  workflow.innerHTML = "";
  (meta.workflow_notes || []).forEach((note) => {
    const item = document.createElement("li");
    item.textContent = note;
    workflow.appendChild(item);
  });
}

function buildTargetLink(href, label) {
  const link = document.createElement("a");
  link.href = href || "#";
  link.textContent = label;
  link.target = "_blank";
  link.rel = "noreferrer";
  if (!href) link.setAttribute("aria-disabled", "true");
  return link;
}

function openPaperDialog(paper) {
  state.activeDialogPaper = paper;
  const dialog = document.getElementById("paper-dialog");
  document.getElementById("dialog-source").textContent =
    `${sourceLabel(paper.source)} · ${paper.journal} · ${paper.published_date_local}`;
  document.getElementById("dialog-title").textContent = paper.title;
  document.getElementById("dialog-authors").textContent =
    `${(paper.authors || []).join(", ") || "Unknown authors"} · 推荐分 ${Number(paper.final_score).toFixed(1)} / 10`;
  renderDialogMeta(paper);
  document.getElementById("dialog-summary").textContent = paper.ai_summary || "暂无自动导读。";
  document.getElementById("dialog-value").textContent = paper.application_value || "暂无应用价值说明。";
  document.getElementById("dialog-limitations").textContent = paper.limitations || "暂无局限说明。";
  document.getElementById("dialog-abstract").textContent = paper.abstract || "公开元数据暂未提供摘要。";
  document.getElementById("dialog-note").value = getPersonalState(paper).note || "";
  renderDialogLinks(paper);

  if (typeof dialog.showModal === "function") {
    dialog.showModal();
  } else {
    dialog.setAttribute("open", "");
  }
}

function closePaperDialog() {
  const dialog = document.getElementById("paper-dialog");
  if (dialog.open && typeof dialog.close === "function") {
    dialog.close();
  } else {
    dialog.removeAttribute("open");
  }
  state.activeDialogPaper = null;
  renderSections();
}

function renderDialogMeta(paper) {
  const container = document.getElementById("dialog-meta");
  container.innerHTML = "";
  [
    ["相关性", paper.relevance_label],
    ["命中类别", (paper.matched_keyword_groups || []).join("、")],
    ["命中关键词", (paper.matched_keywords || []).slice(0, 8).join("、")],
    ["DOI", paper.doi || "暂无"],
  ].forEach(([label, value]) => {
    const item = document.createElement("span");
    item.innerHTML = `<strong>${label}</strong>${value || "暂无"}`;
    container.appendChild(item);
  });
}

function renderDialogLinks(paper) {
  const container = document.getElementById("dialog-links");
  container.innerHTML = "";
  [
    [paper.url, "原文"],
    [paper.pdf_url, "PDF"],
    [paper.doi_url || (paper.doi ? `https://doi.org/${paper.doi}` : ""), "DOI"],
    [paper.xplore_url, "期刊入口"],
  ].forEach(([href, label]) => {
    if (!href) return;
    container.appendChild(buildTargetLink(href, label));
  });
}

function buildReadingListMarkdown() {
  const papers = sortPapers(
    (activePayload()?.papers || []).filter((paper) => {
      const personal = getPersonalState(paper);
      return personal.priority || personal.saved || personal.read || personal.note.trim();
    }),
  );
  const sourcePapers = papers.length ? papers : sortPapers(filterPapers(activePayload()?.papers || []));
  const lines = [
    "# 电力系统论文阅读清单",
    "",
    `生成时间：${new Date().toLocaleString("zh-CN")}`,
    `数据视图：${state.viewMode === "archive" ? "全部历史" : "本周"}`,
    `论文数量：${sourcePapers.length}`,
    "",
  ];

  sourcePapers.forEach((paper, index) => {
    const personal = getPersonalState(paper);
    const tags = [
      personal.priority ? "重点" : "",
      personal.saved ? "收藏" : "",
      personal.read ? "已读" : "未读",
    ].filter(Boolean);
    lines.push(`## ${index + 1}. ${paper.title}`);
    lines.push("");
    lines.push(`- 期刊/来源：${paper.journal} (${sourceLabel(paper.source)})`);
    lines.push(`- 发布时间：${paper.published_date_local}`);
    lines.push(`- 推荐分：${Number(paper.final_score).toFixed(1)} / 10；状态：${tags.join("、")}`);
    lines.push(`- 作者：${(paper.authors || []).join(", ") || "Unknown authors"}`);
    if (paper.doi) lines.push(`- DOI：${paper.doi}`);
    lines.push(`- 链接：${paper.url}`);
    if (paper.matched_keywords?.length) lines.push(`- 命中关键词：${paper.matched_keywords.slice(0, 8).join("、")}`);
    lines.push(`- 导读：${(paper.ai_summary || "").replace(/\s+/g, " ").trim() || "暂无"}`);
    if (personal.note.trim()) lines.push(`- 我的备注：${personal.note.trim().replace(/\s+/g, " ")}`);
    lines.push("");
  });

  return lines.join("\n");
}

function downloadText(filename, content) {
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function enableCopyButton(button, text, status, fallback, message) {
  if (!text) return;
  button.hidden = false;
  button.addEventListener("click", async () => {
    try {
      await copyText(text);
      fallback.hidden = true;
      showCopyStatus(status, message);
    } catch (error) {
      showManualCopy(fallback, text);
      showCopyStatus(status, "已展开引用文本，可手动复制");
    }
  });
}

async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch (error) {
      // Some browsers expose Clipboard API but deny writes without a permission prompt.
    }
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.left = "0";
  textarea.style.top = "0";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  textarea.setSelectionRange(0, textarea.value.length);
  const ok = document.execCommand("copy");
  textarea.remove();
  if (!ok) throw new Error("copy command failed");
}

function showCopyStatus(status, message) {
  status.textContent = message;
  clearTimeout(status.dataset.timerId);
  const timerId = window.setTimeout(() => {
    status.textContent = "";
  }, 1800);
  status.dataset.timerId = String(timerId);
}

function showManualCopy(fallback, text) {
  fallback.hidden = false;
  fallback.value = text;
  fallback.focus();
  fallback.select();
  fallback.setSelectionRange(0, fallback.value.length);
}

function sourceLabel(source) {
  return SOURCE_LABELS[source] || source;
}

function shortJournalName(journal) {
  return journal
    .replace("IEEE Transactions on Power Systems", "IEEE TPWRS")
    .replace("IEEE Transactions on Smart Grid", "IEEE TSG")
    .replace("IEEE Transactions on Sustainable Energy", "IEEE TSTE");
}

function loadSavedState() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
    ["viewMode", "source", "journal", "keywordGroup", "label", "personalFilter", "sort", "query"].forEach((key) => {
      if (typeof saved[key] === "string") state[key] = saved[key];
    });
  } catch (error) {
    localStorage.removeItem(STORAGE_KEY);
  }

  try {
    const savedPersonalState = JSON.parse(localStorage.getItem(PERSONAL_STORAGE_KEY) || "{}");
    state.paperState = savedPersonalState && typeof savedPersonalState === "object" ? savedPersonalState : {};
  } catch (error) {
    localStorage.removeItem(PERSONAL_STORAGE_KEY);
    state.paperState = {};
  }
}

function normalizeSavedState() {
  if (!state.payload) return;
  const { meta, papers } = activePayload();
  const sources = Object.keys(meta.source_counts || {});
  const journals = Object.keys(meta.journal_counts || {});
  const groups = Object.keys(buildKeywordGroupCounts(papers));
  const labels = Object.keys(buildCounts(papers, (paper) => paper.relevance_label || "Background Read"));
  const personalFilters = ["all", "priority", "saved", "unread", "read", "notes"];
  const sorts = ["score", "latest", "journal", "personal"];
  const viewModes = ["latest", "archive"];

  if (!viewModes.includes(state.viewMode)) state.viewMode = "latest";
  if (state.source !== "all" && !sources.includes(state.source)) state.source = "all";
  if (state.journal !== "all" && !journals.includes(state.journal)) state.journal = "all";
  if (state.keywordGroup !== "all" && !groups.includes(state.keywordGroup)) state.keywordGroup = "all";
  if (state.label !== "all" && !labels.includes(state.label)) state.label = "all";
  if (!personalFilters.includes(state.personalFilter)) state.personalFilter = "all";
  if (!sorts.includes(state.sort)) state.sort = "score";
  document.getElementById("sort-select").value = state.sort;
  document.getElementById("search-input").value = state.query;
  saveFilterState();
}

function saveFilterState() {
  const { viewMode, source, journal, keywordGroup, label, personalFilter, sort, query } = state;
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({ viewMode, source, journal, keywordGroup, label, personalFilter, sort, query }),
  );
}

function savePersonalState() {
  localStorage.setItem(PERSONAL_STORAGE_KEY, JSON.stringify(state.paperState));
}

function renderError(error) {
  document.getElementById("visible-count").textContent = "数据加载失败";
  const banner = document.getElementById("error-banner");
  banner.hidden = false;
  banner.textContent = `无法读取 latest.json：${error.message}`;
}

function formatDateTime(value, timezone) {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: timezone,
  }).format(new Date(value));
}

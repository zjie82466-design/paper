const STORAGE_KEY = "power-paper-digest-filters-v2";
const SOURCE_LABELS = {
  arxiv: "arXiv",
  ieee: "IEEE",
  elsevier: "Elsevier",
  nature: "Nature",
};

const state = {
  payload: null,
  source: "all",
  journal: "all",
  keywordGroup: "all",
  label: "all",
  sort: "score",
  query: "",
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
    state.sort = "score";
    state.query = "";
    sortSelect.value = state.sort;
    searchInput.value = "";
    saveFilterState();
    renderFrame();
    renderSections();
  });

  try {
    const response = await fetch("./latest.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`latest.json ${response.status}`);
    state.payload = await response.json();
    normalizeSavedState();
    renderFrame();
    renderSections();
  } catch (error) {
    renderError(error);
  }
});

function renderFrame() {
  const { meta, papers } = state.payload;
  document.getElementById("site-title").textContent = meta.title;
  document.getElementById("site-subtitle").textContent = meta.subtitle;
  document.getElementById("date-window").textContent = `${meta.window_start} 至 ${meta.target_date}`;
  document.getElementById("updated-at").textContent = `生成于 ${formatDateTime(meta.generated_at, meta.timezone)}`;
  document.getElementById("paper-count").textContent = `${meta.paper_count} 篇`;

  const stats = document.getElementById("stats");
  stats.innerHTML = "";
  [
    ["入选论文", meta.paper_count],
    ["来源类型", Object.keys(meta.source_counts || {}).length],
    ["覆盖期刊", Object.keys(meta.journal_counts || {}).length],
    ["关键词类", Object.keys(meta.keyword_group_counts || {}).length],
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

  renderSourceNotes(meta.source_notes || {});

  const errorBanner = document.getElementById("error-banner");
  if (meta.source_errors && meta.source_errors.length > 0) {
    errorBanner.hidden = false;
    errorBanner.textContent = `部分来源抓取异常：${meta.source_errors.join(" | ")}`;
  } else {
    errorBanner.hidden = true;
    errorBanner.textContent = "";
  }
}

function renderSections() {
  if (!state.payload) return;

  const container = document.getElementById("sections");
  container.innerHTML = "";
  const sectionTemplate = document.getElementById("section-template");
  let visibleTotal = 0;

  Object.entries(state.payload.sections).forEach(([, section]) => {
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
  fragment.querySelector(".source").textContent = sourceLabel(paper.source);
  fragment.querySelector(".journal").textContent = paper.journal;
  fragment.querySelector(".age").textContent = paper.published_date_local;
  fragment.querySelector(".title").textContent = paper.title;
  fragment.querySelector(".authors").textContent =
    `${(paper.authors || []).slice(0, 6).join(", ") || "Unknown authors"} · ${paper.published_time_local}`;
  fragment.querySelector(".score").textContent = `推荐分 ${Number(paper.final_score).toFixed(1)} / 10`;
  fragment.querySelector(".label").textContent = paper.relevance_label;
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

  const status = fragment.querySelector(".copy-status");
  const fallback = fragment.querySelector(".citation-fallback");
  enableCopyButton(fragment.querySelector(".copy-doi"), paper.doi, status, fallback, "DOI 已复制");
  enableCopyButton(fragment.querySelector(".copy-bibtex"), paper.bibtex_entry, status, fallback, "BibTeX 已复制");
  enableCopyButton(fragment.querySelector(".copy-ris"), paper.ris_entry, status, fallback, "RIS 已复制");

  return fragment;
}

function filterPapers(papers) {
  return papers.filter((paper) => {
    const sourceMatch = state.source === "all" || paper.source === state.source;
    const journalMatch = state.journal === "all" || paper.journal === state.journal;
    const groupMatch =
      state.keywordGroup === "all" || (paper.matched_keyword_groups || []).includes(state.keywordGroup);
    const labelMatch = state.label === "all" || paper.relevance_label === state.label;
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
    ]
      .join(" ")
      .toLowerCase();
    const queryMatch = !state.query || haystack.includes(state.query);
    return sourceMatch && journalMatch && groupMatch && labelMatch && queryMatch;
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
    ["source", "journal", "keywordGroup", "label", "sort", "query"].forEach((key) => {
      if (typeof saved[key] === "string") state[key] = saved[key];
    });
  } catch (error) {
    localStorage.removeItem(STORAGE_KEY);
  }
}

function normalizeSavedState() {
  const { meta, papers } = state.payload;
  const sources = Object.keys(meta.source_counts || {});
  const journals = Object.keys(meta.journal_counts || {});
  const groups = Object.keys(buildKeywordGroupCounts(papers));
  const labels = Object.keys(buildCounts(papers, (paper) => paper.relevance_label || "Background Read"));
  const sorts = ["score", "latest", "journal"];

  if (state.source !== "all" && !sources.includes(state.source)) state.source = "all";
  if (state.journal !== "all" && !journals.includes(state.journal)) state.journal = "all";
  if (state.keywordGroup !== "all" && !groups.includes(state.keywordGroup)) state.keywordGroup = "all";
  if (state.label !== "all" && !labels.includes(state.label)) state.label = "all";
  if (!sorts.includes(state.sort)) state.sort = "score";
  document.getElementById("sort-select").value = state.sort;
  document.getElementById("search-input").value = state.query;
  saveFilterState();
}

function saveFilterState() {
  const { source, journal, keywordGroup, label, sort, query } = state;
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ source, journal, keywordGroup, label, sort, query }));
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

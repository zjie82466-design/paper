const state = {
  payload: null,
  source: "all",
  keywordGroup: "all",
  sort: "score",
  query: "",
};

document.addEventListener("DOMContentLoaded", async () => {
  document.getElementById("sort-select").addEventListener("change", (event) => {
    state.sort = event.target.value;
    renderSections();
  });
  document.getElementById("search-input").addEventListener("input", (event) => {
    state.query = event.target.value.trim().toLowerCase();
    renderSections();
  });

  try {
    const response = await fetch("./latest.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`latest.json ${response.status}`);
    state.payload = await response.json();
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
      Object.keys(meta.source_counts || {}).map((source) => ({ value: source, label: source })),
    ),
    state.source,
    (value) => {
      state.source = value;
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
      renderSections();
    },
  );

  const errorBanner = document.getElementById("error-banner");
  if (meta.source_errors && meta.source_errors.length > 0) {
    errorBanner.hidden = false;
    errorBanner.textContent = `部分来源抓取异常：${meta.source_errors.join(" | ")}`;
  }
}

function renderSections() {
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
  fragment.querySelector(".source").textContent = paper.source;
  fragment.querySelector(".journal").textContent = paper.journal;
  fragment.querySelector(".age").textContent = paper.published_date_local;
  fragment.querySelector(".title").textContent = paper.title;
  fragment.querySelector(".authors").textContent = `${(paper.authors || []).slice(0, 6).join(", ") || "Unknown authors"} · ${paper.published_time_local}`;
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
    doi.href = `https://doi.org/${paper.doi}`;
    doi.hidden = false;
  }
  return fragment;
}

function filterPapers(papers) {
  return papers.filter((paper) => {
    const sourceMatch = state.source === "all" || paper.source === state.source;
    const groupMatch =
      state.keywordGroup === "all" || (paper.matched_keyword_groups || []).includes(state.keywordGroup);
    const haystack = [
      paper.title,
      paper.journal,
      (paper.authors || []).join(" "),
      (paper.matched_keywords || []).join(" "),
      paper.ai_summary || "",
    ]
      .join(" ")
      .toLowerCase();
    const queryMatch = !state.query || haystack.includes(state.query);
    return sourceMatch && groupMatch && queryMatch;
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

function buildChips(container, options, active, onClick) {
  container.innerHTML = "";
  options.forEach((option) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `chip${option.value === active ? " is-active" : ""}`;
    button.textContent = option.label;
    button.addEventListener("click", () => {
      onClick(option.value);
      buildChips(container, options, option.value, onClick);
    });
    container.appendChild(button);
  });
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


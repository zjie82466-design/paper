from __future__ import annotations

import html
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus
from xml.etree import ElementTree
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

import requests
from dateutil import parser as date_parser


REPO_URL = "https://github.com/zjie82466-design/paper"
SITE_BASE_URL = "https://zjie82466-design.github.io/paper/"
USER_AGENT = f"PowerPaperDigest/0.1 (+{REPO_URL})"


@dataclass(frozen=True)
class JournalSource:
    key: str
    section: str
    title: str
    issns: tuple[str, ...]
    weight: float
    xplore_url: str = ""
    export_slug: str = ""
    zotero_collection: str = ""


@dataclass
class Paper:
    id: str
    source: str
    section: str
    journal: str
    title: str
    authors: list[str]
    abstract: str
    url: str
    pdf_url: str | None
    doi: str | None
    published_at: datetime
    categories: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    matched_keywords: list[str] = field(default_factory=list)
    matched_keyword_groups: list[str] = field(default_factory=list)
    rule_score: float = 0.0
    llm_score: float = 0.0
    final_score: float = 0.0
    relevance_label: str = "Background Read"
    score_reason: str = ""
    ai_summary: str = ""
    application_value: str = ""
    limitations: str = ""

    def to_dict(self, timezone_name: str) -> dict[str, Any]:
        local_dt = self.published_at.astimezone(ZoneInfo(timezone_name))
        payload = asdict(self)
        payload["published_at"] = self.published_at.isoformat()
        payload["published_at_local"] = local_dt.isoformat()
        payload["published_date_local"] = local_dt.date().isoformat()
        payload["published_time_local"] = local_dt.strftime("%H:%M")
        payload["doi_url"] = f"https://doi.org/{self.doi}" if self.doi else None
        payload["citation_key"] = citation_key(self)
        payload["bibtex_entry"] = build_bibtex_entry(self)
        payload["ris_entry"] = build_ris_entry(self)
        payload["xplore_url"] = self.metadata.get("xplore_url")
        payload["zotero_collection"] = self.metadata.get("zotero_collection")
        return payload


@dataclass(frozen=True)
class Settings:
    timezone_name: str
    lookback_days: int
    max_results_per_source: int
    max_results_per_section: int
    summary_count: int
    crossref_mailto: str | None
    deepseek_api_key: str | None
    deepseek_base_url: str
    deepseek_model: str


JOURNAL_SOURCES = (
    JournalSource(
        key="ieee",
        section="ieee",
        title="IEEE Transactions on Power Systems",
        issns=("0885-8950", "1558-0679"),
        weight=1.35,
        xplore_url="https://ieeexplore.ieee.org/xpl/tocresult.jsp?isnumber=4374138",
        export_slug="ieee_tpwrs",
        zotero_collection="IEEE Transactions on Power Systems",
    ),
    JournalSource(
        key="ieee",
        section="ieee",
        title="IEEE Transactions on Smart Grid",
        issns=("1949-3053", "1949-3061"),
        weight=1.35,
        xplore_url="https://ieeexplore.ieee.org/xpl/tocresult.jsp?isnumber=5446437",
        export_slug="ieee_tsg",
        zotero_collection="IEEE Transactions on Smart Grid",
    ),
    JournalSource(
        key="ieee",
        section="ieee",
        title="IEEE Transactions on Sustainable Energy",
        issns=("1949-3029", "1949-3037"),
        weight=1.25,
        xplore_url="https://ieeexplore.ieee.org/xpl/tocresult.jsp?isnumber=5433168",
        export_slug="ieee_tste",
        zotero_collection="IEEE Transactions on Sustainable Energy",
    ),
    JournalSource(
        key="elsevier",
        section="energy",
        title="Applied Energy",
        issns=("0306-2619", "1872-9118"),
        weight=1.18,
    ),
    JournalSource(
        key="elsevier",
        section="energy",
        title="Joule",
        issns=("2542-4351",),
        weight=1.15,
    ),
    JournalSource(
        key="nature",
        section="energy",
        title="Nature Energy",
        issns=("2058-7546",),
        weight=1.16,
    ),
)


REQUIRED_TOPICS = (
    "power system operation",
    "power system planning",
    "unit commitment",
    "dispatch",
    "scheduling",
    "ai for power system optimization",
    "resilience enhancement",
    "resilience evaluation",
    "robust optimization",
    "stochastic optimization",
    "transmission and distribution coordination",
    "generation and transmission coordination",
)


WORKFLOW_NOTES = (
    "每周一自动检查上一周新增记录，优先关注 IEEE 三刊 Early Access/Recent Issue 入口。",
    "每篇入选论文保留 DOI、BibTeX、RIS；IEEE 三刊额外生成分期刊 Zotero 导入文件。",
    "若不能直接下载全文，先导入引用到 Zotero，再用学校账号或 VPN 在原文页面尝试下载。",
    "摘要用于初筛，正式阅读时仍需打开原文确认模型、数据、实验效果和局限性。",
)


SOURCE_NOTES = {
    "arxiv": "arXiv 来源优先使用官方 API；接口限流或超时时，会退回 recent page 做近似抓取。它反映预印本动态，不代表期刊正式发表。",
    "ieee": "IEEE 三刊配置了文档指定的 IEEE Xplore 入口；当前自动检索仍以 Crossref DOI 元数据为主，不依赖 IEEE Xplore API 或机构订阅，Early Access 覆盖取决于元数据登记情况。",
    "elsevier": "Applied Energy 和 Joule 当前通过 Crossref 元数据检索；若摘要缺失，网页会给出保守导读并提示打开原文核对。",
    "nature": "Nature Energy 当前通过 Crossref 元数据检索；高影响期刊论文数量少，筛选更依赖题名、关键词和 DOI 元数据。",
}


KEYWORD_GROUPS: dict[str, dict[str, float]] = {
    "电力系统运行与规划": {
        "power system operation": 2.4,
        "power system planning": 2.4,
        "unit commitment": 2.3,
        "security-constrained unit commitment": 2.5,
        "economic dispatch": 2.2,
        "dispatch": 1.4,
        "scheduling": 1.5,
        "optimal power flow": 2.2,
        "opf": 1.4,
        "market clearing": 1.7,
        "power system": 1.4,
        "power systems": 1.4,
    },
    "AI+电力优化": {
        "ai for power system optimization": 2.5,
        "learning to optimize": 2.2,
        "decision-focused learning": 2.2,
        "predict-and-optimize": 2.0,
        "reinforcement learning": 1.7,
        "graph neural network": 1.5,
        "surrogate model": 1.4,
        "machine learning": 1.2,
        "deep learning": 1.1,
    },
    "鲁棒随机优化": {
        "robust optimization": 2.2,
        "stochastic optimization": 2.2,
        "chance-constrained": 1.8,
        "distributionally robust": 2.1,
        "uncertainty": 1.2,
    },
    "韧性与恢复": {
        "resilience enhancement": 2.4,
        "resilience evaluation": 2.4,
        "grid resilience": 2.2,
        "resilience": 1.7,
        "service restoration": 2.0,
        "black start": 1.8,
        "outage management": 1.8,
        "extreme weather": 1.5,
    },
    "源网荷储协同": {
        "transmission and distribution coordination": 2.4,
        "generation and transmission coordination": 2.4,
        "transmission distribution coordination": 2.1,
        "coordinated planning": 1.7,
        "distributed energy resources": 1.5,
        "virtual power plant": 1.6,
        "demand response": 1.6,
        "energy storage": 1.5,
        "microgrid": 1.4,
        "microgrids": 1.4,
    },
    "构网与暂态稳定": {
        "grid-forming": 2.4,
        "grid forming": 2.4,
        "virtual synchronous generator": 2.2,
        "vsg": 1.8,
        "transient stability": 2.1,
        "large-signal stability": 2.0,
        "fault ride-through": 2.0,
        "current limiting": 1.8,
        "asymmetric fault": 1.8,
        "unbalanced fault": 1.8,
        "negative-sequence": 1.7,
    },
}

KEYWORD_TO_GROUP = {
    keyword: group for group, keywords in KEYWORD_GROUPS.items() for keyword in keywords
}
KEYWORD_WEIGHTS = {
    keyword: weight for keywords in KEYWORD_GROUPS.values() for keyword, weight in keywords.items()
}
POWER_CONTEXT_TERMS = (
    "power system",
    "power systems",
    "grid",
    "electricity",
    "smart grid",
    "microgrid",
    "renewable energy",
    "distributed energy",
    "transmission",
    "distribution",
    "converter",
    "inverter",
)
MATERIAL_RISK_TERMS = (
    "catalyst",
    "electrocatalyst",
    "photocatalyst",
    "nanoparticle",
    "membrane",
    "anode",
    "cathode",
    "electrode",
    "synthesis",
    "perovskite",
)


SECTION_META = {
    "ieee": {
        "title": "IEEE 三刊重点榜",
        "description": "聚焦 TPWRS、TSG、TSTE 中与运行、规划、调度、韧性和优化相关的新论文。",
    },
    "arxiv": {
        "title": "arXiv 预印本榜",
        "description": "跟踪 eess.SY、math.OC 等分类中适合提前关注的方法论文。",
    },
    "energy": {
        "title": "能源期刊发现榜",
        "description": "补充 Applied Energy、Joule、Nature Energy 等期刊中的电力能源系统论文。",
    },
}


def main() -> int:
    settings = load_settings()
    local_tz = ZoneInfo(settings.timezone_name)
    generated_at = datetime.now(local_tz)
    target_date = generated_at.date()
    earliest_date = target_date - timedelta(days=max(settings.lookback_days - 1, 0))

    print(f"Building paper digest for {earliest_date} to {target_date} ({settings.timezone_name})")

    records: list[Paper] = []
    source_errors: list[str] = []

    try:
        arxiv_records = collect_arxiv(settings, target_date, earliest_date)
        print(f"Collected {len(arxiv_records)} arXiv records.")
        records.extend(arxiv_records)
    except Exception as exc:  # noqa: BLE001
        message = f"arXiv collection failed: {exc}"
        print(message)
        source_errors.append(message)

    for source in JOURNAL_SOURCES:
        try:
            journal_records = collect_crossref(source, settings, target_date, earliest_date)
            print(f"Collected {len(journal_records)} records from {source.title}.")
            records.extend(journal_records)
            time.sleep(0.4)
        except Exception as exc:  # noqa: BLE001
            message = f"{source.title} collection failed: {exc}"
            print(message)
            source_errors.append(message)

    score_records(records, settings)
    records = dedupe_records(records)
    selected = select_records(records, settings)
    enrich_records(selected, settings)
    selected = [paper for paper in selected if passes_display_gate(paper)]
    selected.sort(key=lambda paper: (paper.final_score, paper.published_at.timestamp()), reverse=True)

    write_outputs(
        records=selected,
        settings=settings,
        target_date=target_date,
        earliest_date=earliest_date,
        generated_at=generated_at,
        source_errors=source_errors,
    )
    print(f"Wrote {len(selected)} selected papers to site/latest.json")
    return 0


def load_settings() -> Settings:
    return Settings(
        timezone_name=os.environ.get("TARGET_TIMEZONE", "Asia/Shanghai"),
        lookback_days=int(os.environ.get("LOOKBACK_DAYS", "7")),
        max_results_per_source=int(os.environ.get("MAX_RESULTS_PER_SOURCE", "35")),
        max_results_per_section=int(os.environ.get("MAX_RESULTS_PER_SECTION", "12")),
        summary_count=int(os.environ.get("SUMMARY_COUNT", "24")),
        crossref_mailto=os.environ.get("CROSSREF_MAILTO") or None,
        deepseek_api_key=os.environ.get("DEEPSEEK_API_KEY") or None,
        deepseek_base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
    )


def collect_arxiv(settings: Settings, target_date: date, earliest_date: date) -> list[Paper]:
    query = "cat:eess.SY OR cat:math.OC"
    params = {
        "search_query": query,
        "start": "0",
        "max_results": str(settings.max_results_per_source * 2),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    try:
        response = get_with_retries(
            requests,
            "https://export.arxiv.org/api/query",
            params=params,
            headers={"User-Agent": build_user_agent(settings)},
            timeout=45,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"arXiv API failed, using recent-page fallback: {exc}")
        return collect_arxiv_recent_pages(settings, target_date, earliest_date)

    root = ElementTree.fromstring(response.text)
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    local_tz = ZoneInfo(settings.timezone_name)
    papers: list[Paper] = []

    for entry in root.findall("atom:entry", ns):
        published_text = get_xml_text(entry, "atom:published", ns)
        published_at = date_parser.isoparse(published_text)
        published_local = published_at.astimezone(local_tz).date()
        if published_local < earliest_date:
            continue
        if published_local > target_date:
            continue

        entry_id = get_xml_text(entry, "atom:id", ns)
        title = clean_text(get_xml_text(entry, "atom:title", ns))
        abstract = clean_text(get_xml_text(entry, "atom:summary", ns))
        authors = [
            clean_text(author.findtext("atom:name", default="", namespaces=ns))
            for author in entry.findall("atom:author", ns)
        ]
        categories = [category.get("term", "") for category in entry.findall("atom:category", ns)]
        pdf_url = None
        for link in entry.findall("atom:link", ns):
            if link.get("title") == "pdf":
                pdf_url = link.get("href")

        papers.append(
            Paper(
                id=entry_id,
                source="arxiv",
                section="arxiv",
                journal="arXiv",
                title=title,
                authors=[author for author in authors if author],
                abstract=abstract,
                url=entry_id,
                pdf_url=pdf_url,
                doi=None,
                published_at=published_at,
                categories=categories,
                metadata={"query": query},
            )
        )

    return papers


def collect_arxiv_recent_pages(settings: Settings, target_date: date, earliest_date: date) -> list[Paper]:
    papers: list[Paper] = []
    seen_ids: set[str] = set()
    for category in ("eess.SY", "math.OC"):
        url = f"https://arxiv.org/list/{category}/recent?skip=0&show=2000"
        response = get_with_retries(
            requests,
            url,
            headers={"User-Agent": build_user_agent(settings)},
            timeout=45,
        )
        response.raise_for_status()
        records = parse_arxiv_recent_html(
            response.text,
            category=category,
            target_date=target_date,
            earliest_date=earliest_date,
        )
        for record in records:
            if record.id in seen_ids:
                continue
            seen_ids.add(record.id)
            papers.append(record)
        time.sleep(1.2)
    return papers[: settings.max_results_per_source * 2]


def parse_arxiv_recent_html(
    html_text: str,
    category: str,
    target_date: date,
    earliest_date: date,
) -> list[Paper]:
    records: list[Paper] = []
    section_pattern = re.compile(
        r"<h3>(?P<header>[^<]+)</h3>(?P<body>.*?)(?=<h3>|</dl>)",
        re.IGNORECASE | re.DOTALL,
    )
    item_pattern = re.compile(
        r"<dt>.*?title=\"Abstract\"\s+id=\"(?P<id>\d+\.\d+)\".*?</dt>\s*<dd>(?P<body>.*?)</dd>",
        re.IGNORECASE | re.DOTALL,
    )

    for section_match in section_pattern.finditer(html_text):
        section_date = parse_arxiv_recent_date(section_match.group("header"))
        if section_date is None:
            continue
        if section_date < earliest_date:
            continue
        if section_date > target_date:
            continue

        for item_match in item_pattern.finditer(section_match.group("body")):
            arxiv_id = item_match.group("id")
            body = item_match.group("body")
            title = extract_arxiv_meta_field(body, "list-title")
            if not title:
                continue
            authors_html = extract_arxiv_div(body, "list-authors")
            authors = [strip_tags(match) for match in re.findall(r"<a\b[^>]*>(.*?)</a>", authors_html, re.DOTALL)]
            subjects = extract_arxiv_meta_field(body, "list-subjects")
            categories = [part.strip() for part in strip_tags(subjects).split(";") if part.strip()]
            published_at = datetime(section_date.year, section_date.month, section_date.day, tzinfo=timezone.utc)
            records.append(
                Paper(
                    id=f"https://arxiv.org/abs/{arxiv_id}",
                    source="arxiv",
                    section="arxiv",
                    journal="arXiv",
                    title=title,
                    authors=[author for author in authors if author],
                    abstract="",
                    url=f"https://arxiv.org/abs/{arxiv_id}",
                    pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
                    doi=None,
                    published_at=published_at,
                    categories=categories or [category],
                    metadata={"primary_category": category, "fallback_source": "arxiv_recent_page"},
                )
            )
    return records


def parse_arxiv_recent_date(header_text: str) -> date | None:
    match = re.search(r"[A-Za-z]{3},\s+\d{1,2}\s+[A-Za-z]{3}\s+\d{4}", header_text)
    if not match:
        return None
    return datetime.strptime(match.group(0), "%a, %d %b %Y").date()


def extract_arxiv_meta_field(body: str, class_name: str) -> str:
    raw = extract_arxiv_div(body, class_name)
    raw = re.sub(r"<span\b[^>]*class=['\"]descriptor['\"][^>]*>.*?</span>", " ", raw, flags=re.DOTALL)
    return clean_text(strip_tags(raw))


def extract_arxiv_div(body: str, class_name: str) -> str:
    match = re.search(
        rf"<div\b[^>]*class=['\"][^'\"]*{re.escape(class_name)}[^'\"]*['\"][^>]*>(?P<value>.*?)</div>",
        body,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return match.group("value") if match else ""


def strip_tags(value: str) -> str:
    return clean_text(re.sub(r"<[^>]+>", " ", value or ""))


def collect_crossref(
    source: JournalSource,
    settings: Settings,
    target_date: date,
    earliest_date: date,
) -> list[Paper]:
    session = requests.Session()
    session.headers.update({"User-Agent": build_user_agent(settings)})

    papers: list[Paper] = []
    seen: set[str] = set()
    local_tz = ZoneInfo(settings.timezone_name)
    sort_fields = ("created", "deposited") if source.key == "ieee" else ("published-online", "created")

    for issn in source.issns:
        for sort_field in sort_fields:
            params = {
                "filter": f"issn:{issn}",
                "sort": sort_field,
                "order": "desc",
                "rows": str(settings.max_results_per_source),
                "select": ",".join(
                    [
                        "DOI",
                        "URL",
                        "title",
                        "author",
                        "abstract",
                        "container-title",
                        "subject",
                        "link",
                        "type",
                        "publisher",
                        "published-online",
                        "published-print",
                        "published",
                        "created",
                        "deposited",
                        "issued",
                    ]
                ),
            }
            response = get_with_retries(
                session,
                "https://api.crossref.org/works",
                params=params,
                timeout=45,
            )
            response.raise_for_status()
            items = response.json().get("message", {}).get("items", [])
            for item in items:
                paper = crossref_item_to_paper(item, source)
                if paper is None:
                    continue
                if paper.id in seen:
                    continue
                published_local = paper.published_at.astimezone(local_tz).date()
                if published_local < earliest_date or published_local > target_date:
                    continue
                seen.add(paper.id)
                papers.append(paper)
            time.sleep(0.7)

    papers.sort(key=lambda paper: paper.published_at.timestamp(), reverse=True)
    return papers


def get_with_retries(client: Any, url: str, attempts: int = 3, **kwargs: Any) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = client.get(url, **kwargs)
            if response.status_code not in {429, 500, 502, 503, 504}:
                return response
            last_error = requests.HTTPError(f"{response.status_code} response from {url}")
            if attempt == attempts - 1:
                response.raise_for_status()
        except requests.RequestException as exc:
            last_error = exc
            if attempt == attempts - 1:
                raise
        sleep_seconds = 6 + attempt * 10
        print(f"Request throttled or failed; retrying in {sleep_seconds}s: {url}")
        time.sleep(sleep_seconds)
    if last_error:
        raise last_error
    raise RuntimeError(f"Request failed without response: {url}")


def crossref_item_to_paper(item: dict[str, Any], source: JournalSource) -> Paper | None:
    title_values = item.get("title") or []
    title = clean_text(title_values[0]) if title_values else ""
    if not title or is_non_research_title(title):
        return None

    published_at = extract_crossref_date(item, source.key)
    if published_at is None:
        return None

    doi = item.get("DOI")
    url = item.get("URL") or (f"https://doi.org/{doi}" if doi else "")
    identifier = doi or url or title
    container = item.get("container-title") or []
    journal = clean_text(container[0]) if container else source.title
    authors = []
    for author in item.get("author") or []:
        name = " ".join(
            part.strip()
            for part in [author.get("given", ""), author.get("family", "")]
            if part and part.strip()
        )
        if name:
            authors.append(name)

    pdf_url = None
    for link in item.get("link") or []:
        content_type = (link.get("content-type") or "").lower()
        if "pdf" in content_type:
            pdf_url = link.get("URL")
            break

    return Paper(
        id=identifier,
        source=source.key,
        section=source.section,
        journal=journal,
        title=title,
        authors=authors,
        abstract=clean_abstract(item.get("abstract") or ""),
        url=url,
        pdf_url=pdf_url,
        doi=doi,
        published_at=published_at,
        categories=item.get("subject") or [],
        metadata={
            "publisher": item.get("publisher"),
            "journal_weight": source.weight,
            "crossref_type": item.get("type"),
            "configured_journal": source.title,
            "xplore_url": source.xplore_url,
            "zotero_collection": source.zotero_collection or source.title,
        },
    )


def extract_crossref_date(item: dict[str, Any], source_key: str) -> datetime | None:
    if source_key == "ieee":
        fields = ("created", "deposited", "published-online", "published", "issued")
    else:
        fields = ("published-online", "published", "created", "deposited", "issued")

    for field_name in fields:
        parsed = parse_crossref_date(item.get(field_name))
        if parsed is not None:
            return parsed
    return None


def parse_crossref_date(value: dict[str, Any] | None) -> datetime | None:
    if not value:
        return None
    if value.get("date-time"):
        try:
            parsed = date_parser.isoparse(value["date-time"])
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pass
    parts = (value.get("date-parts") or [[]])[0]
    if not parts:
        return None
    year = int(parts[0])
    month = int(parts[1]) if len(parts) > 1 else 1
    day = int(parts[2]) if len(parts) > 2 else 1
    return datetime(year, month, day, tzinfo=timezone.utc)


def score_records(records: list[Paper], settings: Settings) -> None:
    for paper in records:
        matched = match_keywords(paper)
        paper.matched_keywords = matched[:8]
        paper.matched_keyword_groups = keyword_groups(matched)
        paper.rule_score = round(calculate_rule_score(paper, settings), 2)
        paper.llm_score = paper.rule_score
        paper.final_score = paper.rule_score
        paper.relevance_label = label_for_score(paper.final_score)
        paper.score_reason = build_score_reason(paper, settings)


def calculate_rule_score(paper: Paper, settings: Settings) -> float:
    title = paper.title.lower()
    abstract = paper.abstract.lower()
    text = f"{title} {abstract}"

    score = 0.0
    for keyword in paper.matched_keywords:
        weight = KEYWORD_WEIGHTS[keyword]
        score += weight if contains_keyword(title, keyword) else weight * 0.55

    score += min(len(paper.matched_keyword_groups) * 0.28, 1.0)
    score += recency_bonus(paper, settings)
    score += float(paper.metadata.get("journal_weight", 0.55))

    if any(term in text for term in POWER_CONTEXT_TERMS):
        score += 0.8
    if len(paper.abstract) > 500:
        score += 0.35
    elif not paper.abstract and paper.source not in {"ieee", "elsevier"}:
        score -= 0.8
    if len(paper.authors) >= 3:
        score += 0.2

    material_hits = sum(1 for term in MATERIAL_RISK_TERMS if term in text)
    if material_hits >= 2 and not any("电力" in group or "构网" in group for group in paper.matched_keyword_groups):
        score -= 2.2

    return max(0.0, min(score, 10.0))


def match_keywords(paper: Paper) -> list[str]:
    text = f"{paper.title} {paper.abstract}".lower()
    matches = [keyword for keyword in KEYWORD_WEIGHTS if contains_keyword(text, keyword)]
    matches.sort(key=lambda keyword: KEYWORD_WEIGHTS[keyword], reverse=True)
    return matches


def contains_keyword(text: str, keyword: str) -> bool:
    if keyword in {"opf", "vsg"}:
        return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text.lower()) is not None
    return keyword.lower() in text.lower()


def keyword_groups(keywords: list[str]) -> list[str]:
    groups: list[str] = []
    for keyword in keywords:
        group = KEYWORD_TO_GROUP[keyword]
        if group not in groups:
            groups.append(group)
    return groups


def recency_bonus(paper: Paper, settings: Settings) -> float:
    today = datetime.now(ZoneInfo(settings.timezone_name)).date()
    published = paper.published_at.astimezone(ZoneInfo(settings.timezone_name)).date()
    days_old = max((today - published).days, 0)
    if days_old == 0:
        return 1.8
    if days_old <= 2:
        return 1.45
    if days_old <= 7:
        return 1.1
    if days_old <= 14:
        return 0.45
    return -0.5


def build_score_reason(paper: Paper, settings: Settings) -> str:
    if paper.matched_keywords:
        return "命中关键词：" + "、".join(paper.matched_keywords[:4])
    if paper.source == "ieee":
        return "IEEE 核心期刊元数据入选，建议打开原文核对摘要。"
    return "依据期刊来源、发布时间和电力系统语境入选。"


def label_for_score(score: float) -> str:
    if score >= 7.3:
        return "Strong Match"
    if score >= 5.6:
        return "Promising"
    return "Background Read"


def passes_display_gate(paper: Paper) -> bool:
    if paper.final_score >= 5.2 and paper.matched_keyword_groups:
        return True
    if paper.final_score >= 6.2 and paper.source in {"ieee", "elsevier"}:
        return True
    return False


def dedupe_records(records: list[Paper]) -> list[Paper]:
    exact: dict[str, Paper] = {}
    for paper in records:
        for key in exact_keys(paper):
            if not key:
                continue
            old = exact.get(key)
            if old is None or paper_rank(paper) > paper_rank(old):
                exact[key] = paper

    deduped = list({id(paper): paper for paper in exact.values()}.values())
    fuzzy: list[Paper] = []
    for paper in deduped:
        duplicate_index = None
        for index, existing in enumerate(fuzzy):
            if title_similarity(paper.title, existing.title) >= 0.92:
                duplicate_index = index
                break
        if duplicate_index is None:
            fuzzy.append(paper)
        elif paper_rank(paper) > paper_rank(fuzzy[duplicate_index]):
            fuzzy[duplicate_index] = paper
    return fuzzy


def exact_keys(paper: Paper) -> list[str]:
    return [
        f"doi:{paper.doi.lower()}" if paper.doi else "",
        f"url:{paper.url.lower()}" if paper.url else "",
        f"title:{normalize_title(paper.title)}",
    ]


def title_similarity(left: str, right: str) -> float:
    from difflib import SequenceMatcher

    return SequenceMatcher(None, normalize_title(left), normalize_title(right)).ratio()


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", title.lower())).strip()


def paper_rank(paper: Paper) -> tuple[float, float]:
    return (paper.final_score or paper.rule_score, paper.published_at.timestamp())


def select_records(records: list[Paper], settings: Settings) -> list[Paper]:
    records.sort(key=lambda paper: (paper.final_score, paper.published_at.timestamp()), reverse=True)
    selected: list[Paper] = []
    for section in ("ieee", "arxiv", "energy"):
        section_records = [
            paper for paper in records if paper.section == section and paper.rule_score >= 4.8
        ][: settings.max_results_per_section]
        selected.extend(section_records)
    return selected


def enrich_records(records: list[Paper], settings: Settings) -> None:
    client = None
    if settings.deepseek_api_key:
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_base_url,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"LLM client disabled: {exc}")

    for index, paper in enumerate(records):
        if index >= settings.summary_count or client is None:
            apply_fallback_summary(paper)
            continue
        try:
            apply_llm_summary(paper, client, settings.deepseek_model)
        except Exception as exc:  # noqa: BLE001
            print(f"LLM summary failed for {paper.title[:60]}: {exc}")
            apply_fallback_summary(paper)


def apply_llm_summary(paper: Paper, client: Any, model: str) -> None:
    prompt = f"""
你是电力系统方向的科研助理。请基于论文题名、期刊和摘要，生成中文论文快报。
只返回严格 JSON，不要 markdown 代码块。

JSON 字段：
{{
  "summary": "用 4-6 句话说明这篇论文做了什么、解决什么关键问题、主要方法是什么",
  "innovation": "1-2 句话说明创新点",
  "effect": "1 句话说明实现效果或验证结果；缺信息时保守说明需要看原文确认",
  "limitation": "1 句话说明局限或未来方向",
  "application_value": "1 句话说明为什么值得读",
  "relevance_score": 0.0,
  "relevance_label": "Strong Match | Promising | Background Read"
}}

标题：{paper.title}
期刊：{paper.journal}
作者：{", ".join(paper.authors[:8])}
关键词命中：{", ".join(paper.matched_keywords)}
摘要：{paper.abstract or "No abstract available. Please judge conservatively from title and journal metadata."}
""".strip()
    response = client.chat.completions.create(
        model=model,
        temperature=0.2,
        messages=[
            {"role": "system", "content": "Return strict JSON only."},
            {"role": "user", "content": prompt},
        ],
    )
    content = response.choices[0].message.content or ""
    payload = parse_json_object(content)

    paper.ai_summary = payload.get("summary") or fallback_summary_body(paper)
    innovation = payload.get("innovation")
    effect = payload.get("effect")
    if innovation or effect:
        paper.ai_summary = f"{paper.ai_summary}\n\n创新点：{innovation or '需结合原文确认。'}\n\n验证效果：{effect or '需结合原文确认。'}"
    paper.limitations = payload.get("limitation") or fallback_limitation(paper)
    paper.application_value = payload.get("application_value") or fallback_application_value(paper)
    paper.llm_score = safe_score(payload.get("relevance_score"), paper.rule_score)
    paper.final_score = round(0.45 * paper.rule_score + 0.55 * paper.llm_score, 2)
    paper.relevance_label = payload.get("relevance_label") or label_for_score(paper.final_score)
    paper.score_reason = build_score_reason(paper, load_settings())


def apply_fallback_summary(paper: Paper) -> None:
    paper.ai_summary = fallback_summary_body(paper)
    paper.application_value = fallback_application_value(paper)
    paper.limitations = fallback_limitation(paper)
    paper.llm_score = paper.rule_score
    paper.final_score = round(paper.rule_score, 2)
    paper.relevance_label = label_for_score(paper.final_score)


def fallback_summary_body(paper: Paper) -> str:
    if paper.abstract:
        abstract = re.sub(r"\s+", " ", paper.abstract).strip()
        abstract = abstract[:420] + ("..." if len(abstract) > 420 else "")
        return f"该论文题为《{paper.title}》，来自 {paper.journal}。从摘要看，论文主要内容为：{abstract}"
    return (
        f"该论文题为《{paper.title}》，来自 {paper.journal}。当前公开元数据未提供摘要，"
        "本条目先依据题名、期刊来源和关键词命中结果入选，建议进入原文页面核对方法、模型和实验结论。"
    )


def fallback_application_value(paper: Paper) -> str:
    if "构网与暂态稳定" in paper.matched_keyword_groups:
        return "这篇论文可能与你的构网型变流器暂态稳定和故障穿越研究直接相关。"
    if "电力系统运行与规划" in paper.matched_keyword_groups:
        return "这篇论文适合作为电力系统运行、规划或调度优化方向的重点跟踪对象。"
    if "韧性与恢复" in paper.matched_keyword_groups:
        return "这篇论文可用于跟踪电网韧性评估、恢复和极端事件应对方向。"
    return "建议先快速浏览摘要和图表，再决定是否精读。"


def fallback_limitation(paper: Paper) -> str:
    if not paper.abstract:
        return "当前缺少摘要，自动总结可靠性有限，需要下载或打开原文确认。"
    return "自动摘要只能用于初筛，模型细节、数据集和实验边界仍需在原文中核对。"


def parse_json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?", "", candidate).strip()
        candidate = candidate.rstrip("`").strip()
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("No JSON object found in model response.")
    return json.loads(candidate[start : end + 1])


def safe_score(value: Any, default: float) -> float:
    try:
        return max(0.0, min(float(value), 10.0))
    except (TypeError, ValueError):
        return default


def write_outputs(
    records: list[Paper],
    settings: Settings,
    target_date: date,
    earliest_date: date,
    generated_at: datetime,
    source_errors: list[str],
) -> None:
    root = Path(__file__).resolve().parents[1]
    site_dir = root / "site"
    site_dir.mkdir(parents=True, exist_ok=True)

    current_papers = [paper.to_dict(settings.timezone_name) for paper in records]
    archive_papers = merge_archive_papers(site_dir, current_papers, generated_at, target_date, earliest_date)
    sections = build_sections_from_papers(current_papers)
    archive_payload = build_archive_payload(
        archive_papers,
        settings,
        target_date,
        earliest_date,
        generated_at,
        source_errors,
    )

    payload = {
        "meta": {
            "title": "电力系统论文周报",
            "subtitle": "面向电力系统运行规划、优化调度、韧性评估与构网型变流器稳定性的自动论文精选。",
            "site_base_url": SITE_BASE_URL,
            "homepage_url": SITE_BASE_URL,
            "feed_url": f"{SITE_BASE_URL}feed.xml",
            "bibtex_url": f"{SITE_BASE_URL}references.bib",
            "ris_url": f"{SITE_BASE_URL}references.ris",
            "archive_url": f"{SITE_BASE_URL}archive.json",
            "archive_bibtex_url": f"{SITE_BASE_URL}archive.bib",
            "archive_ris_url": f"{SITE_BASE_URL}archive.ris",
            "generated_at": generated_at.isoformat(),
            "target_date": target_date.isoformat(),
            "window_start": earliest_date.isoformat(),
            "lookback_days": settings.lookback_days,
            "timezone": settings.timezone_name,
            "paper_count": len(records),
            "archive_count": len(archive_papers),
            "source_counts": count_by(records, "source"),
            "journal_counts": count_by(records, "journal"),
            "keyword_group_counts": count_keyword_groups(records),
            "required_topics": list(REQUIRED_TOPICS),
            "workflow_notes": list(WORKFLOW_NOTES),
            "ieee_targets": build_ieee_target_manifest(records, archive_papers),
            "source_notes": SOURCE_NOTES,
            "source_errors": source_errors,
        },
        "sections": sections,
        "papers": current_papers,
    }
    (site_dir / "latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (site_dir / "archive.json").write_text(
        json.dumps(archive_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_feed(site_dir, records, target_date, generated_at)
    write_bibtex(site_dir, records)
    write_ris(site_dir, records)
    write_archive_exports(site_dir, archive_papers)
    write_zotero_exports(site_dir, records, archive_papers)


def write_feed(site_dir: Path, records: list[Paper], target_date: date, generated_at: datetime) -> None:
    top_records = sorted(records, key=lambda paper: paper.final_score, reverse=True)[:8]
    lines = [
        f"{index}. {paper.title} [{paper.journal}] - {paper.final_score:.1f}/10"
        for index, paper in enumerate(top_records, start=1)
    ]
    if not lines:
        lines.append("本周期未发现达到展示门槛的新论文。")

    pub_date = generated_at.strftime("%a, %d %b %Y %H:%M:%S %z")
    description = "电力系统论文周报 · " + target_date.isoformat() + "\n" + "\n".join(lines)
    feed_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>{escape("电力系统论文周报")}</title>
    <link>{escape(SITE_BASE_URL)}</link>
    <description>{escape("每周自动精选电力系统运行规划、优化调度、韧性和构网稳定相关论文。")}</description>
    <language>zh-CN</language>
    <lastBuildDate>{escape(pub_date)}</lastBuildDate>
    <item>
      <title>{escape("电力系统论文周报 · " + target_date.isoformat())}</title>
      <link>{escape(SITE_BASE_URL)}</link>
      <guid isPermaLink="false">{escape(SITE_BASE_URL + "#digest-" + target_date.isoformat())}</guid>
      <pubDate>{escape(pub_date)}</pubDate>
      <description>{escape(description)}</description>
    </item>
  </channel>
</rss>
'''
    (site_dir / "feed.xml").write_text(feed_xml, encoding="utf-8")


def write_bibtex(site_dir: Path, records: list[Paper]) -> None:
    entries = [build_bibtex_entry(paper) for paper in records]
    (site_dir / "references.bib").write_text("\n\n".join(entries) + "\n", encoding="utf-8")


def write_ris(site_dir: Path, records: list[Paper]) -> None:
    chunks = [build_ris_entry(paper) for paper in records]
    (site_dir / "references.ris").write_text("\n\n".join(chunks) + "\n", encoding="utf-8")


def write_archive_exports(site_dir: Path, archive_papers: list[dict[str, Any]]) -> None:
    bibtex_entries = [payload_bibtex_entry(paper) for paper in archive_papers]
    ris_entries = [payload_ris_entry(paper) for paper in archive_papers]
    (site_dir / "archive.bib").write_text("\n\n".join(bibtex_entries) + ("\n" if bibtex_entries else ""), encoding="utf-8")
    (site_dir / "archive.ris").write_text("\n\n".join(ris_entries) + ("\n" if ris_entries else ""), encoding="utf-8")


def write_zotero_exports(
    site_dir: Path,
    records: list[Paper],
    archive_papers: list[dict[str, Any]] | None = None,
) -> None:
    zotero_dir = site_dir / "zotero"
    zotero_dir.mkdir(parents=True, exist_ok=True)
    for source in ieee_sources():
        journal_records = records_for_source_journal(records, source)
        bibtex_entries = [build_bibtex_entry(paper) for paper in journal_records]
        ris_entries = [build_ris_entry(paper) for paper in journal_records]
        (zotero_dir / f"{source.export_slug}.bib").write_text(
            "\n\n".join(bibtex_entries) + ("\n" if bibtex_entries else ""),
            encoding="utf-8",
        )
        (zotero_dir / f"{source.export_slug}.ris").write_text(
            "\n\n".join(ris_entries) + ("\n" if ris_entries else ""),
            encoding="utf-8",
        )
        if archive_papers is not None:
            journal_archive = archive_papers_for_source_journal(archive_papers, source)
            archive_bibtex = [payload_bibtex_entry(paper) for paper in journal_archive]
            archive_ris = [payload_ris_entry(paper) for paper in journal_archive]
            (zotero_dir / f"{source.export_slug}_archive.bib").write_text(
                "\n\n".join(archive_bibtex) + ("\n" if archive_bibtex else ""),
                encoding="utf-8",
            )
            (zotero_dir / f"{source.export_slug}_archive.ris").write_text(
                "\n\n".join(archive_ris) + ("\n" if archive_ris else ""),
                encoding="utf-8",
            )


def build_ieee_target_manifest(
    records: list[Paper],
    archive_papers: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    targets = []
    for source in ieee_sources():
        journal_records = records_for_source_journal(records, source)
        journal_archive = archive_papers_for_source_journal(archive_papers or [], source)
        targets.append(
            {
                "journal": source.title,
                "short_title": short_journal_title(source.title),
                "xplore_url": source.xplore_url,
                "zotero_collection": source.zotero_collection or source.title,
                "bibtex_path": f"./zotero/{source.export_slug}.bib",
                "ris_path": f"./zotero/{source.export_slug}.ris",
                "archive_bibtex_path": f"./zotero/{source.export_slug}_archive.bib",
                "archive_ris_path": f"./zotero/{source.export_slug}_archive.ris",
                "selected_count": len(journal_records),
                "archive_count": len(journal_archive),
            }
        )
    return targets


def ieee_sources() -> list[JournalSource]:
    return [source for source in JOURNAL_SOURCES if source.section == "ieee"]


def records_for_source_journal(records: list[Paper], source: JournalSource) -> list[Paper]:
    return [
        paper
        for paper in records
        if paper.source == source.key
        and (
            paper.journal == source.title
            or paper.metadata.get("configured_journal") == source.title
        )
    ]


def archive_papers_for_source_journal(
    papers: list[dict[str, Any]],
    source: JournalSource,
) -> list[dict[str, Any]]:
    return [
        paper
        for paper in papers
        if paper.get("source") == source.key
        and (
            paper.get("journal") == source.title
            or (paper.get("metadata") or {}).get("configured_journal") == source.title
        )
    ]


def merge_archive_papers(
    site_dir: Path,
    current_papers: list[dict[str, Any]],
    generated_at: datetime,
    target_date: date,
    earliest_date: date,
) -> list[dict[str, Any]]:
    archive_path = site_dir / "archive.json"
    existing_papers: list[dict[str, Any]] = []
    if archive_path.exists():
        try:
            existing_payload = json.loads(archive_path.read_text(encoding="utf-8"))
            existing_papers = [
                paper for paper in existing_payload.get("papers", []) if isinstance(paper, dict)
            ]
        except (OSError, json.JSONDecodeError):
            existing_papers = []
    else:
        latest_path = site_dir / "latest.json"
        if latest_path.exists():
            try:
                latest_payload = json.loads(latest_path.read_text(encoding="utf-8"))
                existing_papers = [
                    paper for paper in latest_payload.get("papers", []) if isinstance(paper, dict)
                ]
            except (OSError, json.JSONDecodeError):
                existing_papers = []

    merged: dict[str, dict[str, Any]] = {}
    for paper in existing_papers:
        key = archive_key(paper)
        if key:
            merged[key] = normalize_archive_paper(paper)

    window_entry = {
        "window_start": earliest_date.isoformat(),
        "target_date": target_date.isoformat(),
        "generated_at": generated_at.isoformat(),
    }
    for paper in current_papers:
        key = archive_key(paper)
        if not key:
            continue
        old = merged.get(key, {})
        combined = {**old, **paper}
        combined["first_seen"] = old.get("first_seen") or generated_at.isoformat()
        combined["last_seen"] = generated_at.isoformat()
        combined["seen_windows"] = append_seen_window(old.get("seen_windows", []), window_entry)
        merged[key] = normalize_archive_paper(combined)

    return sorted(
        merged.values(),
        key=lambda paper: (
            paper.get("published_at_local") or paper.get("published_at") or "",
            float(paper.get("final_score") or 0.0),
        ),
        reverse=True,
    )


def normalize_archive_paper(paper: dict[str, Any]) -> dict[str, Any]:
    paper = dict(paper)
    paper.setdefault("first_seen", paper.get("generated_at") or paper.get("published_at"))
    paper.setdefault("last_seen", paper.get("first_seen"))
    paper.setdefault("seen_windows", [])
    return paper


def append_seen_window(existing: Any, window_entry: dict[str, str]) -> list[dict[str, str]]:
    windows = [item for item in existing if isinstance(item, dict)] if isinstance(existing, list) else []
    identity = (window_entry["window_start"], window_entry["target_date"])
    filtered = [
        item
        for item in windows
        if (item.get("window_start"), item.get("target_date")) != identity
    ]
    filtered.append(window_entry)
    return filtered


def archive_key(paper: dict[str, Any]) -> str:
    doi = str(paper.get("doi") or "").strip().lower()
    if doi:
        return f"doi:{doi}"
    identifier = str(paper.get("id") or "").strip().lower()
    if identifier:
        return f"id:{identifier}"
    url = str(paper.get("url") or "").strip().lower()
    if url:
        return f"url:{url}"
    title = str(paper.get("title") or "").strip()
    return f"title:{normalize_title(title)}" if title else ""


def build_archive_payload(
    archive_papers: list[dict[str, Any]],
    settings: Settings,
    target_date: date,
    earliest_date: date,
    generated_at: datetime,
    source_errors: list[str],
) -> dict[str, Any]:
    return {
        "meta": {
            "title": "电力系统论文历史库",
            "subtitle": "长期留存每周自动入选的电力系统论文，按 DOI/标题去重。",
            "site_base_url": SITE_BASE_URL,
            "homepage_url": SITE_BASE_URL,
            "archive_url": f"{SITE_BASE_URL}archive.json",
            "archive_bibtex_url": f"{SITE_BASE_URL}archive.bib",
            "archive_ris_url": f"{SITE_BASE_URL}archive.ris",
            "generated_at": generated_at.isoformat(),
            "target_date": target_date.isoformat(),
            "window_start": earliest_date.isoformat(),
            "lookback_days": settings.lookback_days,
            "timezone": settings.timezone_name,
            "paper_count": len(archive_papers),
            "archive_count": len(archive_papers),
            "source_counts": count_by_payload(archive_papers, "source"),
            "journal_counts": count_by_payload(archive_papers, "journal"),
            "keyword_group_counts": count_keyword_groups_payload(archive_papers),
            "required_topics": list(REQUIRED_TOPICS),
            "workflow_notes": list(WORKFLOW_NOTES),
            "ieee_targets": build_ieee_target_manifest([], archive_papers),
            "source_notes": SOURCE_NOTES,
            "source_errors": source_errors,
        },
        "sections": build_sections_from_papers(archive_papers),
        "papers": archive_papers,
    }


def build_sections_from_papers(papers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    sections: dict[str, dict[str, Any]] = {}
    for section_key, meta in SECTION_META.items():
        section_papers = [paper for paper in papers if paper.get("section") == section_key]
        sections[section_key] = {
            "title": meta["title"],
            "description": meta["description"],
            "count": len(section_papers),
            "papers": section_papers,
        }
    return sections


def short_journal_title(title: str) -> str:
    return {
        "IEEE Transactions on Power Systems": "IEEE TPWRS",
        "IEEE Transactions on Smart Grid": "IEEE TSG",
        "IEEE Transactions on Sustainable Energy": "IEEE TSTE",
    }.get(title, title)


def build_bibtex_entry(paper: Paper) -> str:
    fields = {
        "title": paper.title,
        "author": " and ".join(paper.authors),
        "journal": paper.journal,
        "year": str(paper.published_at.year),
        "doi": paper.doi or "",
        "url": paper.url,
        "keywords": ", ".join(export_keywords(paper)),
        "note": f"Auto-selected by Power Paper Digest; score={paper.final_score:.1f}",
    }
    body = ",\n".join(f"  {name} = {{{escape_bibtex(value)}}}" for name, value in fields.items() if value)
    return f"@article{{{citation_key(paper)},\n{body}\n}}"


def build_ris_entry(paper: Paper) -> str:
    lines = ["TY  - JOUR", f"TI  - {clean_export_text(paper.title)}", f"JO  - {clean_export_text(paper.journal)}"]
    for author in paper.authors:
        lines.append(f"AU  - {clean_export_text(author)}")
    for keyword in export_keywords(paper):
        lines.append(f"KW  - {clean_export_text(keyword)}")
    lines.append(f"PY  - {paper.published_at.year}")
    if paper.doi:
        lines.append(f"DO  - {clean_export_text(paper.doi)}")
    lines.append(f"UR  - {clean_export_text(paper.url)}")
    lines.append(f"N1  - Auto-selected by Power Paper Digest; score={paper.final_score:.1f}")
    lines.append("ER  -")
    return "\n".join(lines)


def payload_bibtex_entry(paper: dict[str, Any]) -> str:
    if paper.get("bibtex_entry"):
        return str(paper["bibtex_entry"]).strip()
    authors = paper.get("authors") or []
    fields = {
        "title": str(paper.get("title") or ""),
        "author": " and ".join(str(author) for author in authors),
        "journal": str(paper.get("journal") or ""),
        "year": str(paper.get("published_date_local") or paper.get("published_at") or "")[:4],
        "doi": str(paper.get("doi") or ""),
        "url": str(paper.get("url") or ""),
        "keywords": ", ".join(payload_export_keywords(paper)),
        "note": f"Archived by Power Paper Digest; score={float(paper.get('final_score') or 0.0):.1f}",
    }
    body = ",\n".join(f"  {name} = {{{escape_bibtex(value)}}}" for name, value in fields.items() if value)
    return f"@article{{{payload_citation_key(paper)},\n{body}\n}}"


def payload_ris_entry(paper: dict[str, Any]) -> str:
    if paper.get("ris_entry"):
        return str(paper["ris_entry"]).strip()
    lines = [
        "TY  - JOUR",
        f"TI  - {clean_export_text(str(paper.get('title') or ''))}",
        f"JO  - {clean_export_text(str(paper.get('journal') or ''))}",
    ]
    for author in paper.get("authors") or []:
        lines.append(f"AU  - {clean_export_text(str(author))}")
    for keyword in payload_export_keywords(paper):
        lines.append(f"KW  - {clean_export_text(keyword)}")
    year = str(paper.get("published_date_local") or paper.get("published_at") or "")[:4]
    if year:
        lines.append(f"PY  - {year}")
    if paper.get("doi"):
        lines.append(f"DO  - {clean_export_text(str(paper['doi']))}")
    if paper.get("url"):
        lines.append(f"UR  - {clean_export_text(str(paper['url']))}")
    lines.append(f"N1  - Archived by Power Paper Digest; score={float(paper.get('final_score') or 0.0):.1f}")
    lines.append("ER  -")
    return "\n".join(lines)


def payload_export_keywords(paper: dict[str, Any]) -> list[str]:
    keywords: list[str] = []
    values = [
        paper.get("relevance_label"),
        *(paper.get("matched_keyword_groups") or []),
        *(paper.get("matched_keywords") or []),
    ]
    for value in values:
        text = str(value).strip()
        if text and text not in keywords:
            keywords.append(text)
    return keywords


def payload_citation_key(paper: dict[str, Any]) -> str:
    if paper.get("citation_key"):
        return re.sub(r"[^A-Za-z0-9:_-]", "", str(paper["citation_key"])) or "paperdigest"
    first_author = "paper"
    authors = paper.get("authors") or []
    if authors:
        first_author = re.sub(r"[^A-Za-z0-9]", "", str(authors[0]).split()[-1]).lower() or "paper"
    title = str(paper.get("title") or "")
    title_word = next(
        (re.sub(r"[^A-Za-z0-9]", "", word).lower() for word in title.split() if len(word) > 3),
        "digest",
    )
    year = str(paper.get("published_date_local") or paper.get("published_at") or "")[:4] or "year"
    identifier = str(paper.get("doi") or paper.get("id") or paper.get("url") or title)
    suffix = re.sub(r"[^A-Za-z0-9]", "", identifier)[-6:].lower() or "paper"
    return f"{first_author}{year}{title_word}{suffix}"


def export_keywords(paper: Paper) -> list[str]:
    keywords: list[str] = []
    for value in [paper.relevance_label, *paper.matched_keyword_groups, *paper.matched_keywords]:
        if value and value not in keywords:
            keywords.append(value)
    return keywords


def citation_key(paper: Paper) -> str:
    first_author = "paper"
    if paper.authors:
        first_author = re.sub(r"[^A-Za-z0-9]", "", paper.authors[0].split()[-1]).lower() or "paper"
    title_word = "digest"
    for word in paper.title.split():
        clean_word = re.sub(r"[^A-Za-z0-9]", "", word).lower()
        if len(clean_word) > 3:
            title_word = clean_word
            break
    identifier = paper.doi or paper.id or paper.url or paper.title
    suffix = re.sub(r"[^A-Za-z0-9]", "", identifier)[-6:].lower() or "paper"
    return f"{first_author}{paper.published_at.year}{title_word}{suffix}"


def escape_bibtex(value: str) -> str:
    return clean_export_text(value).replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def clean_export_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def count_by(records: list[Paper], attr: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for paper in records:
        value = str(getattr(paper, attr))
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def count_by_payload(records: list[dict[str, Any]], attr: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for paper in records:
        value = str(paper.get(attr) or "")
        if not value:
            continue
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def count_keyword_groups(records: list[Paper]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for paper in records:
        for group in paper.matched_keyword_groups:
            counts[group] = counts.get(group, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def count_keyword_groups_payload(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for paper in records:
        for group in paper.get("matched_keyword_groups") or []:
            counts[str(group)] = counts.get(str(group), 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def build_user_agent(settings: Settings) -> str:
    if settings.crossref_mailto:
        return f"{USER_AGENT} mailto:{settings.crossref_mailto}"
    return USER_AGENT


def get_xml_text(node: ElementTree.Element, path: str, ns: dict[str, str]) -> str:
    child = node.find(path, ns)
    return child.text if child is not None and child.text else ""


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def clean_abstract(value: str) -> str:
    cleaned = html.unescape(value or "")
    cleaned = re.sub(r"</?(jats:)?[^>]+>", " ", cleaned)
    return clean_text(cleaned)


def is_non_research_title(title: str) -> bool:
    normalized = title.lower()
    patterns = (
        "table of contents",
        "front cover",
        "back cover",
        "editorial board",
        "masthead",
        "information for authors",
        "blank page",
    )
    return any(pattern in normalized for pattern in patterns)


if __name__ == "__main__":
    raise SystemExit(main())

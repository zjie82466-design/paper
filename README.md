# 电力系统论文周报

这是一个面向电力系统运行规划、优化调度、韧性评估与构网型变流器稳定性方向的自动论文精选网页。

系统每周一由 GitHub Actions 自动运行，抓取最近一周的 arXiv 与重点期刊元数据，按关键词、来源质量和时效打分，生成：

- GitHub Pages 静态网页
- `latest.json` 数据文件
- `feed.xml` RSS
- `references.bib` 与 `references.ris`，用于 Zotero 导入

网页支持按来源、期刊、关键词类别、相关性标签筛选，支持标题/作者/关键词全文检索，并可对单篇论文复制 DOI、BibTeX 或 RIS。筛选状态会保存在浏览器本地，刷新页面后仍会保留。

## 数据来源

- arXiv: `eess.SY`, `math.OC`
- IEEE Transactions on Power Systems
- IEEE Transactions on Smart Grid
- IEEE Transactions on Sustainable Energy
- Applied Energy
- Joule
- Nature Energy

其中 IEEE、Applied Energy、Joule、Nature Energy 当前主要通过 Crossref 元数据检索；若缺少摘要，系统会保守生成导读并提示需要打开原文核对。

## 本地运行

```bash
pip install -r requirements.txt
python -m scripts.build_daily_site
```

生成结果在 `site/` 目录。

## GitHub Secrets

建议在仓库 `Settings -> Secrets and variables -> Actions` 中添加：

- `CROSSREF_MAILTO`: 学校邮箱，可提升 Crossref 请求规范性
- `DEEPSEEK_API_KEY`: 可选，用于生成更完整的中文摘要和相关性评分

没有 `DEEPSEEK_API_KEY` 时，系统仍会生成网页，只是使用规则摘要。

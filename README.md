# UNF Aktivite Web Scraper

本项目用于自动抓取 UNF KBH 和 Lyngby 活动信息,并生成带有欧洲哥本哈根时区的 ICS 日历文件.支持 GitHub Actions 自动化发布.

## 功能简介

- 登录 UNF 活动网站(支持 CI 环境和本地交互式登录)
- 爬取 KBH 和 Lyngby 两地活动,支持多页抓取
- 解析活动表格或管道分隔文本
- 生成符合 iCalendar 标准的 ICS 文件,包含时区信息
- 自动化发布到 GitHub Pages


## 使用方法

### GitHub Actions 自动化

- 工作流文件 `.github/workflows/publish.yml` 已配置定时任务,每天多次自动抓取并发布到 GitHub Pages.
- 需在仓库 Secrets 中设置 `UNF_USER` 和 `UNF_PASS`.
- 自动生成的 ICS 文件会上传到 `dist` 目录,并通过 Pages 发布.

## 主要文件说明

- `unf_events_to_ics.py`:主爬虫及 ICS 生成脚本
- `.github/workflows/publish.yml`:GitHub Actions 自动化发布配置

## 环境变量

- `UNF_USER`:UNF 登录用户名
- `UNF_PASS`:UNF 登录密码

## 输出结果

- `dist/unf_events_kbh.ics`:KBH 活动 ICS 文件
- `dist/unf_events_lyngby.ics`:Lyngby 活动 ICS 文件

name: Cleanup old workflow runs (older than 24h)

on:
  schedule:
    - cron: "15 23 * * *"  # 每晚 23:15 UTC 触发 (可按需调整)
  workflow_dispatch: {}

permissions:
  actions: write   # 需要删除 workflow run
  contents: read

jobs:
  cleanup:
    runs-on: ubuntu-latest
    env:
      HOURS_THRESHOLD: 24         # 超过多少小时删除
      MIN_KEEP: 3                # 至少保留最新的 N 个 run(安全垫)
      DRY_RUN: "false"            # 若想先看效果改成 true
    steps:
      - name: Gather & delete old runs
        shell: bash
        run: |
          set -euo pipefail
          echo "Repository: $GITHUB_REPOSITORY"
          echo "Threshold hours: ${HOURS_THRESHOLD}h"          
          echo "Minimum keep (latest runs): ${MIN_KEEP}"      
          now_epoch=$(date -u +%s)
          cutoff_epoch=$(( now_epoch - HOURS_THRESHOLD*3600 ))
          echo "Cutoff epoch: $cutoff_epoch ($(date -u -d @${cutoff_epoch} '+%Y-%m-%d %H:%M:%S'))"

          page=1
          deleted=0
          kept=0
          examined=0

          # 收集所有需要处理的 run(分页,最多 100 每页)
          # 为简单起见,迭代最多 10 页(如需更多可扩大)
          while [ $page -le 10 ]; do
            echo "Fetching page $page" >&2
            json=$(curl -fsSL -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github+json" \
              "https://api.github.com/repos/${GITHUB_REPOSITORY}/actions/runs?per_page=100&page=${page}") || break

            count=$(echo "$json" | jq '.workflow_runs | length')
            [ "$count" -eq 0 ] && break

            # 按 created_at 降序排序(最新在前),合并进临时文件
            echo "$json" | jq -r '.workflow_runs[] | [.id, .created_at, .name, .status, .conclusion] | @tsv' >> runs_raw.tsv
            page=$((page+1))
          done

          if [ ! -s runs_raw.tsv ]; then
            echo "No runs found."; exit 0
          fi

            # 排序(按时间降序),前 MIN_KEEP 行直接跳过保护
          sort -k2,2r runs_raw.tsv > runs_sorted.tsv

          idx=0
          while IFS=$'\t' read -r run_id created_at name status conclusion; do
            idx=$((idx+1))
            examined=$((examined+1))
            # 保留前 MIN_KEEP 个
            if [ $idx -le $MIN_KEEP ]; then
              kept=$((kept+1))
              continue
            fi
            # 时间判定
            created_epoch=$(date -u -d "$created_at" +%s || echo 0)
            if [ "$created_epoch" -eq 0 ]; then
              echo "Warn: cannot parse time for run $run_id ($created_at)" >&2
              continue
            fi
            if [ $created_epoch -ge $cutoff_epoch ]; then
              kept=$((kept+1))
              continue
            fi

            echo "Delete candidate: id=$run_id created_at=$created_at status=$status conclusion=$conclusion" >&2
            if [ "$DRY_RUN" = "true" ]; then
              echo "(dry-run) Skipping actual delete for $run_id" >&2
              kept=$((kept+1))
            else
              code=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE \
                -H "Authorization: Bearer $GITHUB_TOKEN" \
                -H "Accept: application/vnd.github+json" \
                "https://api.github.com/repos/${GITHUB_REPOSITORY}/actions/runs/${run_id}")
              if [ "$code" = "204" ]; then
                deleted=$((deleted+1))
                echo "Deleted run $run_id" >&2
              else
                echo "Failed to delete run $run_id (HTTP $code)" >&2
                kept=$((kept+1))
              fi
            fi
          done < runs_sorted.tsv

          echo "Examined: $examined"
          echo "Deleted:  $deleted"
          echo "Kept:     $kept"
          if [ "$DRY_RUN" = "true" ]; then
            echo "(Dry run mode enabled – no deletions actually performed)"
          fi

      - name: Summary
        run: |
          echo "Cleanup finished at $(date -u '+%Y-%m-%d %H:%M:%S') UTC"
        header = [c.get_text(" ", strip=True) for c in head_cells]
        hl = [h.lower() for h in header]
        if not header: 
            continue
        hits = sum(kw in " ".join(hl) for kw in ["navn","dato","klokkesl","tid","vagter","reserverede"])
        if hits < 2:
            continue

        def idx_of(keys: list[str]) -> int:
            for k in keys:
                if k in hl: return hl.index(k)
            return -1

        idx_navn = idx_of(["navn","titel","title"])
        idx_dato = idx_of(["dato","date"])
        idx_tid  = idx_of(["klokkeslæt","klokkeslaet","tid","time"])
        idx_vagt = idx_of(["vagter","vagt"])
        idx_res  = idx_of(["reserverede","deltagere","tilmeldte"])

        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if not tds:
                continue
            cells_text = [td.get_text(" ", strip=True) for td in tds]
            url, title = None, ""
            navn_td = tds[idx_navn] if 0 <= idx_navn < len(tds) else None
            if navn_td is not None:
                a = navn_td.find("a", href=True)
                url = absolutize(a["href"]) if a else None
                title = a.get_text(" ", strip=True) if a else cells_text[idx_navn]
            else:
                a = tr.find("a", href=True)
                url = absolutize(a["href"]) if a else None
                title = a.get_text(" ", strip=True) if a else (cells_text[0] if cells_text else "")

            dato = cells_text[idx_dato] if 0 <= idx_dato < len(cells_text) else ""
            tid  = cells_text[idx_tid]  if 0 <= idx_tid  < len(cells_text) else ""
            vagt = cells_text[idx_vagt] if 0 <= idx_vagt < len(cells_text) else ""
            res  = cells_text[idx_res]  if 0 <= idx_res  < len(cells_text) else ""

            out.append({
                "Navn": (title or "").strip(),
                "Dato": norm_date(dato),
                "Klokkeslæt": norm_time(tid),
                "Vagter": to_int(vagt),
                "Reserverede": to_int(res),
                "URL": (url or "").strip(),
            })
    return out

def parse_pipe_lines(soup: BeautifulSoup) -> list[dict]:
    out, texts = [], []
    for node in soup.find_all(string=True):
        s = str(node).strip()
        if "|" in s and len(s) > 10:
            texts.append(s)

    header = None
    for s in texts:
        cells = [c.strip() for c in re.sub(r"\s*\|\s*", "|", s).split("|")]
        if len(cells) >= 5 and cells[0].lower() == "navn":
            header = cells
            break

    def parse_values(line: str) -> dict | None:
        cells = [c.strip() for c in re.sub(r"\s*\|\s*", "|", line).split("|")]
        if len(cells) < 2 or cells[0].lower() == "navn":
            return None
        if header:
            head = header[:len(cells)]
            return dict(zip(head, cells))
        if len(cells) < len(ORDER):
            cells += [""]*(len(ORDER) - len(cells))
        return dict(zip(ORDER, cells[:len(ORDER)]))

    for s in texts:
        d = parse_values(s)
        if not d:
            continue
        out.append({
            "Navn": d.get("Navn","" ).strip(),
            "Dato": norm_date(d.get("Dato","")),
            "Klokkeslæt": norm_time(d.get("Klokkeslæt","")),
            "Vagter": to_int(d.get("Vagter","")),
            "Reserverede": to_int(d.get("Reserverede","") or d.get("Deltagere","")),
            "URL": "",
        })
    return out

def attach_urls_by_title(items: list[dict], soup: BeautifulSoup) -> None:
    anchors = soup.find_all("a", href=True)
    index = {}
    for a in anchors:
        t = a.get_text(" ", strip=True)
        href = absolutize(a["href"])
        if t and href and "/events/" in href:
            index.setdefault(t.lower(), href)
    for it in items:
        if not it.get("URL"):
            href = index.get(it["Navn"].lower())
            if href:
                it["URL"] = href

def find_next_page(soup: BeautifulSoup) -> str | None:
    a = soup.find("a", rel=lambda v: v and "next" in v)
    if a and a.has_attr("href"):
        return absolutize(a["href"])
    for txt in ["Næste","Naeste","Next","›",">>"]:
        link = soup.find("a", string=lambda s: s and txt.lower() in s.lower())
        if link and link.has_attr("href"):
            return absolutize(link["href"])
    link = soup.select_one(".pagination .next a, a.next")
    return absolutize(link["href"]) if link and link.has_attr("href") else None

def crawl_location(session: requests.Session, start_url: str, max_pages: int = 5) -> list[dict]:
    url, seen, rows = start_url, set(), []
    while url and url not in seen and len(seen) < max_pages:
        seen.add(url)
        r = session.get(url, timeout=20)
        if r.status_code != 200:
            break
        soup = BeautifulSoup(r.text, "html.parser")
        batch = parse_table(soup)
        if not batch:
            batch = parse_pipe_lines(soup)
            if batch:
                attach_urls_by_title(batch, soup)
        existing = {(x.get("URL"), x.get("Navn","").lower()) for x in rows}
        for it in batch:
            key = (it.get("URL"), it.get("Navn","").lower())
            if key not in existing:
                rows.append(it)
        url = find_next_page(soup)
        time.sleep(0.6)
    return rows

# ---------- ICS (local times with TZID + VTIMEZONE) ----------
VTIMEZONE_EUROPE_CPH = """BEGIN:VTIMEZONE
TZID:Europe/Copenhagen
X-LIC-LOCATION:Europe/Copenhagen
BEGIN:DAYLIGHT
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
TZNAME:CEST
DTSTART:19700329T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
TZNAME:CET
DTSTART:19701025T030000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
END:VTIMEZONE
""".strip()

def fold_ical_line(line: str) -> str:
    raw = line.encode("utf-8"); chunks = []; start = 0; limit = 75
    while start < len(raw):
        end = min(start + limit, len(raw))
        chunk = raw[start:end].decode("utf-8", errors="ignore")
        chunks.append(chunk if start == 0 else " " + chunk)
        start = end
    return "\r\n".join(chunks)

def ics_escape(text: str) -> str:
    if text is None: return ""
    return str(text).replace("\\","\\\\").replace("\n","\\n").replace(",","\\,").replace(";","\\;")

def parse_dt_local(date_str: str, time_str: str) -> datetime | None:
    if not date_str: return None
    try:
        d = dateparser.parse(date_str, dayfirst=True, fuzzy=True).date()
    except Exception:
        return None
    m = re.search(r"(\d{1,2}):(\d{2})", time_str or "")
    hh, mm = (int(m.group(1)), int(m.group(2))) if m else (18, 0)  # default 18:00
    return datetime(d.year, d.month, d.day, hh, mm)

def uid_for(it: dict, slug: str) -> str:
    key = (slug + "|" + it.get("URL","") + "|" + it.get("Navn","") + "|" + it.get("Dato","") + "|" + it.get("Klokkeslæt","")).encode("utf-8")
    return "unf-" + hashlib.sha1(key).hexdigest() + "@unf"

def rows_to_ics(rows: list[dict], out_path: str, calname: str) -> None:
    now = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "PRODID:-//UNF Export//UNF Events to ICS//EN",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{ics_escape(calname)}",
        "X-WR-TIMEZONE:Europe/Copenhagen",
    ]
    # Add VTIMEZONE for Europe/Copenhagen (required when using TZID)
    lines += [ln for ln in VTIMEZONE_EUROPE_CPH.splitlines()]

    for it in rows:
        start_local = parse_dt_local(it.get("Dato",""), it.get("Klokkeslæt",""))
        if not start_local:
            continue
        end_local = start_local + timedelta(hours=2)  # default duration 2h

        def fmt_local(dt: datetime) -> str:
            return dt.strftime("%Y%m%dT%H%M%S")  # no trailing 'Z', TZID specified on property

        desc = [
            f"Vagter: {int(it.get('Vagter',0))}",
            f"Reserverede: {int(it.get('Reserverede',0))}",
        ]
        if it.get("URL"):
            desc.append(f"URL: {it['URL']}")
        description = "\\n".join(ics_escape(p) for p in desc)

        evt = [
            "BEGIN:VEVENT",
            f"UID:{uid_for(it, calname)}",
            f"DTSTAMP:{now}",
            f"DTSTART;TZID=Europe/Copenhagen:{fmt_local(start_local)}",
            f"DTEND;TZID=Europe/Copenhagen:{fmt_local(end_local)}",
            f"SUMMARY:{ics_escape(it.get('Navn',''))}",
        ]
        if it.get("URL"):
            evt.append(f"URL:{ics_escape(it['URL'])}")
        if description:
            evt.append(f"DESCRIPTION:{description}")
        evt.append("STATUS:CONFIRMED")
        evt += ["TRANSP:OPAQUE","END:VEVENT"]
        lines += [fold_ical_line(e) for e in evt]

    lines.append("END:VCALENDAR")
    content = "\r\n".join(lines) + "\r\n"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)

# ---------- Orchestration ----------
def run_once(out_dir: str, max_pages: int) -> None:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Python-Requests",
        "Accept-Language": "en,da;q=0.9",
    })
    user, pwd = prompt_credentials()
    login(session, user, pwd)

    ics_files = []
    for slug, path in LOCATIONS.items():
        start_url = urljoin(BASE, path)
        rows = crawl_location(session, start_url, max_pages=max_pages)
        out_path = os.path.join(out_dir, f"unf_events_{slug}.ics")
        calname = f"UNF {slug.upper()} Events"
        rows_to_ics(rows, out_path, calname)
        print(f"[{slug}] Saved {len(rows)} events -> {out_path}")
        ics_files.append(out_path)
    # 输出所有生成的ics文件名,方便后续自动插入到html
    print("ICS_FILES:" + ",".join(ics_files))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="dist", help="Output directory for ICS files")
    ap.add_argument("--pages", type=int, default=5, help="Max pages to crawl per location")
    args = ap.parse_args()
    run_once(args.out_dir, args.pages)

if __name__ == "__main__":
    main()

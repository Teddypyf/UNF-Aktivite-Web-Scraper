#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Login -> Crawl -> Parse -> Generate two ICS feeds (KBH & Lyngby) with TZID=Europe/Copenhagen.
No intermediate CSV.

Env (in CI via GitHub Actions Secrets):
  UNF_USER, UNF_PASS
Usage (local):
  python unf_events_to_ics.py --out-dir dist --pages 5
"""
import os, sys, re, time, getpass, argparse, hashlib
from datetime import datetime, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
BASE = "https://frivillig.unf.dk"
LOGIN_URL = "https://frivillig.unf.dk/login/?next=/events/kbh/"
LOCATIONS = {
    "kbh":    "/events/kbh/",
    "lyngby": "/events/lyngby/",
    "aalborg":"/events/aalborg/",
    "aarhus": "/events/aarhus/",
    "danmark":"/events/danmark/",
    "odense": "/events/odense/",
}
ORDER = ["Navn","Dato","Ugedag","Klokkeslæt","Vagter","Reserverede","Pladser","Deltagere","Ekstern/Intern"]

DEFAULT_USERNAME = ""
DEFAULT_PASSWORD = ""

# ---------- Credentials (CI-safe) ----------
def prompt_credentials():
    user = os.getenv("UNF_USER")
    pwd  = os.getenv("UNF_PASS")

    # Non-interactive (CI): require env and never call input()
    if os.getenv("GITHUB_ACTIONS") == "true" or not sys.stdin.isatty():
        if not user or not pwd:
            raise RuntimeError("Missing UNF_USER/UNF_PASS in environment for non-interactive run.")
        return user, pwd

    # Local interactive fallback
    user = user or input(f"Username [{DEFAULT_USERNAME}]: ") or DEFAULT_USERNAME
    entered = getpass.getpass("Password (press Enter to use default): ")
    pwd = pwd or (entered if entered else DEFAULT_PASSWORD)
    return user, pwd

# ---------- Session & Login ----------
def get_csrf(session: requests.Session) -> str:
    r = session.get(LOGIN_URL, timeout=20); r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    hidden = soup.find("input", {"name": "csrfmiddlewaretoken"})
    field_token = hidden["value"] if hidden and hidden.has_attr("value") else None
    cookie_token = session.cookies.get("csrftoken")
    if not field_token and not cookie_token:
        raise RuntimeError("CSRF token not found.")
    return field_token or cookie_token

def login(session: requests.Session, username: str, password: str) -> None:
    token = get_csrf(session)
    headers = {"Referer": LOGIN_URL, "Origin": BASE}
    payload = {
        "username": username,
        "password": password,
        "csrfmiddlewaretoken": token,
        "next": "/events/kbh/",
    }
    session.post(LOGIN_URL, data=payload, headers=headers, timeout=20, allow_redirects=True)
    # Sanity check (look for logout marker on KBH page)
    chk = session.get(urljoin(BASE, LOCATIONS["kbh"]), timeout=20)
    ok = (chk.status_code == 200) and any(x in chk.text.lower() for x in ["log ud", "logout", "/logout"])
    if not ok:
        raise RuntimeError("Login failed. Check credentials or additional protections.")

# ---------- Parsing helpers ----------
def absolutize(href: str) -> str | None:
    return urljoin(BASE, href) if href else None

def norm_time(s: str) -> str:
    if not s: return ""
    m = re.search(r"(\d{1,2}):(\d{2})", str(s))
    return m.group(1) if m else str(s).strip()

def norm_date(s: str) -> str:
    if not s: return ""
    try:
        dt = dateparser.parse(str(s), dayfirst=True, fuzzy=True)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return ""

def to_int(s) -> int:
    if s is None: return 0
    m = re.search(r"\d+", str(s))
    return int(m.group(0)) if m else 0

def parse_table(soup: BeautifulSoup) -> list[dict]:
    out = []
    for table in soup.select("table"):
        head_cells = table.find_all("th")
        if not head_cells:
            tr0 = table.find("tr")
            head_cells = tr0.find_all("td") if tr0 else []
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

            # 检查是否取消: 取消行包含独立 class token: rowExternal danger footable-even/footable-odd
            # 之前逻辑错误地把多个标记当成单一 token 内同时出现,改为集合匹配
            cls_tokens = []
            for c in tr.get("class", []) or []:
                if isinstance(c, str):
                    cls_tokens.append(c.lower())
            if navn_td is not None:
                for c in navn_td.get("class", []) or []:
                    if isinstance(c, str):
                        cls_tokens.append(c.lower())
            cls_set = set(cls_tokens)
            is_cancelled = (
                "rowexternal" in cls_set and
                "danger" in cls_set and
                ("footable-even" in cls_set or "footable-odd" in cls_set)
            )

            out.append({
                "Navn": (title or "").strip(),
                "Dato": norm_date(dato),
                "Klokkeslæt": norm_time(tid),
                "Vagter": to_int(vagt),
                "Reserverede": to_int(res),
                "URL": (url or "").strip(),
                "Cancelled": is_cancelled,
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
            "Cancelled": False,  # 管道文本模式无法识别取消
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
        if it.get("Cancelled"):
            desc.append("[已取消]")
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
        if it.get("Cancelled"):
            evt.append("STATUS:CANCELLED")
        else:
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

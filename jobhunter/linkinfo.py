"""Paste a link, get the details: title, company, location, pay and description for a job posting.

Greenhouse, Lever and Ashby links are read from those boards' public APIs. Other links are read from the
posting's own page, using the standard job-posting data (schema.org JobPosting) that most career sites
include for search engines. Nothing here logs in anywhere.
"""
import html
import json
import re
import urllib.parse
import urllib.request

from .config import UA
from .sources import http_json, pay_line, parse_salary, strip_html, workday_base

TRACKING = re.compile(r"^(utm_.*|gh_src|ref|refid|referrer|source|src|trk|trkinfo|lipi|lever-source|"
                      r"lever-origin|fbclid|gclid|mc_cid|mc_eid|_hs.*|ccuid)$", re.I)


def clean_url(url):
    """Drop tracking parameters so the same job isn't saved twice under different links."""
    url = (url or "").strip()
    if not re.match(r"https?://", url, re.I):
        url = "https://" + url if url else ""
    u = urllib.parse.urlsplit(url)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(u.query, keep_blank_values=True) if not TRACKING.match(k)]
    return urllib.parse.urlunsplit((u.scheme.lower(), u.netloc.lower(), u.path.rstrip("/") or "/",
                                    urllib.parse.urlencode(q), ""))


def _result(title, company, location="", description="", apply_url="", salary=(None, None), hint=None):
    return {"title": html.unescape(title or "").strip(), "company": html.unescape(company or "").strip(),
            "location": (location or "").strip(), "description": description or "", "apply_url": apply_url,
            "salary": salary, "workplace_hint": hint}


def from_greenhouse(board, jid, url):
    j = http_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{jid}")
    desc = strip_html(j.get("content"))
    return _result(j.get("title"), j.get("company_name") or board.replace("-", " ").title(),
                   (j.get("location") or {}).get("name", ""), desc, url, parse_salary(pay_line(desc)))


def from_lever(company, jid, url):
    j = http_json(f"https://api.lever.co/v0/postings/{company}/{jid}")
    cats = j.get("categories") or {}
    desc = (j.get("descriptionPlain") or "") + "\n" + "\n".join(
        strip_html(x.get("content", "")) for x in j.get("lists") or [])
    sr = j.get("salaryRange") or {}
    sal = (sr.get("min"), sr.get("max")) if sr.get("currency", "USD") == "USD" else (None, None)
    return _result(j.get("text"), company.replace("-", " ").title(), cats.get("location") or "", desc,
                   j.get("applyUrl") or url, sal, j.get("workplaceType"))


def from_ashby(board, jid, url):
    data = http_json(f"https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true")
    for j in data.get("jobs", []):
        if jid in (j.get("id") or "") or jid in (j.get("jobUrl") or ""):
            comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
            hint = j.get("workplaceType") or ("remote" if j.get("isRemote") else None)
            return _result(j.get("title"), board.replace("-", " ").title(), j.get("location") or "",
                           j.get("descriptionPlain") or strip_html(j.get("descriptionHtml")),
                           j.get("applyUrl") or url, parse_salary(comp), hint)
    raise LookupError("That job isn't on the company's Ashby board any more.")


def from_workday(url):
    base, site, _ = workday_base(url)
    path = urllib.parse.urlsplit(url).path
    i = path.find("/job/")
    if i < 0:
        raise LookupError("That Workday link isn't a single job.")
    data = http_json(base + path[i:])
    info = data.get("jobPostingInfo") or {}
    desc = strip_html(info.get("jobDescription"))
    org = (data.get("hiringOrganization") or {}).get("name") or ""
    rt = (info.get("remoteType") or "").lower()
    hint = "remote" if "remote" in rt else "hybrid" if "hybrid" in rt else None
    return _result(info.get("title"), org or site.split("//")[1].split(".")[0].title(),
                   info.get("location") or "", desc, info.get("externalUrl") or url,
                   parse_salary(pay_line(desc)), hint)


def _first(x):
    return x[0] if isinstance(x, list) and x else x


def parse_jsonld(page):
    """The JobPosting data embedded in a career-site page, as a _result dict, or None."""
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for it in items:
            if not isinstance(it, dict):
                continue
            typ = it.get("@type")
            if typ != "JobPosting" and not (isinstance(typ, list) and "JobPosting" in typ):
                continue
            org = _first(it.get("hiringOrganization")) or {}
            loc = _first(it.get("jobLocation")) or {}
            addr = loc.get("address", {}) if isinstance(loc, dict) else {}
            addr = _first(addr) if isinstance(addr, list) else addr
            place = ", ".join(x for x in ((addr or {}).get("addressLocality"), (addr or {}).get("addressRegion"))
                              if isinstance(x, str) and x) if isinstance(addr, dict) else ""
            remote = "TELECOMMUTE" in json.dumps(it.get("jobLocationType") or "").upper()
            sal = (None, None)
            bs = it.get("baseSalary")
            if isinstance(bs, dict) and (bs.get("currency") or "USD") == "USD":
                v = bs.get("value") or {}
                if isinstance(v, dict):
                    lo, hi = v.get("minValue") or v.get("value"), v.get("maxValue") or v.get("value")
                    mult = 2080 if str(v.get("unitText", "")).upper() == "HOUR" else 1
                    try:
                        sal = (float(lo) * mult if lo else None, float(hi) * mult if hi else None)
                    except (TypeError, ValueError):
                        pass
            desc = strip_html(it.get("description") or "")
            if sal == (None, None):
                sal = parse_salary(pay_line(desc))
            return _result(it.get("title"), org.get("name") if isinstance(org, dict) else str(org),
                           place or ("Remote" if remote else ""), desc, "", sal, "remote" if remote else None)
    return None


def _meta(page, prop):
    m = re.search(r'<meta[^>]+(?:property|name)=["\']' + re.escape(prop) + r'["\'][^>]+content=["\']([^"\']*)',
                  page, re.I)
    return html.unescape(m.group(1)).strip() if m else ""


def from_page(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=20) as r:
        page = r.read(3_000_000).decode("utf-8", "replace")
    found = parse_jsonld(page)
    if found and found["title"]:
        found["apply_url"] = url
        return found
    title = _meta(page, "og:title") or (re.search(r"<title>(.*?)</title>", page, re.S | re.I) or [None, ""])[1]
    return _result(title, _meta(page, "og:site_name"), "", _meta(page, "og:description"), url)


def lookup(url):
    """Details for the job at url. Raises an exception if the page can't be read."""
    url = clean_url(url)
    u = urllib.parse.urlsplit(url)
    host, parts = u.netloc, [p for p in u.path.split("/") if p]
    qs = dict(urllib.parse.parse_qsl(u.query))
    if host.endswith("greenhouse.io") and len(parts) >= 3 and parts[1] == "jobs":
        return from_greenhouse(parts[0], parts[2], url)
    if host.endswith("greenhouse.io") and qs.get("for") and qs.get("token"):
        return from_greenhouse(qs["for"], qs["token"], url)
    if host == "jobs.lever.co" and len(parts) >= 2:
        return from_lever(parts[0], parts[1], url)
    if host == "jobs.ashbyhq.com" and len(parts) >= 2:
        return from_ashby(parts[0], parts[1], url)
    if host.endswith("myworkdayjobs.com") and "/job/" in u.path:
        return from_workday(url)
    return from_page(url)

"""Job sources. Every source here is an official public API or a company's own public job board feed:
no logins, no scraping of sites whose terms forbid it (LinkedIn, Indeed, Glassdoor).

No key needed:  Remotive, RemoteOK, Himalayas, Jobicy (remote jobs), The Muse (city + remote),
                and company boards on Greenhouse, Lever, Ashby and Workday (data/companies.json).
                Workday is the careers site most banks and credit unions use.
Free key:       Adzuna (any US city with a radius; best for on-site and hybrid),
                USAJOBS (US federal government jobs).
"""
import concurrent.futures as cf
import datetime as dt
import html
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import UA, load_companies
from .locations import workplace
from .matching import title_score


def http_json(url, timeout=25, headers=None):
    h = {"User-Agent": UA, "Accept": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def strip_html(text):
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>|</div>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def parse_date(value):
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            v = value / 1000 if value > 1e11 else value
            return dt.datetime.fromtimestamp(v, dt.timezone.utc)
        s = str(value).strip().replace("Z", "+00:00")
        if re.fullmatch(r"\d+", s):
            return parse_date(int(s))
        d = dt.datetime.fromisoformat(s[:25]) if "T" in s else dt.datetime.fromisoformat(s[:10])
        return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
    except Exception:
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(str(value))
        except Exception:
            return None


def parse_salary(text):
    """(min, max) yearly USD from text like '$60k - $80k' or '$35/hr'. (None, None) if unclear."""
    if not text:
        return None, None
    t = str(text).lower().replace(",", "")
    if any(c in t for c in ("€", "£", "eur", "gbp", "inr", "₹", "cad", "aud")):
        return None, None
    nums = []
    for m in re.finditer(r"\$?\s?(\d+(?:\.\d+)?)\s*(k)?", t):
        n = float(m.group(1)) * (1000 if m.group(2) else 1)
        nums.append(n)
    nums = [n for n in nums if n >= 10]
    if not nums:
        return None, None
    hourly = bool(re.search(r"/\s*h(ou)?r|per hour|hourly|an hour", t))
    nums = [n * 2080 if (hourly or n < 300) else n for n in nums]
    nums = [n for n in nums if 15000 <= n <= 1500000]
    return (min(nums), max(nums)) if nums else (None, None)


def pay_line(desc):
    m = re.search(r"(?i)(salary|pay|compensation|base|range)[^\n]{0,120}\$\s?\d[\d,]*(?:\.\d+)?k?[^\n]{0,60}", desc or "")
    return m.group(0) if m else ""


def job(source, sid, title, company, location, url, apply_url, description, posted=None,
        salary=(None, None), workplace_hint=None):
    desc = description or ""
    return {
        "id": f"{source}:{sid}", "source": source, "title": html.unescape(title or "").strip(),
        "company": html.unescape(company or "").strip(), "location": (location or "").strip(),
        "url": url or apply_url or "", "apply_url": apply_url or url or "", "description": desc,
        "posted": posted.isoformat() if posted else None,
        "salary_min": salary[0] or None, "salary_max": salary[1] or None,
        "workplace": workplace(location, desc, workplace_hint),
    }


# --------------------------------------------------------------------------- remote-only boards

def src_remotive(q):
    out = []
    for kw in q["keywords"][:6]:
        data = http_json("https://remotive.com/api/remote-jobs?limit=100&search=" + urllib.parse.quote(kw))
        for j in data.get("jobs", []):
            out.append(job("remotive", j.get("id"), j.get("title"), j.get("company_name"),
                           j.get("candidate_required_location") or "Remote", j.get("url"), j.get("url"),
                           strip_html(j.get("description")), parse_date(j.get("publication_date")),
                           parse_salary(j.get("salary")), "remote"))
    return out


def src_remoteok(q):
    data = http_json("https://remoteok.com/api")
    out = []
    for j in data:
        if not isinstance(j, dict) or "position" not in j:
            continue           # the first element is RemoteOK's legal notice
        out.append(job("remoteok", j.get("id"), j.get("position"), j.get("company"),
                       j.get("location") or "Remote", j.get("url"), j.get("apply_url") or j.get("url"),
                       strip_html(j.get("description")) + "\nTags: " + ", ".join(j.get("tags") or []),
                       parse_date(j.get("epoch") or j.get("date")),
                       (j.get("salary_min"), j.get("salary_max")), "remote"))
    return out


def src_himalayas(q):
    out = []
    for offset in range(0, 300, 20):
        data = http_json(f"https://himalayas.app/jobs/api?limit=20&offset={offset}")
        jobs = data.get("jobs", [])
        if not jobs:
            break
        for j in jobs:
            loc = ", ".join(j.get("locationRestrictions") or []) or "Remote"
            out.append(job("himalayas", j.get("guid") or j.get("applicationLink"), j.get("title"),
                           j.get("companyName"), loc, j.get("applicationLink"), j.get("applicationLink"),
                           strip_html(j.get("description") or j.get("excerpt")), parse_date(j.get("pubDate")),
                           (j.get("minSalary"), j.get("maxSalary")), "remote"))
    return out


def src_jobicy(q):
    out = []
    geo = "&geo=usa" if q["country"].upper() == "US" else ""
    for kw in q["keywords"][:5]:
        data = http_json(f"https://jobicy.com/api/v2/remote-jobs?count=50{geo}&tag=" + urllib.parse.quote(kw))
        for j in data.get("jobs", []):
            out.append(job("jobicy", j.get("id"), j.get("jobTitle"), j.get("companyName"), j.get("jobGeo"),
                           j.get("url"), j.get("url"), strip_html(j.get("jobDescription")),
                           parse_date(j.get("pubDate")), (j.get("annualSalaryMin"), j.get("annualSalaryMax")),
                           "remote"))
    return out


# --------------------------------------------------------------------------- location-aware sources

def src_themuse(q):
    out = []
    locs = []
    if q["location"] and ({"hybrid", "onsite"} & set(q["workplace"])):
        locs.append(q["location"])
    if "remote" in q["workplace"]:
        locs.append("Flexible / Remote")
    key = f"&api_key={urllib.parse.quote(q['keys']['themuse_key'])}" if q["keys"].get("themuse_key") else ""
    for loc in locs:
        for page in range(0, 5):
            data = http_json(f"https://www.themuse.com/api/public/jobs?page={page}&descending=true"
                             f"&location={urllib.parse.quote(loc)}{key}")
            for j in data.get("results", []):
                jl = ", ".join(l.get("name", "") for l in j.get("locations") or [])
                hint = "remote" if loc.startswith("Flexible") and "remote" in jl.lower() else None
                url = (j.get("refs") or {}).get("landing_page")
                out.append(job("themuse", j.get("id"), j.get("name"), (j.get("company") or {}).get("name"), jl,
                               url, url, strip_html(j.get("contents")), parse_date(j.get("publication_date")),
                               (None, None), hint))
            if page + 1 >= (data.get("page_count") or 0):
                break
    return out


def src_adzuna(q):
    k = q["keys"]
    if not (k.get("adzuna_app_id") and k.get("adzuna_app_key")):
        return []
    country = {"US": "us", "GB": "gb", "CA": "ca", "AU": "au", "IN": "in", "DE": "de"}.get(q["country"].upper(), "us")
    out = []
    for kw in q["keywords"][:6]:
        params = {"app_id": k["adzuna_app_id"], "app_key": k["adzuna_app_key"], "results_per_page": 50,
                  "what": kw, "max_days_old": q["max_age_days"], "content-type": "application/json"}
        if q["location"] and ({"hybrid", "onsite"} & set(q["workplace"])):
            params["where"] = q["location"]
            params["distance"] = int(round(q["radius_miles"] * 1.609))
        elif "remote" in q["workplace"]:
            params["what"] = kw + " remote"
        data = http_json(f"https://api.adzuna.com/v1/api/jobs/{country}/search/1?" + urllib.parse.urlencode(params))
        for j in data.get("results", []):
            out.append(job("adzuna", j.get("id"), strip_html(j.get("title")),
                           (j.get("company") or {}).get("display_name"),
                           (j.get("location") or {}).get("display_name"), j.get("redirect_url"),
                           j.get("redirect_url"), strip_html(j.get("description")), parse_date(j.get("created")),
                           (j.get("salary_min"), j.get("salary_max"))))
    return out


def src_usajobs(q):
    k = q["keys"]
    if not (k.get("usajobs_email") and k.get("usajobs_key")):
        return []
    headers = {"Host": "data.usajobs.gov", "User-Agent": k["usajobs_email"], "Authorization-Key": k["usajobs_key"]}
    out = []
    for kw in q["keywords"][:4]:
        params = {"Keyword": kw, "ResultsPerPage": 100, "DatePosted": min(60, q["max_age_days"])}
        if q["location"] and ({"hybrid", "onsite"} & set(q["workplace"])) and "remote" not in q["workplace"]:
            params["LocationName"] = q["location"]
            params["Radius"] = q["radius_miles"]
        data = http_json("https://data.usajobs.gov/api/search?" + urllib.parse.urlencode(params), headers=headers)
        for item in (data.get("SearchResult") or {}).get("SearchResultItems", []):
            d = item.get("MatchedObjectDescriptor") or {}
            pay = (d.get("PositionRemuneration") or [{}])[0]
            lo, hi = pay.get("MinimumRange"), pay.get("MaximumRange")
            try:
                lo, hi = float(lo), float(hi)
                if pay.get("RateIntervalCode") == "PH":
                    lo, hi = lo * 2080, hi * 2080
            except (TypeError, ValueError):
                lo = hi = None
            details = ((d.get("UserArea") or {}).get("Details") or {})
            remote = str(details.get("RemoteIndicator", "")).lower() == "true"
            out.append(job("usajobs", d.get("PositionID") or d.get("PositionURI"), d.get("PositionTitle"),
                           d.get("OrganizationName"), d.get("PositionLocationDisplay"), d.get("PositionURI"),
                           (d.get("ApplyURI") or [d.get("PositionURI")])[0],
                           strip_html(details.get("JobSummary") or d.get("QualificationSummary")),
                           parse_date(d.get("PublicationStartDate")), (lo, hi), "remote" if remote else None))
    return out


# --------------------------------------------------------------------------- company job boards (ATS)

def src_greenhouse(board):
    data = http_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true")
    out = []
    for j in data.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        desc = strip_html(j.get("content"))
        apply = f"https://boards.greenhouse.io/{board}/jobs/{j.get('id')}"
        out.append(job("greenhouse", f"{board}-{j.get('id')}", j.get("title"),
                       j.get("company_name") or board.title(), loc, j.get("absolute_url") or apply, apply, desc,
                       parse_date(j.get("first_published") or j.get("updated_at")), parse_salary(pay_line(desc))))
    return out


def src_lever(company):
    data = http_json(f"https://api.lever.co/v0/postings/{company}?mode=json")
    out = []
    for j in data:
        cats = j.get("categories") or {}
        loc = cats.get("location") or ", ".join(cats.get("allLocations") or [])
        sr = j.get("salaryRange") or {}
        sal = (sr.get("min"), sr.get("max")) if sr.get("currency", "USD") == "USD" else (None, None)
        if sr.get("interval") == "per-hour-wage" and sal[0]:
            sal = (sal[0] * 2080, (sal[1] or sal[0]) * 2080)
        desc = (j.get("descriptionPlain") or "") + "\n" + "\n".join(
            strip_html(l.get("content", "")) for l in j.get("lists") or [])
        out.append(job("lever", j.get("id"), j.get("text"), company.title(), loc, j.get("hostedUrl"),
                       j.get("applyUrl") or (j.get("hostedUrl", "") + "/apply"), desc,
                       parse_date(j.get("createdAt")), sal, j.get("workplaceType")))
    return out


def src_ashby(board):
    data = http_json(f"https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true")
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
        hint = j.get("workplaceType") or ("remote" if j.get("isRemote") else None)
        locs = [j.get("location") or ""] + [(s.get("location") or "") for s in j.get("secondaryLocations") or []
                                            if isinstance(s, dict)]
        out.append(job("ashby", f"{board}-{j.get('id') or j.get('jobUrl')}", j.get("title"), board.title(),
                       ", ".join(l for l in locs if l), j.get("jobUrl"),
                       j.get("applyUrl") or (j.get("jobUrl", "") + "/application"),
                       j.get("descriptionPlain") or strip_html(j.get("descriptionHtml")),
                       parse_date(j.get("publishedAt")), parse_salary(comp), hint))
    return out


# --------------------------------------------------------------------------- Workday career sites
# Most banks and credit unions (and many banking-software companies) post jobs on Workday. Each entry in
# companies.json "workday" is {"name": "PNC", "url": "https://pnc.wd5.myworkdayjobs.com/External"}: the
# address of the company's careers page. The site's own search is used with your target titles, and only
# jobs whose title is close to one of them are kept, since a bank's board can hold thousands of jobs.

# Workday answers too many requests at once with HTTP 429, dropped connections and even failed name lookups,
# so only a few Workday sites are searched at the same time and each waits a moment between requests.
WORKDAY_AT_ONCE = threading.BoundedSemaphore(3)
WORKDAY_GAP = 0.8               # seconds between requests to the same Workday site


def _retryable(e):
    if isinstance(e, urllib.error.HTTPError):
        return e.code in (429, 502, 503, 504)
    return isinstance(e, (urllib.error.URLError, ConnectionError, TimeoutError))


def workday_request(url, payload=None, timeout=25, tries=4, sleep=time.sleep):
    """GET (or POST payload) JSON from a Workday site, waiting and trying again when it says it's busy."""
    for attempt in range(tries):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                     headers={"User-Agent": UA, "Accept": "application/json",
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            if not _retryable(e) or attempt == tries - 1:
                raise
            try:
                wait = int(getattr(e, "headers", None) and e.headers.get("Retry-After") or 0)
            except ValueError:
                wait = 0
            sleep(min(wait or 4 * (attempt + 1), 30))


def http_post_json(url, payload, timeout=25, tries=4, sleep=time.sleep):
    """POST JSON and read JSON back, with Workday's wait-and-retry."""
    return workday_request(url, payload, timeout, tries, sleep)


def workday_base(url):
    """The API address for a Workday careers page, plus the page's scheme://host/site prefix."""
    u = urllib.parse.urlsplit(url)
    tenant = u.netloc.split(".")[0]
    parts = [p for p in u.path.split("/") if p and not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", p)]
    if not parts:
        raise ValueError(f"No careers site name in {url}")
    return f"{u.scheme}://{u.netloc}/wday/cxs/{tenant}/{parts[0]}", f"{u.scheme}://{u.netloc}/{parts[0]}", tenant


def _workday_mode(remote_type, text):
    rt, low = (remote_type or "").lower(), (text or "").lower()
    # "Home Location-XX" is how several banks (PNC, U.S. Bank) label work-from-home roles.
    if "remote" in rt or "remote" in low or "virtual" in low or "home location" in low:
        return "remote"
    if "hybrid" in rt or "flex" in rt or "hybrid" in low:
        return "hybrid"
    return "onsite" if rt or low.strip() else None


def remote_or_several(place):
    """A Workday location that may be remote: 'Remote - US', 'Home Location-PA', or '3 Locations'."""
    low = (place or "").lower()
    return bool(re.search(r"remote|virtual|home location|\d+ locations", low))


def src_workday(entry, terms, targets, fetch=None, post=None, sleep=time.sleep, place_ok=None):
    """place_ok(location_text): False skips opening a posting that would be dropped anyway (for example
    on-site in another city when you only want remote jobs), which saves Workday requests."""
    fetch = fetch or (lambda url: workday_request(url, tries=2, sleep=sleep))
    post = post or (lambda url, payload: http_post_json(url, payload, sleep=sleep))
    base, site, tenant = workday_base(entry["url"])
    seen, out = set(), []
    details_blocked = False        # detail pages are rate-limited harder than search: stop after a refusal
    for term in terms:
        sleep(WORKDAY_GAP)
        data = post(base + "/jobs", {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": term})
        for p in data.get("jobPostings") or []:
            path = p.get("externalPath")
            if not path or path in seen or title_score(p.get("title") or "", targets)[0] < 20:
                continue
            seen.add(path)
            if place_ok and not place_ok(p.get("locationsText") or ""):
                continue
            info = {}
            if not details_blocked:
                sleep(WORKDAY_GAP)
                try:
                    info = fetch(base + path).get("jobPostingInfo") or {}
                except Exception:
                    details_blocked = True
            # When the detail page is refused, the job is still kept from the search result.
            title = info.get("title") or p.get("title")
            loc = ", ".join(x for x in [info.get("location") or p.get("locationsText") or ""]
                            + list(info.get("additionalLocations") or []) if x)
            mode = _workday_mode(info.get("remoteType") or p.get("remoteType"), f"{loc} {title}")
            desc = strip_html(info.get("jobDescription"))
            url = info.get("externalUrl") or site + path
            out.append(job("workday", f"{tenant}-{path.rsplit('_', 1)[-1]}", title, entry.get("name") or tenant.title(),
                           loc or ("Remote" if mode == "remote" else ""), url, url.rstrip("/") + "/apply", desc,
                           parse_date(info.get("startDate")), parse_salary(pay_line(desc)), mode))
    return out


# --------------------------------------------------------------------------- all together

def query_from_profile(profile):
    s = profile["search"]
    loc = s.get("location") or ", ".join(x for x in (profile.get("city"), profile.get("state")) if x)
    kws = [k for k in (s.get("keywords") or profile.get("target_titles") or []) if k.strip()]
    return {"keywords": kws, "location": loc, "workplace": s.get("workplace") or ["remote"],
            "country": s.get("remote_country") or "US", "radius_miles": int(s.get("radius_miles") or 30),
            "max_age_days": int(s.get("max_age_days") or 30), "keys": profile.get("api_keys") or {}}


def fetch_all(profile, log=print):
    q = query_from_profile(profile)
    comps = load_companies()
    tasks = []
    if "remote" in q["workplace"]:
        tasks += [("Remotive", src_remotive, q), ("RemoteOK", src_remoteok, q),
                  ("Himalayas", src_himalayas, q), ("Jobicy", src_jobicy, q)]
    tasks += [("The Muse", src_themuse, q)]
    if q["keys"].get("adzuna_app_id"):
        tasks.append(("Adzuna", src_adzuna, q))
    if q["keys"].get("usajobs_key"):
        tasks.append(("USAJOBS", src_usajobs, q))
    tasks += [(f"Greenhouse/{b}", src_greenhouse, b) for b in comps.get("greenhouse", [])]
    tasks += [(f"Lever/{c}", src_lever, c) for c in comps.get("lever", [])]
    tasks += [(f"Ashby/{b}", src_ashby, b) for b in comps.get("ashby", [])]
    targets = profile.get("target_titles") or q["keywords"]
    terms = profile.get("workday_search") or q["keywords"] or targets
    place_ok = remote_or_several if q["workplace"] == ["remote"] else None

    def workday(w):
        with WORKDAY_AT_ONCE:
            return src_workday(w, terms, targets, place_ok=place_ok)
    tasks += [(f"Workday/{w.get('name')}", workday, w)
              for w in comps.get("workday", []) if isinstance(w, dict) and w.get("url") and terms]
    results, failed, boards = [], [], 0
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(fn, arg): name for name, fn, arg in tasks}
        for f in cf.as_completed(futs):
            name = futs[f]
            try:
                got = f.result()
                results.extend(got)
                if "/" in name:
                    boards += 1
                else:
                    log(f"  {name}: {len(got)} listings")
            except Exception as e:
                failed.append(f"{name} ({type(e).__name__})")
    log(f"  Company job boards: {boards} checked")
    if failed:
        log(f"  {len(failed)} sources didn't answer (normal for boards that moved): "
            + ", ".join(sorted(failed)[:6]) + (" ..." if len(failed) > 6 else ""))
    return results

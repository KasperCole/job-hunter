"""The local job database (my-data/jobs.db) and the logic that turns fetched listings into saved matches."""
import datetime as dt
import json
import os
import re
import sqlite3

from . import config
from .matching import best_resume, gap_analysis, resume_low, score_job
from .resume import extract_text

STATUSES = ["new", "saved", "applied", "interview", "offer", "rejected", "ghosted", "skipped"]
# Columns added after the first release; db() adds them to older databases.
LATER_COLUMNS = {"applied_at": "TEXT", "interview_at": "TEXT", "followed_up_at": "TEXT", "closed_at": "TEXT"}

COLUMNS = """id TEXT PRIMARY KEY, source TEXT, title TEXT, company TEXT, location TEXT, workplace TEXT,
    url TEXT, apply_url TEXT, description TEXT, posted TEXT, salary_min REAL, salary_max REAL,
    score INTEGER, fit INTEGER, fit_label TEXT, matched TEXT, missing TEXT, flags TEXT, reasons TEXT,
    resume INTEGER DEFAULT 0, cover_letter TEXT, status TEXT DEFAULT 'new', first_seen TEXT, updated TEXT,
    notes TEXT"""


def db():
    con = sqlite3.connect(config.path("jobs.db"), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute(f"CREATE TABLE IF NOT EXISTS jobs ({COLUMNS})")
    have = {r[1] for r in con.execute("PRAGMA table_info(jobs)")}
    for col, typ in LATER_COLUMNS.items():
        if col not in have:
            con.execute(f"ALTER TABLE jobs ADD COLUMN {col} {typ}")
    return con


def set_status(con, job_id, status, now=None):
    """Change a job's status and remember when it was applied to, interviewed or closed."""
    now = now or dt.datetime.now(dt.timezone.utc).isoformat()
    con.execute("UPDATE jobs SET status=?, updated=? WHERE id=?", (status, now, job_id))
    if status == "applied":
        con.execute("UPDATE jobs SET applied_at=COALESCE(applied_at, ?) WHERE id=?", (now, job_id))
    elif status == "interview":
        con.execute("UPDATE jobs SET applied_at=COALESCE(applied_at, ?), interview_at=COALESCE(interview_at, ?) "
                    "WHERE id=?", (now, now, job_id))
    elif status == "offer":
        con.execute("UPDATE jobs SET applied_at=COALESCE(applied_at, ?), closed_at=? WHERE id=?", (now, now, job_id))
    elif status in ("rejected", "ghosted"):
        con.execute("UPDATE jobs SET closed_at=? WHERE id=?", (now, job_id))
    elif status in ("new", "saved"):
        con.execute("UPDATE jobs SET applied_at=NULL, interview_at=NULL, followed_up_at=NULL, closed_at=NULL "
                    "WHERE id=?", (job_id,))
    con.commit()


def resume_texts(profile):
    """[(label, text)] for every resume in the profile."""
    out = []
    for r in profile.get("resumes") or []:
        p = config.path(r["file"])
        try:
            out.append((r.get("label") or os.path.basename(p), extract_text(p)))
        except Exception:
            out.append((r.get("label") or os.path.basename(p), ""))
    return out


def dedupe_key(company, title):
    n = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
    return n(company) + "|" + n(title)


def analyze(j, profile, resumes, rlow):
    """Scores for one job, or None if it doesn't fit."""
    res = score_job(j, profile, rlow)
    if not res:
        return None
    score, reasons = res
    ridx = best_resume(j.get("description"), resumes)
    r_low = resume_low(profile, [resumes[ridx][1]]) if resumes else rlow
    g = gap_analysis(j.get("description"), r_low, profile.get("skills") or [],
                     int(profile.get("years_experience") or 0))
    return score, reasons, ridx, g


def save_matches(jobs, profile):
    resumes = resume_texts(profile)
    rlow = resume_low(profile, [t for _, t in resumes])
    s = profile["search"]
    threshold = int(s.get("min_match") or 40)
    max_age = int(s.get("max_age_days") or 30)
    con = db()
    seen = {dedupe_key(r["company"], r["title"]) for r in con.execute("SELECT company, title FROM jobs")}
    now = dt.datetime.now(dt.timezone.utc)
    added = 0
    for j in jobs:
        if j.get("posted"):
            try:
                if (now - dt.datetime.fromisoformat(j["posted"])).days > max_age:
                    continue
            except (ValueError, TypeError):
                pass
        k = dedupe_key(j["company"], j["title"])
        if k in seen:
            continue
        a = analyze(j, profile, resumes, rlow)
        if not a or a[0] < threshold:
            continue
        seen.add(k)
        score, reasons, ridx, g = a
        con.execute("""INSERT OR IGNORE INTO jobs (id, source, title, company, location, workplace, url, apply_url,
            description, posted, salary_min, salary_max, score, fit, fit_label, matched, missing, flags, reasons,
            resume, status, first_seen, updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'new',?,?)""",
                    (j["id"], j["source"], j["title"], j["company"], j["location"], j["workplace"], j["url"],
                     j["apply_url"], j["description"], j["posted"], j["salary_min"], j["salary_max"], score,
                     g["fit"], g["label"], json.dumps(g["matched"]), json.dumps(g["missing"]),
                     json.dumps(g["flags"]), "; ".join(reasons), ridx, now.isoformat(), now.isoformat()))
        added += 1
    con.commit()
    return added


def rescore(profile):
    """Re-check unreviewed jobs after you change your profile; drop the ones that no longer fit."""
    resumes = resume_texts(profile)
    rlow = resume_low(profile, [t for _, t in resumes])
    threshold = int(profile["search"].get("min_match") or 40)
    con = db()
    dropped = 0
    for r in con.execute("SELECT * FROM jobs WHERE status='new'").fetchall():
        a = analyze(dict(r), profile, resumes, rlow)
        if not a or a[0] < threshold:
            con.execute("DELETE FROM jobs WHERE id=?", (r["id"],))
            dropped += 1
            continue
        score, reasons, ridx, g = a
        con.execute("UPDATE jobs SET score=?, reasons=?, resume=?, fit=?, fit_label=?, matched=?, missing=?, "
                    "flags=? WHERE id=?", (score, "; ".join(reasons), ridx, g["fit"], g["label"],
                                           json.dumps(g["matched"]), json.dumps(g["missing"]),
                                           json.dumps(g["flags"]), r["id"]))
    con.commit()
    return dropped


def add_manual(profile, url, title, company, location="", description="", salary=(None, None), hint=None,
               apply_url=""):
    """A job you found yourself. It's always kept, whatever its score."""
    from .linkinfo import clean_url
    from .sources import job
    url = clean_url(url)
    j = job("manual", re.sub(r"[^a-z0-9]+", "-", (company + "-" + title).lower())[:80], title, company,
            location or "", url, apply_url or url, description, None, salary, hint)
    resumes = resume_texts(profile)
    rlow = resume_low(profile, [t for _, t in resumes])
    ridx = best_resume(description, resumes)
    g = gap_analysis(description, rlow, profile.get("skills") or [], int(profile.get("years_experience") or 0))
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    con = db()
    con.execute("""INSERT OR REPLACE INTO jobs (id, source, title, company, location, workplace, url, apply_url,
        description, salary_min, salary_max, score, fit, fit_label, matched, missing, flags, reasons, resume, status,
        first_seen, updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'new',?,?)""",
                (j["id"], "manual", title, company, location, j["workplace"], url, j["apply_url"], description,
                 j["salary_min"], j["salary_max"], 100, g["fit"],
                 g["label"], json.dumps(g["matched"]), json.dumps(g["missing"]), json.dumps(g["flags"]),
                 "added by you", ridx, now, now))
    con.commit()
    return j["id"]


def salary_str(r):
    a, b = r["salary_min"], r["salary_max"]
    if a and b and a != b:
        return f"${int(a):,} - ${int(b):,}"
    if a or b:
        return f"${int(a or b):,}"
    return ""

"""Two scores for every job:

Match (0-100): how well the job fits what you're looking for: title, skills, pay, location, level.
Fit   (0-100): the share of the skills the listing asks for that are on your resume. The skills it
               asks for that you don't show are listed as "missing skills".
"""
import re

from . import skills as sk
from .locations import is_local, remote_ok_for

STOP = {"and", "of", "the", "for", "in", "to", "a", "an", "&", "/", "-", "with", "at", "on"}
GENERIC = {"manager", "specialist", "analyst", "associate", "coordinator", "engineer", "representative",
           "assistant", "consultant", "officer", "lead", "director", "administrator", "technician",
           "senior", "sr", "junior", "jr", "staff", "principal", "ii", "iii", "i", "head", "team", "remote",
           "hybrid", "contract", "part-time", "full-time", "temporary", "level", "entry"}
SENIOR_RE = re.compile(r"\b(senior|sr\.?|lead|principal|staff|head of|director|vp|vice president|chief)\b", re.I)
JUNIOR_RE = re.compile(r"\b(junior|jr\.?|entry[- ]level|intern|internship|trainee|apprentice)\b", re.I)
YEARS_RE = re.compile(r"(\d{1,2})\+?\s*(?:-\s*\d{1,2}\s*)?years?(?:\s+of)?(?:\s+[\w/-]+){0,4}\s+experience", re.I)
DEGREE_RE = re.compile(r"\b(bachelor'?s?|master'?s?|ph\.?d|degree)\b[^.\n]{0,80}\brequired\b|\brequired\b[^.\n]{0,40}"
                       r"\b(bachelor'?s?|master'?s?|ph\.?d)\b", re.I)


def tokens(text):
    return [w for w in re.findall(r"[a-z0-9+#.]+", (text or "").lower().replace("/", " ")) if w not in STOP]


def title_score(job_title, targets):
    """0-50: how close the job title is to one of your target titles."""
    jt = " ".join(tokens(job_title))
    jset = set(jt.split())
    best, best_t = 0, ""
    for t in targets:
        tt = [w for w in tokens(t) if w not in ("senior", "sr", "junior", "jr", "i", "ii", "iii")]
        if not tt:
            continue
        phrase = " ".join(tt)
        if re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", jt):
            s = 50
        else:
            shared = set(tt) & jset
            domain = [w for w in shared if w not in GENERIC]
            if not domain:
                continue
            s = round(42 * len(shared) / len(set(tt)))
            if tt[-1] in jset:           # same kind of role (specialist, nurse, accountant...)
                s += 6
        if s > best:
            best, best_t = s, t
    return min(50, best), best_t


def resume_low(profile, resume_texts):
    return (" ".join(resume_texts) + " " + " ".join(profile.get("skills") or [])).lower()


def score_job(j, profile, rlow):
    """Return (match 0-100, reasons) or None when the job doesn't fit your filters."""
    s = profile["search"]
    title = j["title"]
    text = (title + "\n" + (j.get("description") or "")).lower()
    for w in s.get("exclude_words") or []:
        if w.strip() and re.search(r"(?<![a-z0-9])" + re.escape(w.strip().lower()) + r"(?![a-z0-9])", title.lower()):
            return None
    # where the job is
    wp = j.get("workplace") or "onsite"
    allowed = s.get("workplace") or ["remote"]
    if wp not in allowed:
        return None
    reasons = []
    loc_pts = 0
    if wp == "remote":
        if not remote_ok_for(j.get("location"), s.get("remote_country") or "US"):
            return None
        reasons.append("remote")
    else:
        city = (s.get("location") or profile.get("city") or "").split(",")[0]
        state = profile.get("state") or (s.get("location", "").split(",")[1].strip() if "," in s.get("location", "") else "")
        if not is_local(j.get("location"), city, state):
            return None
        loc_pts = 5
        reasons.append(f"{wp} near you")
    # title
    targets = list(dict.fromkeys((profile.get("target_titles") or []) + (s.get("keywords") or [])))
    tpts, tmatch = title_score(title, targets)
    if tpts < 15:
        return None
    reasons.append(f"title fits '{tmatch}'")
    # skills
    hits = [k for k in profile.get("skills") or [] if sk.has_term(k, text)]
    skill_pts = min(30, 3 * len(hits))
    if j.get("source") == "workday" and not (j.get("description") or "").strip():
        # The site wouldn't show the full posting, so skills can't be counted. Give the points a posting
        # usually earns instead of zero, so a strong title match still shows up.
        skill_pts = 9
        reasons.append("full posting not loaded; open the listing to check skills")
    if hits:
        reasons.append("skills: " + ", ".join(sk.display(h) for h in hits[:8]))
    score = tpts + skill_pts + loc_pts
    # level
    yrs = int(profile.get("years_experience") or 0)
    if SENIOR_RE.search(title):
        if yrs and yrs < 4:
            score -= 15
        elif yrs >= 7:
            score += 5
    if JUNIOR_RE.search(title) and yrs >= 8:
        score -= 5
    asked = [int(m.group(1)) for m in YEARS_RE.finditer(j.get("description") or "") if int(m.group(1)) <= 20]
    if asked and yrs and min(asked) > yrs + 2:
        score -= 10
        reasons.append(f"asks for {min(asked)}+ years")
    # pay
    floor = float(s.get("min_salary") or 0)
    smin, smax = j.get("salary_min"), j.get("salary_max")
    if floor and smax and smax < floor:
        return None
    if smin and floor and smin >= floor:
        score += 10
        reasons.append(f"pay ${int(smin):,}+")
    elif smax and (not floor or smax >= floor):
        score += 5
        reasons.append(f"pay up to ${int(smax):,}")
    if j.get("source") in ("greenhouse", "lever", "ashby"):
        score += 5
        reasons.append("apply on company site")
    return max(0, min(100, score)), reasons


def gap_analysis(description, rlow, profile_skills=(), years=0):
    """Fit rating: which skills the listing asks for are on your resume, and which are missing."""
    asked = sk.find_terms(description or "", extra_terms=profile_skills)
    matched = [t for t in asked if sk.has_skill(t, rlow)]
    missing = [t for t in asked if t not in matched]
    flags = []
    yrs = [int(m.group(1)) for m in YEARS_RE.finditer(description or "") if int(m.group(1)) <= 20]
    if yrs and years and min(yrs) > years:
        flags.append(f"asks for {min(yrs)}+ years (you have {years})")
    if DEGREE_RE.search(description or ""):
        flags.append("lists a degree as required")
    coverage = len(matched) / len(asked) if asked else 0.5
    fit = max(0, min(100, round(100 * coverage) - 10 * len(flags)))
    label = "Strong" if fit >= 75 else "Good" if fit >= 55 else "Fair" if fit >= 35 else "Stretch"
    return {"fit": fit, "label": label, "matched": matched, "missing": missing, "flags": flags}


def best_resume(description, resumes):
    """Index of the resume (list of (label, text)) that covers the most skills this job asks for."""
    if len(resumes) <= 1:
        return 0
    asked = sk.find_terms(description or "")
    scores = [sum(1 for t in asked if sk.has_skill(t, txt.lower())) for _, txt in resumes]
    return max(range(len(resumes)), key=lambda i: scores[i])

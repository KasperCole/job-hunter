"""Where Job Hunter keeps its files, and the default settings for a new profile.

Everything personal (your resume, profile, job database, cover letters) lives in one data
folder, `my-data/` next to the app by default. That folder is listed in .gitignore, so it is
never committed or shared. Set JOBHUNTER_HOME (or pass --home) to keep it somewhere else,
for example one folder per person when several people share a computer.
"""
import json
import os

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(APP_DIR, "data")          # shipped defaults (company boards, skills)
UA = "JobHunter/2.0 (open-source personal job search tool)"

_home = None


def home():
    """The personal data folder. Created on first use."""
    global _home
    if _home is None:
        set_home(os.environ.get("JOBHUNTER_HOME") or os.path.join(APP_DIR, "my-data"))
    return _home


def set_home(path):
    global _home
    _home = os.path.abspath(os.path.expanduser(path))
    os.makedirs(os.path.join(_home, "resumes"), exist_ok=True)
    os.makedirs(os.path.join(_home, "letters"), exist_ok=True)


def path(*parts):
    return os.path.join(home(), *parts)


DEFAULT_PROFILE = {
    "first_name": "", "last_name": "", "email": "", "phone": "",
    "city": "", "state": "", "country": "United States", "postal_code": "",
    "linkedin": "", "github": "", "website": "", "current_company": "", "current_title": "",
    "years_experience": 0,
    "work_authorized": "",        # "yes" / "no" / "" (leave the question for you to answer)
    "needs_sponsorship": "",      # "yes" / "no" / ""
    "notice_period": "",
    "timezone": "",
    "resumes": [],                # [{"label": "...", "file": "resumes/x.docx"}]
    "target_titles": [],          # plain job titles, e.g. "IT Support Specialist"
    "skills": [],                 # skills found on (or added to) your resume
    "achievements": [],           # resume lines with numbers, used by template cover letters
    "show_tips": True,            # hover tips and page tours (the "Show tips" box at the top of the app)
    "tour_seen": [],              # pages whose tour you've finished or skipped
    "search": {
        "keywords": [],           # what to search job boards for (built from your titles)
        "workplace": ["remote", "hybrid", "onsite"],
        "location": "",           # e.g. "New York, NY" (used for hybrid and on-site jobs)
        "radius_miles": 30,       # used by Adzuna; other sources match your metro area
        "remote_country": "US",   # remote jobs must be open to people in this country
        "min_salary": 0,
        "exclude_words": ["intern", "internship"],
        "max_age_days": 30,
        "min_match": 40,
    },
    "api_keys": {                 # optional extra job sources (free keys)
        "adzuna_app_id": "", "adzuna_app_key": "",
        "usajobs_email": "", "usajobs_key": "",
        "themuse_key": "",
    },
}


def _merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            out[k] = _merge(base[k], v)
        else:
            out[k] = v
    return out


def load_profile():
    p = path("profile.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return _merge(DEFAULT_PROFILE, json.load(f))


def save_profile(profile):
    with open(path("profile.json"), "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)


def load_companies():
    """Company job boards to check: the shipped list plus my-data/companies.json if present."""
    with open(os.path.join(DATA_DIR, "companies.json"), encoding="utf-8") as f:
        comps = json.load(f)
    extra = path("companies.json")
    if os.path.exists(extra):
        with open(extra, encoding="utf-8") as f:
            for k, v in json.load(f).items():
                if isinstance(v, list) and k == "workday":
                    known = {w.get("url") for w in comps.get(k, []) if isinstance(w, dict)}
                    comps[k] = comps.get(k, []) + [w for w in v if isinstance(w, dict) and w.get("url") not in known]
                elif isinstance(v, list):
                    comps[k] = sorted(set(comps.get(k, [])) | set(v))
    return comps

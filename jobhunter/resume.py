"""Read a resume (.docx, .pdf, .txt, .md) and pull out what the job search needs:
contact details, location, recent job titles, years of experience, skills and achievements.

The parser is rule-based so it works offline and costs nothing. It won't be perfect for every
layout, which is why the setup page shows everything it found and lets you correct it.
"""
import datetime as dt
import html
import os
import re
import zipfile

from . import skills as sk

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}

# Words that make a phrase look like a job title.
TITLE_NOUNS = (
    "engineer|developer|programmer|architect|administrator|admin|analyst|specialist|technician|consultant|"
    "manager|director|coordinator|representative|rep|associate|assistant|officer|lead|supervisor|"
    "designer|writer|editor|scientist|researcher|accountant|bookkeeper|auditor|controller|clerk|"
    "nurse|therapist|technologist|pharmacist|physician|medical assistant|teacher|tutor|instructor|"
    "trainer|recruiter|generalist|advisor|adviser|agent|cashier|driver|operator|mechanic|electrician|"
    "installer|planner|strategist|marketer|producer|owner|founder|president|intern|paralegal|"
    "attorney|counselor|coach|librarian|dispatcher|receptionist|secretary|scheduler|buyer|"
    "superintendent|foreman|chef|cook|server|bartender|barista|guard|inspector|estimator|"
    "head of [a-z ]+|vp of [a-z ]+|vice president"
)
TITLE_RE = re.compile(r"\b(" + TITLE_NOUNS + r")s?\b", re.I)
SENIORITY = re.compile(r"\b(senior|sr\.?|junior|jr\.?|lead|principal|staff|chief|head|entry[- ]level|"
                       r"i{1,3}|iv|[123])\b\.?", re.I)
MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
DATE = rf"(?:(?:{MONTHS})[a-z]*\.?\s+\d{{4}}|\d{{1,2}}/\d{{4}}|\d{{4}})"
RANGE_RE = re.compile(rf"({DATE})\s*(?:-|–|—|to|until)\s*({DATE}|present|current|now|today)", re.I)
HEADINGS = re.compile(r"^\s*(professional\s+)?(summary|profile|objective|experience|work experience|employment|"
                      r"employment history|work history|education|skills|technical skills|core skills|"
                      r"key skills|core competencies|competencies|certifications?|licenses|projects|awards|"
                      r"volunteer|languages|tools|technologies|interests|references)\s*:?\s*$", re.I)
SKILL_HEADINGS = re.compile(r"^\s*(technical\s+|core\s+|key\s+)?(skills|competencies|core competencies|tools|"
                            r"technologies|tools & technologies|certifications?|languages)\b", re.I)


# --------------------------------------------------------------------------- text extraction

def extract_text(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".docx":
        return docx_text(file_path)
    if ext == ".pdf":
        return pdf_text(file_path)
    with open(file_path, encoding="utf-8", errors="replace") as f:
        return f.read()


def docx_text(file_path):
    try:
        with zipfile.ZipFile(file_path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
    except Exception:
        return ""
    xml = re.sub(r"<w:tab/>", "\t", xml)
    xml = re.sub(r"<w:br[^>]*/>", "\n", xml)
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"</w:tc>", " | ", xml)
    text = html.unescape(re.sub(r"<[^>]+>", "", xml))
    return re.sub(r"[ \t]+\n", "\n", text).strip()


def pdf_text(file_path):
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError("Reading PDF resumes needs the pypdf package: pip install pypdf "
                           "(or upload a .docx or .txt copy of your resume).")
    reader = PdfReader(file_path)
    return "\n".join((p.extract_text() or "") for p in reader.pages).strip()


# --------------------------------------------------------------------------- field parsing

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b|\+\d{1,3}[\s.-]?\d[\d\s.-]{6,14}\d")
URL_RE = re.compile(r"(?:https?://)?(?:www\.)?([a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s|,;)]*)?", re.I)
CITY_STATE_RE = re.compile(r"\b([A-Z][a-zA-Z.'-]+(?:\s+[A-Z][a-zA-Z.'-]+){0,3}),\s*(" + "|".join(US_STATES) +
                           r")\b(?:\s+(\d{5}))?")


def _lines(text):
    return [l.strip(" \t•·▪◦●-–—*|") for l in text.splitlines() if l.strip(" \t•·▪◦●-–—*|")]


def parse_name(lines):
    for l in lines[:8]:
        clean = re.sub(r"\s+", " ", l).strip()
        if EMAIL_RE.search(clean) or re.search(r"\d", clean) or HEADINGS.match(clean):
            continue
        clean = re.split(r"\s[|•·,]\s|\t", clean)[0].strip()
        words = clean.split()
        if 2 <= len(words) <= 4 and all(re.fullmatch(r"[A-Za-z][A-Za-z.'-]*", w) for w in words) \
                and clean.lower() not in ("curriculum vitae", "resume") and not TITLE_RE.search(clean):
            if clean.isupper():
                clean = clean.title()
            return words[0].title() if words[0].isupper() else words[0], " ".join(clean.split()[1:])
    return "", ""


def parse_links(text):
    linkedin = github = website = ""
    for m in URL_RE.finditer(text):
        u = m.group(0).rstrip(".")
        if "@" in text[max(0, m.start() - 1):m.start()] or "." not in u:
            continue
        low = u.lower()
        full = u if low.startswith("http") else "https://" + u
        if "linkedin.com" in low and not linkedin:
            linkedin = full
        elif "github.com" in low and not github:
            github = full
        elif not website and not re.search(r"(linkedin|github|gmail|yahoo|outlook|hotmail|icloud)\.", low) \
                and re.search(r"\.(com|io|dev|me|net|org|co|site|design|ai|app|art|studio|portfolio)\b", low) and len(low) > 6:
            website = full
    return linkedin, github, website


def parse_location(lines):
    for l in lines[:12]:
        m = CITY_STATE_RE.search(l)
        if m:
            city = re.sub(r"^.*[|•·]\s*", "", m.group(1)).strip()
            return city, m.group(2), m.group(3) or ""
    return "", "", ""


def _to_date(s, end=False):
    s = s.strip().lower()
    today = dt.date.today()
    if s in ("present", "current", "now", "today"):
        return today
    m = re.match(rf"({MONTHS})[a-z]*\.?\s+(\d{{4}})", s)
    if m:
        mon = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
        return dt.date(int(m.group(2)), mon.index(m.group(1)[:3]) + 1, 1)
    m = re.match(r"(\d{1,2})/(\d{4})", s)
    if m:
        return dt.date(int(m.group(2)), max(1, min(12, int(m.group(1)))), 1)
    m = re.match(r"(\d{4})", s)
    if m:
        return dt.date(int(m.group(1)), 12 if end else 1, 1)
    return None


def parse_years(text):
    """Years of experience: the stated '10+ years' if there is one, else the span of work dates
    (overlapping jobs are merged, education dates are skipped)."""
    stated = [int(m.group(1)) for m in re.finditer(r"(\d{1,2})\+?\s*years?(?:\s+of)?\s+(?:\w+\s+){0,3}experience",
                                                   text, re.I) if int(m.group(1)) <= 50]
    edu = re.search(r"(?im)^\s*education\s*:?\s*$", text)
    work_text = text[:edu.start()] + text[edu.end() + 600:] if edu else text
    spans = []
    for m in RANGE_RE.finditer(work_text):
        a, b = _to_date(m.group(1)), _to_date(m.group(2), end=True)
        if a and b and a <= b and a.year > 1960:
            spans.append((a, b))
    spans.sort()
    total_days, cur = 0, None
    for a, b in spans:
        if cur and a <= cur[1]:
            cur = (cur[0], max(cur[1], b))
        else:
            if cur:
                total_days += (cur[1] - cur[0]).days
            cur = (a, b)
    if cur:
        total_days += (cur[1] - cur[0]).days
    from_dates = round(total_days / 365.25)
    return max([from_dates] + stated) if (stated or from_dates) else 0


def clean_title(t):
    t = re.sub(r"\s+", " ", t).strip(" ,.;:-–—|")
    t = re.sub(r"\(.*?\)", "", t).strip()
    return t


def parse_titles(lines):
    """Job titles in the order they appear (most recent first on most resumes)."""
    titles = []
    for l in lines:
        if len(l) > 120 or HEADINGS.match(l) or EMAIL_RE.search(l):
            continue
        if re.match(r"(?i)^(responsible|managed|led|built|created|developed|worked|handled|provided|"
                    r"supported|trained|improved|reduced|increased)\b", l):
            continue
        for seg in re.split(r"\s+[|•·@]\s+|\s+[-–—]\s+|,\s+(?=[A-Z])|\t|\s+at\s+", l):
            seg = clean_title(RANGE_RE.sub("", seg))
            words = seg.split()
            if not (1 <= len(words) <= 7) or not TITLE_RE.search(seg) or re.search(r"\d{3,}", seg):
                continue
            if seg[0].islower() or seg.endswith("."):
                continue
            if seg.lower() not in [t.lower() for t in titles]:
                titles.append(seg)
    return titles[:8]


def core_title(t):
    """A title without seniority words: 'Senior IT Support Specialist II' -> 'IT Support Specialist'."""
    return re.sub(r"\s+", " ", SENIORITY.sub(" ", t)).strip(" ,-/") or t


def parse_skill_section(lines):
    """Items listed under a Skills / Tools / Certifications heading."""
    out, on = [], False
    for l in lines:
        if SKILL_HEADINGS.match(l):
            on = True
            rest = re.sub(SKILL_HEADINGS, "", l).strip(" :")
            if rest:
                l = rest
            else:
                continue
        elif on and HEADINGS.match(l):
            on = False
        if not on:
            continue
        body = l.split(":", 1)[1] if re.match(r"^[A-Za-z &/]{2,30}:", l) else l
        for item in re.split(r"[,;|•·/]|\s{2,}|\t", body):
            item = item.strip(" .()")
            if 2 <= len(item) <= 40 and len(item.split()) <= 4 and not re.search(r"\d{4}", item):
                out.append(item)
    return list(dict.fromkeys(out))


def parse_achievements(lines):
    """Bullet-style lines with a number in them ('cut response times by 50%')."""
    out = []
    for l in lines:
        if 40 <= len(l) <= 300 and re.search(r"\d+%|\$\s?\d|\b\d[\d,]*\+?\s+(?:[a-z]+\s+){0,2}"
                                              r"(?:customers|clients|users|tickets|employees|staff|people|"
                                              r"projects|accounts|sites|students|patients|stores|calls)", l, re.I) \
                and not RANGE_RE.search(l):
            out.append(l.rstrip("."))
    return out[:12]


def parse_resume(text):
    """Return a dict of everything found. Keys match the profile."""
    lines = _lines(text)
    first, last = parse_name(lines)
    emails = EMAIL_RE.findall(text)
    phone = PHONE_RE.search(text)
    linkedin, github, website = parse_links(text)
    city, state, zipc = parse_location(lines)
    titles = parse_titles(lines)
    section_skills = parse_skill_section(lines)
    vocab_skills = sk.find_terms(text)
    extra = []
    for item in section_skills:
        rest = item.lower()
        for t in sk.find_terms(item):
            rest = rest.replace(t, " ")
        if re.sub(r"[\s,&/+.-]|\band\b", "", rest):      # something the vocabulary didn't already cover
            extra.append(item.lower())
    skills = list(dict.fromkeys(vocab_skills + [s for s in extra if s not in vocab_skills]))
    cores = list(dict.fromkeys(core_title(t) for t in titles))
    return {
        "first_name": first, "last_name": last,
        "email": emails[0] if emails else "",
        "phone": phone.group(0).strip() if phone else "",
        "linkedin": linkedin, "github": github, "website": website,
        "city": city, "state": state, "postal_code": zipc,
        "current_title": titles[0] if titles else "",
        "years_experience": parse_years(text),
        "titles_found": titles,
        "target_titles": cores[:5],
        "skills": skills[:60],
        "achievements": parse_achievements(lines),
        "search_keywords": cores[:5],
    }

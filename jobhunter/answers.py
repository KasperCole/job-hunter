"""Your answer bank: the custom questions application forms ask, how often they come up, and your answers.

How it works:
- Each time pre-fill opens an application, it notes every question it couldn't fill from your profile,
  so the Answers page can list the questions you see most often, with a box to answer each one.
- While the form is open, it also watches what you type into those questions. When you close the
  window, those answers are saved to my-data/answers.json.
- Next time a form asks the same question, worded the same or close to it, pre-fill fills in your
  answer. Common questions are grouped by topic, so "Why do you want to work at Acme?" and "What
  interests you about joining Globex?" share one answer.
- Answers can use {company} and {title}, which are replaced with the company and job title of each
  application. "I'd like to join {company} as a {title} because..." works for every job.
- An answer you typed that names the company (for example "...at Acme") is saved with {company} in
  its place but marked "check before reuse", and isn't filled in again until you approve it on the
  Answers page. That way a company-specific answer never lands on another company's form unchecked.

You always see the filled-in form and click Submit yourself.
"""
import datetime as dt
import json
import os
import re

from . import config

FILE = "answers.json"
MAX_LEN = 4000
# Never save these: they're files, or too personal to keep in a file.
SKIP_LABEL = re.compile(r"password|social security|\bssn\b|date of birth|\bdob\b|credit card|bank account|"
                        r"captcha|resume|\bcv\b|cover letter", re.I)
FILLER = {"please", "the", "a", "an", "your", "you", "do", "are", "is", "what", "of", "to", "in", "for", "and",
          "required", "optional", "select", "enter", "answer", "this", "our", "us", "we"}

# Common questions, grouped by topic. (key, how the Answers page shows it, pattern)
TOPICS = [
    ("why_company", "Why do you want to work at {company}?",
     r"why (do|would) you (want|like|wish) to (work|join|be)|why (are you|you are) (interested|applying|excited)|"
     r"why (this|our) (company|team|organi[sz]ation)|why \{company\}|what (excites|interests|attracts|draws) you "
     r"(most )?(about|to)|interest(ed|s)? you (in|about) (this|our|the) (company|role|position|opportunity)|"
     r"why (did you|are you) apply"),
    ("good_fit", "What makes you a good fit for this role?",
     r"(what makes|why are|why would) you (be )?(a |an )?(good|great|strong|ideal|excellent|right) "
     r"(fit|candidate|match)|why should we hire|what (would|will|can) you bring"),
    ("about_you", "Tell us about yourself.",
     r"tell us (a (little|bit) )?about (yourself|you)\b|introduce yourself|describe yourself"),
    ("relocate", "Are you willing to relocate?", r"(willing|able|open) to relocate|relocation"),
    ("commute", "Can you work on-site or commute to the office?",
     r"(able|willing|open) to (work|commute|come)[^?]{0,30}(on-?site|office|in person|hybrid)|reliably commute"),
    ("background_check", "Will you consent to a background check?", r"background (check|screen)|drug (test|screen)"),
    ("age_18", "Are you at least 18 years old?", r"\b(18|eighteen)\b.{0,15}(years|older|age)"),
    ("worked_here", "Have you worked for {company} before?",
     r"(previously|ever|currently) (worked|been employed|employed|applied)\b.{0,25}(here|us|this company|\{company\})|"
     r"former employee"),
    ("non_compete", "Are you bound by a non-compete agreement?", r"non-?compete|restrictive covenant"),
    ("referral_name", "Were you referred by someone? Who?", r"referr(ed|al)\b.{0,30}(name|who|employee)|who referred"),
    ("gender", "Gender (voluntary)", r"^gender\b|gender identity|what is your gender|^sex\b"),
    ("race", "Race / ethnicity (voluntary)", r"\brace\b|ethnicit|hispanic|latino"),
    ("veteran", "Veteran status (voluntary)", r"veteran"),
    ("disability", "Disability status (voluntary)", r"disabilit"),
    ("pronouns", "Pronouns", r"pronoun"),
]
_TOPIC_RE = [(k, q, re.compile(p, re.I)) for k, q, p in TOPICS]
TOPIC_QUESTION = {k: q for k, q, _ in TOPICS}


def _company_re(company):
    c = re.sub(r"\s+", " ", (company or "").strip())
    if len(c) < 3:
        return None
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(c) + r"(?![A-Za-z0-9])", re.I)


def generalize(text, company="", title=""):
    """Swap the company name and job title for {company} and {title}."""
    out = text or ""
    cre = _company_re(company)
    if cre:
        out = cre.sub("{company}", out)
    if title and len(title) >= 4:
        out = re.sub(r"(?<![A-Za-z0-9])" + re.escape(title.strip()) + r"(?![A-Za-z0-9])", "{title}", out, flags=re.I)
    return out


def fill_in(answer, company="", title=""):
    return (answer or "").replace("{company}", company or "the company").replace("{title}", title or "this role")


def norm_label(label, company=""):
    """'Why Acme? *' -> 'why {company}'."""
    t = generalize(label or "", company).lower()
    t = re.sub(r"\((required|optional)\)|\*", " ", t)
    t = re.sub(r"[^a-z0-9+#{}]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()[:200]


def topic_of(label, company=""):
    n = norm_label(label, company)
    for key, _, rx in _TOPIC_RE:
        if rx.search(n):
            return key
    return None


def key_for(label, company=""):
    return topic_of(label, company) or norm_label(label, company)


def _words(n):
    return {w for w in n.split() if w not in FILLER}


def load():
    try:
        with open(config.path(FILE), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(bank):
    tmp = config.path(FILE + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(bank, f, indent=2, ensure_ascii=False)
    os.replace(tmp, config.path(FILE))


def usable_label(label):
    n = norm_label(label)
    return bool(n and len(n) >= 3 and not SKIP_LABEL.search(label or ""))


def _entry(bank, label, company=""):
    key = key_for(label, company)
    e = bank.get(key)
    if e is None:
        e = bank[key] = {"question": TOPIC_QUESTION.get(key) or generalize(re.sub(r"\s+", " ", label).strip(),
                                                                            company)[:300],
                         "topic": key in TOPIC_QUESTION, "answer": "", "needs_review": False,
                         "seen": 0, "uses": 0, "variants": [], "updated": ""}
    v = generalize(re.sub(r"\s+", " ", label).strip(), company)[:300]
    if v and v not in e["variants"] and v != e["question"]:
        e["variants"] = (e["variants"] + [v])[-8:]
    return key, e


def note_seen(bank, labels, job_id, company=""):
    """Count each question once per job, so the Answers page can show the most common ones."""
    changed = False
    for label in labels:
        if not usable_label(label):
            continue
        _, e = _entry(bank, label, company)
        if e.get("last_job") != job_id:
            e["seen"] = e.get("seen", 0) + 1
            e["last_job"] = job_id
            changed = True
    return changed


def learn(bank, label, value, company="", title=""):
    """Remember an answer you typed. Returns True if the bank changed."""
    value = (value or "").strip()
    if not usable_label(label) or not value or len(value) > MAX_LEN:
        return False
    key, e = _entry(bank, label, company)
    general = generalize(value, company, title)
    if e.get("answer") and fill_in(e["answer"], company, title) == value:
        return False
    e["answer"] = general
    e["needs_review"] = general != value and "{company}" in general
    e["updated"] = dt.date.today().isoformat()
    return True


def set_answer(bank, key, answer, approved=True):
    e = bank.get(key)
    if e is None:
        return False
    e["answer"] = (answer or "").strip()[:MAX_LEN]
    e["needs_review"] = not approved
    e["updated"] = dt.date.today().isoformat()
    return True


def add_question(bank, question, answer=""):
    if not usable_label(question):
        return None
    key, e = _entry(bank, question)
    if answer:
        set_answer(bank, key, answer)
    return key


def find(bank, label, company="", title=""):
    """Your answer for this question, ready to type in, or "" if there isn't one you've approved."""
    if not usable_label(label):
        return ""
    key = key_for(label, company)
    e = bank.get(key)
    if not e or not e.get("answer"):
        words = _words(norm_label(label, company))
        if len(words) < 3:
            return ""
        best, best_sim = None, 0.0
        for k, other in bank.items():
            if not other.get("answer"):
                continue
            ow = _words(k if not other.get("topic") else norm_label(other["question"]))
            if not ow:
                continue
            sim = len(words & ow) / len(words | ow)
            if sim > best_sim:
                best, best_sim = other, sim
        if best_sim < 0.8:
            return ""
        e = best
    if e.get("needs_review"):
        return ""
    return fill_in(e["answer"], company, title)


def mark_used(bank, label, company=""):
    e = bank.get(key_for(label, company))
    if e:
        e["uses"] = e.get("uses", 0) + 1


def most_common(bank):
    """[(key, entry)], the questions you see most often first."""
    return sorted(bank.items(), key=lambda kv: (-kv[1].get("seen", 0), kv[1].get("question", "").lower()))

"""Cover letters. With an Anthropic API key, Claude writes each one from your resume and the job
description. Without one, a template fills in your own resume facts. Either way, only experience
that's on your resume is claimed, and you can edit every letter before it's used.
"""
import datetime as dt
import json
import os
import re

from . import skills as sk
from .store import db, resume_texts

MODEL = os.environ.get("JOBHUNTER_MODEL", "claude-opus-5-5")


def full_name(p):
    return " ".join(x for x in (p.get("first_name"), p.get("last_name")) if x).strip()


def claude_letter(row, profile, resume_text):
    try:
        import anthropic
    except ImportError:
        return None
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return None          # no key set: use the free template instead
    client = anthropic.Anthropic()
    prompt = (
        "Write a cover letter for this job application.\n\n"
        f"<resume>\n{resume_text}\n</resume>\n\n"
        f"<job company=\"{row['company']}\" title=\"{row['title']}\">\n{row['description']}\n</job>\n\n"
        "Rules: 220 to 320 words, plain text, no placeholders or brackets. Open with the specific role. "
        "Pick the two or three resume achievements (with their numbers) that best fit this job's "
        "requirements and say why they matter for this team. Only claim experience the resume shows. "
        "Plain, confident, warm tone, no cliches like 'I am writing to express'. "
        f"Sign off with: {full_name(profile) or 'the applicant'}. Output only the letter."
    )
    try:
        resp = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.AuthenticationError:
        return None
    except anthropic.RateLimitError:
        print("    Claude rate limit reached; using the template letter instead.")
        return None
    except anthropic.APIStatusError as e:
        print(f"    Claude API error {e.status_code}; using the template letter instead.")
        return None
    except anthropic.APIConnectionError:
        print("    Couldn't reach the Claude API; using the template letter instead.")
        return None
    except anthropic.AnthropicError as e:
        print(f"    Claude letter failed ({type(e).__name__}); using the template letter instead.")
        return None
    if resp.stop_reason == "refusal":
        return None
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    return text or None


def _pick_achievements(profile, resume_text, job_text, n=2):
    """Resume lines with numbers, ranked by how many of the job's words they share."""
    cands = list(profile.get("achievements") or [])
    if not cands:
        from .resume import _lines, parse_achievements
        cands = parse_achievements(_lines(resume_text))
    jw = set(re.findall(r"[a-z]{4,}", job_text.lower()))
    ranked = sorted(cands, key=lambda a: -len(set(re.findall(r"[a-z]{4,}", a.lower())) & jw))
    return ranked[:n]


def _sentence(a):
    a = a.strip().rstrip(".")
    a = re.sub(r"^(?:[-•*]\s*)", "", a)
    first = a.split()[0].lower() if a.split() else ""
    if re.match(r"^[a-z]+ed$", first) or first in ("led", "built", "ran", "won", "cut", "grew", "made", "kept",
                                                   "taught", "drove", "brought"):
        return "I " + a[0].lower() + a[1:] + "."
    return a[0].upper() + a[1:] + "."


def template_letter(row, profile, resume_text):
    p = profile
    name = full_name(p)
    matched = json.loads(row["matched"] or "[]")
    rlow = resume_text.lower()
    skills = [sk.display(s) for s in matched if sk.has_skill(s, rlow)][:4]
    yrs = int(p.get("years_experience") or 0)
    role = p.get("current_title") or (p.get("target_titles") or ["this field"])[0]
    intro = f"I'm applying for the {row['title']} role at {row['company']}."
    if yrs >= 2:
        intro += f" I bring {yrs} years of experience, most recently as {_a(role)} {role}."
    elif role:
        intro += f" I'm currently working as {_a(role)} {role}."
    skill_line = ""
    if skills:
        listed = ", ".join(skills[:-1]) + (" and " if len(skills) > 1 else "") + skills[-1]
        skill_line = f" Your posting asks for {listed}, all of which I use in my work."
    wins = _pick_achievements(p, resume_text, row["description"] or "")
    middle = (" ".join(_sentence(w) for w in wins)) if wins else (
        "In each of my roles I've taken ownership of problems from start to finish and kept the people "
        "who depend on me informed along the way.")
    close = ("I'd welcome the chance to talk about how I can help your team. Thank you for your time and "
             "consideration.")
    contact = " | ".join(x for x in (p.get("email"), p.get("phone")) if x)
    sig = "\n".join(x for x in (name, contact, p.get("linkedin")) if x)
    return (f"Dear {row['company']} hiring team,\n\n{intro}{skill_line}\n\n{middle}\n\n{close}\n\n"
            f"Sincerely,\n{sig}")


def _a(word):
    return "an" if word[:1].lower() in "aeiou" else "a"


def draft_letters(profile, limit=20, job_id=None):
    con = db()
    if job_id:
        rows = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchall()
    else:
        rows = con.execute("SELECT * FROM jobs WHERE status='new' AND cover_letter IS NULL "
                           "ORDER BY score DESC LIMIT ?", (limit,)).fetchall()
    resumes = resume_texts(profile)
    by_claude = 0
    for r in rows:
        rtext = resumes[r["resume"]][1] if resumes and r["resume"] < len(resumes) else ""
        letter = claude_letter(r, profile, rtext) if rtext else None
        if letter:
            by_claude += 1
        else:
            letter = template_letter(r, profile, rtext)
        con.execute("UPDATE jobs SET cover_letter=?, updated=? WHERE id=?",
                    (letter, dt.datetime.now(dt.timezone.utc).isoformat(), r["id"]))
        con.commit()
    return len(rows), by_claude

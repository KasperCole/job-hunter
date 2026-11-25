"""Open a job application in a browser and fill in what we know: name, contact details, links,
resume, cover letter, location, and the yes/no questions you've answered in your profile.

It never clicks Submit. Job sites ban accounts that auto-submit, many forms have CAPTCHAs, and
some questions only you should answer. You read the form, finish it, and submit it yourself.
"""
import os
import re
import sys
import webbrowser

from . import config
from .letters import draft_letters, full_name
from .store import db

FIELD_RULES = [
    (r"first.?name|given name|preferred first", "first_name"),
    (r"last.?name|surname|family name", "last_name"),
    (r"^(full )?name\b|your name|legal name", "full_name"),
    (r"e-?mail", "email"),
    (r"phone|mobile|cell", "phone"),
    (r"linkedin", "linkedin"),
    (r"github", "github"),
    (r"website|portfolio|personal site", "website"),
    (r"current (company|employer)|^company$|organization", "current_company"),
    (r"current (title|role|position)", "current_title"),
    (r"zip|postal", "postal_code"),
    (r"^state\b|state/province|province", "state"),
    (r"^city\b", "city_only"),
    (r"(current )?location|where are you (located|based)|city", "city"),
    (r"country", "country"),
    (r"salary|compensation|pay expectation", "salary"),
    (r"notice period|start date|when can you start|availability", "notice_period"),
    (r"years of (relevant |professional )?experience", "years"),
    (r"time ?zone", "timezone"),
    (r"how did you (hear|find)|referral source", "source"),
    (r"sponsor|visa", "sponsorship"),
    (r"(legally )?(authori[sz]ed|eligible) to work|work authori[sz]ation|right to work", "work_authorized"),
    (r"cover letter|additional information|anything else", "cover_letter"),
]


def field_value(key, row, p):
    city = ", ".join(x for x in (p.get("city"), p.get("state")) if x)
    yn = lambda v: {"yes": "Yes", "no": "No"}.get((v or "").lower(), "")
    sal = int(p.get("search", {}).get("min_salary") or 0)
    return {
        "first_name": p.get("first_name", ""), "last_name": p.get("last_name", ""), "full_name": full_name(p),
        "email": p.get("email", ""), "phone": p.get("phone", ""), "linkedin": p.get("linkedin", ""),
        "github": p.get("github", ""), "website": p.get("website") or p.get("linkedin", ""),
        "current_company": p.get("current_company", ""), "current_title": p.get("current_title", ""),
        "postal_code": p.get("postal_code", ""), "state": p.get("state", ""), "city_only": p.get("city", ""),
        "city": city, "country": p.get("country", ""), "salary": f"${sal:,}+ (flexible)" if sal else "",
        "notice_period": p.get("notice_period", ""), "years": str(p.get("years_experience") or ""),
        "timezone": p.get("timezone", ""), "source": "Online job board",
        "sponsorship": yn(p.get("needs_sponsorship")), "work_authorized": yn(p.get("work_authorized")),
        "cover_letter": row["cover_letter"] or "",
    }.get(key, "")


LABEL_JS = r"""
() => {
  const out = [];
  document.querySelectorAll('input, textarea, select').forEach((el, i) => {
    if (el.type === 'hidden' || el.disabled) return;
    let label = '';
    if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) label = l.innerText; }
    if (!label) { const l = el.closest('label'); if (l) label = l.innerText; }
    if (!label) { const fs = el.closest('fieldset, .field, .application-question, [class*="question"], [class*="Field"]');
                  if (fs) { const t = fs.querySelector('legend, label, .text, [class*="label"]'); if (t) label = t.innerText; } }
    label = (label || el.getAttribute('aria-label') || el.placeholder || el.name || el.id || '').trim();
    el.setAttribute('data-jh', String(i));
    out.push({idx: i, tag: el.tagName.toLowerCase(), type: (el.type || '').toLowerCase(), name: el.name || '',
              label: label.slice(0, 200), filled: el.tagName === 'SELECT' ? el.selectedIndex > 0 : !!el.value});
  });
  return out;
}
"""


def browser_profile_dir(n=""):
    return config.path("browser-profile" + n)


def launch_browser(pw):
    """Prefer the installed Chrome or Edge; fall back to Playwright's Chromium."""
    errors = []
    for prof in (browser_profile_dir(), browser_profile_dir("-2")):
        for channel in ("chrome", "msedge", None):
            try:
                kw = {"channel": channel} if channel else {}
                return pw.chromium.launch_persistent_context(prof, headless=False, **kw)
            except Exception as e:
                errors.append(f"{channel or 'chromium'}: {str(e).splitlines()[0][:120]}")
    raise RuntimeError("Couldn't start a browser. " + " | ".join(errors))


def fill(job_id, profile):
    con = db()
    row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        sys.exit(f"No job with id {job_id}")
    if not row["cover_letter"]:
        draft_letters(profile, job_id=job_id)
        row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright isn't installed, so I'll just open the page.\n"
              "To turn on pre-filling: pip install playwright && python -m playwright install chromium")
        webbrowser.open(row["apply_url"])
        return
    resumes = profile.get("resumes") or []
    resume = config.path(resumes[min(row["resume"] or 0, len(resumes) - 1)]["file"]) if resumes else None
    letter_path = config.path("letters", re.sub(r"[^A-Za-z0-9]+", "_", f"{row['company']}_{row['title']}")[:80] + ".txt")
    with open(letter_path, "w", encoding="utf-8") as f:
        f.write(row["cover_letter"] or "")
    try:
        with sync_playwright() as pw:
            ctx = launch_browser(pw)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.bring_to_front()
            page.goto(row["apply_url"], wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            for sel in ("a.postings-btn", "a:has-text('Apply for this job')", "button:has-text('Apply')"):
                try:
                    if page.locator(sel).first.is_visible(timeout=800):
                        page.locator(sel).first.click()
                        page.wait_for_timeout(2500)
                        break
                except Exception:
                    pass
            n = fill_page(page, row, profile, resume, letter_path)
            print(f"Pre-filled {n} fields for {row['title']} at {row['company']}.")
            print("Check the form, answer anything left blank, and click Submit yourself. "
                  "Close the browser window when you're done.")
            try:
                page.wait_for_event("close", timeout=0)
            except Exception:
                pass
            try:
                ctx.close()
            except Exception:
                pass
    except Exception:
        import traceback
        traceback.print_exc()
        print("Pre-fill failed; opening the application in your normal browser instead.")
        webbrowser.open(row["apply_url"])


def fill_page(page, row, profile, resume, letter_path):
    count = 0
    for frame in page.frames:
        try:
            fields = frame.evaluate(LABEL_JS)
        except Exception:
            continue
        for f in fields:
            sel = f'[data-jh="{f["idx"]}"]'
            label = f["label"].lower()
            try:
                if f["type"] == "file":
                    if re.search(r"cover", label):
                        frame.set_input_files(sel, letter_path)
                    elif resume and (re.search(r"resume|cv\b", label) or f["name"] in ("resume", "_systemfield_resume")):
                        frame.set_input_files(sel, resume)
                    else:
                        continue
                    print(f"  attached file -> {f['label'][:60]}")
                    count += 1
                    continue
                if f["filled"] or f["type"] in ("checkbox", "radio", "submit", "button", "search"):
                    continue
                key = next((k for pat, k in FIELD_RULES if re.search(pat, label)), None)
                val = field_value(key, row, profile) if key else ""
                if not val:
                    continue
                if f["tag"] == "select":
                    opts = frame.eval_on_selector(sel, "s => [...s.options].map(o => o.text)")
                    pick = next((o for o in opts if o.strip().lower().startswith(val.lower()[:3])), None)
                    if pick:
                        frame.select_option(sel, label=pick)
                        count += 1
                    continue
                if key == "cover_letter" and f["tag"] != "textarea":
                    continue
                frame.fill(sel, val)
                print(f"  {key} -> {f['label'][:60]}")
                count += 1
            except Exception:
                continue
    return count

"""The local web page (http://127.0.0.1:8765). It only listens on your own computer."""
import datetime as dt
import email.parser
import email.policy
import html
import json
import os
import re
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config
from . import skills as sk
from .letters import draft_letters
from .resume import extract_text, parse_resume
from .search import run_search
from .store import STATUSES, add_manual, db, rescore, salary_str

PORT = int(os.environ.get("JOBHUNTER_PORT", "8765"))
MAX_UPLOAD = 10 * 1024 * 1024
SEARCH = {"running": False, "log": [], "finished": None}
esc = html.escape

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--mute:#6b6b66;--line:#e4e3de;--acc:#2f6f4f;--acc2:#e9f2ec;--warn:#9a4b16;--warn2:#fbefe6}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--card:#20201e;--ink:#ecebe6;--mute:#9a998f;--line:#33322e;--acc:#7cc39c;--acc2:#1f2e25;--warn:#e0a070;--warn2:#33261c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
.wrap{max-width:980px;margin:0 auto;padding:20px 16px 60px}h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:18px 0 6px}.mute{color:var(--mute)}
header{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}header a{color:var(--ink)}
nav{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}nav a{padding:5px 12px;border:1px solid var(--line);border-radius:999px;color:var(--ink);text-decoration:none;background:var(--card);font-size:14px}
nav a.on{background:var(--acc);border-color:var(--acc);color:var(--bg)}nav .lab{align-self:center;color:var(--mute);font-size:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:10px 0}
.row{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.row>div:first-child{flex:1;min-width:0}
.t{font-weight:600;font-size:16px}.t a{color:var(--ink)}.score{font-variant-numeric:tabular-nums;background:var(--acc2);color:var(--acc);border-radius:6px;padding:2px 8px;font-weight:600;white-space:nowrap}
.pill{font-size:12px;border:1px solid var(--line);border-radius:999px;padding:1px 8px;margin-left:6px;color:var(--mute)}
.why{font-size:13px;color:var(--mute);margin-top:4px}.btns{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
button,.b{font:inherit;font-size:14px;padding:6px 12px;border-radius:7px;border:1px solid var(--line);background:var(--card);color:var(--ink);cursor:pointer;text-decoration:none;display:inline-block}
button.p,.b.p{background:var(--acc);border-color:var(--acc);color:var(--bg)}
textarea,input[type=text],input[type=number],input[type=email],select{width:100%;font:14px/1.5 system-ui,sans-serif;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink)}
textarea{min-height:90px}textarea.letter{min-height:340px}label{display:block;font-size:13px;color:var(--mute);margin:10px 0 3px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:0 14px}.checks label{display:inline-flex;gap:6px;align-items:center;margin-right:16px;color:var(--ink);font-size:15px}
pre{white-space:pre-wrap;font:14px/1.5 system-ui,sans-serif;max-height:420px;overflow:auto}form.inline{display:inline}
.flash{background:var(--acc2);color:var(--acc);padding:8px 12px;border-radius:8px}.warn{background:var(--warn2);color:var(--warn);padding:8px 12px;border-radius:8px}
.log{font:13px/1.45 ui-monospace,Menlo,Consolas,monospace;white-space:pre-wrap;color:var(--mute)}
"""


def shell(title, body, refresh=False):
    meta = '<meta http-equiv="refresh" content="3">' if refresh else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1">{meta}<title>{esc(title)}</title><style>{CSS}</style>'
            f'</head><body><div class="wrap"><header><h1><a href="/" style="text-decoration:none">Job Hunter</a></h1>'
            f'<nav style="margin:0"><a href="/">Jobs</a><a href="/settings">My profile</a></nav></header>'
            f'{body}</div></body></html>')


def post_btn(action, fields, label, primary=False):
    hidden = "".join(f'<input type="hidden" name="{esc(k)}" value="{esc(str(v))}">' for k, v in fields.items())
    return (f'<form class="inline" method="post" action="{action}">{hidden}'
            f'<button class="{"p" if primary else ""}">{esc(label)}</button></form>')


def flash_html(msg):
    return f'<p class="flash">{esc(msg)}</p>' if msg else ""


# --------------------------------------------------------------------------- setup / profile

UPLOAD_FORM = """<div class="card"><h2 style="margin-top:0">{heading}</h2>
<p class="mute">Word (.docx), PDF or text. It stays on this computer, in the <code>my-data</code> folder.
{extra}</p>
<form method="post" action="/upload" enctype="multipart/form-data">
<input type="file" name="resume" accept=".docx,.pdf,.txt,.md" required>
<label>Name for this resume (optional, for example "IT" or "General")</label><input type="text" name="label">
<div class="btns"><button class="p">Upload and analyze</button></div></form></div>"""


def setup_page(flash=""):
    body = (f"{flash_html(flash)}<p>Job Hunter reads your resume, works out which jobs fit you, searches job "
            "boards and company career sites for them, writes a cover letter for each, and fills in the "
            "application for you to check and submit.</p>"
            + UPLOAD_FORM.format(heading="Step 1: upload your resume", extra=""))
    return shell("Set up Job Hunter", body)


def _lines(v):
    return "\n".join(v or [])


def settings_page(p, flash=""):
    s = p["search"]
    k = p.get("api_keys") or {}
    wp = set(s.get("workplace") or [])
    resumes = "".join(
        f'<li>{esc(r.get("label") or "")} <span class="mute">({esc(os.path.basename(r["file"]))})</span> '
        f'{post_btn("/resume/remove", {"file": r["file"]}, "Remove")}</li>' for r in p.get("resumes") or [])
    yn = lambda name, v: (f'<select name="{name}"><option value="">Leave for me to answer</option>'
                          + "".join(f'<option value="{o}"{" selected" if v == o else ""}>{o.title()}</option>'
                                    for o in ("yes", "no")) + "</select>")
    inp = lambda name, v, typ="text": f'<input type="{typ}" name="{name}" value="{esc(str(v or ""))}">'
    body = f"""{flash_html(flash)}
<p class="mute">This is what Job Hunter found on your resume. Fix anything that's wrong, then save.
Your search uses the <b>job titles</b> and <b>search keywords</b>; your <b>skills</b> decide the Match and Fit scores.</p>
<div class="card"><h2 style="margin-top:0">Resumes</h2><ul>{resumes or '<li class="mute">None yet</li>'}</ul>
<details><summary>Add another resume</summary>{UPLOAD_FORM.format(heading="Upload another version", extra="For each job, the app uses the resume that covers the most of the skills it asks for.")}</details></div>
<form method="post" action="/settings">
<div class="card"><h2 style="margin-top:0">What to look for</h2>
<label>Job titles you want (one per line)</label><textarea name="target_titles">{esc(_lines(p.get("target_titles")))}</textarea>
<label>Search keywords sent to job boards (one per line; usually the same as your titles)</label><textarea name="keywords">{esc(_lines(s.get("keywords")))}</textarea>
<label>Skip jobs whose title contains (comma separated)</label>{inp("exclude_words", ", ".join(s.get("exclude_words") or []))}
<label>Work arrangement</label><div class="checks">
{''.join(f'<label><input type="checkbox" name="workplace" value="{v}"{" checked" if v in wp else ""}> {lab}</label>' for v, lab in (("remote", "Remote"), ("hybrid", "Hybrid"), ("onsite", "On-site")))}</div>
<div class="grid"><div><label>Your area for hybrid and on-site jobs (City, State)</label>{inp("location", s.get("location"))}</div>
<div><label>Distance in miles (Adzuna and USAJOBS)</label>{inp("radius_miles", s.get("radius_miles"), "number")}</div>
<div><label>Remote jobs must be open to people in (country code)</label>{inp("remote_country", s.get("remote_country"))}</div>
<div><label>Minimum yearly pay in USD (0 = any)</label>{inp("min_salary", s.get("min_salary"), "number")}</div>
<div><label>Ignore listings older than (days)</label>{inp("max_age_days", s.get("max_age_days"), "number")}</div>
<div><label>Only show jobs with a Match of at least</label>{inp("min_match", s.get("min_match"), "number")}</div></div></div>

<div class="card"><h2 style="margin-top:0">Your skills</h2>
<label>Comma separated. Add skills you have that your resume doesn't mention yet.</label>
<textarea name="skills">{esc(", ".join(sk.display(x) for x in p.get("skills") or []))}</textarea>
<label>Achievements used in template cover letters (one per line, from your resume)</label>
<textarea name="achievements">{esc(_lines(p.get("achievements")))}</textarea></div>

<div class="card"><h2 style="margin-top:0">Your details (used to fill in applications)</h2><div class="grid">
<div><label>First name</label>{inp("first_name", p.get("first_name"))}</div><div><label>Last name</label>{inp("last_name", p.get("last_name"))}</div>
<div><label>Email</label>{inp("email", p.get("email"), "email")}</div><div><label>Phone</label>{inp("phone", p.get("phone"))}</div>
<div><label>City</label>{inp("city", p.get("city"))}</div><div><label>State</label>{inp("state", p.get("state"))}</div>
<div><label>ZIP / postal code</label>{inp("postal_code", p.get("postal_code"))}</div><div><label>Country</label>{inp("country", p.get("country"))}</div>
<div><label>LinkedIn URL</label>{inp("linkedin", p.get("linkedin"))}</div><div><label>Website / portfolio</label>{inp("website", p.get("website"))}</div>
<div><label>GitHub</label>{inp("github", p.get("github"))}</div><div><label>Time zone</label>{inp("timezone", p.get("timezone"))}</div>
<div><label>Current or last employer</label>{inp("current_company", p.get("current_company"))}</div><div><label>Current or last title</label>{inp("current_title", p.get("current_title"))}</div>
<div><label>Years of experience</label>{inp("years_experience", p.get("years_experience"), "number")}</div><div><label>Notice period / start date</label>{inp("notice_period", p.get("notice_period"))}</div>
<div><label>Legally authorized to work in this country?</label>{yn("work_authorized", p.get("work_authorized"))}</div>
<div><label>Need visa sponsorship?</label>{yn("needs_sponsorship", p.get("needs_sponsorship"))}</div></div></div>

<details class="card"><summary><b>Optional: more job sources (free API keys)</b></summary>
<p class="mute">Adzuna covers jobs at local employers in any US city, which is the best source for on-site and hybrid roles.
Get a free key at developer.adzuna.com. USAJOBS lists US government jobs; get a key at developer.usajobs.gov.</p><div class="grid">
<div><label>Adzuna app ID</label>{inp("adzuna_app_id", k.get("adzuna_app_id"))}</div><div><label>Adzuna app key</label>{inp("adzuna_app_key", k.get("adzuna_app_key"))}</div>
<div><label>USAJOBS email</label>{inp("usajobs_email", k.get("usajobs_email"))}</div><div><label>USAJOBS key</label>{inp("usajobs_key", k.get("usajobs_key"))}</div>
<div><label>The Muse key (optional, raises its rate limit)</label>{inp("themuse_key", k.get("themuse_key"))}</div></div></details>
<div class="btns"><button class="p">Save profile</button></div></form>"""
    return shell("My profile", body)


def apply_parsed(p, parsed, overwrite_empty_only):
    """Copy what the resume parser found into the profile."""
    for key in ("first_name", "last_name", "email", "phone", "linkedin", "github", "website", "city", "state",
                "postal_code", "current_title"):
        if parsed.get(key) and (not overwrite_empty_only or not p.get(key)):
            p[key] = parsed[key]
    if parsed.get("years_experience") and (not overwrite_empty_only or not p.get("years_experience")):
        p["years_experience"] = parsed["years_experience"]
    p["target_titles"] = list(dict.fromkeys((p.get("target_titles") or []) + parsed["target_titles"]))[:8]
    p["skills"] = list(dict.fromkeys((p.get("skills") or []) + parsed["skills"]))
    p["achievements"] = list(dict.fromkeys((p.get("achievements") or []) + parsed["achievements"]))[:15]
    s = p["search"]
    s["keywords"] = list(dict.fromkeys((s.get("keywords") or []) + parsed["search_keywords"]))[:8]
    if not s.get("location") and p.get("city"):
        s["location"] = ", ".join(x for x in (p.get("city"), p.get("state")) if x)
    return p


def save_settings_form(p, f):
    split_lines = lambda v: [x.strip() for x in (v or "").splitlines() if x.strip()]
    split_commas = lambda v: [x.strip() for x in (v or "").split(",") if x.strip()]
    num = lambda v, d=0: int(float(v)) if str(v or "").strip() else d
    for key in ("first_name", "last_name", "email", "phone", "city", "state", "postal_code", "country", "linkedin",
                "website", "github", "timezone", "current_company", "current_title", "notice_period",
                "work_authorized", "needs_sponsorship"):
        p[key] = (f.get(key) or [""])[0].strip()
    p["years_experience"] = num((f.get("years_experience") or [""])[0])
    p["target_titles"] = split_lines((f.get("target_titles") or [""])[0])
    p["skills"] = [sk.norm(x) for x in split_commas((f.get("skills") or [""])[0])]
    p["achievements"] = split_lines((f.get("achievements") or [""])[0])
    s = p["search"]
    s["keywords"] = split_lines((f.get("keywords") or [""])[0])
    s["exclude_words"] = split_commas((f.get("exclude_words") or [""])[0])
    s["workplace"] = [w for w in f.get("workplace", []) if w in ("remote", "hybrid", "onsite")] or ["remote"]
    s["location"] = (f.get("location") or [""])[0].strip()
    s["remote_country"] = ((f.get("remote_country") or ["US"])[0].strip() or "US").upper()
    s["radius_miles"] = num((f.get("radius_miles") or [""])[0], 30)
    s["min_salary"] = num((f.get("min_salary") or [""])[0])
    s["max_age_days"] = num((f.get("max_age_days") or [""])[0], 30)
    s["min_match"] = num((f.get("min_match") or [""])[0], 40)
    for key in ("adzuna_app_id", "adzuna_app_key", "usajobs_email", "usajobs_key", "themuse_key"):
        p.setdefault("api_keys", {})[key] = (f.get(key) or [""])[0].strip()
    return p


# --------------------------------------------------------------------------- job list / job page

def list_page(p, status, wp="", min_fit=0, sort="match", flash=""):
    con = db()
    counts = {s: con.execute("SELECT COUNT(*) FROM jobs WHERE status=?", (s,)).fetchone()[0] for s in STATUSES}
    q, args = "SELECT * FROM jobs WHERE status=?", [status]
    if wp:
        q += " AND workplace=?"
        args.append(wp)
    if min_fit:
        q += " AND fit>=?"
        args.append(min_fit)
    q += " ORDER BY " + ("fit DESC, score DESC" if sort == "fit" else "score DESC, fit DESC") + " LIMIT 300"
    rows = con.execute(q, args).fetchall()
    link = lambda **kw: "/?" + urllib.parse.urlencode({k: v for k, v in dict(
        dict(s=status, wp=wp, fit=min_fit or "", sort=sort if sort == "fit" else ""), **kw).items() if v})
    nav = "".join(f'<a class="{"on" if s == status else ""}" href="{link(s=s)}">{s.title()} ({counts[s]})</a>'
                  for s in STATUSES)
    filt = ('<nav><span class="lab">Where:</span>'
            + "".join(f'<a class="{"on" if v == wp else ""}" href="{link(wp=v)}">{lab}</a>'
                      for v, lab in (("", "All"), ("remote", "Remote"), ("hybrid", "Hybrid"), ("onsite", "On-site")))
            + '<span class="lab">Fit:</span>'
            + "".join(f'<a class="{"on" if v == min_fit else ""}" href="{link(fit=v)}">{lab}</a>'
                      for v, lab in ((0, "Any"), (35, "Fair+"), (55, "Good+"), (75, "Strong")))
            + '<span class="lab">Sort:</span>'
            + "".join(f'<a class="{"on" if k == sort else ""}" href="{link(sort=k)}">{lab}</a>'
                      for k, lab in (("match", "Match"), ("fit", "Fit")))
            + "</nav>")
    back = link()
    cards = []
    for r in rows:
        f = {"id": r["id"], "back": back}
        acts = []
        if status in ("new", "saved"):
            acts += [post_btn("/action", dict(f, do="fill"), "Pre-fill application", True),
                     f'<a class="b" href="{esc(r["apply_url"])}" target="_blank" rel="noopener">Open listing</a>',
                     post_btn("/action", dict(f, do="applied"), "Mark applied")]
            if status == "new":
                acts.append(post_btn("/action", dict(f, do="saved"), "Save for later"))
            acts.append(post_btn("/action", dict(f, do="skipped"), "Skip"))
        elif status == "applied":
            acts.append(post_btn("/action", dict(f, do="interview"), "Got an interview", True))
        else:
            acts.append(post_btn("/action", dict(f, do="new"), "Move back to New"))
        sal = salary_str(r)
        missing = json.loads(r["missing"] or "[]")
        wp_label = {"remote": "Remote", "hybrid": "Hybrid", "onsite": "On-site"}.get(r["workplace"], "")
        cards.append(f"""<div class="card"><div class="row"><div>
<div class="t"><a href="/job?id={urllib.parse.quote(r['id'])}">{esc(r['title'])}</a><span class="pill">{wp_label}</span></div>
<div class="mute">{esc(r['company'])} · {esc(r['location'] or '')}{' · ' + sal if sal else ''} · {esc(r['source'])}</div>
<div class="why">{esc(r['reasons'] or '')}</div>
{f'<div class="why">Missing: {esc(", ".join(sk.display(m) for m in missing[:8]))}</div>' if missing else ''}</div>
<span class="score" title="Match: how well the job fits what you're looking for. Fit: share of the listing's skills that are on your resume.">Match {r['score']} · Fit {r['fit']}</span></div>
<div class="btns">{''.join(acts)}</div></div>""")
    if not cards:
        cards.append('<p class="mute">Nothing here yet. Click <b>Find jobs now</b>.</p>' if status == "new"
                     else '<p class="mute">Nothing here yet.</p>')
    running = SEARCH["running"]
    search_box = (f'<div class="card"><b>Searching…</b> this page refreshes on its own.<div class="log">'
                  f'{esc(chr(10).join(SEARCH["log"][-12:]))}</div></div>') if running else (
        '<div class="card row"><div><b>Find new jobs</b><div class="mute">Searches for: '
        + esc(", ".join((p["search"].get("keywords") or p.get("target_titles") or [])[:6]) or "nothing yet: add job titles in My profile")
        + "</div>"
        + (f'<div class="log">Last search: {esc(SEARCH["finished"])}</div>' if SEARCH["finished"] else "")
        + '</div><form method="post" action="/search"><button class="p">Find jobs now</button></form></div>')
    add = """<details class="card"><summary><b>Add a job you found yourself</b></summary>
<form method="post" action="/add"><label>Link to the job posting</label><input type="text" name="url" required>
<div class="grid"><div><label>Job title</label><input type="text" name="title" required></div>
<div><label>Company</label><input type="text" name="company" required></div>
<div><label>Location</label><input type="text" name="location"></div></div>
<label>Job description (paste it in; it improves the Fit rating and cover letter)</label><textarea name="description"></textarea>
<div class="btns"><button class="p">Add job</button></div></form></details>"""
    body = (f"{flash_html(flash)}{search_box}<p class='mute'><b>Match</b> = how well the job fits what you're "
            "looking for (title, skills, pay, location). <b>Fit</b> = how many of the listing's skills are on your "
            f"resume. Pre-fill opens the application with your details filled in; you check it and click Submit.</p>"
            f"<nav>{nav}</nav>{filt}{''.join(cards)}{add}")
    return shell("Job Hunter", body, refresh=running)


def job_page(p, job_id, flash=""):
    r = db().execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not r:
        return shell("Not found", "<p>Job not found. <a href='/'>Back</a></p>")
    back = f"/job?id={urllib.parse.quote(job_id)}"
    f = {"id": job_id, "back": back}
    matched = [sk.display(x) for x in json.loads(r["matched"] or "[]")]
    missing = [sk.display(x) for x in json.loads(r["missing"] or "[]")]
    flags = json.loads(r["flags"] or "[]")
    resumes = p.get("resumes") or []
    rname = resumes[r["resume"]]["label"] if resumes and r["resume"] < len(resumes) else "none"
    body = f"""<p><a href="/?s={r['status']}">&larr; Back</a></p>{flash_html(flash)}
<h1>{esc(r['title'])}</h1><p class="mute">{esc(r['company'])} · {esc(r['location'] or '')} · {esc(r['workplace'] or '')} ·
{salary_str(r) or 'pay not listed'} · status: {r['status']}</p>
<div class="btns">{post_btn('/action', dict(f, do='fill'), 'Pre-fill application', True)}
<a class="b" href="{esc(r['apply_url'])}" target="_blank" rel="noopener">Open listing</a>
{post_btn('/action', dict(f, do='applied'), 'Mark applied')}{post_btn('/action', dict(f, do='regen'), 'Rewrite cover letter')}
{post_btn('/action', dict(f, do='skipped', back='/'), 'Skip')}</div>
<div class="card"><b>Match {r['score']}/100</b> <span class="mute">{esc(r['reasons'] or '')}</span><br>
<b>Fit {r['fit']}/100 ({esc(r['fit_label'] or '')})</b> <span class="mute">share of this listing's skills that are on your resume</span><br>
<b>You have:</b> {esc(", ".join(matched) or "none of the skills it lists")}<br>
<b>Missing:</b> {esc(", ".join(missing) or "nothing it lists")}
{('<br><b>Watch:</b> ' + esc("; ".join(flags))) if flags else ''}<br><b>Resume used:</b> {esc(rname)}</div>
<div class="card"><b>Cover letter</b> <span class="mute">(edit and save; pre-fill uses this text)</span>
<form method="post" action="/letter"><input type="hidden" name="id" value="{esc(job_id)}">
<textarea class="letter" name="letter">{esc(r['cover_letter'] or '')}</textarea>
<div class="btns"><button class="p">Save letter</button></div></form></div>
<div class="card"><b>Job description</b><pre>{esc(r['description'] or '')}</pre></div>"""
    return shell(r["title"], body)


# --------------------------------------------------------------------------- server

def parse_multipart(content_type, body):
    """Return ({field: [values]}, {field: (filename, bytes)}) from a multipart/form-data body."""
    msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
        b"Content-Type: " + content_type.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
    fields, files = {}, {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        fn = part.get_filename()
        data = part.get_payload(decode=True) or b""
        if fn:
            files[name] = (fn, data)
        else:
            fields.setdefault(name, []).append(data.decode("utf-8", "replace"))
    return fields, files


def _start_search():
    if SEARCH["running"]:
        return
    p = config.load_profile()
    SEARCH.update(running=True, log=[])

    def work():
        try:
            run_search(p, log=SEARCH["log"].append)
        except Exception as e:
            SEARCH["log"].append(f"Search failed: {type(e).__name__}: {e}")
        finally:
            SEARCH["running"] = False
            SEARCH["finished"] = dt.datetime.now().strftime("%b %d, %I:%M %p") + " · " + (SEARCH["log"] or [""])[-1]
    threading.Thread(target=work, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, code=200):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, to, msg=""):
        if msg:
            to += ("&" if "?" in to else "?") + "m=" + urllib.parse.quote(msg)
        self.send_response(303)
        self.send_header("Location", to)
        self.end_headers()

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        g = lambda k, d="": q.get(k, [d])[0]
        p = config.load_profile()
        if u.path == "/setup" or (p is None and u.path in ("/", "/settings")):
            return self._send(setup_page(g("m")))
        if u.path == "/settings":
            return self._send(settings_page(p, g("m")))
        if u.path == "/job":
            return self._send(job_page(p, g("id"), g("m")))
        if u.path == "/":
            s = g("s", "new")
            try:
                mf = max(0, min(100, int(g("fit", "0") or 0)))
            except ValueError:
                mf = 0
            wp = g("wp") if g("wp") in ("remote", "hybrid", "onsite") else ""
            return self._send(list_page(p, s if s in STATUSES else "new", wp, mf,
                                        "fit" if g("sort") == "fit" else "match", g("m")))
        self._send("Not found", 404)

    def do_POST(self):
        # Only accept posts from this page, so other websites can't drive the app.
        origin = self.headers.get("Origin") or self.headers.get("Referer") or ""
        if origin and not origin.startswith((f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}")):
            return self._send("Forbidden", 403)
        n = int(self.headers.get("Content-Length", 0))
        if n > MAX_UPLOAD:
            return self._send("That file is too large (10 MB max).", 413)
        raw = self.rfile.read(n)
        ctype = self.headers.get("Content-Type", "")
        if ctype.startswith("multipart/form-data"):
            form, files = parse_multipart(ctype, raw)
        else:
            form, files = urllib.parse.parse_qs(raw.decode("utf-8"), keep_blank_values=True), {}
        g = lambda k: (form.get(k) or [""])[0]
        p = config.load_profile()
        if self.path == "/upload":
            return self._upload(p, files.get("resume"), g("label"))
        if p is None:
            return self._redirect("/setup")
        if self.path == "/settings":
            p = save_settings_form(p, form)
            config.save_profile(p)
            dropped = rescore(p)
            return self._redirect("/settings", "Saved." + (f" Removed {dropped} jobs that no longer fit." if dropped else ""))
        if self.path == "/resume/remove":
            p["resumes"] = [r for r in p.get("resumes") or [] if r["file"] != g("file")]
            config.save_profile(p)
            return self._redirect("/settings", "Resume removed from your profile (the file is still in my-data/resumes).")
        if self.path == "/search":
            _start_search()
            return self._redirect("/")
        if self.path == "/add":
            if g("url") and g("title") and g("company"):
                jid = add_manual(p, g("url"), g("title"), g("company"), g("location"), g("description"))
                draft_letters(p, job_id=jid)
                return self._redirect("/", "Job added.")
            return self._redirect("/", "Link, title and company are required.")
        jid = g("id")
        con = db()
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        if self.path == "/letter":
            con.execute("UPDATE jobs SET cover_letter=?, updated=? WHERE id=?", (g("letter"), now, jid))
            con.commit()
            return self._redirect(f"/job?id={urllib.parse.quote(jid)}", "Saved.")
        back = g("back") if g("back").startswith("/") else "/"
        action, msg = g("do"), ""
        if action in STATUSES:
            con.execute("UPDATE jobs SET status=?, updated=? WHERE id=?", (action, now, jid))
            con.commit()
            msg = {"applied": "Marked as applied.", "skipped": "Skipped.", "saved": "Saved for later.",
                   "interview": "Nice! Marked as interview.", "new": "Moved back to New."}[action]
        elif action == "fill":
            log = open(config.path("fill.log"), "a", encoding="utf-8")
            log.write(f"\n===== {now}  fill {jid} =====\n")
            log.flush()
            flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
            main = os.path.join(config.APP_DIR, "main.py")
            subprocess.Popen([sys.executable, "-u", main, "--home", config.home(), "fill", jid], cwd=config.APP_DIR,
                             stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
            log.close()
            msg = "Opening the application in a new browser window. Check it, click Submit, then Mark applied here."
        elif action == "regen":
            con.execute("UPDATE jobs SET cover_letter=NULL WHERE id=?", (jid,))
            con.commit()
            draft_letters(p, job_id=jid)
            msg = "Cover letter rewritten."
        self._redirect(back, msg)

    def _upload(self, p, upload, label):
        if not upload or not upload[1]:
            return self._redirect("/setup", "Choose a resume file first.")
        name, data = upload
        ext = os.path.splitext(name)[1].lower()
        if ext not in (".docx", ".pdf", ".txt", ".md"):
            return self._redirect("/setup", "Please upload a .docx, .pdf or .txt file.")
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(name))[:80] or "resume" + ext
        rel = os.path.join("resumes", safe).replace("\\", "/")
        with open(config.path(rel), "wb") as f:
            f.write(data)
        try:
            text = extract_text(config.path(rel))
        except RuntimeError as e:
            return self._redirect("/setup" if p is None else "/settings", str(e))
        if len(text.strip()) < 100:
            return self._redirect("/setup" if p is None else "/settings",
                                  "I couldn't read much text from that file. If it's a scanned PDF, upload a .docx instead.")
        parsed = parse_resume(text)
        first = p is None
        p = p or config._merge(config.DEFAULT_PROFILE, {})
        p = apply_parsed(p, parsed, overwrite_empty_only=not first)
        p["resumes"] = [r for r in p.get("resumes") or [] if r["file"] != rel] + [
            {"label": label or os.path.splitext(safe)[0].replace("_", " "), "file": rel}]
        config.save_profile(p)
        msg = (f"Read your resume: found {len(parsed['skills'])} skills and {len(parsed['titles_found'])} job titles. "
               "Check everything below, choose Remote / Hybrid / On-site and your area, then save.")
        return self._redirect("/settings", msg)


def serve(open_browser=True):
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"Job Hunter is running at {url}  (press Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")

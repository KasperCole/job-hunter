"""One full search: fetch listings, keep the ones that fit, draft cover letters for the best."""
from . import sources
from .letters import draft_letters
from .store import db, save_matches


def run_search(profile, log=print, letters=20):
    s = profile["search"]
    kws = s.get("keywords") or profile.get("target_titles") or []
    where = ", ".join(w.title() if w != "onsite" else "On-site" for w in s.get("workplace") or [])
    log(f"Searching for: {', '.join(kws) or '(no keywords yet)'}")
    log(f"Workplace: {where}" + (f" · near {s['location']}" if s.get("location") else ""))
    jobs = sources.fetch_all(profile, log=log)
    log(f"Fetched {len(jobs)} listings in total.")
    added = save_matches(jobs, profile)
    log(f"{added} new matches saved.")
    n, by_claude = draft_letters(profile, limit=letters)
    if n:
        log(f"Drafted {n} cover letters" + (f" ({by_claude} by Claude)." if by_claude else "."))
    total = db().execute("SELECT COUNT(*) FROM jobs WHERE status='new'").fetchone()[0]
    log(f"{total} matches are waiting for your review.")
    return added

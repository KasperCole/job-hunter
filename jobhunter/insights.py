"""The Skills and Progress pages: which missing skills come up most for the roles you want, and how your
applications are going (follow-ups due, replies, interviews, offers)."""
import datetime as dt
import json

from .matching import title_score

FOLLOW_UP_DAYS = 7
GHOST_DAYS = 30
ACTIVE = ("new", "saved", "applied", "interview", "offer", "rejected", "ghosted")


def role_for(job_title, targets):
    """Which of your target titles a job belongs to, or 'Other'."""
    score, t = title_score(job_title, targets or [])
    return t if t and score >= 20 else "Other"


def heatmap(rows, targets, top=12, min_jobs=1):
    """Missing skills by role.

    rows: job rows with title and missing (JSON list). Returns
    {"roles": [(role, n_jobs)], "skills": [(skill, n_jobs)], "cells": {(role, skill): n}}
    with the skills missed most often overall first and only roles that have jobs.
    """
    by_role, total = {}, {}
    cells = {}
    for r in rows:
        role = role_for(r["title"], targets)
        by_role[role] = by_role.get(role, 0) + 1
        for s in set(json.loads(r["missing"] or "[]")):
            total[s] = total.get(s, 0) + 1
            cells[(role, s)] = cells.get((role, s), 0) + 1
    skills = sorted(total.items(), key=lambda kv: (-kv[1], kv[0]))
    skills = [kv for kv in skills if kv[1] >= min_jobs][:top]
    order = {t: i for i, t in enumerate(targets or [])}
    roles = sorted(by_role.items(), key=lambda kv: (kv[0] == "Other", order.get(kv[0], 99), -kv[1]))
    return {"roles": roles, "skills": skills, "cells": cells}


def _days_since(iso, now):
    if not iso:
        return None
    try:
        d = dt.datetime.fromisoformat(iso)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return (now - d).days


def mark_ghosted(con, ghost_days=GHOST_DAYS, now=None):
    """Applied jobs with no news for ghost_days move to 'ghosted'. Returns how many moved."""
    now = now or dt.datetime.now(dt.timezone.utc)
    moved = 0
    for r in con.execute("SELECT id, applied_at, followed_up_at, updated FROM jobs WHERE status='applied'").fetchall():
        dates = [x for x in (r["applied_at"], r["followed_up_at"], r["updated"]) if x]
        days = _days_since(max(dates), now) if dates else None
        if days is not None and days >= ghost_days:
            con.execute("UPDATE jobs SET status='ghosted', closed_at=?, updated=? WHERE id=?",
                        (now.isoformat(), now.isoformat(), r["id"]))
            moved += 1
    if moved:
        con.commit()
    return moved


def follow_ups_due(con, days=FOLLOW_UP_DAYS, now=None):
    """Applied jobs you haven't followed up on, {days}+ days after applying."""
    now = now or dt.datetime.now(dt.timezone.utc)
    out = []
    for r in con.execute("SELECT * FROM jobs WHERE status='applied' AND followed_up_at IS NULL "
                         "ORDER BY applied_at").fetchall():
        d = _days_since(r["applied_at"] or r["updated"], now)
        if d is not None and d >= days:
            out.append((r, d))
    return out


def funnel(con):
    """Counts for applied -> heard back -> interview -> offer."""
    c = lambda q: con.execute("SELECT COUNT(*) FROM jobs WHERE " + q).fetchone()[0]
    applied = c("status IN ('applied','interview','offer','rejected','ghosted') OR applied_at IS NOT NULL")
    return {
        "applied": applied,
        "replied": c("status IN ('interview','offer','rejected') OR interview_at IS NOT NULL"),
        "interview": c("status IN ('interview','offer') OR interview_at IS NOT NULL"),
        "offer": c("status='offer'"),
        "rejected": c("status='rejected'"),
        "ghosted": c("status='ghosted'"),
        "waiting": c("status='applied'"),
    }

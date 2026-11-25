#!/usr/bin/env python3
"""Job Hunter: reads your resume, finds remote, hybrid and on-site jobs that fit it, drafts cover
letters, and pre-fills applications for you to check and submit.

Usage
  python main.py                 open the app in your browser (same as `serve`)
  python main.py serve           open the app
  python main.py setup <resume>  read a resume from the command line instead of the web page
  python main.py find            search for new jobs now (no web page)
  python main.py run             search, then open the app
  python main.py rescore         re-check unreviewed jobs after editing your profile
  python main.py fill <job_id>   open one application in a browser and pre-fill it
  python main.py export [file]   save every job to a CSV file (opens in Excel / Google Sheets)

Options
  --home <folder>   keep this person's data in <folder> instead of ./my-data
                    (lets several people share one copy of the app)
"""
import csv
import sys

from jobhunter import config


def need_profile():
    p = config.load_profile()
    if p is None:
        sys.exit("No profile yet. Run `python main.py` and upload your resume, "
                 "or `python main.py setup path/to/resume.docx`.")
    return p


def cmd_setup(path):
    import os
    import shutil
    from jobhunter.resume import extract_text, parse_resume
    from jobhunter.web import apply_parsed
    name = os.path.basename(path)
    rel = "resumes/" + name
    shutil.copyfile(path, config.path(rel))
    parsed = parse_resume(extract_text(config.path(rel)))
    p = config.load_profile()
    first = p is None
    p = p or config._merge(config.DEFAULT_PROFILE, {})
    p = apply_parsed(p, parsed, overwrite_empty_only=not first)
    p["resumes"] = [r for r in p["resumes"] if r["file"] != rel] + [{"label": os.path.splitext(name)[0], "file": rel}]
    config.save_profile(p)
    print(f"Name:      {p['first_name']} {p['last_name']}")
    print(f"Contact:   {p['email']}  {p['phone']}")
    print(f"Location:  {p['search']['location']}")
    print(f"Years:     {p['years_experience']}")
    print(f"Titles:    {', '.join(p['target_titles'])}")
    print(f"Skills:    {', '.join(p['skills'][:30])}")
    print(f"\nSaved to {config.path('profile.json')}. Review it in the app (python main.py) "
          "or edit the file, then run: python main.py find")


def cmd_export(out=None):
    from jobhunter.store import db, salary_str
    out = out or config.path("applications.csv")
    rows = db().execute("SELECT * FROM jobs ORDER BY status, score DESC").fetchall()
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Status", "Match", "Fit", "Missing skills", "Company", "Title", "Workplace", "Location", "Salary",
                    "Apply link", "Source", "Found", "Updated"])
        for r in rows:
            import json
            w.writerow([r["status"], r["score"], r["fit"], ", ".join(json.loads(r["missing"] or "[]")), r["company"],
                        r["title"], r["workplace"], r["location"], salary_str(r), r["apply_url"], r["source"],
                        (r["first_seen"] or "")[:10], (r["updated"] or "")[:10]])
    print(f"Wrote {len(rows)} jobs to {out}")


def main(argv):
    args = list(argv[1:])
    if "--home" in args:
        i = args.index("--home")
        config.set_home(args[i + 1])
        del args[i:i + 2]
    cmd = args[0] if args else "serve"
    if cmd in ("serve", "run", "find", "rescore", "fill", "export"):
        if cmd != "serve":
            p = need_profile()
    if cmd == "serve":
        from jobhunter.web import serve
        serve()
    elif cmd == "setup" and len(args) > 1:
        cmd_setup(args[1])
    elif cmd in ("find", "run"):
        from jobhunter.search import run_search
        run_search(p)
        if cmd == "run":
            from jobhunter.web import serve
            serve()
    elif cmd == "rescore":
        from jobhunter.store import rescore
        print(f"Removed {rescore(p)} jobs that no longer fit.")
    elif cmd == "fill" and len(args) > 1:
        from jobhunter.prefill import fill
        fill(args[1], p)
    elif cmd == "export":
        cmd_export(args[1] if len(args) > 1 else None)
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)

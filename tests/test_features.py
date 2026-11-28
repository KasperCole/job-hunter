"""Offline tests for the answer bank, skills heat map, follow-up tracking, paste-a-link and Workday boards."""
import datetime as dt
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from jobhunter import answers, config, insights, linkinfo, prefill, sources, store  # noqa: E402


class AnswerBankTests(unittest.TestCase):
    def test_topics_group_variants(self):
        self.assertEqual(answers.topic_of("Why do you want to work at Acme?", "Acme"), "why_company")
        self.assertEqual(answers.topic_of("What interests you about joining Globex?", "Globex"), "why_company")
        self.assertEqual(answers.topic_of("Why Initech? *", "Initech"), "why_company")
        self.assertEqual(answers.topic_of("What makes you a great fit for this role?"), "good_fit")
        self.assertEqual(answers.topic_of("Are you willing to relocate?"), "relocate")
        self.assertEqual(answers.topic_of("Veteran Status"), "veteran")
        self.assertIsNone(answers.topic_of("Years of Active Directory experience"))

    def test_company_answer_is_templated_and_held_for_review(self):
        bank = {}
        self.assertTrue(answers.learn(bank, "Why do you want to work at Acme?",
                                      "Acme's help desk tools are ones I use every day.", "Acme", "IT Support"))
        e = bank["why_company"]
        self.assertEqual(e["answer"], "{company}'s help desk tools are ones I use every day.")
        self.assertTrue(e["needs_review"])
        # Not reused anywhere until approved.
        self.assertEqual(answers.find(bank, "Why do you want to work at Globex?", "Globex"), "")
        answers.set_answer(bank, "why_company", "I'd like to bring my support experience to {company} as a {title}.")
        self.assertEqual(answers.find(bank, "Why Globex?", "Globex", "Help Desk Analyst"),
                         "I'd like to bring my support experience to Globex as a Help Desk Analyst.")

    def test_plain_answers_reused_and_fuzzy_matched(self):
        bank = {}
        answers.learn(bank, "How many years of Active Directory experience do you have?", "4", "Acme")
        self.assertFalse(bank[answers.key_for("How many years of Active Directory experience do you have?")]
                         ["needs_review"])
        self.assertEqual(answers.find(bank, "How many years of Active Directory experience do you have? *"), "4")
        self.assertEqual(answers.find(bank, "How many years of Active Directory experience have you?"), "4")
        self.assertEqual(answers.find(bank, "How many years of Python experience do you have?"), "")

    def test_frequency_counts_once_per_job(self):
        bank = {}
        answers.note_seen(bank, ["Why Acme?", "Why do you want to work at Acme?"], "job1", "Acme")
        answers.note_seen(bank, ["Why Acme?"], "job1", "Acme")
        answers.note_seen(bank, ["What excites you about Globex?"], "job2", "Globex")
        answers.note_seen(bank, ["Are you willing to relocate?"], "job2", "Globex")
        top = answers.most_common(bank)
        self.assertEqual(top[0][0], "why_company")
        self.assertEqual(top[0][1]["seen"], 2)

    def test_sensitive_questions_never_saved(self):
        bank = {}
        self.assertFalse(answers.learn(bank, "Social Security Number", "123-45-6789"))
        self.assertFalse(answers.learn(bank, "Password", "hunter2"))
        self.assertEqual(bank, {})

    def test_prefill_picks_custom_questions(self):
        fields = [{"label": "First Name", "type": "text", "value": "Jordan"},
                  {"label": "Why do you want to work here?", "type": "textarea", "value": "Because"},
                  {"label": "Race / Ethnicity", "type": "select-one", "value": ""},
                  {"label": "Resume", "type": "file", "value": ""}]
        got = prefill.custom_questions(fields)
        self.assertEqual(got, {"Why do you want to work here?": "Because", "Race / Ethnicity": ""})


class WorkdayTests(unittest.TestCase):
    ENTRY = {"name": "Example Bank", "url": "https://examplebank.wd5.myworkdayjobs.com/en-US/External"}

    def test_base_from_careers_page(self):
        base, site, tenant = sources.workday_base(self.ENTRY["url"])
        self.assertEqual(base, "https://examplebank.wd5.myworkdayjobs.com/wday/cxs/examplebank/External")
        self.assertEqual((site, tenant), ("https://examplebank.wd5.myworkdayjobs.com/External", "examplebank"))

    def test_search_keeps_matching_titles(self):
        posts, fetched = [], []

        def post(url, payload):
            posts.append((url, payload["searchText"]))
            return {"jobPostings": [
                {"title": "Technology Support Analyst", "externalPath": "/job/Home-Location-PA/Tech-Support_R100",
                 "locationsText": "Home Location-PA"},
                {"title": "Branch Teller", "externalPath": "/job/Pittsburgh/Teller_R200", "locationsText": "Pittsburgh, PA"},
                {"title": "Client Support Specialist", "externalPath": "/job/Cleveland/Client-Support_R300",
                 "locationsText": "Cleveland, OH"}]}

        def fetch(url):
            fetched.append(url)
            if url.endswith("R300"):
                raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)
            return {"jobPostingInfo": {"title": "Technology Support Analyst", "location": "Home Location-PA",
                                       "jobDescription": "<p>Pay range: $55,000 - $65,000 per year</p>",
                                       "startDate": "2026-11-20"}}

        jobs = sources.src_workday(self.ENTRY, ["technology support", "client support"],
                                   ["Technology Support Analyst", "Client Support Specialist"],
                                   fetch=fetch, post=post, sleep=lambda s: None)
        self.assertEqual(len(posts), 2)
        self.assertEqual([j["title"] for j in jobs], ["Technology Support Analyst", "Client Support Specialist"])
        tech, client = jobs
        self.assertEqual((tech["company"], tech["workplace"], tech["salary_min"]), ("Example Bank", "remote", 55000))
        self.assertEqual(tech["id"], "workday:examplebank-R100")
        self.assertTrue(tech["apply_url"].endswith("/apply"))
        # The detail page was refused, so the job is kept from the search result.
        self.assertEqual((client["location"], client["workplace"]), ("Cleveland, OH", "onsite"))
        self.assertEqual(client["url"], "https://examplebank.wd5.myworkdayjobs.com/External/job/Cleveland/Client-Support_R300")

    def test_post_retries_rate_limit(self):
        calls, waits = [], []

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b'{"jobPostings": []}'

        def opener(req, timeout=0):
            calls.append(req.full_url)
            if len(calls) < 3:
                raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {"Retry-After": "2"}, None)
            return Resp()

        orig = urllib.request.urlopen
        urllib.request.urlopen = opener
        try:
            got = sources.http_post_json("https://x.wd1.myworkdayjobs.com/wday/cxs/x/y/jobs", {}, sleep=waits.append)
        finally:
            urllib.request.urlopen = orig
        self.assertEqual(got, {"jobPostings": []})
        self.assertEqual((len(calls), waits), (3, [2, 2]))

    def test_shipped_boards_and_my_data_merge(self):
        comps = config.load_companies()
        self.assertTrue(any(w["name"] == "PNC" for w in comps["workday"]))
        for w in comps["workday"]:
            sources.workday_base(w["url"])
        with tempfile.TemporaryDirectory() as d:
            extra = {"workday": [{"name": "My CU", "url": "https://mycu.wd1.myworkdayjobs.com/Careers"},
                                 comps["workday"][0]]}
            orig_path = config.path
            config.path = lambda name: os.path.join(d, name)
            try:
                with open(os.path.join(d, "companies.json"), "w") as f:
                    json.dump(extra, f)
                merged = config.load_companies()
            finally:
                config.path = orig_path
        self.assertEqual(len(merged["workday"]), len(comps["workday"]) + 1)
        self.assertEqual(merged["workday"][-1]["name"], "My CU")

    def test_workday_link_lookup(self):
        seen = []

        def fake(url, **kw):
            seen.append(url)
            return {"jobPostingInfo": {"title": "Solution Center Analyst", "location": "Remote - US",
                                       "remoteType": "Fully Remote", "jobDescription": "<p>Help members.</p>"},
                    "hiringOrganization": {"name": "Example Credit Union"}}
        orig = linkinfo.http_json
        linkinfo.http_json = fake
        try:
            got = linkinfo.lookup("https://excu.wd1.myworkdayjobs.com/en-US/Careers/job/Remote/Solution-Center_R9?source=LinkedIn")
        finally:
            linkinfo.http_json = orig
        self.assertEqual(seen, ["https://excu.wd1.myworkdayjobs.com/wday/cxs/excu/Careers/job/Remote/Solution-Center_R9"])
        self.assertEqual((got["title"], got["company"], got["workplace_hint"]),
                         ("Solution Center Analyst", "Example Credit Union", "remote"))


class LinkTests(unittest.TestCase):
    def test_clean_url(self):
        self.assertEqual(linkinfo.clean_url("https://Jobs.Lever.co/acme/abc-123/?utm_source=x&lever-source=LinkedIn"),
                         "https://jobs.lever.co/acme/abc-123")
        self.assertEqual(linkinfo.clean_url("acme.com/careers?id=5&gh_src=abc"), "https://acme.com/careers?id=5")

    def test_jsonld(self):
        page = """<html><script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting",
        "title":"IT Support Specialist","hiringOrganization":{"@type":"Organization","name":"Acme Corp"},
        "jobLocationType":"TELECOMMUTE","description":"<p>Support Okta and Jamf.</p>",
        "baseSalary":{"@type":"MonetaryAmount","currency":"USD","value":{"@type":"QuantitativeValue",
        "minValue":30,"maxValue":36,"unitText":"HOUR"}}}</script></html>"""
        got = linkinfo.parse_jsonld(page)
        self.assertEqual((got["title"], got["company"], got["location"]), ("IT Support Specialist", "Acme Corp", "Remote"))
        self.assertIn("Okta", got["description"])
        self.assertEqual(got["salary"], (62400, 74880))

    def test_board_links_use_apis(self):
        calls = []

        def fake(url, **kw):
            calls.append(url)
            if "greenhouse" in url:
                return {"title": "Help Desk Analyst", "company_name": "Acme", "location": {"name": "Remote"},
                        "content": "&lt;p&gt;Pay: $60,000 - $70,000&lt;/p&gt;"}
            return {"text": "IT Technician", "categories": {"location": "New York, NY"}, "descriptionPlain": "x",
                    "applyUrl": "https://jobs.lever.co/globex/1/apply", "workplaceType": "hybrid"}
        orig = linkinfo.http_json
        linkinfo.http_json = fake
        try:
            g = linkinfo.lookup("https://job-boards.greenhouse.io/acme/jobs/123?gh_src=li")
            l = linkinfo.lookup("https://jobs.lever.co/globex/1")
        finally:
            linkinfo.http_json = orig
        self.assertEqual(calls[0], "https://boards-api.greenhouse.io/v1/boards/acme/jobs/123")
        self.assertEqual((g["title"], g["company"], g["salary"]), ("Help Desk Analyst", "Acme", (60000, 70000)))
        self.assertEqual((l["title"], l["company"], l["workplace_hint"]), ("IT Technician", "Globex", "hybrid"))


class TrackingTests(unittest.TestCase):
    def setUp(self):
        config.set_home(tempfile.mkdtemp())
        self.con = store.db()
        now = dt.datetime.now(dt.timezone.utc)
        for i, (title, missing) in enumerate([("IT Support Specialist", ["okta", "jamf"]),
                                              ("Senior IT Support Specialist", ["okta"]),
                                              ("Help Desk Technician", ["servicenow"]),
                                              ("Nurse", ["cpr"])]):
            self.con.execute("INSERT INTO jobs (id, title, company, missing, status, score, first_seen, updated) "
                             "VALUES (?,?,?,?,?,?,?,?)", (f"j{i}", title, "Acme", json.dumps(missing), "new", 70,
                                                         now.isoformat(), now.isoformat()))
        self.con.commit()

    def test_heatmap(self):
        rows = self.con.execute("SELECT title, missing FROM jobs").fetchall()
        hm = insights.heatmap(rows, ["IT Support Specialist", "Help Desk Technician"])
        self.assertEqual(hm["skills"][0], ("okta", 2))
        self.assertEqual(dict(hm["roles"]), {"IT Support Specialist": 2, "Help Desk Technician": 1, "Other": 1})
        self.assertEqual(hm["roles"][-1][0], "Other")
        self.assertEqual(hm["cells"][("IT Support Specialist", "okta")], 2)

    def test_status_dates_follow_ups_and_ghosting(self):
        old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=10)).isoformat()
        store.set_status(self.con, "j0", "applied", old)
        store.set_status(self.con, "j1", "applied")
        store.set_status(self.con, "j2", "interview")
        due = insights.follow_ups_due(self.con)
        self.assertEqual([r["id"] for r, _ in due], ["j0"])
        very_old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=40)).isoformat()
        self.con.execute("UPDATE jobs SET applied_at=?, updated=? WHERE id='j0'", (very_old, very_old))
        self.con.commit()
        self.assertEqual(insights.mark_ghosted(self.con), 1)
        f = insights.funnel(self.con)
        self.assertEqual((f["applied"], f["interview"], f["ghosted"], f["waiting"]), (3, 1, 1, 1))
        store.set_status(self.con, "j2", "offer")
        self.assertEqual(insights.funnel(self.con)["offer"], 1)
        store.set_status(self.con, "j2", "new")
        self.assertIsNone(self.con.execute("SELECT applied_at FROM jobs WHERE id='j2'").fetchone()[0])

    def test_old_database_gets_new_columns(self):
        import sqlite3
        home = tempfile.mkdtemp()
        con = sqlite3.connect(os.path.join(home, "jobs.db"))
        con.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, title TEXT, status TEXT)")
        con.commit()
        con.close()
        config.set_home(home)
        cols = {r[1] for r in store.db().execute("PRAGMA table_info(jobs)")}
        self.assertTrue({"applied_at", "interview_at", "followed_up_at", "closed_at"} <= cols)


class QuietServerTests(unittest.TestCase):
    def test_dropped_connections_are_quiet(self):
        import contextlib
        import io
        from jobhunter import web

        class Probe(web.QuietHTTPServer):
            def __init__(self):
                pass
        out = io.StringIO()
        with contextlib.redirect_stderr(out):
            for exc in (ConnectionAbortedError(10053, "aborted"), BrokenPipeError(), ValueError("real bug")):
                try:
                    raise exc
                except Exception:
                    Probe().handle_error(None, ("127.0.0.1", 1))
        self.assertNotIn("ConnectionAbortedError", out.getvalue())
        self.assertNotIn("BrokenPipeError", out.getvalue())
        self.assertIn("ValueError: real bug", out.getvalue())


class HelpTests(unittest.TestCase):
    def test_tips_added_to_known_buttons(self):
        from jobhunter import help as guide
        out = guide.add_tips('<button class="p">Pre-fill application</button><a href="/?s=applied">Applied (5)</a>'
                             '<button>Something new</button>')
        self.assertIn('data-tip="Opens the job', out)
        self.assertIn('data-tip="Jobs you&#x27;ve applied to', out)
        self.assertIn("<button>Something new</button>", out)

    def test_every_tour_has_steps(self):
        from jobhunter import help as guide
        for page in ("jobs", "job", "progress", "skills", "answers", "settings"):
            self.assertTrue(guide.TOURS[page])


class PagesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config.set_home(tempfile.mkdtemp())
        p = config._merge(config.DEFAULT_PROFILE, {})
        p["target_titles"] = ["IT Support Specialist"]
        p["first_name"] = "Jordan"
        config.save_profile(p)
        from jobhunter import web
        from http.server import ThreadingHTTPServer
        cls.web = web
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        web.PORT = cls.srv.server_address[1]
        cls.base = f"http://127.0.0.1:{web.PORT}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def post(self, path, fields):
        req = urllib.request.Request(self.base + path, data=urllib.parse.urlencode(fields).encode(), method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req) as r:
            return r.read().decode()

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as r:
            return r.read().decode()

    def test_pages(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        orig = linkinfo.lookup
        linkinfo.lookup = lambda url: {"title": "IT Support Specialist", "company": "Acme", "location": "Remote",
                                       "description": "Okta, Jamf and ServiceNow.", "apply_url": url,
                                       "salary": (60000, 70000), "workplace_hint": "remote"}
        try:
            page = self.post("/add", {"url": "https://acme.example/jobs/1?utm_source=x"})
        finally:
            linkinfo.lookup = orig
        self.assertIn("Added IT Support Specialist at Acme", page)
        row = store.db().execute("SELECT * FROM jobs").fetchone()
        self.assertEqual((row["url"], row["salary_min"]), ("https://acme.example/jobs/1", 60000))

        listing = self.get("/")
        for header in ("Job Status", "Workplace Setup", "Job Fit"):
            self.assertIn(f'<h3 class="sec">{header}</h3>', listing)
        skills = self.get("/skills")
        self.assertIn("IT Support Specialist (1)", skills)
        self.assertIn("100%", skills)
        self.assertIn("Showing jobs that ask for", self.get("/?s=new&miss=" + json.loads(row["missing"])[0]))

        self.post("/action", {"id": row["id"], "do": "applied", "back": "/"})
        self.assertIn("Applied today", self.get("/?s=applied"))
        progress = self.get("/progress")
        self.assertIn("Follow-ups due (0)", progress)

        self.post("/answers/add", {"question": "Why do you want to work at {company}?",
                                   "answer": "I like {company}."})
        page = self.get("/answers")
        self.assertIn("Why do you want to work at {company}?", page)
        self.assertIn("fills in automatically", page)
        self.assertEqual(answers.find(answers.load(), "Why Globex?", "Globex"), "I like Globex.")
        self.post("/answers/delete", {"key": "why_company"})
        self.assertEqual(answers.load(), {})

    def test_rejected_list(self):
        con = store.db()
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        con.execute("INSERT INTO jobs (id, title, company, status, score, first_seen, updated) VALUES "
                    "('rj1', 'Help Desk Analyst', 'Initech', 'new', 70, ?, ?)", (now, now))
        con.commit()
        store.set_status(con, "rj1", "applied")
        page = self.get("/progress")
        self.assertIn("Waiting to hear back (", page)
        self.assertIn("Initech", page.split('data-tour="waiting"')[1].split('data-tour="rejected"')[0])
        self.post("/action", {"id": "rj1", "do": "rejected", "back": "/progress"})
        page = self.get("/progress")
        self.assertIn("Initech", page.split('data-tour="rejected"')[1])
        self.assertIn("rejected today", page)
        self.assertIn('<div class="frow"><div>Rejected</div><div><div class="bar rej"', page)
        self.assertIsNotNone(con.execute("SELECT closed_at FROM jobs WHERE id='rj1'").fetchone()[0])
        self.post("/action", {"id": "rj1", "do": "applied", "back": "/progress"})
        row = con.execute("SELECT status, closed_at, applied_at FROM jobs WHERE id='rj1'").fetchone()
        self.assertEqual((row[0], row[1]), ("applied", None))
        self.assertIsNotNone(row[2])
        con.execute("DELETE FROM jobs WHERE id='rj1'")
        con.commit()

    def test_remove_added_job(self):
        con = store.db()
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        con.execute("INSERT INTO jobs (id, source, title, company, url, apply_url, description, status, score, "
                    "first_seen, updated) VALUES "
                    "('manual:rm1', 'manual', 'Help Desk Lead', 'Umbrella', 'https://u.example/1', 'https://u.example/1', "
                    "'', 'new', 100, ?, ?), "
                    "('greenhouse:rm2', 'greenhouse', 'Help Desk Analyst', 'Hooli', 'https://h.example/2', "
                    "'https://h.example/2', '', 'new', 70, ?, ?)", (now, now, now, now))
        con.commit()
        page = self.get("/")
        umbrella = page.split("Umbrella")[1].split('data-tour="card"')[0]
        hooli = page.split("Hooli")[1].split('data-tour="card"')[0]
        self.assertIn(">Remove</button>", umbrella)
        self.assertIn("return confirm(", umbrella)
        self.assertNotIn(">Remove</button>", hooli)
        self.assertIn(">Remove</button>", self.get("/job?id=manual:rm1"))
        # A request from a sandboxed page or file (Origin: null) is refused, like every other action.
        req = urllib.request.Request(self.base + "/action", method="POST",
                                     data=urllib.parse.urlencode({"id": "manual:rm1", "do": "remove"}).encode(),
                                     headers={"Content-Type": "application/x-www-form-urlencoded", "Origin": "null"})
        with self.assertRaises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req)
        self.assertEqual(err.exception.code, 403)
        self.assertIsNotNone(con.execute("SELECT 1 FROM jobs WHERE id='manual:rm1'").fetchone())
        self.post("/action", {"id": "manual:rm1", "do": "remove", "back": "/job?id=manual:rm1"})
        self.assertIsNone(con.execute("SELECT 1 FROM jobs WHERE id='manual:rm1'").fetchone())
        self.post("/action", {"id": "greenhouse:rm2", "do": "remove", "back": "/"})
        self.assertIsNotNone(con.execute("SELECT 1 FROM jobs WHERE id='greenhouse:rm2'").fetchone())
        con.execute("DELETE FROM jobs WHERE id='greenhouse:rm2'")
        con.commit()

    def test_tips_and_tour_toggle(self):
        p = config.load_profile()
        p.update(show_tips=True, tour_seen=[])
        config.save_profile(p)
        page = self.get("/progress")
        self.assertIn('<body class="tips">', page)
        self.assertIn("auto=true", page)
        self.assertIn("Show tips", page)
        self.post("/tour/seen", {"page": "progress"})
        self.assertIn("auto=false", self.get("/progress"))
        self.assertIn("auto=true", self.get("/answers"))
        self.assertIn("Tips and tours are off", self.post("/tips", {"on": ""}))
        page = self.get("/answers")
        self.assertIn('<body class="">', page)
        self.assertIn("auto=false", page)
        self.assertIn("Take the tour", page)
        self.post("/tips", {"on": "1"})
        self.assertIn("auto=true", self.get("/progress"))
        self.post("/tour/seen", {"page": "../etc"})
        self.assertNotIn("../etc", config.load_profile()["tour_seen"])

    def test_search_button(self):
        import time
        release = threading.Event()
        calls = []

        def fake_search(profile, log=print, letters=20):
            calls.append(1)
            log("Fetched 12 listings in total.")
            release.wait(10)
            log("3 new matches saved.")
            return 3
        orig = self.web.run_search
        self.web.run_search = fake_search
        try:
            self.assertIn("Search for new jobs", self.get("/answers"))
            self.assertIn("Search started", self.post("/search", {}))
            self.assertIn("Searching for new jobs", self.get("/progress"))
            self.assertIn("setTimeout(tick", self.get("/"))
            self.assertNotIn("setTimeout(tick", self.get("/skills"))
            self.assertIn("already running", self.post("/search", {}))
            release.set()
            for _ in range(50):
                if not self.web.SEARCH["running"]:
                    break
                time.sleep(0.1)
            page = self.get("/skills")
            self.assertIn("Last search:", page)
            self.assertIn("3 new matches saved", page)
            self.assertEqual(len(calls), 1)
        finally:
            release.set()
            self.web.run_search = orig


if __name__ == "__main__":
    unittest.main()

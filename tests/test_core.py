"""Offline tests: no network, no real personal data. Run with: python -m unittest discover tests"""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from jobhunter import config, locations, matching, resume, sources, store  # noqa: E402

SAMPLE = os.path.join(ROOT, "examples", "sample_resume.txt")
SAMPLE_DOCX = os.path.join(ROOT, "examples", "sample_resume.docx")


def profile_from_sample():
    from jobhunter.web import apply_parsed
    parsed = resume.parse_resume(resume.extract_text(SAMPLE))
    p = apply_parsed(config._merge(config.DEFAULT_PROFILE, {}), parsed, overwrite_empty_only=False)
    p["resumes"] = [{"label": "Sample", "file": "resumes/sample_resume.txt"}]
    return p


def fake_job(title, location, desc="", source="greenhouse", hint=None, salary=(None, None)):
    return sources.job(source, uuid.uuid4().hex[:8], title, "Acme", location, "https://example.com/j",
                       "https://example.com/j/apply", desc, None, salary, hint)


class ResumeTests(unittest.TestCase):
    def test_parse_txt_and_docx(self):
        for f in (SAMPLE, SAMPLE_DOCX):
            r = resume.parse_resume(resume.extract_text(f))
            self.assertEqual((r["first_name"], r["last_name"]), ("Jordan", "Rivera"))
            self.assertEqual(r["email"], "jordan.rivera@example.com")
            self.assertEqual((r["city"], r["state"]), ("Brooklyn", "NY"))
            self.assertIn("IT Support Specialist", r["target_titles"])
            self.assertIn("okta", r["skills"])
            self.assertGreaterEqual(r["years_experience"], 6)
            self.assertTrue(any("40%" in a for a in r["achievements"]))

    def test_core_title(self):
        self.assertEqual(resume.core_title("Senior IT Support Specialist II"), "IT Support Specialist")


class LocationTests(unittest.TestCase):
    def test_workplace(self):
        self.assertEqual(locations.workplace("Remote - US"), "remote")
        self.assertEqual(locations.workplace("New York, NY (Hybrid)"), "hybrid")
        self.assertEqual(locations.workplace("New York, NY", "You'll work 3 days a week in the office."), "hybrid")
        self.assertEqual(locations.workplace("Austin, TX", "Join our team."), "onsite")
        self.assertEqual(locations.workplace("Chicago, IL", "", "OnSite"), "onsite")

    def test_local(self):
        self.assertTrue(locations.is_local("Jersey City, NJ", "Brooklyn", "NY"))
        self.assertTrue(locations.is_local("New York, New York, United States", "New York", "NY"))
        self.assertFalse(locations.is_local("Albany, New York", "New York", "NY"))
        self.assertFalse(locations.is_local("San Francisco, CA", "New York", "NY"))
        # A metro place name in another state isn't local.
        self.assertFalse(locations.is_local("Brooklyn, OH", "New York", "NY"))
        self.assertFalse(locations.is_local("Queens, TX", "Brooklyn", "NY"))
        self.assertTrue(locations.is_local("Columbus, OH; Brooklyn, NY", "New York", "NY"))
        self.assertTrue(locations.is_local("Stamford, CT", "New York", "NY"))
        self.assertFalse(locations.is_local("Arlington, TX", "Washington", "DC"))
        self.assertTrue(locations.is_local("Arlington, VA", "Washington", "DC"))
        self.assertTrue(locations.is_local("Springfield, IL", "Decatur", "IL"))   # small town: same state

    def test_remote_country(self):
        self.assertTrue(locations.remote_ok_for("Remote - USA"))
        self.assertTrue(locations.remote_ok_for("Anywhere in the world"))
        self.assertTrue(locations.remote_ok_for("Remote (Texas)"))
        self.assertFalse(locations.remote_ok_for("Remote - EMEA"))
        self.assertFalse(locations.remote_ok_for("Toronto, Canada"))
        self.assertTrue(locations.remote_ok_for("Toronto, Canada", "CA"))


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.p = profile_from_sample()
        self.p["search"]["location"] = "New York, NY"
        self.rlow = matching.resume_low(self.p, [resume.extract_text(SAMPLE)])

    def score(self, j):
        return matching.score_job(j, self.p, self.rlow)

    def test_good_remote_match(self):
        r = self.score(fake_job("IT Support Specialist", "Remote - US", "Okta, Jamf, ServiceNow, Microsoft 365"))
        self.assertIsNotNone(r)
        self.assertGreaterEqual(r[0], 60)

    def test_unrelated_title_dropped(self):
        self.assertIsNone(self.score(fake_job("Marketing Manager", "Remote - US")))
        self.assertIsNone(self.score(fake_job("Software Engineer", "Remote - US")))

    def test_location_and_workplace_filters(self):
        self.assertIsNotNone(self.score(fake_job("Help Desk Technician", "Manhattan, NY")))
        self.assertIsNone(self.score(fake_job("Help Desk Technician", "Denver, CO")))
        self.p["search"]["workplace"] = ["remote"]
        self.assertIsNone(self.score(fake_job("Help Desk Technician", "Manhattan, NY")))

    def test_salary_floor(self):
        self.p["search"]["min_salary"] = 70000
        self.assertIsNone(self.score(fake_job("IT Support Specialist", "Remote", salary=(40000, 50000))))
        self.assertIsNotNone(self.score(fake_job("IT Support Specialist", "Remote", salary=(75000, 90000))))

    def test_gap_analysis(self):
        g = matching.gap_analysis("We use Okta, Jamf, Splunk and Kubernetes. 3+ years of experience.", self.rlow,
                                  self.p["skills"], 8)
        self.assertIn("okta", g["matched"])
        self.assertIn("splunk", g["missing"])
        self.assertIn("kubernetes", g["missing"])
        self.assertEqual(g["fit"], 50)


class SourceParsingTests(unittest.TestCase):
    def test_parsers(self):
        canned = {
            "greenhouse": {"jobs": [{"id": 1, "title": "IT Support Specialist", "location": {"name": "New York, NY"},
                                     "content": "&lt;p&gt;Hybrid, 3 days a week in the office. Salary: $70,000 - $85,000&lt;/p&gt;",
                                     "absolute_url": "https://x/1", "updated_at": "2026-11-01T00:00:00Z"}]},
            "lever": [{"id": "a", "text": "Help Desk Technician", "categories": {"location": "Remote - US"},
                       "workplaceType": "remote", "hostedUrl": "https://jobs.lever.co/x/a", "descriptionPlain": "Jamf",
                       "createdAt": 1767225600000}],
            "ashby": {"jobs": [{"id": "z", "title": "IT Support Specialist", "location": "Brooklyn, NY",
                                "workplaceType": "OnSite", "jobUrl": "https://jobs.ashbyhq.com/x/z",
                                "descriptionPlain": "Okta"}]},
        }
        orig = sources.http_json
        try:
            sources.http_json = lambda url, **kw: canned["greenhouse"] if "greenhouse" in url else (
                canned["lever"] if "lever" in url else canned["ashby"])
            g = sources.src_greenhouse("x")[0]
            self.assertEqual((g["workplace"], g["salary_min"], g["salary_max"]), ("hybrid", 70000, 85000))
            self.assertEqual(sources.src_lever("x")[0]["workplace"], "remote")
            self.assertEqual(sources.src_ashby("x")[0]["workplace"], "onsite")
        finally:
            sources.http_json = orig

    def test_salary(self):
        self.assertEqual(sources.parse_salary("$35/hr"), (72800, 72800))
        self.assertEqual(sources.parse_salary("$60k - $80k"), (60000, 80000))
        self.assertEqual(sources.parse_salary("€50,000"), (None, None))


class AppFlowTests(unittest.TestCase):
    """Upload a resume through the web page, save settings, store jobs, draft a letter."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        config.set_home(cls.tmp)
        from jobhunter import web
        from http.server import ThreadingHTTPServer
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        web.PORT = cls.srv.server_address[1]
        cls.base = f"http://127.0.0.1:{web.PORT}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def post(self, path, body, ctype):
        req = urllib.request.Request(self.base + path, data=body, headers={"Content-Type": ctype}, method="POST")
        with urllib.request.urlopen(req) as r:
            return r.read().decode()

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as r:
            return r.read().decode()

    def test_flow(self):
        setup = self.get("/")
        self.assertIn("upload your resume", setup)
        self.assertNotIn("Search for new jobs", setup)
        boundary = "XyZ" + uuid.uuid4().hex
        with open(SAMPLE_DOCX, "rb") as fh:
            data = fh.read()
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"label\"\r\n\r\nIT\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"resume\"; filename=\"my resume.docx\"\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
        page = self.post("/upload", body, f"multipart/form-data; boundary={boundary}")
        self.assertIn("Read your resume", page)
        self.assertIn("jordan.rivera@example.com", page)
        p = config.load_profile()
        self.assertEqual(p["search"]["location"], "Brooklyn, NY")
        self.assertEqual(p["resumes"][0]["file"], "resumes/my_resume.docx")

        jobs = [fake_job("IT Support Specialist", "Remote - US", "Okta and Jamf. Splunk a plus."),
                fake_job("Help Desk Technician", "New York, NY (Hybrid)", "ServiceNow"),
                fake_job("Help Desk Technician", "Denver, CO", "ServiceNow", source="themuse"),
                fake_job("Nurse Practitioner", "Remote - US", "")]
        self.assertEqual(store.save_matches(jobs, p), 2)
        from jobhunter.letters import draft_letters
        os.environ.pop("ANTHROPIC_API_KEY", None)
        self.assertEqual(draft_letters(p)[0], 2)
        row = store.db().execute("SELECT * FROM jobs WHERE workplace='remote'").fetchone()
        self.assertIn("Jordan Rivera", row["cover_letter"])
        self.assertIn("splunk", row["missing"])
        listing = self.get("/?wp=hybrid")
        self.assertIn("Help Desk Technician", listing)
        self.assertNotIn("Remote - US", listing)
        self.assertIn("Cover letter", self.get("/job?id=" + urllib.request.quote(row["id"])))

        # Saving settings with only remote drops the hybrid job.
        form = urllib.parse.urlencode({"first_name": "Jordan", "target_titles": "IT Support Specialist\nHelp Desk Technician",
                                       "keywords": "IT Support", "skills": "Okta, Jamf", "workplace": "remote",
                                       "min_match": "40", "location": "New York, NY"}).encode()
        page = self.post("/settings", form, "application/x-www-form-urlencoded")
        self.assertIn("Removed 1 jobs", page)
        self.assertEqual(config.load_profile()["search"]["workplace"], ["remote"])

    def test_cross_site_post_blocked(self):
        req = urllib.request.Request(self.base + "/search", data=b"", method="POST",
                                     headers={"Origin": "https://evil.example"})
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        self.assertEqual(e.exception.code, 403)


import urllib.parse  # noqa: E402
import urllib.error  # noqa: E402

if __name__ == "__main__":
    unittest.main()

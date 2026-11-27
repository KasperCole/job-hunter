# Job Hunter

Upload your resume, and Job Hunter finds remote, hybrid and on-site jobs that fit it, writes a cover letter for each one, and fills in the application on the company's own website. You check the form and click Submit yourself.

It runs on your own computer. Your resume and everything else it learns about you stays in a local folder and is never uploaded anywhere.

## What it does

1. **Reads your resume** (Word, PDF or text). It finds your name and contact details, city, recent job titles, years of experience, skills and achievements. A setup page shows what it found so you can fix anything it got wrong.
2. **Searches for jobs** using your job titles as keywords. You choose **Remote**, **Hybrid**, **On-site** or any mix, plus your area (for example "New York, NY"). Hybrid and on-site jobs are only kept if they're in your metro area. Remote jobs are only kept if they're open to people in your country.
3. **Scores every job two ways:**
   - **Match** (0 to 100): how well the job fits what you're looking for, based on title, skills, pay, location and level.
   - **Fit** (0 to 100): the share of the skills the listing asks for that are on your resume. The skills you're missing are listed, which is useful for deciding what to learn next.
4. **Writes a cover letter** for each match, using only experience that's on your resume. With an Anthropic API key, Claude writes it. Without one, a template fills in your own achievements.
5. **Pre-fills the application** on the company's site: name, email, phone, links, location, resume file, cover letter, the work-authorization answers you set, and your saved answers to custom questions. It works best on Greenhouse, Lever and Ashby forms, which many companies use. It never clicks Submit.
6. **Remembers your answers to custom questions.** The **Answers** page lists the questions application forms ask most often ("Why do you want to work at ...?", "Are you willing to relocate?", "Years of ... experience?"), with a box to answer each. Answers you type into a pre-filled form are saved there too when you close the window. Similar questions share one answer, and `{company}` and `{title}` in an answer are replaced for each job. An answer that names a specific company is held for you to check before it's used on another company's form.
7. **Shows which skills to learn next.** The **Skills** page is a heat map of the skills listings ask for that aren't on your resume, by the kind of role you're looking for. Click a skill to see the jobs that want it.
8. **Tracks your applications.** After you apply, mark jobs as interview, offer or rejected. The **Progress** page shows how many applications got replies, interviews and offers, lists follow-ups that are due a week after you apply, and moves jobs with no news after 30 days to Ghosted.

## Where the jobs come from

Job Hunter only uses official public APIs and companies' own public job boards. It does not log in to or scrape LinkedIn, Indeed or Glassdoor, whose terms forbid it.

| Source | Covers | Key needed |
|---|---|---|
| Company career sites on Greenhouse, Lever and Ashby (list in `data/companies.json`) | Remote, hybrid and on-site jobs at about 100 companies. You apply directly on the company's site. | No |
| The Muse | Jobs in your city, plus remote jobs | No |
| Remotive, RemoteOK, Himalayas, Jobicy | Remote jobs | No |
| [Adzuna](https://developer.adzuna.com/) | Jobs at local employers in any US city, within a distance you choose. The best source for on-site and hybrid work. | Free |
| [USAJOBS](https://developer.usajobs.gov/) | US federal government jobs | Free |

To add a single job you found yourself, paste its link into **Add a job you found yourself** on the Jobs page. Job Hunter reads the title, company, location, pay and description from the posting (Greenhouse, Lever and Ashby links always work, and most other career sites do too).

To add a company, find the board name in its careers link (`boards.greenhouse.io/<name>`, `jobs.lever.co/<name>` or `jobs.ashbyhq.com/<name>`) and add it to `data/companies.json`, or to `my-data/companies.json` to keep your list private.

## Install

You need **Python 3.10 or newer**.

- **Windows:** install Python from [python.org](https://www.python.org/downloads/) and tick **"Add python.exe to PATH"** during setup.
- **Mac:** open Terminal and run `python3 --version`. If it isn't installed, macOS offers to install it.
- **Linux:** Python 3 is usually already installed.

Then download this project (green **Code** button, then **Download ZIP**, then unzip it), or `git clone` it. Open a terminal in the project folder and install the optional extras:

```
pip install -r requirements.txt
python -m playwright install chromium
```

On a Mac, use `pip3` and `python3`. The extras are optional: without them the app still finds and scores jobs, but it can't read PDF resumes, pre-fill forms, or use Claude for cover letters.

## First run

Double-click **`start-windows.bat`** (Windows) or **`start-mac.command`** (Mac), or run:

```
python main.py
```

Your browser opens the app at `http://127.0.0.1:8765`.

1. **Upload your resume.** You can add more than one version later (for example a technical one and a general one). For each job, the app uses the version that covers the most of the skills it asks for.
2. **Check your profile.** Fix your job titles, skills and contact details if needed. Tick **Remote**, **Hybrid** and/or **On-site**, enter your area, and set a minimum salary if you want one. Save.
3. **Click "Search for new jobs".** The button is at the top of every page. The first search takes a minute or two, and you can keep using the app while it runs.
4. **Review your matches.** Filter by Remote / Hybrid / On-site and by Fit. Open a job to read and edit its cover letter.
5. **Click "Pre-fill application".** A browser window opens with the form filled in. Answer anything left blank, check everything, and click Submit. Then click **Mark applied**.

Click **Search for new jobs** once a day to pick up new listings.

## Help inside the app

The first time you open each page, a short tour points out what each part does. Hover over any button (or tab to it with the keyboard) for a one-line explanation. Untick **Show tips** at the top of any page to turn tips and tours off, tick it to bring them back, and click **Take the tour** to replay a page's tour at any time. The setting is saved in your profile, so each person using the app chooses for themselves.

## Claude-written cover letters (optional)

Create an API key at [console.anthropic.com](https://console.anthropic.com/), then set it before starting the app:

- Windows (Command Prompt): `set ANTHROPIC_API_KEY=sk-ant-...`
- Mac / Linux: `export ANTHROPIC_API_KEY=sk-ant-...`

Each letter costs a few cents. Without a key, you get template letters, which cost nothing.

## Several people on one computer

Each person's data lives in its own folder. By default it's `my-data/` inside the app folder. To keep separate profiles, start the app with a different folder for each person:

```
python main.py --home "C:\Users\alex\JobHunter"
```

or set the `JOBHUNTER_HOME` environment variable.

## Commands

| Command | What it does |
|---|---|
| `python main.py` | Open the app (the everyday command) |
| `python main.py setup resume.docx` | Read a resume from the command line instead of the setup page |
| `python main.py find` | Search for new jobs without opening the app |
| `python main.py run` | Search, then open the app |
| `python main.py rescore` | Re-check unreviewed jobs after editing `profile.json` by hand |
| `python main.py export` | Save all jobs, with Match, Fit and missing skills, to a CSV for Excel or Google Sheets |

## Why it doesn't click Submit for you

Job sites ban accounts that submit applications automatically, many forms have CAPTCHAs, and some questions only you should answer. Submitting applications you haven't read can also hurt your chances. So Job Hunter does everything up to the Submit button, and you take the last step. That usually takes under a minute per job.

## Why it doesn't rewrite your resume for each job

Some job tools rewrite your resume for every listing. Job Hunter doesn't, on purpose:

- Doing it well takes an AI model. Without one, a program can only reorder bullets or stuff in the listing's keywords, which reads as robotic to recruiters and can trip keyword-stuffing checks.
- Even with an AI model, rewrites can overstate or invent experience, and you'd have to check every copy line by line.
- You know which of your experience matters most for a role. A few minutes tailoring your own resume, using the **Missing** skills on each job page and the **Skills** page as a guide, works better.

What it does instead: you can upload more than one version of your resume (for example a technical one and a general one), and for each job the app picks the version that covers the most of the skills the listing asks for.

## Your privacy

- Everything personal is stored in `my-data/`: your resume, `profile.json`, the job database, cover letters, your saved answers (`answers.json`) and the pre-fill browser profile. Answers to questions about passwords, Social Security numbers, dates of birth or bank details are never saved. That folder is in `.gitignore`, so it is never committed if you fork this project.
- The app talks only to the job sources listed above and, if you add a key, the Anthropic API (which receives your resume text and the job description to write a letter).
- The local web page only accepts connections from your own computer.

## Limits

- The resume reader is rule-based. Unusual layouts (tables, columns, text inside images) may need more fixing on the setup page. A scanned PDF can't be read; use a Word copy.
- "Near you" is based on a table of US metro areas in `jobhunter/locations.py`. If your town isn't in a listed metro, jobs in your state count as local. Adzuna searches by distance, so add a free Adzuna key for the best local results.
- Pre-fill recognizes common form fields and questions you've saved answers for. Other questions are left for you, and radio buttons and checkboxes are always left for you.

## Contributing

Pull requests are welcome, especially more skills for other fields (`jobhunter/skills.py`), more metro areas (`jobhunter/locations.py`), more company boards (`data/companies.json`) and more official job APIs. Run the tests before sending one:

```
python -m unittest discover tests
```

The tests use a made-up sample resume in `examples/` and never touch the network. Please don't commit real resumes or personal details.

## License

MIT. See [LICENSE](LICENSE).

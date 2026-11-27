"""Built-in help: short tips when you hover over a button, and a step-by-step tour of each page.

Both are on for new users. The "Show tips" box at the top of every page turns them off (or back on),
and "Take the tour" replays the current page's tour at any time.
"""
import html
import json
import re

# What each button and tab does, shown when you hover over it (or tab to it with the keyboard).
TIPS = {
    # top navigation
    "Jobs": "Your matched jobs, sorted by how well they fit.",
    "Progress": "How your applications are going, and which ones need a follow-up.",
    "Skills": "The skills job listings ask for that aren't on your resume yet.",
    "Answers": "Your saved answers to the extra questions application forms ask.",
    "My profile": "Your resume, the jobs you're looking for, and the details used to fill in applications.",
    "Search for new jobs": "Checks the job boards for new listings that fit your profile. Takes 1 to 3 minutes; "
                           "you can keep using the app meanwhile.",
    # job status tabs
    "New": "Jobs found by the search that you haven't looked at yet.",
    "Saved": "Jobs you saved to look at later.",
    "Applied": "Jobs you've applied to. You'll get a follow-up reminder after a week.",
    "Interview": "Jobs where you got an interview.",
    "Offer": "Jobs that made you an offer.",
    "Rejected": "Jobs that turned you down.",
    "Ghosted": "Jobs with no reply 30 days after you applied or followed up.",
    "Skipped": "Jobs you decided not to apply to.",
    # filters
    "All": "Show every job in this tab.",
    "Remote": "Only fully remote jobs.",
    "Hybrid": "Only hybrid jobs in your area.",
    "On-site": "Only on-site jobs in your area.",
    "Any": "Don't filter by Fit.",
    "Fair+": "Jobs where your resume covers at least 35% of the skills listed.",
    "Good+": "Jobs where your resume covers at least 55% of the skills listed.",
    "Strong": "Jobs where your resume covers at least 75% of the skills listed.",
    "Match": "Sort by Match: how well the job fits what you're looking for.",
    "Fit": "Sort by Fit: how much of the listing's skill list your resume covers.",
    # job actions
    "Pre-fill application": "Opens the job's application form in a new browser window with your details, resume, "
                            "cover letter and saved answers filled in. You check it and click Submit yourself.",
    "Open listing": "Opens the job posting on the company's site in a new tab.",
    "Mark applied": "Moves the job to Applied once you've submitted the application.",
    "Save for later": "Moves the job to Saved so you can come back to it.",
    "Skip": "Hides the job. You can find it again under Skipped.",
    "Got an interview": "Moves the job to Interview.",
    "They replied: interview": "Moves the job to Interview.",
    "I followed up": "Notes that you sent a follow-up, so the reminder goes away.",
    "Got an offer": "Moves the job to Offer.",
    "Mark rejected": "Moves the job to your Rejected list (Progress page and the Rejected tab).",
    "Undo": "Moves the job back to Applied.",
    "Move back to New": "Puts the job back in New.",
    "Rewrite cover letter": "Throws away this cover letter and writes a fresh one.",
    "Save letter": "Saves your edits. Pre-fill uses this text.",
    "Add job": "Adds the job from the link. The title, company and description are read from the posting.",
    # answers, profile
    "Save answer": "Saves this answer. Pre-fill fills it in whenever a form asks this question.",
    "Delete": "Removes this question and its answer.",
    "Add": "Adds the question to your answer bank.",
    "Save profile": "Saves your profile and re-checks your current matches against it.",
    "Upload and analyze": "Reads the resume and fills in your profile from it.",
    "Remove": "Removes this resume from your profile. The file stays in my-data/resumes.",
    "Take the tour": "Walks you through this page step by step.",
}

# The tour for each page: (where to point, heading, what it does). Steps whose target isn't on the page are skipped.
TOURS = {
    "jobs": [
        (None, "Welcome to Job Hunter",
         "This short tour shows what each part of the page does. It takes about a minute. "
         "You can leave at any time, and replay it later with \"Take the tour\" at the top."),
        ('[data-tour="nav"]', "Pages",
         "Jobs is your list of matches. Progress tracks your applications, Skills shows what to learn next, "
         "Answers keeps your answers to form questions, and My profile holds your resume and preferences."),
        ('[data-tour="search"]', "Search for new jobs",
         "Click this once a day. It checks the job boards for new listings that fit your profile. "
         "It takes 1 to 3 minutes, and the list updates by itself."),
        ('[data-tour="tabs"]', "Where each job is",
         "Every job sits in one tab: New, Saved, Applied, Interview, Offer, Rejected, Ghosted or Skipped. "
         "The buttons on a job move it between tabs."),
        ('[data-tour="filters"]', "Narrow the list",
         "Show only remote, hybrid or on-site jobs, hide jobs that don't fit your skills well, "
         "and sort by Match or Fit."),
        ('[data-tour="card"]', "A job",
         "Click the title to read the listing and its cover letter. Match is how well the job fits what you "
         "want; Fit is how much of its skill list your resume covers. \"Missing\" lists skills it asks for "
         "that your resume doesn't show."),
        ('[data-tour="card-actions"]', "Apply",
         "Pre-fill application opens the form with everything filled in. Check it, answer anything blank, "
         "click Submit on the company's site, then come back and click Mark applied."),
        ('[data-tour="add"]', "Found a job yourself?",
         "Paste its link here and Job Hunter adds it, with a cover letter."),
        ('[data-tour="tips"]', "Tips on or off",
         "Hover over any button to see what it does. Untick this box to turn tips and tours off; "
         "tick it to bring them back."),
    ],
    "job": [
        ('[data-tour="job-actions"]', "Apply for this job",
         "Pre-fill opens the application with your details filled in; you check it and submit it yourself. "
         "Mark applied once you have."),
        ('[data-tour="scores"]', "Why it matched",
         "Match is how well the job fits what you want. Fit is how much of its skill list your resume covers. "
         "\"Missing\" is what to brush up on or mention if you have it."),
        ('[data-tour="letter"]', "Cover letter",
         "Edit it here and click Save letter. Pre-fill pastes this text into the form."),
    ],
    "progress": [
        ('[data-tour="funnel"]', "How it's going",
         "How many applications got a reply, an interview, an offer or a rejection."),
        ('[data-tour="followups"]', "Follow-ups",
         "Applications from a week or more ago that you haven't followed up on. Send a short note to the "
         "recruiter, then click I followed up."),
        ('[data-tour="waiting"]', "Waiting to hear back",
         "Every application still waiting for a reply. When a company turns you down, click Mark rejected."),
        ('[data-tour="rejected"]', "Rejected",
         "Jobs that turned you down, kept here for your records. Undo moves one back to Applied."),
    ],
    "skills": [
        ('[data-tour="heat"]', "Skills to learn next",
         "Rows are the kinds of jobs you want; columns are skills you're missing. Darker cells mean more of "
         "those jobs ask for that skill. Click a skill to see the jobs."),
        ('[data-tour="skill-filters"]', "Which jobs to count",
         "Count every job, only good matches, or only recent ones."),
    ],
    "answers": [
        (None, "Your answer bank",
         "Application forms often ask extra questions like \"Why do you want to work here?\". "
         "Pre-fill lists them here, most common first."),
        ('[data-tour="answer"]', "Answer once, reuse",
         "Type an answer and click Save answer. Pre-fill fills it in on every form that asks the same or a "
         "similar question. {company} and {title} are replaced with each job's company and title."),
        ('[data-tour="add-question"]', "Add your own",
         "Add a question you expect to see, with your answer."),
    ],
    "settings": [
        ('[data-tour="resumes"]', "Your resumes",
         "Upload one or more versions. For each job, Job Hunter uses the one that covers the most of what "
         "it asks for."),
        ('[data-tour="looking-for"]', "What you're looking for",
         "Job titles, remote, hybrid or on-site, your area, and minimum pay. The search uses these."),
        ('[data-tour="details"]', "Your details",
         "Used to fill in application forms. Check they're right before you pre-fill."),
    ],
}

CSS = """
[data-tip]{position:relative}
body.tips [data-tip]:hover::after,body.tips [data-tip]:focus-visible::after{content:attr(data-tip);position:absolute;left:0;top:calc(100% + 6px);
width:max-content;max-width:260px;white-space:normal;background:var(--ink);color:var(--bg);font:400 12.5px/1.4 system-ui,sans-serif;
padding:6px 9px;border-radius:6px;z-index:50;pointer-events:none;text-align:left;box-shadow:0 2px 8px rgba(0,0,0,.2)}
header nav [data-tip]:hover::after,header nav [data-tip]:focus-visible::after,.tip-r:hover::after{left:auto;right:0}
.tipsbar{display:flex;gap:12px;align-items:center;justify-content:flex-end;font-size:13px;color:var(--mute);margin:6px 0 0}
.tipsbar label{display:inline-flex;gap:5px;align-items:center;margin:0;color:var(--mute);font-size:13px;cursor:pointer}
.tipsbar button{font-size:13px;padding:3px 10px}
.tour-hi{position:relative;z-index:60;border-radius:8px;box-shadow:0 0 0 4px var(--acc),0 0 0 100vmax rgba(0,0,0,.45)!important}
#tourcard{position:fixed;z-index:70;max-width:360px;width:calc(100vw - 32px);background:var(--card);color:var(--ink);border:1px solid var(--line);
border-radius:12px;padding:14px 16px;box-shadow:0 8px 30px rgba(0,0,0,.3)}
#tourcard h3{margin:0 0 6px;font-size:16px}#tourcard p{margin:0 0 10px;font-size:14px}
#tourcard .foot{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}
#tourcard .n{font-size:12px;color:var(--mute)}#tourcard label{display:inline-flex;gap:5px;align-items:center;margin:8px 0 0;font-size:12.5px}
#tourdim{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:55}
"""

TOUR_JS = r"""<script>(function(){
var steps=%(steps)s, page=%(page)s, auto=%(auto)s, i=0, card=null, dim=null, hi=null, off=false;
function post(path,data){try{var b=new URLSearchParams(data);return fetch(path,{method:'POST',body:b,headers:{'Content-Type':'application/x-www-form-urlencoded'}});}catch(e){}}
function clear(){if(hi){hi.classList.remove('tour-hi');hi=null;}if(dim){dim.remove();dim=null;}}
function end(){clear();if(card){card.remove();card=null;var p=post('/tour/seen',{page:page});
  if(off){Promise.resolve(p).then(function(){return post('/tips',{on:''});}).then(function(){location.reload();});}}}
function show(k){
  var live=steps.filter(function(s){return !s[0]||document.querySelector(s[0]);});
  if(!live.length)return; steps=live; i=Math.max(0,Math.min(k,steps.length-1)); clear();
  var s=steps[i], el=s[0]?document.querySelector(s[0]):null;
  if(el){el.scrollIntoView({block:'center',behavior:'instant'});el.classList.add('tour-hi');hi=el;}
  else{dim=document.createElement('div');dim.id='tourdim';document.body.appendChild(dim);}
  if(!card){card=document.createElement('div');card.id='tourcard';card.setAttribute('role','dialog');document.body.appendChild(card);}
  var last=i==steps.length-1;
  card.innerHTML='<h3></h3><p></p><div class="foot"><span class="n">'+(i+1)+' of '+steps.length+'</span><span class="btns" style="margin:0">'
    +(i?'<button type="button" id="tour-back">Back</button>':'')+'<button type="button" id="tour-skip">'+(last?'Close':'Skip tour')+'</button>'
    +'<button type="button" class="p" id="tour-next">'+(last?'Done':'Next')+'</button></span></div>'
    +'<label><input type="checkbox" id="tour-off"'+(off?' checked':'')+'> Don\'t show tips and tours again</label>';
  card.querySelector('h3').textContent=s[1]; card.querySelector('p').textContent=s[2];
  card.querySelector('#tour-next').onclick=function(){last?end():show(i+1);};
  card.querySelector('#tour-skip').onclick=end;
  card.querySelector('#tour-off').onchange=function(){off=this.checked;};
  var b=card.querySelector('#tour-back'); if(b)b.onclick=function(){show(i-1);};
  var r=el?el.getBoundingClientRect():null, ch=card.offsetHeight, vh=innerHeight, cw=card.offsetWidth;
  var top=!r?(vh-ch)/2:(r.bottom+12+ch<vh?r.bottom+12:(r.top-12-ch>0?r.top-12-ch:vh-ch-12));
  var left=!r?(innerWidth-cw)/2:Math.min(Math.max(12,r.left),innerWidth-cw-12);
  card.style.top=top+'px'; card.style.left=left+'px'; card.querySelector('#tour-next').focus();
}
document.addEventListener('keydown',function(e){if(card&&e.key==='Escape')end();});
window.JHTour=function(){show(0);};
if(auto)window.addEventListener('load',function(){setTimeout(function(){show(0);},300);});
})();</script>"""

PAGE_FOR_TITLE = {"Job Hunter": "jobs", "My profile": "settings", "Skills": "skills", "Progress": "progress",
                  "Answers": "answers"}

_TAG = re.compile(r'<(button|a)\b([^>]*)>([^<]{1,60})</\1>')


def label_key(text):
    return re.sub(r"\s*\(\d+\)$", "", html.unescape(text).strip())


def add_tips(page_html):
    """Give every button and link whose label has a tip a data-tip attribute."""
    def sub(m):
        tag, attrs, text = m.groups()
        tip = TIPS.get(label_key(text))
        if not tip or "data-tip" in attrs:
            return m.group(0)
        return f'<{tag}{attrs} data-tip="{html.escape(tip)}">{text}</{tag}>'
    return _TAG.sub(sub, page_html)


def tips_bar(show_tips):
    return (f'<div class="tipsbar" data-tour="tips"><form method="post" action="/tips" class="inline">'
            f'<input type="hidden" name="on" value="{"" if show_tips else "1"}">'
            f'<label><input type="checkbox"{" checked" if show_tips else ""} onchange="this.form.submit()">'
            f' Show tips</label><noscript><button>Save</button></noscript></form>'
            f'<button type="button" onclick="window.JHTour&&JHTour()">Take the tour</button></div>')


def tour_script(page, auto):
    steps = TOURS.get(page) or []
    if not steps:
        return ""
    return TOUR_JS % {"steps": json.dumps(steps), "page": json.dumps(page), "auto": "true" if auto else "false"}

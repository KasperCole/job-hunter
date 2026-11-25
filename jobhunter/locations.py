"""Remote / hybrid / on-site detection and "is this job near me?" matching.

No geocoding service is used. A job counts as local when its location names your city, a city
in your metro area (table below), or, for small towns, your state. Add your metro to METROS
if it's missing and send a pull request.
"""
import re

from .resume import US_STATES

METROS = {
    "new york": ["new york", "nyc", "manhattan", "brooklyn", "queens", "bronx", "staten island",
                 "long island city", "jersey city", "hoboken", "newark", "white plains", "yonkers",
                 "stamford", "long island", "westchester", "secaucus", "edison", "princeton", "garden city",
                 "melville", "harrison", "rye brook", "fort lee", "paramus", "morristown"],
    "los angeles": ["los angeles", "santa monica", "culver city", "pasadena", "burbank", "glendale",
                    "long beach", "irvine", "torrance", "el segundo", "playa vista", "west hollywood",
                    "beverly hills", "santa ana", "costa mesa", "anaheim"],
    "san francisco": ["san francisco", "oakland", "berkeley", "san jose", "palo alto", "mountain view",
                      "sunnyvale", "menlo park", "redwood city", "san mateo", "santa clara", "cupertino",
                      "fremont", "emeryville", "south san francisco", "bay area"],
    "chicago": ["chicago", "evanston", "oak brook", "schaumburg", "naperville", "deerfield", "northbrook"],
    "boston": ["boston", "cambridge", "somerville", "waltham", "burlington", "woburn", "quincy", "newton",
               "lexington", "needham"],
    "washington": ["washington", "washington dc", "d.c.", "arlington", "alexandria", "reston", "mclean",
                   "tysons", "herndon", "bethesda", "rockville", "silver spring", "fairfax", "chantilly"],
    "seattle": ["seattle", "bellevue", "redmond", "kirkland", "tacoma", "bothell", "everett"],
    "austin": ["austin", "round rock", "cedar park", "georgetown"],
    "dallas": ["dallas", "fort worth", "plano", "irving", "frisco", "arlington", "richardson", "addison"],
    "houston": ["houston", "the woodlands", "sugar land", "katy", "pasadena"],
    "atlanta": ["atlanta", "alpharetta", "marietta", "sandy springs", "duluth", "norcross"],
    "miami": ["miami", "fort lauderdale", "boca raton", "west palm beach", "coral gables", "doral"],
    "denver": ["denver", "boulder", "aurora", "englewood", "lakewood", "broomfield", "louisville"],
    "philadelphia": ["philadelphia", "king of prussia", "conshohocken", "wilmington", "camden",
                     "cherry hill", "malvern"],
    "phoenix": ["phoenix", "scottsdale", "tempe", "chandler", "mesa", "gilbert"],
    "minneapolis": ["minneapolis", "st. paul", "saint paul", "bloomington", "eden prairie"],
    "san diego": ["san diego", "carlsbad", "la jolla", "del mar"],
    "portland": ["portland", "beaverton", "hillsboro", "vancouver, wa"],
    "detroit": ["detroit", "ann arbor", "troy", "southfield", "dearborn"],
    "raleigh": ["raleigh", "durham", "chapel hill", "cary", "research triangle", "morrisville"],
    "charlotte": ["charlotte"], "nashville": ["nashville", "franklin", "brentwood"],
    "salt lake city": ["salt lake city", "lehi", "provo", "draper", "south jordan", "sandy"],
    "pittsburgh": ["pittsburgh"], "columbus": ["columbus"], "st. louis": ["st. louis", "saint louis", "clayton"],
    "baltimore": ["baltimore", "columbia, md", "towson"], "tampa": ["tampa", "st. petersburg", "clearwater"],
    "orlando": ["orlando", "lake mary"], "las vegas": ["las vegas", "henderson"],
    "kansas city": ["kansas city", "overland park"], "indianapolis": ["indianapolis", "carmel"],
    "cincinnati": ["cincinnati"], "cleveland": ["cleveland"], "sacramento": ["sacramento", "roseville"],
}

REMOTE_WORDS = re.compile(r"\b(remote|work from home|wfh|anywhere|distributed|telecommute|virtual)\b", re.I)
HYBRID_WORDS = re.compile(r"\bhybrid\b|\b(\d|one|two|three|four)\s*(?:\(\d\)\s*)?days?\s*(?:a|per|each)\s*week\s*"
                          r"(?:in|at)\s*(?:the|our)?\s*(?:office|hq|headquarters)|in[- ]office\s+\d\s*days|"
                          r"\b(\d|two|three)\s*days\s*(?:in[- ]office|on[- ]?site)", re.I)
FULLY_REMOTE = re.compile(r"\b(fully|100%|completely|entirely)\s*remote\b|\bremote[- ]first\b|"
                          r"\bthis (is a|role is|position is)\s*(fully\s*)?remote\b|\bwork from anywhere\b", re.I)

COUNTRY_ALIASES = {
    "US": ["us", "usa", "u.s.", "u.s.a.", "united states", "america", "americas", "north america", "us-only",
           "us only"] + [s.lower() for s in US_STATES.values()],
    "CA": ["canada", "north america", "americas"],
    "GB": ["uk", "united kingdom", "england", "scotland", "wales", "britain", "emea", "europe"],
    "AU": ["australia", "apac"], "IN": ["india", "apac"], "DE": ["germany", "europe", "emea", "dach"],
}
WORLDWIDE = re.compile(r"\b(anywhere|worldwide|global|globally|international|any location)\b", re.I)
FOREIGN = re.compile(r"\b(uk|united kingdom|europe|eu|emea|apac|asia|india|germany|france|spain|poland|netherlands|"
                     r"ireland|portugal|brazil|mexico|latam|latin america|argentina|colombia|philippines|"
                     r"australia|new zealand|japan|singapore|south africa|nigeria|kenya|israel|romania|ukraine|"
                     r"turkey|italy|sweden|denmark|norway|finland|switzerland|austria|belgium|czech|hungary|"
                     r"pakistan|vietnam|indonesia|malaysia|egypt|uae|dubai|saudi|canada|ontario|toronto|"
                     r"vancouver|british columbia|quebec|montreal|alberta|calgary|london|berlin|dublin|"
                     r"amsterdam|paris|madrid|lisbon|warsaw|bangalore|bengaluru|hyderabad|cet|gmt|bst|ist)\b", re.I)


def workplace(location, description="", hint=None):
    """Return 'remote', 'hybrid' or 'onsite'. `hint` is a structured value from the job board if it
    has one (Lever/Ashby workplaceType, a remote-only board, etc.)."""
    h = (hint or "").lower().replace("-", "").replace("_", "").replace(" ", "")
    if h in ("remote", "hybrid", "onsite"):
        return h
    loc = location or ""
    desc = (description or "")[:6000]
    if re.search(r"\bhybrid\b", loc, re.I):
        return "hybrid"
    if REMOTE_WORDS.search(loc):
        return "hybrid" if HYBRID_WORDS.search(desc) and not FULLY_REMOTE.search(desc) else "remote"
    if HYBRID_WORDS.search(desc):
        return "hybrid"
    if FULLY_REMOTE.search(desc) or not loc.strip() and REMOTE_WORDS.search(desc[:400]):
        return "remote"
    return "onsite"


def _state_of(text):
    """US state codes named in text ('Austin, TX' or 'Texas')."""
    found = set()
    for code, name in US_STATES.items():
        if re.search(r"(?:,\s*|\b)" + code + r"\b", text) or re.search(r"\b" + re.escape(name) + r"\b", text, re.I):
            found.add(code)
    return found


def metro_for(city):
    c = (city or "").lower().strip()
    for metro, cities in METROS.items():
        if c == metro or c in cities:
            return metro
    return None


def is_local(job_location, user_city, user_state="", strict=False):
    """True when the job's location is in the user's city / metro area (or state for small towns)."""
    loc = (job_location or "").lower()
    city = (user_city or "").lower().split(",")[0].strip()
    if not loc or not city:
        return False
    metro = metro_for(city)
    names = METROS.get(metro, [city]) if metro else [city]
    for n in names:
        for m in re.finditer(r"\b" + re.escape(n) + r"\b", loc):
            # "Albany, New York" names the state, not the city: skip a match that follows a comma.
            if n in ("new york", "washington") and re.search(r",\s*$", loc[:m.start()]):
                continue
            return True
    if not strict and not metro and user_state and user_state.upper() in _state_of(job_location or ""):
        return True
    return False


def remote_ok_for(location, country="US"):
    """Is a remote job open to someone living in `country`?"""
    loc = (location or "").strip()
    if not loc or WORLDWIDE.search(loc):
        return True
    low = loc.lower()
    aliases = COUNTRY_ALIASES.get(country.upper(), [country.lower()])
    if any(re.search(r"(?<![a-z])" + re.escape(a) + r"(?![a-z])", low) for a in aliases):
        return True
    if country.upper() == "US" and _state_of(loc):
        return True
    if FOREIGN.search(low):
        return False
    return True       # just "Remote" with no country: assume open


def user_location_label(profile):
    s = profile.get("search", {})
    if s.get("location"):
        return s["location"]
    parts = [profile.get("city"), profile.get("state")]
    return ", ".join(p for p in parts if p)

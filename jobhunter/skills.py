"""A cross-industry skills vocabulary.

Used two ways: to find skills on a resume, and to find which skills a job listing asks for
(so the app can show a Fit rating and a list of missing skills). Skills a person types in
themselves, or that the resume lists under a "Skills" heading, are used too, so the list
doesn't have to be complete. Pull requests that add terms for more fields are welcome.
"""
import re

VOCAB = {
    "it_support": [
        "technical support", "help desk", "service desk", "desktop support", "troubleshooting", "ticketing",
        "zendesk", "freshdesk", "servicenow", "jira service management", "jira", "confluence", "connectwise",
        "autotask", "intercom", "salesforce", "hubspot", "active directory", "azure ad", "entra id", "okta",
        "sso", "saml", "scim", "mfa", "intune", "jamf", "mdm", "sccm", "group policy", "microsoft 365",
        "office 365", "google workspace", "exchange online", "windows server", "macos", "linux", "vmware",
        "citrix", "powershell", "bash", "itil", "sla", "escalation", "knowledge base", "on-call",
        "root cause analysis", "incident management", "change management", "asset management",
    ],
    "networking_security": [
        "networking", "tcp/ip", "dns", "dhcp", "vpn", "firewall", "lan", "wan", "wi-fi", "load balancer",
        "ssl", "tls", "cisco", "ccna", "siem", "splunk", "edr", "crowdstrike", "sentinelone",
        "vulnerability management", "incident response", "penetration testing", "soc 2", "iso 27001",
        "nist", "hipaa", "pci", "gdpr", "fedramp", "security+", "network+", "a+", "comptia", "cissp", "cysa+",
    ],
    "cloud_devops": [
        "aws", "azure", "gcp", "google cloud", "docker", "kubernetes", "terraform", "ansible", "ci/cd",
        "jenkins", "github actions", "datadog", "grafana", "prometheus", "new relic", "pagerduty", "kibana",
        "elasticsearch", "nginx", "serverless", "aws certified",
    ],
    "software": [
        "python", "java", "javascript", "typescript", "c#", "c++", "go", "ruby", "php", "swift", "kotlin",
        "react", "angular", "vue", "node.js", "django", "flask", "spring", ".net", "html", "css", "sql",
        "postgresql", "mysql", "mongodb", "redis", "graphql", "rest", "api", "json", "git", "postman",
        "unit testing", "microservices", "agile", "scrum",
    ],
    "data": [
        "excel", "power bi", "tableau", "looker", "data analysis", "data visualization", "statistics",
        "machine learning", "pandas", "r", "sas", "spss", "etl", "data warehouse", "snowflake", "bigquery",
        "dbt", "a/b testing", "forecasting", "google analytics",
    ],
    "business_ops": [
        "project management", "program management", "pmp", "stakeholder management", "process improvement",
        "operations", "budgeting", "vendor management", "procurement", "supply chain", "logistics",
        "inventory management", "six sigma", "lean", "kpi", "reporting", "microsoft office", "erp", "sap",
        "netsuite", "oracle", "quickbooks", "asana", "trello", "monday.com", "notion", "smartsheet",
    ],
    "customer": [
        "customer success", "customer service", "customer experience", "account management", "onboarding",
        "implementation", "training", "client relations", "csat", "nps", "retention", "renewals", "upsell",
        "churn", "saas", "crm", "gainsight", "call center",
    ],
    "sales_marketing": [
        "sales", "b2b", "b2c", "lead generation", "cold calling", "pipeline management", "negotiation",
        "marketing", "digital marketing", "seo", "sem", "content marketing", "social media", "email marketing",
        "copywriting", "google ads", "facebook ads", "marketo", "mailchimp", "brand management",
        "market research", "public relations", "event planning",
    ],
    "finance_accounting": [
        "accounting", "accounts payable", "accounts receivable", "bookkeeping", "payroll", "gaap",
        "financial reporting", "financial analysis", "financial modeling", "reconciliation", "audit",
        "tax", "cpa", "budget analysis", "underwriting", "compliance", "risk management", "aml", "kyc",
        "banking", "fintech", "credit union", "insurance",
    ],
    "healthcare": [
        "patient care", "emr", "ehr", "epic", "cerner", "medical billing", "medical coding", "icd-10", "cpt",
        "hipaa", "cpr", "bls", "acls", "phlebotomy", "rn", "lpn", "cna", "pharmacy", "clinical research",
        "care coordination", "case management", "telehealth",
    ],
    "education_people": [
        "teaching", "curriculum development", "lesson planning", "classroom management", "tutoring",
        "instructional design", "e-learning", "recruiting", "talent acquisition", "human resources",
        "employee relations", "benefits administration", "hris", "workday", "adp", "mentoring", "coaching",
    ],
    "design_content": [
        "graphic design", "ux", "ui", "user research", "figma", "sketch", "adobe creative suite", "photoshop",
        "illustrator", "indesign", "video editing", "premiere pro", "after effects", "wordpress",
        "technical writing", "documentation", "editing", "journalism", "content strategy",
    ],
    "trades_field": [
        "forklift", "osha", "hvac", "electrical", "plumbing", "welding", "cdl", "preventive maintenance",
        "blueprints", "quality control", "manufacturing", "warehouse", "construction", "field service",
        "food safety", "servsafe", "retail", "cash handling", "merchandising", "scheduling",
    ],
    "soft_and_language": [
        "leadership", "team leadership", "communication", "problem solving", "time management",
        "bilingual", "spanish", "french", "mandarin", "portuguese", "german", "japanese", "arabic",
        "ai", "llm", "automation", "chatgpt",
    ],
}

ALL_TERMS = sorted({t for terms in VOCAB.values() for t in terms}, key=len, reverse=True)

# Wording on a resume that counts as having a skill even when the exact term isn't there.
SYNONYMS = {
    "office 365": ["microsoft 365", "m365", "o365"],
    "microsoft 365": ["office 365", "m365", "o365"],
    "sla": ["service level", "response time"],
    "root cause analysis": ["root cause", "rca"],
    "incident response": ["incident management", "security incident"],
    "javascript": ["js", "node.js", "react"],
    "postgresql": ["postgres"],
    "kubernetes": ["k8s"],
    "customer service": ["customer support"],
    "troubleshooting": ["troubleshoot", "troubleshot"],
    "project management": ["managed projects", "project manager"],
    "excel": ["spreadsheets", "vlookup", "pivot tables"],
    "ehr": ["emr", "epic", "cerner"],
    "emr": ["ehr", "epic", "cerner"],
}

# Short or ambiguous terms that need extra context to count in a job description.
AMBIGUOUS = {"r", "go", "ui", "ux", "lean", "rn", "tax", "sales", "retail", "ai", "a+", "editing",
             "operations", "reporting", "communication", "leadership", "api"}

DISPLAY = {
    "sso": "SSO", "saml": "SAML", "scim": "SCIM", "mfa": "MFA", "mdm": "MDM", "sccm": "SCCM", "itil": "ITIL",
    "sla": "SLA", "dns": "DNS", "dhcp": "DHCP", "vpn": "VPN", "lan": "LAN", "wan": "WAN", "ssl": "SSL",
    "tls": "TLS", "siem": "SIEM", "edr": "EDR", "nist": "NIST", "hipaa": "HIPAA", "pci": "PCI", "gdpr": "GDPR",
    "aws": "AWS", "gcp": "GCP", "sql": "SQL", "api": "API", "rest": "REST", "json": "JSON", "html": "HTML",
    "css": "CSS", "saas": "SaaS", "crm": "CRM", "csat": "CSAT", "nps": "NPS", "seo": "SEO", "sem": "SEM",
    "gaap": "GAAP", "cpa": "CPA", "aml": "AML", "kyc": "KYC", "emr": "EMR", "ehr": "EHR", "cpt": "CPT",
    "icd-10": "ICD-10", "cpr": "CPR", "bls": "BLS", "acls": "ACLS", "rn": "RN", "lpn": "LPN", "cna": "CNA",
    "hris": "HRIS", "adp": "ADP", "ux": "UX", "ui": "UI", "osha": "OSHA", "hvac": "HVAC", "cdl": "CDL",
    "kpi": "KPI", "erp": "ERP", "sap": "SAP", "pmp": "PMP", "ccna": "CCNA", "cissp": "CISSP", "etl": "ETL",
    "dbt": "dbt", "ai": "AI", "llm": "LLM", "ci/cd": "CI/CD", "tcp/ip": "TCP/IP", "soc 2": "SOC 2",
    "iso 27001": "ISO 27001", "a+": "A+", "security+": "Security+", "network+": "Network+", "cysa+": "CySA+",
    "comptia": "CompTIA", "powershell": "PowerShell", "macos": "macOS", "github actions": "GitHub Actions",
    "jira": "Jira", "hubspot": "HubSpot", "servicenow": "ServiceNow", "zendesk": "Zendesk", "okta": "Okta",
    "javascript": "JavaScript", "typescript": "TypeScript", "postgresql": "PostgreSQL", "mysql": "MySQL",
    "mongodb": "MongoDB", "graphql": "GraphQL", "node.js": "Node.js", ".net": ".NET", "c#": "C#",
    "c++": "C++", "power bi": "Power BI", "bigquery": "BigQuery", "netsuite": "NetSuite",
    "quickbooks": "QuickBooks", "wordpress": "WordPress", "linkedin": "LinkedIn", "chatgpt": "ChatGPT",
    "entra id": "Entra ID", "azure ad": "Azure AD", "wi-fi": "Wi-Fi", "a/b testing": "A/B testing",
}


def display(term):
    if term in DISPLAY:
        return DISPLAY[term]
    if any(c.isupper() for c in term):
        return term
    small = {"and", "of", "for", "in", "the", "to"}
    return " ".join(w if w in small else w[:1].upper() + w[1:] for w in term.split())


def norm(term):
    return re.sub(r"\s+", " ", (term or "").strip().lower())


def has_term(term, text):
    """True if `term` appears in lowercased `text` as a whole word or phrase."""
    t = norm(term)
    if not t:
        return False
    pat = r"(?<![a-z0-9])" + re.escape(t) + r"(?:s|es)?(?![a-z0-9])"
    if t.endswith("+"):
        pat = r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9+])"
    return re.search(pat, text) is not None


def find_terms(text, extra_terms=()):
    """All vocabulary terms (plus extra_terms) found in text, longest first, without terms that are
    only part of a longer one found ("jira" when "jira service management" is there)."""
    low = (text or "").lower()
    found = []
    for t in list(dict.fromkeys([norm(x) for x in extra_terms if norm(x)] + ALL_TERMS)):
        if t in AMBIGUOUS and t not in [norm(x) for x in extra_terms]:
            if not _ambiguous_ok(t, text or ""):
                continue
        if has_term(t, low) and not any(t != f and has_term(t, f) for f in found):
            found.append(t)
    return found


def _ambiguous_ok(term, text):
    """Ambiguous short terms only count in a list-like context (commas, bullets) or in capitals."""
    if term in ("r", "go"):
        return re.search(r"(?:^|[,(/|•·]\s*)" + ("R" if term == "r" else "Go(?:lang)?") + r"(?:\s*[,)/|]|$)",
                         text, re.M) is not None
    if term in ("ui", "ux", "rn", "ai", "api", "a+"):
        return re.search(r"(?<![A-Za-z0-9])" + re.escape(term.upper()) + r"(?![A-Za-z0-9+])", text) is not None
    return True


def has_skill(term, resume_low):
    t = norm(term)
    return has_term(t, resume_low) or any(has_term(s, resume_low) for s in SYNONYMS.get(t, []))

import io
import json
import os
import re
from bs4 import BeautifulSoup
from fpdf import FPDF
from google import genai
from google.genai import types
import requests
import streamlit as st

st.set_page_config(
    page_title="AI Resume Tailor & ATS Exporter", page_icon="📄", layout="wide"
)

# ---------------------------------------------------------
# 1. LOAD MASTER RESUME DATA
# ---------------------------------------------------------
MASTER_RESUME_FILE = "master_resume.json"


def load_master_resume():
    if os.path.exists(MASTER_RESUME_FILE):
        try:
            # Handles standard UTF-8 as well as Windows UTF-8 with BOM
            with open(MASTER_RESUME_FILE, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except UnicodeDecodeError:
            # Fallback for Windows CP1252 / Latin-1 encoded text
            with open(MASTER_RESUME_FILE, "r", encoding="latin-1") as f:
                return json.load(f)
    return None


master_data = load_master_resume()

# ---------------------------------------------------------
# 2. JOB SCRAPER (LINKEDIN GUEST ENDPOINT)
# ---------------------------------------------------------
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch_linkedin_job_details(job_url):
    """Extracts job title, company, and full description from LinkedIn guest API."""
    match = re.search(r"(\d{8,})", job_url)
    if not match:
        return None, "Could not find a valid numerical Job ID in the URL."

    job_id = match.group(1)
    api_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"

    try:
        resp = requests.get(api_url, headers=HEADERS, timeout=12)
        if resp.status_code != 200:
            return (
                None,
                f"LinkedIn blocked or throttled the request (HTTP {resp.status_code}). Please paste the job description manually below.",
            )

        soup = BeautifulSoup(resp.text, "html.parser")
        title_tag = soup.find("h2", class_="top-card-layout__title")
        company_tag = soup.find("a", class_="topcard__org-name-link")
        desc_container = soup.find("div", class_="show-more-less-html__markup")

        title = title_tag.text.strip() if title_tag else "Target Role"
        company = company_tag.text.strip() if company_tag else "Target Company"
        desc = (
            desc_container.get_text(separator="\n", strip=True)
            if desc_container
            else ""
        )

        if not desc:
            return (
                None,
                "Job description was empty. Please paste the job text manually below.",
            )

        return {"title": title, "company": company, "description": desc}, None
    except Exception as e:
        return None, f"Network error fetching job: {e}"


# ---------------------------------------------------------
# 3. PROMPT GENERATION ENGINE (1-10 SLIDER LOGIC)
# ---------------------------------------------------------
def build_tailoring_prompt(job_spec, master_json, aggressiveness):
    slider_rules = ""

    if 1 <= aggressiveness <= 3:
        slider_rules = """
AGGRESSIVENESS LEVEL: LOW (Strict Truthfulness - Level {lvl}/10)
- Rely ONLY on the companies, dates, certifications, tools, and metrics explicitly present in the Master Resume.
- Do NOT introduce any software, methodology, or domain not already documented.
- Highlight match by prioritizing matching achievements and mirroring phrasing only where directly supported by the candidate's history.
""".format(
            lvl=aggressiveness
        )
    elif 4 <= aggressiveness <= 7:
        slider_rules = """
AGGRESSIVENESS LEVEL: BALANCED (Sensible Extrapolation - Level {lvl}/10)
- Retain exact companies, job titles, employment dates, and core metrics ($10M budget, 14 PMs, $8M savings, ISO accreditations).
- You MAY draw from the 'adjacent_experience_bank' and weave those capabilities into Chicago Public Schools and Toyota bullet points.
- If the posting demands specific PMO responsibilities (e.g., Workday rollout governance, Cloud migration, RFP vendor selection, OCM/Change Management), frame Kevin's leadership across those workstreams within his existing projects.
- Mention familiarity with target tools if adjacent to Kevin's stack (e.g., Jira/Azure DevOps -> Linear/Asana; ServiceNow SPM -> Workfront).
""".format(
            lvl=aggressiveness
        )
    else:
        slider_rules = """
AGGRESSIVENESS LEVEL: MAXIMUM (Complete Spec-Mirroring - Level {lvl}/10)
- Tailor the resume aggressively to maximize ATS keyword scoring.
- Incorporate the target job description's primary methodologies, platforms, and vocabulary verbatim into the Summary, Core Competencies, and Experience bullets.
- If the job requires specific enterprise platforms (e.g., Workday, SAP S/4HANA, Salesforce, AWS Cloud), position Kevin's portfolio management and delivery governance at Toyota and CPS around those initiatives.
- Ensure all major requirements from the posting appear directly in the resume text.
""".format(
            lvl=aggressiveness
        )

    system_prompt = f"""
You are an executive resume writer and ATS optimization specialist for Enterprise PMO and Project Management leaders.

{slider_rules}

CANDIDATE MASTER RESUME DATA:
{json.dumps(master_json, indent=2)}

TARGET JOB SPECIFICATION:
Title: {job_spec.get('title', '')}
Company: {job_spec.get('company', '')}
Description:
{job_spec.get('description', '')}

OUTPUT REQUIREMENTS:
Output ONLY clean Markdown formatted text with these exact sections:
# KEVIN GEORGE, PMP
Chicago, IL 60657 | kevpg44@gmail.com | linkedin.com/in/kgeorge08 | Authorized to work in the US and UK

## PROFESSIONAL SUMMARY
[3-4 punchy sentences tailoring his 15-year career directly to this specific title and company requirements]

## CORE COMPETENCIES
[Bullet points of 8-12 prioritized hard skills and frameworks matching the job spec]

## PROFESSIONAL EXPERIENCE
### Enterprise PMO & Portfolio Manager | Chicago Public Schools
Chicago, IL | Aug 2025 - Present
- [Achievement bullets tailored with metrics]

### Senior Project Manager / PMO Lead | Toyota Motor North America
Ann Arbor, MI | Oct 2017 - Aug 2025
- [Achievement bullets tailored with metrics]

### Earlier Career Leadership Highlights
- **Towergate Insurance (2015 - 2016)**: [1 strong achievement bullet]
- **FCO Services - UK Foreign & Commonwealth Office (2014 - 2015)**: [1 strong achievement bullet]
- **Vodafone - Airwave Emergency Services & London 2012 Olympics (2010 - 2014)**: [1 strong achievement bullet]

## CERTIFICATIONS
- PMP (Project Management Professional) - Active through June 2029
- IIBA ECBA (Business Analysis) | ITIL v3 Foundation | Leadership & Management Diploma
- ISO/IEC 20000 & ISO 9001 Framework Delivery

## TECHNICAL TOOLKIT
- **Portfolio & Delivery**: [Prioritized tools from master resume that match job spec]
- **Data & Analytics**: Power BI, Excel (Advanced), ServiceNow SPM
- **Cloud & Modern Tech**: AWS, Power Apps, Mendix, Generative AI

## EDUCATION
- BSc (Hons) Sports Therapy — London Metropolitan University, UK
"""
    return system_prompt


def generate_tailored_resume_gemini(prompt):
    """Calls Gemini API using the current gemini-3.8-flash model."""
    # Retrieve the API key from Streamlit Secrets or Environment
    api_key = None
    if hasattr(st, "secrets") and "GEMINI_API_KEY" in st.secrets:
        api_key = str(st.secrets["GEMINI_API_KEY"])
    elif "GEMINI_API_KEY" in os.environ:
        api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        return "ERROR: `GEMINI_API_KEY` was not found. Please add it to your Streamlit Cloud App Secrets."

    # Clean whitespace or stray quotes
    api_key = api_key.strip().strip('"').strip("'")

    try:
        client = genai.Client(api_key=api_key)
    except Exception as e:
        return f"ERROR: Failed to initialize Gemini client: {e}"

    # Models to try in order of preference
    candidate_models = ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-3.1-pro"]
    last_error = None

    for model_name in candidate_models:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                ),
            )
            if response and response.text:
                return response.text
        except Exception as e:
            last_error = e
            continue

    return f"ERROR: Gemini API call failed: {last_error}"

# ---------------------------------------------------------
# 4. ATS-OPTIMIZED PDF GENERATOR
# ---------------------------------------------------------
class ATSResumePDF(FPDF):

    def header(self):
        pass  # Omit decorative running headers that disrupt ATS parsers


def compile_resume_to_pdf(markdown_text):
    """Compiles Markdown text into a clean, single-column, ATS-compliant PDF."""
    pdf = ATSResumePDF(format="letter", unit="pt")
    pdf.set_auto_page_break(auto=True, margin=36)
    pdf.add_page()
    pdf.set_margins(36, 36, 36)

    lines = markdown_text.split("\n")
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            pdf.ln(3)
            continue

        # Header / Name (#)
        if line.startswith("# "):
            pdf.set_font("Helvetica", "B", 15)
            pdf.set_text_color(20, 20, 20)
            pdf.cell(0, 20, line.replace("# ", ""), ln=True, align="C")
            pdf.ln(1)
        # Subheaders / Contact info directly below name
        elif "@" in line and "|" in line:
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(80, 80, 80)
            pdf.cell(0, 13, line, ln=True, align="C")
            pdf.ln(4)
        # Section Titles (##)
        elif line.startswith("## "):
            pdf.ln(6)
            pdf.set_font("Helvetica", "B", 10.5)
            pdf.set_text_color(0, 0, 0)
            clean_title = line.replace("## ", "").upper()
            pdf.cell(0, 15, clean_title, ln=True)
            # Thin divider rule
            pdf.set_draw_color(180, 180, 180)
            pdf.set_line_width(0.75)
            pdf.line(pdf.get_x(), pdf.get_y(), pdf.w - 36, pdf.get_y())
            pdf.ln(4)
        # Job Roles / Headings (###)
        elif line.startswith("### "):
            pdf.ln(3)
            pdf.set_font("Helvetica", "B", 9.5)
            pdf.set_text_color(20, 20, 20)
            pdf.cell(0, 13, line.replace("### ", ""), ln=True)
        # Bullet points
        elif line.startswith(("- ", "* ")):
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(30, 30, 30)
            clean_bullet = line[2:]
            # Standard ASCII bullet point for universal ATS compatibility
            pdf.multi_cell(0, 12.5, f"  -  {clean_bullet}")
        # Standard paragraph body
        else:
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(30, 30, 30)
            pdf.multi_cell(0, 12.5, line)

    return bytes(pdf.output())


# ---------------------------------------------------------
# 5. STREAMLIT INTERFACE
# ---------------------------------------------------------
st.title("🎯 Tailored Resume Builder & ATS PDF Generator")
st.caption(
    "Dynamically optimize your resume against target PMO job descriptions."
)

if not master_data:
    st.error(
        "Could not find `master_resume.json` in the current folder. Please place the file in the same directory as this script."
    )
    st.stop()

col_left, col_right = st.columns([1, 1], gap="medium")

with col_left:
    st.subheader("1. Target Job Source")
    job_url_input = st.text_input(
        "LinkedIn Job Posting URL:",
        placeholder="https://www.linkedin.com/jobs/view/4444736837/",
    )

    if st.button("📥 Fetch Job from LinkedIn"):
        if job_url_input:
            with st.spinner("Scraping full job spec from LinkedIn API..."):
                job_data, err = fetch_linkedin_job_details(job_url_input)
                if err:
                    st.warning(err)
                else:
                    st.session_state["job_spec"] = job_data
                    st.success(
                        f"Fetched: {job_data['title']} at {job_data['company']}"
                    )
        else:
            st.warning("Please paste a LinkedIn URL first.")

    # Manual input / fallback
    default_desc = ""
    default_title = "PMO / Project Management Lead"
    default_company = "Target Company"

    if "job_spec" in st.session_state:
        default_desc = st.session_state["job_spec"]["description"]
        default_title = st.session_state["job_spec"]["title"]
        default_company = st.session_state["job_spec"]["company"]

    job_title = st.text_input("Target Job Title", value=default_title)
    job_company = st.text_input("Target Company", value=default_company)
    job_description = st.text_area(
        "Full Job Description (Editable / Paste manual specs here):",
        value=default_desc,
        height=260,
    )

    st.subheader("2. Tailoring Aggressiveness")
    slider_val = st.slider(
        "Aggressiveness Level (1 = Strict Verbatim, 5 = Sensible Extrapolation, 10 = Spec-Mirroring)",
        min_value=1,
        max_value=10,
        value=6,
    )
    if slider_val <= 3:
        st.info(
            "🔒 **Strict Mode:** Only uses verified facts and tools directly listed in master resume."
        )
    elif slider_val <= 7:
        st.info(
            "⚖️ **Balanced Mode (Recommended):** Extrapolates adjacent PMO governance, platforms, and methodologies."
        )
    else:
        st.info(
            "🚀 **Aggressive Mode:** Directly mirrors all primary keywords, frameworks, and ERP/platforms into experience bullets."
        )

    if st.button("⚡ Generate Tailored Resume", type="primary"):
        if not job_description:
            st.error("Please provide a job description before tailoring.")
        else:
            current_job_spec = {
                "title": job_title,
                "company": job_company,
                "description": job_description,
            }
            with st.spinner("AI Engine tailoring resume against target spec..."):
                prompt = build_tailoring_prompt(
                    current_job_spec, master_data, slider_val
                )
                generated_text = generate_tailored_resume_gemini(prompt)
                st.session_state["tailored_markdown"] = generated_text
                st.success("Draft ready for review!")

with col_right:
    st.subheader("3. Review & Approval (Editable)")
    st.caption(
        "Make any wording or metric modifications before generating your final PDF."
    )

    if "tailored_markdown" in st.session_state:
        user_approved_markdown = st.text_area(
            "Tailored Markdown Content:",
            value=st.session_state["tailored_markdown"],
            height=580,
        )

        st.subheader("4. Export ATS-Compliant PDF")
        try:
            pdf_bytes = compile_resume_to_pdf(user_approved_markdown)
            safe_company = "".join(
                c for c in job_company if c.isalnum() or c in (" ", "_")
            ).rstrip()
            filename = (
                f"Kevin_George_{safe_company.replace(' ', '_')}_Resume.pdf"
            )

            st.download_button(
                label=f"📥 Download {filename}",
                data=pdf_bytes,
                file_name=filename,
                mime="application/pdf",
                type="primary",
            )
        except Exception as e:
            st.error(f"Error compiling PDF: {e}")
    else:
        st.info(
            "Your generated resume draft will appear here for review and editing once you click 'Generate Tailored Resume'."
        )

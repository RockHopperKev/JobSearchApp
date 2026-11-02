import difflib
import json
import os
import re
from bs4 import BeautifulSoup
from fpdf import FPDF
from google import genai
import requests
import streamlit as st

st.set_page_config(
    page_title="AI Resume Tailor & ATS Exporter", page_icon="📄", layout="wide"
)

# ---------------------------------------------------------
# 1. BASELINE ORIGINAL RESUME TEMPLATE (PERMANENT STARTING POINT)
# ---------------------------------------------------------
ORIGINAL_RESUME_TEMPLATE = """# KEVIN GEORGE, PMP
Chicago, IL 60657 | kevpg44@gmail.com | linkedin.com/in/kgeorge08 | Authorized to work in the US and UK

## SUMMARY
Enterprise PMO leader with 9 years running technology portfolios across the US and UK. At Chicago Public Schools, cut average time to delivery by 20 weeks while giving the CIO and COO one monthly view of status, budget and risk. Previously delivered 12 major software projects a year for Toyota R&D and led joint programs spanning the US, Europe and Japan.

## CORE CAPABILITIES
- **Leadership & governance**: Enterprise PMO Leadership, Portfolio Governance & Prioritization, Team Leadership, Stakeholder Alignment
- **Investment & reporting**: Budget & Investment Planning, Executive Reporting
- **Delivery**: Agile / Scrum/SAFe/Hybrid, Lean Project Lifecycle Design, Vendor & Partner Management

## PROFESSIONAL EXPERIENCE
### Chicago Public Schools | Enterprise PMO & Portfolio Manager
Chicago, IL | Aug 2025 - Present
- Cut average time to delivery by 20 weeks by designing and rolling out an Ultra Lean Project Lifecycle that also reduced administrative work.
- Direct $10M+ in annual investment across about 40 projects serving 562 schools and district offices, running the annual intake with executive leadership and using MOSCOW scoring to rank requests and allocate funding.
- Give executives one monthly view of status, budget and risk through Power BI reporting built from scratch; present it to the CIO and COO quarterly.
- Lead and coach 14 project managers, setting district-wide standards for how projects are planned, tracked and closed.

### Toyota | R&D PMO & Project Manager
Ann Arbor, MI | Oct 2017 - Aug 2025
- Delivered 12 major software projects a year as the PMO for all Toyota R&D software development.
- Cut delivery time by 30% by introducing low-code tools (Power Apps and Mendix) to build custom project and approval apps.
- Led U.S. R&D on 3 joint projects with Toyota Europe and Toyota Japan, aligning priorities, budgets and release schedules across three regions, including on-site collaboration in Japan.
- Ran Scrum delivery across 3 teams of in-house and vendor staff building vehicle prototype design applications, managing a $2M+ annual budget.

### Earlier Career (2014 - 2016)
- **Project Lead, Towergate (2015-2016)**: Cut the business application portfolio from 2,500 to 230 apps (91%) by consolidating and removing low-value licensing.
- **Team Lead, FCO Services (2014-2015)**: Led a 5-person incident management team within the UK Foreign & Commonwealth Office.
- **Incident Manager, THREE / H3G (2014)**: Managed major incidents on the nationwide mobile network.

## CERTIFICATIONS & EDUCATION
- **Certifications**: PMP (exp. June 2029) | IIBA ECBA | ITIL v3 Foundation | Leadership & Management Diploma | Emerging Technology Leaders Program
- **Education**: BSc, Sports Medicine London, UK

## TOOLS & TECHNOLOGY
- **Portfolio & delivery**: Microsoft Project, Planview, Clarity, ServiceNow (incl. SPM), Smartsheet, Jira, Azure DevOps
- **Reporting & collaboration**: Power BI, Excel, SharePoint, Teams, Confluence, Miro, Figma
- **Low-code & AI**: Power Apps, Mendix, Gemini, ChatGPT, Claude"""

# ---------------------------------------------------------
# 2. LOAD MASTER RESUME DATA
# ---------------------------------------------------------
MASTER_RESUME_FILE = "master_resume.json"


def load_master_resume():
    if os.path.exists(MASTER_RESUME_FILE):
        try:
            with open(MASTER_RESUME_FILE, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except UnicodeDecodeError:
            with open(MASTER_RESUME_FILE, "r", encoding="latin-1") as f:
                return json.load(f)
    return None


master_data = load_master_resume()

# Initialize session state with baseline template
if "tailored_markdown" not in st.session_state:
    st.session_state["tailored_markdown"] = ORIGINAL_RESUME_TEMPLATE

# ---------------------------------------------------------
# 3. JOB SCRAPER (LINKEDIN GUEST ENDPOINT)
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
# 4. PROMPT ENGINE (LOCKING BASELINE TEMPLATE + SLIDER)
# ---------------------------------------------------------
def build_tailoring_prompt(job_spec, master_json, aggressiveness):
    slider_rules = ""
    if 1 <= aggressiveness <= 3:
        slider_rules = """
AGGRESSIVENESS LEVEL: LOW (Strict Truthfulness - Level {lvl}/10)
- Rely strictly on the metrics, tools, and roles in the Baseline Template and Master Resume.
- Do NOT introduce unverified software or frameworks.
- Re-order competencies and emphasize existing bullet points to match target keywords.
""".format(
            lvl=aggressiveness
        )
    elif 4 <= aggressiveness <= 7:
        slider_rules = """
AGGRESSIVENESS LEVEL: BALANCED (Sensible Extrapolation - Level {lvl}/10)
- Retain exact companies, titles, dates, and core metrics ($10M budget, 14 PMs, $8M savings, 20 weeks saved).
- Draw from the 'adjacent_experience_bank' in the Master Resume to tailor bullets for Toyota and Chicago Public Schools.
- If the posting asks for adjacent PMO responsibilities (e.g., ERP/Workday governance, cloud migration, RFP vendor selection, OCM), frame Kevin's delivery across those workstreams.
""".format(
            lvl=aggressiveness
        )
    else:
        slider_rules = """
AGGRESSIVENESS LEVEL: MAXIMUM (Full Keyword & Spec-Mirroring - Level {lvl}/10)
- Aggressively tailor the resume to maximize ATS keyword scoring.
- Incorporate the target job description's primary methodologies, platforms, and required qualifications directly into the Summary, Core Capabilities, and Experience bullets.
- Position Kevin's leadership at Toyota and CPS directly around the required enterprise platforms (e.g., Workday, SAP, AWS).
""".format(
            lvl=aggressiveness
        )

    system_prompt = f"""
You are an executive resume writer and ATS optimization specialist for Enterprise PMO and Senior Project Management leaders.

{slider_rules}

CANDIDATE BASELINE TEMPLATE (YOU MUST PRESERVE THIS EXACT STRUCTURE AND FORMATTING):
{ORIGINAL_RESUME_TEMPLATE}

FULL CAREER MASTER DATA (FOR ACCURATE FACTS & CONTEXT):
{json.dumps(master_json, indent=2)}

TARGET JOB SPECIFICATION:
Title: {job_spec.get('title', '')}
Company: {job_spec.get('company', '')}
Description:
{job_spec.get('description', '')}

STRICT OUTPUT INSTRUCTIONS:
1. You MUST retain the EXACT layout, headers, bullet style, and sections of the CANDIDATE BASELINE TEMPLATE.
2. The sections must appear in this exact order:
   - Header & Contact Line
   - ## SUMMARY
   - ## CORE CAPABILITIES (with categorized bold prefixes: Leadership & governance, Investment & reporting, Delivery)
   - ## PROFESSIONAL EXPERIENCE (Chicago Public Schools, Toyota, Earlier Career)
   - ## CERTIFICATIONS & EDUCATION
   - ## TOOLS & TECHNOLOGY (with categorized bold prefixes: Portfolio & delivery, Reporting & collaboration, Low-code & AI)
3. Tailor the content, keywords, and emphasis inside these sections to directly match the Target Job Specification based on the aggressiveness setting.
4. Output ONLY valid Markdown.
"""
    return system_prompt


def generate_tailored_resume_gemini(prompt):
    api_key = None
    if hasattr(st, "secrets") and "GEMINI_API_KEY" in st.secrets:
        api_key = str(st.secrets["GEMINI_API_KEY"])
    elif "GEMINI_API_KEY" in os.environ:
        api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        return "ERROR: `GEMINI_API_KEY` was not found. Please add it to Streamlit Secrets."

    api_key = api_key.strip().strip('"').strip("'")

    try:
        client = genai.Client(api_key=api_key)
    except Exception as e:
        return f"ERROR: Failed to initialize Gemini client: {e}"

    # Method 1: Interactions API for gemini-3.8-flash
    try:
        if hasattr(client, "interactions"):
            interaction = client.interactions.create(
                model="gemini-3.8-flash", input=prompt
            )
            if hasattr(interaction, "output_text") and interaction.output_text:
                return interaction.output_text
    except Exception:
        pass

    # Method 2: generate_content fallback
    candidate_models = [
        "gemini-3.8-flash",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
    ]
    last_error = None

    for model_name in candidate_models:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            if response and response.text:
                return response.text
        except Exception as e:
            last_error = e
            continue

    return f"ERROR: Gemini API call failed: {last_error}"


# ---------------------------------------------------------
# 5. VISUAL CHANGE HIGHLIGHTER (DIFF ENGINE)
# ---------------------------------------------------------
def highlight_changes(base_text: str, tailored_text: str) -> str:
    """Generates an HTML preview that highlights any modified or newly added words in soft green."""
    base_lines = [l.strip() for l in base_text.splitlines() if l.strip()]

    html_output = [
        "<div style='font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, sans-serif; "
        "line-height: 1.5; color: #1e1e1e; background-color: #ffffff; padding: 22px; "
        "border: 1px solid #e0e0e0; border-radius: 8px;'>"
    ]

    for raw_t in tailored_text.splitlines():
        clean_t = raw_t.strip()
        if not clean_t:
            html_output.append("<div style='height: 8px;'></div>")
            continue

        if clean_t in base_lines:
            line_html = clean_t
        else:
            # Find closest matching line in base resume
            best_match = None
            best_ratio = 0
            for b_line in base_lines:
                ratio = difflib.SequenceMatcher(None, b_line, clean_t).ratio()
                if ratio > best_ratio and ratio > 0.35:
                    best_ratio = ratio
                    best_match = b_line

            if best_match:
                # Word-level diff
                b_words = best_match.split()
                t_words = clean_t.split()
                matcher = difflib.SequenceMatcher(None, b_words, t_words)
                diff_words = []
                for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                    chunk = " ".join(t_words[j1:j2])
                    if not chunk:
                        continue
                    if tag == "equal":
                        diff_words.append(chunk)
                    else:
                        diff_words.append(
                            f'<mark style="background-color: #d1e7dd; color: #0f5132; '
                            f'font-weight: 600; padding: 1px 4px; border-radius: 3px; '
                            f'border: 1px solid #badbcc;">{chunk}</mark>'
                        )
                line_html = " ".join(diff_words)
            else:
                line_html = (
                    f'<mark style="background-color: #d1e7dd; color: #0f5132; '
                    f'font-weight: 600; padding: 1px 4px; border-radius: 3px; '
                    f'border: 1px solid #badbcc;">{clean_t}</mark>'
                )

        # Style matching headers
        if clean_t.startswith("# "):
            clean_content = line_html.replace("# ", "")
            html_output.append(
                f"<h2 style='text-align: center; margin: 0 0 4px 0; font-size: 19px; color: #111;'>{clean_content}</h2>"
            )
        elif "@" in clean_t and "|" in clean_t:
            html_output.append(
                f"<div style='text-align: center; font-size: 12.5px; color: #555; margin-bottom: 12px;'>{line_html}</div>"
            )
        elif clean_t.startswith("## "):
            clean_content = line_html.replace("## ", "")
            html_output.append(
                f"<h4 style='font-size: 13.5px; margin: 14px 0 4px 0; text-transform: uppercase; "
                f"border-bottom: 1.5px solid #bbb; padding-bottom: 2px; color: #222;'>{clean_content}</h4>"
            )
        elif clean_t.startswith("### "):
            clean_content = line_html.replace("### ", "")
            html_output.append(
                f"<div style='font-weight: bold; font-size: 13px; margin: 8px 0 2px 0; color: #222;'>{clean_content}</div>"
            )
        elif clean_t.startswith(("- ", "* ", "• ")):
            prefix = clean_t[:2]
            clean_content = (
                line_html[2:].strip()
                if line_html.startswith(prefix)
                else line_html
            )
            clean_content = re.sub(
                r"\*\*(.*?)\*\*", r"<strong>\1</strong>", clean_content
            )
            html_output.append(
                f"<div style='margin-left: 16px; margin-bottom: 4px; font-size: 12.5px;'>• {clean_content}</div>"
            )
        else:
            clean_content = re.sub(
                r"\*\*(.*?)\*\*", r"<strong>\1</strong>", line_html
            )
            html_output.append(
                f"<div style='font-size: 12.5px; margin-bottom: 4px;'>{clean_content}</div>"
            )

    html_output.append("</div>")
    return "\n".join(html_output)


# ---------------------------------------------------------
# 6. ATS PDF COMPILER (UNICODE SAFE & ATS-COMPLIANT)
# ---------------------------------------------------------
def clean_text_for_pdf(text: str) -> str:
    replacements = {
        "\u2014": " - ",
        "\u2013": "-",
        "\u2015": " - ",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2022": "-",
        "\u2026": "...",
        "\u00a0": " ",
        "\u2010": "-",
        "\u2011": "-",
        "\u00b7": "-",
    }
    for bad_char, good_char in replacements.items():
        text = text.replace(bad_char, good_char)
    return text.encode("latin-1", "replace").decode("latin-1")


class ATSResumePDF(FPDF):
    def header(self):
        pass


def safe_cell(pdf, w, h, txt, align="L"):
    try:
        pdf.cell(w, h, txt, align=align, new_x="LMARGIN", new_y="NEXT")
    except TypeError:
        pdf.cell(w, h, txt, ln=1, align=align)


def safe_multi_cell(pdf, w, h, txt):
    try:
        pdf.multi_cell(w, h, txt, markdown=True, new_x="LMARGIN", new_y="NEXT")
    except TypeError:
        try:
            pdf.multi_cell(w, h, txt, markdown=True)
            pdf.set_x(pdf.l_margin)
        except TypeError:
            pdf.multi_cell(w, h, txt)
            pdf.set_x(pdf.l_margin)


def compile_resume_to_pdf(markdown_text):
    pdf = ATSResumePDF(format="letter", unit="pt")
    pdf.set_margins(36, 36, 36)
    pdf.set_auto_page_break(auto=True, margin=36)
    pdf.add_page()

    content_width = (
        pdf.epw
        if hasattr(pdf, "epw")
        else (pdf.w - pdf.l_margin - pdf.r_margin)
    )
    clean_markdown = clean_text_for_pdf(markdown_text)

    lines = clean_markdown.split("\n")
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            pdf.ln(3)
            continue

        pdf.set_x(pdf.l_margin)

        if line.startswith("# "):
            pdf.set_font("Helvetica", "B", 14)
            pdf.set_text_color(20, 20, 20)
            clean_name = line.replace("# ", "").replace("*", "")
            safe_cell(pdf, content_width, 18, clean_name, align="C")
            pdf.ln(1)
        elif "@" in line and "|" in line:
            pdf.set_font("Helvetica", "", 8.5)
            pdf.set_text_color(70, 70, 70)
            clean_contact = line.replace("*", "")
            safe_cell(pdf, content_width, 12, clean_contact, align="C")
            pdf.ln(3)
        elif line.startswith("## "):
            pdf.ln(4)
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(0, 0, 0)
            clean_title = line.replace("## ", "").replace("*", "").upper()
            safe_cell(pdf, content_width, 13, clean_title, align="L")
            line_y = pdf.get_y()
            pdf.set_draw_color(180, 180, 180)
            pdf.set_line_width(0.75)
            pdf.line(pdf.l_margin, line_y, pdf.w - pdf.r_margin, line_y)
            pdf.ln(3)
        elif line.startswith("### "):
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(20, 20, 20)
            clean_subhead = line.replace("### ", "").replace("*", "")
            safe_cell(pdf, content_width, 12, clean_subhead, align="L")
        elif line.startswith(("- ", "* ")):
            pdf.set_font("Helvetica", "", 8.5)
            pdf.set_text_color(30, 30, 30)
            bullet_body = line[2:].strip()
            safe_multi_cell(pdf, content_width, 11.5, f"  -  {bullet_body}")
        else:
            pdf.set_font("Helvetica", "", 8.5)
            pdf.set_text_color(30, 30, 30)
            safe_multi_cell(pdf, content_width, 11.5, line)

    return bytes(pdf.output())


# ---------------------------------------------------------
# 7. STREAMLIT APPLICATION INTERFACE
# ---------------------------------------------------------
st.title("🎯 Tailored Resume Builder & ATS PDF Generator")
st.caption("Baseline Template locked • AI Keyword Optimization • Live Diff")

if not master_data:
    st.error(
        "Could not find `master_resume.json` in the current folder. Please verify the file is in the repo root."
    )
    st.stop()

col_left, col_right = st.columns([1, 1], gap="medium")

with col_left:
    st.subheader("1. Target Job Source")
    
    # Read incoming URL parameter from Telegram deep link
    url_from_params = st.query_params.get("job_url", "")

    # Auto-fetch if the page was opened directly via Telegram link and not yet parsed
    if url_from_params and "job_spec" not in st.session_state:
        with st.spinner("Auto-fetching job spec from link..."):
            job_data, err = fetch_linkedin_job_details(url_from_params)
            if not err:
                st.session_state["job_spec"] = job_data

    job_url_input = st.text_input(
        "LinkedIn Job Posting URL:",
        value=url_from_params,
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
        height=240,
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
            "🔒 **Strict Mode:** Only uses verified facts and tools directly in your baseline resume."
        )
    elif slider_val <= 7:
        st.info(
            "⚖️ **Balanced Mode (Recommended):** Extrapolates adjacent PMO governance, platforms, and methodologies."
        )
    else:
        st.info(
            "🚀 **Aggressive Mode:** Directly mirrors all primary job keywords, frameworks, and ERP/platforms into experience bullets."
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

                if generated_text.startswith("ERROR:"):
                    st.error(generated_text)
                else:
                    st.session_state["tailored_markdown"] = generated_text
                    st.session_state["has_tailored"] = True
                    st.success("Draft ready for review!")

with col_right:
    st.subheader("3. Review & Approval")

    tab_preview, tab_edit = st.tabs(
        ["🔍 Highlighted Changes Preview", "✏️ Edit Markdown (Approval)"]
    )

    with tab_preview:
        st.markdown(
            "> 🟢 **Green highlighted text** marks keywords, metrics, or phrases modified/added from your original baseline resume."
        )
        diff_html = highlight_changes(
            ORIGINAL_RESUME_TEMPLATE, st.session_state["tailored_markdown"]
        )
        st.markdown(diff_html, unsafe_allow_html=True)

    with tab_edit:
        st.caption(
            "Make any manual adjustments below. Edits here will be included in the exported PDF."
        )
        user_approved_markdown = st.text_area(
            "Markdown Editor:",
            value=st.session_state["tailored_markdown"],
            height=540,
        )
        st.session_state["tailored_markdown"] = user_approved_markdown

    st.subheader("4. Export ATS-Compliant PDF")
    
    is_tailored = st.session_state.get("has_tailored", False) or st.session_state.get("tailored_markdown") != ORIGINAL_RESUME_TEMPLATE
    
    if not is_tailored:
        st.warning(
            "⚠️ You are viewing the default baseline resume. Tap **'⚡ Generate Tailored Resume'** above before downloading."
        )
        
    try:
        pdf_bytes = compile_resume_to_pdf(st.session_state["tailored_markdown"])
        safe_company = "".join(
            c for c in job_company if c.isalnum() or c in (" ", "_")
        ).rstrip()
        filename = (
            f"Kevin_George_{safe_company.replace(' ', '_')}_Resume.pdf"
            if safe_company
            else "Kevin_George_Resume.pdf"
        )

        st.download_button(
            label=f"📥 Download {filename}",
            data=pdf_bytes,
            file_name=filename,
            mime="application/pdf",
            type="primary",
            disabled=not is_tailored,
        )
    except Exception as e:
        st.error(f"Error compiling PDF: {e}")

import difflib
import json
import os
import re
import threading
import time
from bs4 import BeautifulSoup
from fpdf import FPDF
from google import genai
import requests
import streamlit as st

st.set_page_config(
    page_title="AI Resume Tailor & ATS Exporter", page_icon="📄", layout="wide"
)

def get_secret(key, default=None):
    if hasattr(st, "secrets") and key in st.secrets:
        return str(st.secrets[key]).strip().strip('"').strip("'")
    val = os.environ.get(key, default)
    if val:
        return str(val).strip().strip('"').strip("'")
    return default

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

if "tailored_markdown" not in st.session_state:
    st.session_state["tailored_markdown"] = ORIGINAL_RESUME_TEMPLATE

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
            return None, f"LinkedIn blocked or throttled the request (HTTP {resp.status_code})."
        soup = BeautifulSoup(resp.text, "html.parser")
        title_tag = soup.find("h2", class_="top-card-layout__title")
        company_tag = soup.find("a", class_="topcard__org-name-link")
        desc_container = soup.find("div", class_="show-more-less-html__markup")
        title = title_tag.text.strip() if title_tag else "Target Role"
        company = company_tag.text.strip() if company_tag else "Target Company"
        desc = desc_container.get_text(separator="\n", strip=True) if desc_container else ""
        if not desc:
            return None, "Job description was empty."
        return {"title": title, "company": company, "description": desc}, None
    except Exception as e:
        return None, f"Network error fetching job: {e}"

def build_tailoring_prompt(job_spec, master_json, aggressiveness):
    slider_rules = ""
    if 1 <= aggressiveness <= 3:
        slider_rules = """AGGRESSIVENESS LEVEL: LOW (Strict Truthfulness)\n- Rely strictly on the metrics, tools, and roles in the Baseline Template and Master Resume.\n- Do NOT introduce unverified software or frameworks."""
    elif 4 <= aggressiveness <= 7:
        slider_rules = """AGGRESSIVENESS LEVEL: BALANCED (Sensible Extrapolation)\n- Retain exact companies, titles, dates, and core metrics.\n- Draw from the 'adjacent_experience_bank' in the Master Resume."""
    else:
        slider_rules = """AGGRESSIVENESS LEVEL: MAXIMUM (Full Keyword Mirroring)\n- Aggressively tailor the resume to maximize ATS keyword scoring."""

    system_prompt = f"""You are an executive resume writer and ATS optimization specialist.
{slider_rules}
CANDIDATE BASELINE TEMPLATE (PRESERVE THIS EXACT STRUCTURE):
{ORIGINAL_RESUME_TEMPLATE}
FULL CAREER MASTER DATA:
{json.dumps(master_json, indent=2)}
TARGET JOB SPECIFICATION:
Title: {job_spec.get('title', '')}
Company: {job_spec.get('company', '')}
Description:
{job_spec.get('description', '')}

STRICT OUTPUT INSTRUCTIONS:
1. Retain EXACT layout, headers, bullet style, and sections of the BASELINE TEMPLATE.
2. Output ONLY valid Markdown.
"""
    return system_prompt

def generate_tailored_resume_gemini(prompt):
    api_key = get_secret("GEMINI_API_KEY")
    if not api_key:
        return "ERROR: `GEMINI_API_KEY` missing in Streamlit Secrets."
    try:
        client = genai.Client(api_key=api_key)
    except Exception as e:
        return f"ERROR: Failed to initialize Gemini client: {e}"
    
    candidate_models = ["gemini-3.8-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    last_error = None
    for model_name in candidate_models:
        try:
            response = client.models.generate_content(model=model_name, contents=prompt)
            if response and response.text:
                return response.text
        except Exception as e:
            last_error = e
            continue
    return f"ERROR: Gemini API call failed: {last_error}"

def highlight_changes(base_text: str, tailored_text: str) -> str:
    base_lines = [l.strip() for l in base_text.splitlines() if l.strip()]
    html_output = ["<div style='font-family: -apple-system, sans-serif; line-height: 1.5; color: #1e1e1e; background-color: #ffffff; padding: 22px; border: 1px solid #e0e0e0; border-radius: 8px;'>"]
    for raw_t in tailored_text.splitlines():
        clean_t = raw_t.strip()
        if not clean_t:
            html_output.append("<div style='height: 8px;'></div>")
            continue
        if clean_t in base_lines:
            line_html = clean_t
        else:
            best_match = None
            best_ratio = 0
            for b_line in base_lines:
                ratio = difflib.SequenceMatcher(None, b_line, clean_t).ratio()
                if ratio > best_ratio and ratio > 0.35:
                    best_ratio = ratio
                    best_match = b_line
            if best_match:
                b_words = best_match.split()
                t_words = clean_t.split()
                matcher = difflib.SequenceMatcher(None, b_words, t_words)
                diff_words = []
                for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                    chunk = " ".join(t_words[j1:j2])
                    if not chunk: continue
                    if tag == "equal":
                        diff_words.append(chunk)
                    else:
                        diff_words.append(f'<mark style="background-color: #d1e7dd; color: #0f5132; font-weight: 600; padding: 1px 4px; border-radius: 3px; border: 1px solid #badbcc;">{chunk}</mark>')
                line_html = " ".join(diff_words)
            else:
                line_html = f'<mark style="background-color: #d1e7dd; color: #0f5132; font-weight: 600; padding: 1px 4px; border-radius: 3px; border: 1px solid #badbcc;">{clean_t}</mark>'

        if clean_t.startswith("# "):
            html_output.append(f"<h2 style='text-align: center; margin: 0 0 4px 0; font-size: 19px; color: #111;'>{line_html.replace('# ', '')}</h2>")
        elif "@" in clean_t and "|" in clean_t:
            html_output.append(f"<div style='text-align: center; font-size: 12.5px; color: #555; margin-bottom: 12px;'>{line_html}</div>")
        elif clean_t.startswith("## "):
            html_output.append(f"<h4 style='font-size: 13.5px; margin: 14px 0 4px 0; text-transform: uppercase; border-bottom: 1.5px solid #bbb; padding-bottom: 2px; color: #222;'>{line_html.replace('## ', '')}</h4>")
        elif clean_t.startswith("### "):
            html_output.append(f"<div style='font-weight: bold; font-size: 13px; margin: 8px 0 2px 0; color: #222;'>{line_html.replace('### ', '')}</div>")
        elif clean_t.startswith(("- ", "* ", "• ")):
            clean_content = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", line_html[2:].strip() if line_html.startswith(clean_t[:2]) else line_html)
            html_output.append(f"<div style='margin-left: 16px; margin-bottom: 4px; font-size: 12.5px;'>• {clean_content}</div>")
        else:
            html_output.append(f"<div style='font-size: 12.5px; margin-bottom: 4px;'>{re.sub(r'\\*\\*(.*?)\\*\\*', r'<strong>\1</strong>', line_html)}</div>")
    html_output.append("</div>")
    return "\n".join(html_output)

def clean_text_for_pdf(text: str) -> str:
    replacements = {"\u2014": " - ", "\u2013": "-", "\u2015": " - ", "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2022": "-", "\u2026": "...", "\u00a0": " ", "\u2010": "-", "\u2011": "-", "\u00b7": "-"}
    for bad_char, good_char in replacements.items():
        text = text.replace(bad_char, good_char)
    return text.encode("latin-1", "replace").decode("latin-1")

class ATSResumePDF(FPDF):
    def header(self): pass

def safe_cell(pdf, w, h, txt, align="L"):
    try: pdf.cell(w, h, txt, align=align, new_x="LMARGIN", new_y="NEXT")
    except TypeError: pdf.cell(w, h, txt, ln=1, align=align)

def safe_multi_cell(pdf, w, h, txt):
    try: pdf.multi_cell(w, h, txt, markdown=True, new_x="LMARGIN", new_y="NEXT")
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
    content_width = pdf.epw if hasattr(pdf, "epw") else (pdf.w - pdf.l_margin - pdf.r_margin)
    clean_markdown = clean_text_for_pdf(markdown_text)
    for raw_line in clean_markdown.split("\n"):
        line = raw_line.strip()
        if not line:
            pdf.ln(3)
            continue
        pdf.set_x(pdf.l_margin)
        if line.startswith("# "):
            pdf.set_font("Helvetica", "B", 14)
            pdf.set_text_color(20, 20, 20)
            safe_cell(pdf, content_width, 18, line.replace("# ", "").replace("*", ""), align="C")
            pdf.ln(1)
        elif "@" in line and "|" in line:
            pdf.set_font("Helvetica", "", 8.5)
            pdf.set_text_color(70, 70, 70)
            safe_cell(pdf, content_width, 12, line.replace("*", ""), align="C")
            pdf.ln(3)
        elif line.startswith("## "):
            pdf.ln(4)
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(0, 0, 0)
            safe_cell(pdf, content_width, 13, line.replace("## ", "").replace("*", "").upper(), align="L")
            line_y = pdf.get_y()
            pdf.set_draw_color(180, 180, 180)
            pdf.set_line_width(0.75)
            pdf.line(pdf.l_margin, line_y, pdf.w - pdf.r_margin, line_y)
            pdf.ln(3)
        elif line.startswith("### "):
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(20, 20, 20)
            safe_cell(pdf, content_width, 12, line.replace("### ", "").replace("*", ""), align="L")
        elif line.startswith(("- ", "* ")):
            pdf.set_font("Helvetica", "", 8.5)
            pdf.set_text_color(30, 30, 30)
            safe_multi_cell(pdf, content_width, 11.5, f"  -  {line[2:].strip()}")
        else:
            pdf.set_font("Helvetica", "", 8.5)
            pdf.set_text_color(30, 30, 30)
            safe_multi_cell(pdf, content_width, 11.5, line)
    return bytes(pdf.output())

def answer_callback_query(bot_token, callback_id, text):
    url = f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery"
    try:
        requests.post(url, json={"callback_query_id": callback_id, "text": text, "show_alert": True}, timeout=5)
    except Exception as e:
        print(f"Callback answer warning: {e}")

def send_pdf_to_telegram(bot_token, target_chat_id, pdf_bytes, filename, caption, thread_id=None):
    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    data = {"chat_id": target_chat_id, "caption": caption, "parse_mode": "HTML"}
    if thread_id:
        try: data["message_thread_id"] = int(thread_id)
        except Exception: pass
    files = {"document": (filename, pdf_bytes, "application/pdf")}
    try:
        resp = requests.post(url, data=data, files=files, timeout=30)
        if resp.status_code != 200: print(f"❌ Telegram sendDocument error ({resp.status_code}): {resp.text}")
        else: print(f"✅ Delivered tailored PDF to chat {target_chat_id}: {filename}")
    except Exception as e:
        print(f"❌ Exception uploading PDF: {e}")

def process_telegram_tailor_request(bot_token, job_id, chat_id):
    print(f"⚡ Processing tailor request for Job ID: {job_id}")
    job_url = f"https://www.linkedin.com/jobs/view/{job_id}/"
    job_data, err = fetch_linkedin_job_details(job_url)
    if err or not job_data:
        job_data = {"title": "PMO / Project Management Lead", "company": "Target Company", "description": f"Target job ID: {job_id}"}
    
    prompt = build_tailoring_prompt(job_data, master_data, aggressiveness=6)
    tailored_md = generate_tailored_resume_gemini(prompt)
    if tailored_md.startswith("ERROR:"):
        requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={"chat_id": chat_id, "text": f"❌ Tailoring failed: {tailored_md}"}, timeout=10)
        return
    
    pdf_bytes = compile_resume_to_pdf(tailored_md)
    safe_company = "".join(c for c in job_data["company"] if c.isalnum() or c in (" ", "_")).strip()
    filename = f"Kevin_George_{safe_company.replace(' ', '_')}_Resume.pdf" if safe_company else "Kevin_George_Resume.pdf"
    caption = f"🎯 <b>TAILORED RESUME READY</b>\n\n💼 <b>{job_data['title']}</b>\n🏢 {job_data['company']}\n\n🔗 <a href='{job_url}'>Click Here to Apply on LinkedIn</a>"
    
    applied_chat = get_secret("APPLIED_CHAT_ID")
    send_pdf_to_telegram(bot_token, applied_chat if applied_chat else chat_id, pdf_bytes, filename, caption)

def telegram_polling_daemon():
    bot_token = get_secret("TELEGRAM_TOKEN")
    if not bot_token:
        print("❌ TELEGRAM_TOKEN missing; listener idle.")
        return
    try: requests.get(f"https://api.telegram.org/bot{bot_token}/deleteWebhook?drop_pending_updates=false", timeout=10)
    except Exception: pass
    
    offset = 0
    print("🚀 Telegram background listener started and actively polling...")
    while True:
        try:
            resp = requests.get(f"https://api.telegram.org/bot{bot_token}/getUpdates?offset={offset}&timeout=20", timeout=25)
            if resp.status_code == 200:
                data = resp.json()
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    
                    # 1. Catch /ping commands to prove Streamlit is alive
                    if "message" in update and "text" in update["message"]:
                        if update["message"]["text"].strip().lower() == "/ping":
                            chat_id = update["message"]["chat"]["id"]
                            requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={"chat_id": chat_id, "text": "🏓 Pong from Streamlit! Listener is alive."})
                    
                    # 2. Catch ALL button clicks and echo them to the chat
                    if "callback_query" in update:
                        cb = update["callback_query"]
                        cb_data = cb.get("data", "")
                        chat_id = cb.get("message", {}).get("chat", {}).get("id") or cb.get("from", {}).get("id")
                        
                        # Debug: Send the exact callback data back to Telegram so we can see it
                        requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={"chat_id": chat_id, "text": f"🛠️ Debug: Button tapped! Hidden data is: '{cb_data}'"})
                        
                        if cb_data.startswith("tailor:"):
                            job_id = cb_data.split(":", 1)[1]
                            answer_callback_query(bot_token, cb.get("id"), "⏳ Tailoring resume in background... PDF incoming!")
                            threading.Thread(target=process_telegram_tailor_request, args=(bot_token, job_id, chat_id), daemon=True).start()
            elif resp.status_code == 409: time.sleep(10)
            else: time.sleep(5)
        except Exception: time.sleep(5)

class BotRunner:
    def __init__(self):
        self.thread = None
        self.ensure_running()
    def ensure_running(self):
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=telegram_polling_daemon, daemon=True)
            self.thread.start()

@st.cache_resource
def get_bot_runner():
    return BotRunner()

runner = get_bot_runner()
runner.ensure_running()

# --- DIAGNOSTIC PANEL & UI ---
st.title("🎯 Tailored Resume Builder & ATS PDF Generator")

with st.expander("🛠️ Telegram Bot & System Diagnostic Panel", expanded=False):
    t_token = get_secret("TELEGRAM_TOKEN")
    g_key = get_secret("GEMINI_API_KEY")
    chat_dest = get_secret("APPLIED_CHAT_ID")
    is_alive = runner.thread.is_alive() if runner.thread else False

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Gemini API Key", "✅ Found" if g_key else "❌ Missing")
    c2.metric("Telegram Token", "✅ Found" if t_token else "❌ Missing")
    c3.metric("Dest Chat ID", chat_dest if chat_dest else "Default")
    c4.metric("Bot Listener Thread", "🟢 Running" if is_alive else "🔴 Stopped")

    if st.button("🧪 Send Test Message to My Applications"):
        if not t_token: st.error("Cannot test: TELEGRAM_TOKEN is missing in Streamlit secrets.")
        else:
            test_resp = requests.post(f"https://api.telegram.org/bot{t_token}/sendMessage", json={"chat_id": chat_dest or "0", "text": "✅ Test connection successful!"})
            if test_resp.status_code == 200: st.success("Message delivered!")
            else: st.error(f"Telegram Error ({test_resp.status_code}): {test_resp.text}")

if not master_data:
    st.error("Could not find `master_resume.json`.")
    st.stop()

col_left, col_right = st.columns([1, 1], gap="medium")
with col_left:
    st.subheader("1. Target Job Source")
    job_url_input = st.text_input("LinkedIn Job Posting URL:", placeholder="https://www.linkedin.com/jobs/view/...")
    if st.button("📥 Fetch Job from LinkedIn") and job_url_input:
        with st.spinner("Scraping..."):
            job_data, err = fetch_linkedin_job_details(job_url_input)
            if err: st.warning(err)
            else:
                st.session_state["job_spec"] = job_data
                st.success(f"Fetched: {job_data['title']}")

    default_desc = st.session_state.get("job_spec", {}).get("description", "")
    default_title = st.session_state.get("job_spec", {}).get("title", "PMO / Project Management Lead")
    default_company = st.session_state.get("job_spec", {}).get("company", "Target Company")

    job_title = st.text_input("Target Job Title", value=default_title)
    job_company = st.text_input("Target Company", value=default_company)
    job_description = st.text_area("Full Job Description:", value=default_desc, height=240)

    st.subheader("2. Tailoring Aggressiveness")
    slider_val = st.slider("Aggressiveness Level", 1, 10, 6)

    if st.button("⚡ Generate Tailored Resume", type="primary") and job_description:
        with st.spinner("AI Engine tailoring resume..."):
            prompt = build_tailoring_prompt({"title": job_title, "company": job_company, "description": job_description}, master_data, slider_val)
            generated = generate_tailored_resume_gemini(prompt)
            if generated.startswith("ERROR:"): st.error(generated)
            else:
                st.session_state["tailored_markdown"] = generated
                st.session_state["has_tailored"] = True
                st.success("Draft ready!")

with col_right:
    st.subheader("3. Review & Approval")
    tab_preview, tab_edit = st.tabs(["🔍 Preview", "✏️ Edit"])
    with tab_preview:
        st.markdown(highlight_changes(ORIGINAL_RESUME_TEMPLATE, st.session_state["tailored_markdown"]), unsafe_allow_html=True)
    with tab_edit:
        st.session_state["tailored_markdown"] = st.text_area("Markdown Editor:", value=st.session_state["tailored_markdown"], height=540)
    
    st.subheader("4. Export ATS-Compliant PDF")
    is_tailored = st.session_state.get("has_tailored", False)
    try:
        safe_c = "".join(c for c in job_company if c.isalnum() or c in (" ", "_")).rstrip()
        filename = f"Kevin_George_{safe_c.replace(' ', '_')}_Resume.pdf" if safe_c else "Kevin_George_Resume.pdf"
        st.download_button("📥 Download PDF", data=compile_resume_to_pdf(st.session_state["tailored_markdown"]), file_name=filename, mime="application/pdf", type="primary", disabled=not is_tailored)
    except Exception as e: st.error(f"Error compiling PDF: {e}")

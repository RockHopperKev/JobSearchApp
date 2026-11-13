import html
import json
import os
import re
import time
import urllib.parse
from bs4 import BeautifulSoup
import requests

# Fetch secrets from GitHub Actions environment
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
SEEN_JOBS_FILE = "seen_jobs.txt"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ---------------------------------------------------------------------------
# Salary detection
# ---------------------------------------------------------------------------
# Matches things like: $120,000 - $150,000 | $120K-$150K | $120-150k |
# $55/hr | $55.00 - $65.00 per hour | USD $140,000 per year
SALARY_RE = re.compile(
    r"""
    (?:USD\s?)?\$\s?(?P<lo>\d[\d,]*(?:\.\d+)?)\s?(?P<lo_k>[kK])?(?!\w)
    (?:
        \s?(?:-|–|—|to)\s?
        (?:USD\s?)?\$?\s?(?P<hi>\d[\d,]*(?:\.\d+)?)\s?(?P<hi_k>[kK])?(?!\w)
    )?
    (?P<unit>
        \s?(?:/|per\s+)\s?(?:yr|year|hr|hour|annum)\b
        |\s(?:annually|hourly)\b
    )?
    """,
    re.VERBOSE | re.IGNORECASE,
)

# A dollar figure only counts if pay-related wording appears near it.
# This avoids false positives like "$500,000 project budget".
SALARY_CONTEXT_RE = re.compile(
    r"\b(salary|salaries|compensation|pay|wage|wages|earn|earnings|ote|hourly)\b",
    re.IGNORECASE,
)


def _amount(num, k_suffix):
    if not num:
        return None
    try:
        value = float(num.replace(",", ""))
    except ValueError:
        return None
    return value * 1000 if k_suffix else value


def extract_salary(text):
    """Finds a salary or pay range in free text. Returns a short string or None."""
    if not text:
        return None

    best_single = None
    for m in SALARY_RE.finditer(text):
        lo = _amount(m.group("lo"), m.group("lo_k"))
        hi = _amount(m.group("hi"), m.group("hi_k"))
        if lo is None:
            continue

        # Shorthand like "$120-150k": the k applies to both numbers
        if hi is not None and m.group("hi_k") and not m.group("lo_k") and lo < 1000:
            lo *= 1000

        unit = (m.group("unit") or "").lower()
        hourly = "hr" in unit or "hour" in unit
        values = [v for v in (lo, hi) if v is not None]

        if hourly:
            plausible = all(10 <= v <= 500 for v in values)
        else:
            plausible = all(30000 <= v <= 1000000 for v in values)
        if not plausible:
            continue

        window = text[max(0, m.start() - 200): m.end() + 60]
        if not SALARY_CONTEXT_RE.search(window):
            continue

        found = re.sub(r"\s+", " ", m.group(0)).strip()
        if hi is not None:
            return found  # a full range is the best match
        if best_single is None:
            best_single = found

    return best_single


def find_salary(job, job_card, headers):
    """Looks for salary on the search card first, then inside the job posting itself."""
    # 1. Salary shown directly on the search card (when LinkedIn provides it)
    if job_card:
        tag = job_card.find("span", class_="job-search-card__salary-info")
        if tag and tag.get_text(strip=True):
            return re.sub(r"\s+", " ", tag.get_text(" ", strip=True))

    # 2. Otherwise open the posting and look for it
    match = re.search(r"(\d{8,})", job["Link"])
    if not match:
        return None
    api_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{match.group(1)}"
    try:
        resp = requests.get(api_url, headers=headers, timeout=10)
        if resp.status_code != 200:
            print(f"Salary lookup skipped (HTTP {resp.status_code}) for {job['Link']}")
            return None
        soup = BeautifulSoup(resp.text, "html.parser")

        # LinkedIn's own salary field, when the posting has one
        tag = soup.find(class_="compensation__salary")
        if tag and tag.get_text(strip=True):
            return re.sub(r"\s+", " ", tag.get_text(" ", strip=True))

        # Otherwise search the job description text
        desc = soup.find("div", class_="show-more-less-html__markup")
        if desc:
            return extract_salary(desc.get_text(separator="\n", strip=True))
    except Exception as e:
        print(f"Salary lookup failed: {e}")
    return None


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
def send_telegram_alert(job):
    """Sends a job alert with an interactive in-app callback button."""
    match = re.search(r"(\d{8,})", job["Link"])
    job_id = match.group(1) if match else "unknown"

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    message = (
        f"🚨 <b>NEW PRIORITY JOB</b> 🚨\n\n"
        f"💼 <b>{job['Title']}</b>\n"
        f"🏢 {job['Company']}\n"
        f"📍 {job['Location']}\n"
    )
    if job.get("Salary"):
        message += f"💰 {html.escape(job['Salary'])}\n"
    message += f"🕒 {job['Posted']}"

    # Pass reply_markup directly as a dictionary when using json=payload
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "🔗 View Posting", "url": job["Link"]},
                    {
                        "text": "⚡ Tailor & Apply",
                        "callback_data": f"tailor:{job_id}",
                    },
                ]
            ]
        },
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            print(f"Telegram API Error ({resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"Failed to send Telegram alert: {e}")


def load_seen_jobs():
    """Loads previously seen job URLs to avoid duplicate alerts."""
    if os.path.exists(SEEN_JOBS_FILE):
        with open(SEEN_JOBS_FILE, "r") as f:
            return set(f.read().splitlines())
    return set()


def save_seen_jobs(seen_urls):
    """Saves job URLs so the bot remembers them for next run."""
    with open(SEEN_JOBS_FILE, "w") as f:
        f.write("\n".join(seen_urls))


def is_priority(job, job_card):
    """Priority check for Illinois (Chicago + suburbs) & Remote roles."""
    title = job["Title"].lower()
    location = job["Location"].lower()
    link = job["Link"].lower()
    card_text = (
        job_card.get_text(separator=" ", strip=True).lower() if job_card else ""
    )

    combined_text = f"{title} {location} {link} {card_text}"

    # 1. Check for Chicago, Illinois, or IL state tags
    il_terms = ["chicago", "illinois", ", il", " il ", "il,"]
    for term in il_terms:
        if term in location or term in combined_text:
            return True

    # 2. Check for Remote & common remote synonyms
    remote_terms = ["remote", "work from home", "wfh", "telecommute", "virtual"]
    for term in remote_terms:
        if term in combined_text:
            return True

    return False


def run_scraper():
    headers = HEADERS

    seen_urls = load_seen_jobs()
    new_jobs_found = False

    # Targeted searches for Illinois & Remote
    search_configs = [
        {
            "keywords": 'PMO OR "Project Management"',
            "location": "Illinois, United States",
        },
        {
            "keywords": 'PMO OR "Project Management" AND Remote',
            "location": "United States",
        },
    ]

    for config in search_configs:
        encoded_keywords = urllib.parse.quote(config["keywords"])
        encoded_location = urllib.parse.quote(config["location"])

        for page in range(2):
            start = page * 25
            url = (
                f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?"
                f"keywords={encoded_keywords}&location={encoded_location}&f_TPR=r86400&sortBy=DD&start={start}"
            )

            try:
                response = requests.get(url, headers=headers, timeout=10)
                if response.status_code != 200:
                    break

                soup = BeautifulSoup(response.text, "html.parser")
                cards = soup.find_all("li")
                if not cards:
                    break

                for job_card in cards:
                    title_tag = job_card.find(
                        "h3", class_="base-search-card__title"
                    )
                    company_tag = job_card.find(
                        "h4", class_="base-search-card__subtitle"
                    )
                    location_tag = job_card.find(
                        "span", class_="job-search-card__location"
                    )
                    link_tag = job_card.find("a", class_="base-card__full-link")
                    time_tag = job_card.find("time")

                    if title_tag and company_tag and link_tag:
                        clean_url = link_tag["href"].split("?")[0]

                        if clean_url in seen_urls:
                            continue

                        job = {
                            "Title": title_tag.text.strip(),
                            "Company": company_tag.text.strip(),
                            "Location": (
                                location_tag.text.strip()
                                if location_tag
                                else "N/A"
                            ),
                            "Posted": (
                                time_tag.text.strip() if time_tag else "N/A"
                            ),
                            "Link": clean_url,
                        }

                        if is_priority(job, job_card):
                            job["Salary"] = find_salary(job, job_card, headers)
                            send_telegram_alert(job)
                            seen_urls.add(clean_url)
                            new_jobs_found = True
                            time.sleep(1)

                time.sleep(2)
            except Exception as e:
                print(f"Error scraping page: {e}")
                break

    if new_jobs_found:
        save_seen_jobs(seen_urls)
        print("Alerts sent and memory updated.")
    else:
        print("No new priority jobs found this run.")


if __name__ == "__main__":
    run_scraper()

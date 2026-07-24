import os
import urllib.parse
import time
from bs4 import BeautifulSoup
import requests

# Fetch secrets from GitHub Actions environment
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
SEEN_JOBS_FILE = "seen_jobs.txt"


def send_telegram_alert(job):
    """Sends a formatted message to your Telegram app."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    message = (
        f"🚨 <b>NEW PRIORITY JOB</b> 🚨\n\n"
        f"💼 <b>{job['Title']}</b>\n"
        f"🏢 {job['Company']}\n"
        f"📍 {job['Location']}\n"
        f"🕒 {job['Posted']}\n\n"
        f"<a href='{job['Link']}'>🔗 Apply Here</a>"
    )
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    requests.post(url, data=data)


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
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    seen_urls = load_seen_jobs()
    new_jobs_found = False

    # Targeted API searches for Illinois (Chicago + suburbs) & Remote
    search_configs = [
        # Target 1: PMO/PM across all of Illinois
        {
            "keywords": 'PMO OR "Project Management"',
            "location": "Illinois, United States",
        },
        # Target 2: Remote PMO/PM across the US
        {
            "keywords": 'PMO OR "Project Management" AND Remote',
            "location": "United States",
        },
    ]

    for config in search_configs:
        encoded_keywords = urllib.parse.quote(config["keywords"])
        encoded_location = urllib.parse.quote(config["location"])

        # Fetch 2 pages (50 jobs) per targeted search bucket
        for page in range(2):
            start = page * 25
            url = (
                f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?"
                f"keywords={encoded_keywords}&location={encoded_location}&f_TPR=r86400&sortBy=DD&start={start}"
            )

            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                break

            soup = BeautifulSoup(response.text, "html.parser")
            cards = soup.find_all("li")
            if not cards:
                break

            for job_card in cards:
                title_tag = job_card.find("h3", class_="base-search-card__title")
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

                    # Skip if already alerted
                    if clean_url in seen_urls:
                        continue

                    job = {
                        "Title": title_tag.text.strip(),
                        "Company": company_tag.text.strip(),
                        "Location": (
                            location_tag.text.strip() if location_tag else "N/A"
                        ),
                        "Posted": time_tag.text.strip() if time_tag else "N/A",
                        "Link": clean_url,
                    }

                    if is_priority(job, job_card):
                        send_telegram_alert(job)
                        seen_urls.add(clean_url)
                        new_jobs_found = True
                        time.sleep(1)

            time.sleep(2)  # Pause between page loads

    if new_jobs_found:
        save_seen_jobs(seen_urls)
        print("Alerts sent and memory updated.")
    else:
        print("No new priority jobs found this run.")


if __name__ == "__main__":
    run_scraper()

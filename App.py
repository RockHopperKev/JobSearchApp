import urllib.parse
import time
from bs4 import BeautifulSoup
import requests
import streamlit as st


def is_priority(job):
    """Returns True if the job matches Chicago or Remote criteria."""
    location = job["Location"].lower()
    title = job["Title"].lower()
    return "chicago" in location or "remote" in location or "remote" in title


def fetch_linkedin_jobs(max_pages=3):
    """Fetches multiple pages of jobs (25 jobs per page) and sorts priority roles to the top."""
    keywords = 'PMO OR "Project Management"'
    location = "United States"

    encoded_keywords = urllib.parse.quote(keywords)
    encoded_location = urllib.parse.quote(location)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 10; Mobile) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Mobile Safari/537.36"
        )
    }

    all_jobs = []
    seen_urls = set()

    print(
        f"Searching LinkedIn across {max_pages} pages (~{max_pages * 25} jobs max)..."
    )

    for page in range(max_pages):
        # LinkedIn paginates by 25 results (start=0, start=25, start=50, etc.)
        start = page * 25
        url = (
            f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?"
            f"keywords={encoded_keywords}&location={encoded_location}&f_TPR=r86400&sortBy=DD&start={start}"
        )

        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            print(f"Stopped at page {page + 1} (HTTP {response.status_code})")
            break

        soup = BeautifulSoup(response.text, "html.parser")
        cards = soup.find_all("li")

        if not cards:
            break

        for job_card in cards:
            title_tag = job_card.find("h3", class_="base-search-card__title")
            company_tag = job_card.find("h4", class_="base-search-card__subtitle")
            location_tag = job_card.find("span", class_="job-search-card__location")
            link_tag = job_card.find("a", class_="base-card__full-link")
            time_tag = job_card.find("time")

            if title_tag and company_tag and link_tag:
                clean_url = link_tag["href"].split("?")[0]

                # Skip duplicates across pages
                if clean_url in seen_urls:
                    continue
                seen_urls.add(clean_url)

                all_jobs.append({
                    "Title": title_tag.text.strip(),
                    "Company": company_tag.text.strip(),
                    "Location": (
                        location_tag.text.strip() if location_tag else "N/A"
                    ),
                    "Posted": time_tag.text.strip() if time_tag else "N/A",
                    "Link": clean_url,
                })

        # Brief pause between page fetches to avoid rate-limiting
        time.sleep(1.5)

    # Sort list: Priority jobs (True) come first, standard jobs (False) second
    all_jobs.sort(key=lambda j: not is_priority(j))

    return all_jobs


if __name__ == "__main__":
    # Adjust max_pages=3 (75 jobs) or max_pages=4 (100 jobs) as needed
    jobs = fetch_linkedin_jobs(max_pages=3)

    if jobs:
        print(f"\nFound {len(jobs)} jobs in the last 24 hours:")
        print("=" * 45 + "\n")

        for idx, job in enumerate(jobs, 1):
            tag = "⭐ [PRIORITY]" if is_priority(job) else "  [STANDARD]"
            print(f"{idx}. {tag} {job['Title']}")
            print(f"   🏢 {job['Company']} | 📍 {job['Location']}")
            print(f"   🕒 {job['Posted']}")
            print(f"   🔗 {job['Link']}\n")
    else:
        print("No jobs found or request was throttled. Try again shortly.")

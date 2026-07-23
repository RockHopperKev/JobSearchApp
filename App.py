import urllib.parse
import time
from bs4 import BeautifulSoup
import requests
import streamlit as st

st.set_page_config(page_title="PMO Job Finder", page_icon="💼", layout="centered")

st.title("💼 PMO & Project Management Jobs")
st.caption("LinkedIn listings from the last 24 hours (US)")

def is_priority(job):
    location = job["Location"].lower()
    title = job["Title"].lower()
    return "chicago" in location or "remote" in location or "remote" in title

def fetch_linkedin_jobs(max_pages=2):
    keywords = 'PMO OR "Project Management"'
    location = "United States"

    encoded_keywords = urllib.parse.quote(keywords)
    encoded_location = urllib.parse.quote(location)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    all_jobs = []
    seen_urls = set()

    for page in range(max_pages):
        start = page * 25
        url = (
            f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?"
            f"keywords={encoded_keywords}&location={encoded_location}&f_TPR=r86400&sortBy=DD&start={start}"
        )

        try:
            response = requests.get(url, headers=headers, timeout=10)
            
            # Show diagnostic info if blocked
            if response.status_code != 200:
                st.error(f"LinkedIn returned HTTP Status {response.status_code}. (Cloud IP may be throttled)")
                break

            soup = BeautifulSoup(response.text, "html.parser")
            cards = soup.find_all("li")

            if not cards:
                if page == 0:
                    st.warning("LinkedIn returned 0 job cards. The cloud server IP might be temporarily restricted.")
                break

            for job_card in cards:
                title_tag = job_card.find("h3", class_="base-search-card__title")
                company_tag = job_card.find("h4", class_="base-search-card__subtitle")
                location_tag = job_card.find("span", class_="job-search-card__location")
                link_tag = job_card.find("a", class_="base-card__full-link")
                time_tag = job_card.find("time")

                if title_tag and company_tag and link_tag:
                    clean_url = link_tag["href"].split("?")[0]

                    if clean_url in seen_urls:
                        continue
                    seen_urls.add(clean_url)

                    all_jobs.append({
                        "Title": title_tag.text.strip(),
                        "Company": company_tag.text.strip(),
                        "Location": location_tag.text.strip() if location_tag else "N/A",
                        "Posted": time_tag.text.strip() if time_tag else "N/A",
                        "Link": clean_url,
                    })

            time.sleep(1)

        except Exception as e:
            st.error(f"Request failed: {e}")
            break

    all_jobs.sort(key=lambda j: not is_priority(j))
    return all_jobs

# Auto-run search when page loads
with st.spinner("Searching LinkedIn for fresh postings..."):
    jobs = fetch_linkedin_jobs(max_pages=2)

if jobs:
    st.success(f"Found {len(jobs)} jobs posted in the last 24 hours!")
    for job in jobs:
        priority = is_priority(job)
        title_text = f"⭐ **{job['Title']}**" if priority else job['Title']

        with st.container(border=True):
            st.markdown(f"### {title_text}")
            st.write(f"🏢 **{job['Company']}** | 📍 **{job['Location']}** | 🕒 {job['Posted']}")
            st.link_button("Apply on LinkedIn 🔗", job["Link"])
elif not jobs:
    st.info("Click below to retry the search.")
    if st.button("🔄 Refresh Search"):
        st.rerun()

#!/usr/bin/env python3
"""
Sunglass Hut US Store Locations Scraper

This script extracts all US store details from https://stores.sunglasshut.com/us.

Extracted fields:
- Name
- Address (Full Street, City, State, Zip)
- Phone Number
- Operation Hours
- Store URL
- Google Map Link
"""

import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

SITEMAP_URL = "https://stores.sunglasshut.com/sitemap1.xml"
BASE_US_URL = "https://stores.sunglasshut.com/us"


def get_store_urls_from_sitemap():
    """Fetch and filter US store URLs from sitemap1.xml."""
    logging.info("Fetching sitemap from %s...", SITEMAP_URL)
    try:
        r = requests.get(SITEMAP_URL, headers=HEADERS, timeout=15)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        urls = [loc.text for loc in root.findall(".//sm:loc", ns) if loc.text]
        
        us_store_urls = set()
        for u in urls:
            p = urlparse(u).path.rstrip("/")
            parts = [seg for seg in p.split("/") if seg]
            # US Store URLs have depth 4: ['us', '<state>', '<city>', '<store-street>']
            if len(parts) == 4 and parts[0] == "us":
                us_store_urls.add(u)
                
        logging.info("Discovered %d US store URLs from sitemap.", len(us_store_urls))
        return us_store_urls
    except Exception as e:
        logging.error("Failed to fetch sitemap: %s", e)
        return set()


def get_store_urls_from_directory():
    """Fallback directory crawler for stores via https://stores.sunglasshut.com/us."""
    logging.info("Scanning directory at %s...", BASE_US_URL)
    store_urls = set()
    city_urls = set()
    state_urls = set()

    def clean_href(href):
        path = href.replace("../", "").lstrip("/")
        if not path.startswith("us/"):
            path = "us/" + path
        url = "https://stores.sunglasshut.com/" + path
        if url.endswith(".html"):
            url = url[:-5]
        return url.rstrip("/")

    try:
        r_us = requests.get(BASE_US_URL, headers=HEADERS, timeout=15)
        soup_us = BeautifulSoup(r_us.text, "html.parser")
        for a in soup_us.find_all("a", href=True):
            href = a["href"]
            if href.startswith("us/"):
                state_urls.add(clean_href(href))

        logging.info("Discovered %d state directory pages.", len(state_urls))

        # Fetch state pages
        def scan_state(st_url):
            local_stores = set()
            local_cities = set()
            try:
                r_st = requests.get(st_url, headers=HEADERS, timeout=10)
                soup_st = BeautifulSoup(r_st.text, "html.parser")
                for a in soup_st.find_all("a", href=True):
                    href = a["href"]
                    if ("us/" in href or "../" in href) and not href.startswith("http"):
                        full = clean_href(href)
                        p = urlparse(full).path.rstrip("/")
                        parts = [seg for seg in p.split("/") if seg]
                        if len(parts) == 4 and parts[0] == "us":
                            local_stores.add(full)
                        elif len(parts) == 3 and parts[0] == "us":
                            local_cities.add(full)
            except Exception as e:
                logging.warning("Error scanning state page %s: %s", st_url, e)
            return local_stores, local_cities

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(scan_state, st) for st in state_urls]
            for f in as_completed(futures):
                s_stores, s_cities = f.result()
                store_urls.update(s_stores)
                city_urls.update(s_cities)

        logging.info("Scanned states: found %d direct stores, %d city pages.", len(store_urls), len(city_urls))

        # Fetch city pages
        def scan_city(ct_url):
            local_stores = set()
            try:
                r_ct = requests.get(ct_url, headers=HEADERS, timeout=10)
                soup_ct = BeautifulSoup(r_ct.text, "html.parser")
                for a in soup_ct.find_all("a", href=True):
                    href = a["href"]
                    if ("us/" in href or "../" in href) and not href.startswith("http"):
                        full = clean_href(href)
                        p = urlparse(full).path.rstrip("/")
                        parts = [seg for seg in p.split("/") if seg]
                        if len(parts) == 4 and parts[0] == "us":
                            local_stores.add(full)
            except Exception as e:
                logging.warning("Error scanning city page %s: %s", ct_url, e)
            return local_stores

        with ThreadPoolExecutor(max_workers=15) as executor:
            futures = [executor.submit(scan_city, ct) for ct in city_urls]
            for f in as_completed(futures):
                store_urls.update(f.result())

        logging.info("Directory scan completed: %d store URLs discovered.", len(store_urls))
        return store_urls
    except Exception as e:
        logging.error("Failed to crawl store directory: %s", e)
        return set()


def extract_store_details(url):
    """Fetch a store page and extract all required store fields."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        if r.status_code != 200:
            logging.warning("Received status %d for %s", r.status_code, url)
            return None

        soup = BeautifulSoup(r.text, "html.parser")

        name = ""
        street = ""
        city = ""
        state = ""
        postal_code = ""
        phone = ""
        opening_hours = []

        # 1. Parse JSON-LD metadata
        for s in soup.find_all("script", type="application/ld+json"):
            if not s.string:
                continue
            try:
                data = json.loads(s.string)
                graph = data.get("@graph", [data]) if isinstance(data, dict) else [data]
                for item in graph:
                    if not isinstance(item, dict):
                        continue
                    item_type = item.get("@type", "")
                    if item_type in ["LocalBusiness", "Optician", "Store", "ClothingStore"]:
                        name = item.get("name", "")
                        phone = item.get("telephone", "")
                        raw_hours = item.get("openingHours", [])
                        if isinstance(raw_hours, list):
                            opening_hours = raw_hours
                        elif isinstance(raw_hours, str):
                            opening_hours = [raw_hours]

                        addr = item.get("address", {})
                        if isinstance(addr, dict):
                            street = addr.get("streetAddress", "")
                            city = addr.get("addressLocality", "")
                            state = addr.get("addressRegion", "")
                            postal_code = str(addr.get("postalCode", ""))
            except Exception:
                pass

        # Fallbacks for Name and Phone
        if not name:
            h1 = soup.find("h1")
            if h1:
                name = h1.get_text(strip=True)

        if not phone:
            tel_link = soup.find("a", href=re.compile(r"tel:"))
            if tel_link:
                phone = tel_link.get_text(strip=True)

        # 2. Extract Google Map link
        map_link = ""
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "maps.google.com" in href or "google.com/maps" in href:
                map_link = href
                break

        # Fallback 1: Extract coordinates from script tags
        if not map_link:
            for s in soup.find_all("script"):
                if s.string and "latitude" in s.string:
                    m_lat = re.search(r'\"latitude\"\s*:\s*([0-9\.-]+)', s.string)
                    m_lng = re.search(r'\"longitude\"\s*:\s*([0-9\.-]+)', s.string)
                    if m_lat and m_lng:
                        map_link = f"https://www.google.com/maps?q={m_lat.group(1)},{m_lng.group(1)}"
                        break

        # Fallback 2: Construct search URL using address
        full_address = ", ".join(filter(None, [street, city, f"{state} {postal_code}".strip()]))
        if not map_link and full_address:
            map_link = f"https://www.google.com/maps/search/?api=1&query={quote(full_address)}"

        hours_str = "; ".join(opening_hours)

        return {
            "name": name,
            "address": full_address,
            "phone": phone,
            "operation_hrs": hours_str,
            "store_url": url,
            "google_map_link": map_link,
        }
    except Exception as e:
        logging.error("Error parsing store %s: %s", url, e)
        return None


def main():
    logging.info("Starting Sunglass Hut US Store scraper...")

    # Step 1: Combine store URLs from sitemap and directory traversal
    store_urls = get_store_urls_from_sitemap()
    if not store_urls:
        logging.info("Sitemap yielded no URLs, falling back to directory crawling...")
        store_urls = get_store_urls_from_directory()
    else:
        # Complement with directory to guarantee 100% coverage
        dir_urls = get_store_urls_from_directory()
        store_urls.update(dir_urls)

    sorted_store_urls = sorted(list(store_urls))
    logging.info("Total unique active store URLs to scrape: %d", len(sorted_store_urls))

    stores_data = []

    # Step 2: Extract store details concurrently
    with ThreadPoolExecutor(max_workers=20) as executor:
        future_to_url = {executor.submit(extract_store_details, url): url for url in sorted_store_urls}
        completed = 0
        total = len(sorted_store_urls)
        for future in as_completed(future_to_url):
            completed += 1
            res = future.result()
            if res:
                stores_data.append(res)
            if completed % 100 == 0 or completed == total:
                logging.info("Progress: %d / %d stores processed.", completed, total)

    logging.info("Successfully extracted %d store records.", len(stores_data))

    # Step 3: Save to JSON and CSV
    json_path = "sunglasshut_us_stores.json"
    csv_path = "sunglasshut_us_stores.csv"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(stores_data, f, indent=2, ensure_ascii=False)
    logging.info("Saved JSON output to %s", json_path)

    df = pd.DataFrame(stores_data)
    # Reorder columns explicitly as requested
    df = df[["name", "address", "phone", "operation_hrs", "store_url", "google_map_link"]]
    df.to_csv(csv_path, index=False, encoding="utf-8")
    logging.info("Saved CSV output to %s", csv_path)

    print("\n" + "=" * 60)
    print(f"COMPLETE: Extracted {len(stores_data)} US Sunglass Hut stores.")
    print(f"Outputs generated:\n - {json_path}\n - {csv_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()

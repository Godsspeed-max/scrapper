import csv
import os
import re
import time
import random
import logging
from urllib.parse import urljoin, urlparse

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    StaleElementReferenceException,
    WebDriverException,
)

# ============================================================
# CONFIGURATION
# ============================================================

BASE_URL = "https://www.walmart.com"
DIRECTORY_URL = "https://www.walmart.com/store-directory"

CITY_OUTPUT_FILE = "walmart_city_urls.csv"
STORE_OUTPUT_FILE = "walmart_store_urls.csv"

HEADLESS = False
PAGE_TIMEOUT = 45
MIN_DELAY = 10
MAX_DELAY = 15
MAX_RETRIES = 3

CITY_CSV_COLUMNS = ["State", "StateCode", "City", "CitySlug", "URL"]
STORE_CSV_COLUMNS = ["State", "StateCode", "City", "StoreName", "URL"]

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("walmart")

# ============================================================
# DRIVER SETUP
# ============================================================

def create_driver():
    options = uc.ChromeOptions()
    if HEADLESS:
        options.add_argument("--headless=new")
    
    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")

    driver = uc.Chrome(
        options=options,
        headless=HEADLESS,
        use_subprocess=True,
        version_main=151 # Update this to match your installed Chrome version if needed
    )
    driver.set_page_load_timeout(PAGE_TIMEOUT)
    return driver

# ============================================================
# HELPERS
# ============================================================

def random_delay():
    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

def clean_text(value):
    if value is None:
        return ""
    value = re.sub(r"\s+", " ", str(value))
    return value.strip()

def normalize_url(url):
    if not url:
        return None
    url = url.strip()
    if url.startswith("/"):
        url = urljoin(BASE_URL, url)
    return url.split("#")[0]

def safe_get(driver, url):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info("OPEN [%s] attempt=%s", url, attempt)
            driver.get(url)
            random_delay()
            return True
        except Exception as ex:
            logger.warning("Load failed: %s", ex)
            if attempt < MAX_RETRIES:
                time.sleep(attempt * 2)
    return False

def scroll_page(driver):
    last_height = 0
    for _ in range(8):
        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(random.uniform(1, 2))
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
        except Exception:
            break

# ============================================================
# CSV APPEND FUNCTIONS
# ============================================================

def append_city_csv(city_data):
    file_exists = os.path.exists(CITY_OUTPUT_FILE)
    file_empty = not file_exists or os.path.getsize(CITY_OUTPUT_FILE) == 0
    
    try:
        with open(CITY_OUTPUT_FILE, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=CITY_CSV_COLUMNS, extrasaction="ignore")
            if file_empty:
                writer.writeheader()
            
            row = {
                "State": city_data["state"],
                "StateCode": city_data["state_code"],
                "City": city_data["city"],
                "CitySlug": city_data["city_slug"],
                "URL": city_data["url"]
            }
            writer.writerow(row)
    except Exception as ex:
        logger.exception("City CSV write failed: %s", ex)


def append_store_csv(store_data):
    file_exists = os.path.exists(STORE_OUTPUT_FILE)
    file_empty = not file_exists or os.path.getsize(STORE_OUTPUT_FILE) == 0
    
    try:
        with open(STORE_OUTPUT_FILE, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=STORE_CSV_COLUMNS, extrasaction="ignore")
            if file_empty:
                writer.writeheader()
            
            row = {
                "State": store_data["state"],
                "StateCode": store_data["state_code"],
                "City": store_data["city"],
                "StoreName": store_data["link_text"],
                "URL": store_data["url"]
            }
            writer.writerow(row)
    except Exception as ex:
        logger.exception("Store CSV write failed: %s", ex)

# ============================================================
# EXTRACT SCRAPERS
# ============================================================

def extract_states(driver):
    logger.info("Opening store directory")
    if not safe_get(driver, DIRECTORY_URL):
        return []
    scroll_page(driver)
    states = []
    
    try:
        links = driver.find_elements(By.XPATH, '//a[contains(@href,"/store-directory/")]')
        for link in links:
            try:
                href = normalize_url(link.get_attribute("href"))
                text = clean_text(link.text)
                if not href: continue
                
                path = urlparse(href).path.rstrip("/")
                match = re.match(r"^/store-directory/([a-z]{2})$", path, re.I)
                if not match: continue
                
                state_code = match.group(1).upper()
                states.append({
                    "state": text,
                    "state_code": state_code,
                    "url": href
                })
            except StaleElementReferenceException:
                continue
    except Exception:
        logger.exception("State extraction failed")

    # Deduplicate
    unique = {item["state_code"]: item for item in states}
    states = sorted(unique.values(), key=lambda x: x["state"])
    
    logger.info("STATES FOUND: %s", len(states))
    return states


def extract_city_links(driver, state):
    logger.info("Scraping Cities for STATE: %s", state["state"])
    if not safe_get(driver, state["url"]):
        return []
    scroll_page(driver)
    cities = []
    
    try:
        links = driver.find_elements(By.XPATH, '//a[contains(@href,"/store-directory/")]')
        for link in links:
            try:
                href = normalize_url(link.get_attribute("href"))
                text = clean_text(link.text)
                if not href: continue
                
                path = urlparse(href).path.rstrip("/")
                parts = path.split("/")
                if len(parts) != 4 or parts[1].lower() != "store-directory":
                    continue
                
                state_code = parts[2]
                if state_code.lower() != state["state_code"].lower():
                    continue
                
                city_slug = parts[3]
                if not city_slug: continue
                
                cities.append({
                    "state": state["state"],
                    "state_code": state["state_code"],
                    "city": text,
                    "city_slug": city_slug,
                    "url": href
                })
            except Exception:
                continue
    except Exception:
        logger.exception("City extraction failed")

    # Deduplicate
    unique = {city["url"]: city for city in cities}
    cities = sorted(unique.values(), key=lambda x: x["city"])
    
    logger.info("CITIES FOUND: %s | %s", len(cities), state["state"])
    return cities


def extract_store_links(driver, city):
    logger.info("Scraping Stores for CITY: %s, %s", city["city"], city["state"])
    if not safe_get(driver, city["url"]):
        return []
    scroll_page(driver)
    stores = []
    
    try:
        links = driver.find_elements(By.XPATH, '//a[contains(@href,"/store/")]')
        for link in links:
            try:
                href = normalize_url(link.get_attribute("href"))
                text = clean_text(link.text)
                if not href: continue
                
                path = urlparse(href).path
                if not re.search(r"/store/[^/]+/[^/]+/", path, re.I):
                    continue
                
                stores.append({
                    "state": city["state"],
                    "state_code": city["state_code"],
                    "city": city["city"],
                    "url": href,
                    "link_text": text
                })
            except Exception:
                continue
    except Exception:
        logger.exception("Store URL extraction failed")

    # Deduplicate
    unique = {store["url"]: store for store in stores}
    stores = list(unique.values())
    
    logger.info("STORES FOUND: %s | %s", len(stores), city["city"])
    return stores

# ============================================================
# MAIN
# ============================================================

def main():
    logger.info("================================================")
    logger.info("WALMART URL EXTRACTOR (STATE -> CITY -> STORE)")
    logger.info("================================================")

    driver = create_driver()

    try:
        # 1. Grab all states
        states = extract_states(driver)
        if not states:
            logger.error("No states found")
            return

        # 2. Iterate through states to extract cities
        for state in states:
            cities = extract_city_links(driver, state)
            
            # Save the city URLs immediately for this state
            for city in cities:
                append_city_csv(city)

            # # 3. For each city, navigate and extract store URLs
            # for city in cities:
            #     stores = extract_store_links(driver, city)
                
            #     # Save the store URLs immediately for this city
            #     for store in stores:
            #         append_store_csv(store)

    except Exception as ex:
        logger.exception("Critical error during scraping: %s", ex)
    finally:
        try:
            driver.quit()
        except Exception:
            pass
        logger.info("Scraper finished. Check 'walmart_city_urls.csv' and 'walmart_store_urls.csv'.")


if __name__ == "__main__":
    main()
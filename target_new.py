import time
import os
import pandas as pd
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

# ===========================================================
# Configuration & File Paths
# ===========================================================
INPUT_EXCEL = "uszips.xlsx"          # Your input file with a 'Zipcode' column
CSV_FILE = "target_stores_backup.csv"  # Live backup of scraped data
EXCEL_FILE = "target_stores.xlsx"      # Final output file
ERROR_CSV_FILE = "error.csv"           # Logs any failed URLs

# ----------------------------
# 1. Read Zip Codes from Excel
# ----------------------------
try:
    df_zip = pd.read_excel(INPUT_EXCEL)
    # Convert to string and clean up in case Excel formatted them as decimals (e.g., 10002.0)
    #zip_codes = df_zip['zip'].astype(str).str.replace('.0', '', regex=False).str.strip().tolist()

    zip_codes = (
        df_zip['zip']
        .astype(str)
        .str.replace('.0', '', regex=False)
        .str.strip()
        .str.zfill(5)  # Adds leading zeros to make it exactly 5 characters
        .tolist()
    )

    print(f"Loaded {len(zip_codes)} zip codes from {INPUT_EXCEL}")
except Exception as e:
    print(f"Failed to load {INPUT_EXCEL}. Make sure the file exists and has a 'Zipcode' column.")
    print(f"Error: {e}")
    exit()

# ----------------------------
# Chrome Configuration (undetected_chromedriver)
# ----------------------------
options = uc.ChromeOptions()
options.add_argument("--start-maximized")
options.add_argument("--disable-notifications")
options.add_argument('--ignore-certificate-errors') 
# Note: undetected_chromedriver automatically handles removing the "AutomationControlled" flags

driver = uc.Chrome(options=options, version_main=149)
wait = WebDriverWait(driver, 20)

def safe_text(css):
    try:
        return driver.find_element(By.CSS_SELECTOR, css).text.strip()
    except:
        return None

# ===========================================================
# Step 2: Gather Unique Store URLs from Zip Code Searches
# ===========================================================
all_store_links = set()

print("\n--- Starting Zip Code Search ---")
for zip_code in zip_codes:
    search_url = f"https://www.target.com/store-locator/find-stores/{zip_code}"
    print(f"Searching zip code: {zip_code}...")
    
    try:
        driver.get(search_url)
        time.sleep(4)  # Give React time to load the search results
        
        links_found_for_zip = 0
        for e in driver.find_elements(By.TAG_NAME, "a"):
            href = e.get_attribute("href")
            # Grab all individual store links from the search results
            if href and "/sl/" in href:
                all_store_links.add(href)
                links_found_for_zip += 1
                
        print(f"  -> Found {links_found_for_zip} stores (Total unique across all zips: {len(all_store_links)})")
        
    except Exception as ex:
        print(f"  -> Error loading search results for {zip_code}: {ex}")

# ===========================================================
# Step 3: Scrape Individual Store Pages
# ===========================================================
print(f"\n--- Beginning Extraction for {len(all_store_links)} Unique Stores ---")

for store_url in list(all_store_links):
    try:
        driver.get(store_url)
        time.sleep(3) 

        business_name = safe_text("h1")
        
        # --- 1. Extract Address & Phone ---
        address = None
        phone = None
        try:
            info_container = driver.find_element(By.XPATH, "//div[p[contains(text(), 'Phone:')]]")
            p_tags = info_container.find_elements(By.TAG_NAME, "p")
            
            if len(p_tags) >= 2:
                address = f"{p_tags[0].text.strip()}, {p_tags[1].text.strip()}"
            
            if len(p_tags) >= 3:
                phone_text = p_tags[2].text.strip()
                phone = phone_text.replace("Phone:", "").strip()
        except:
            pass

        # --- 2. Extract Operating Hours (Removing Month & Date) ---
        hours_str = None
        try:
            hours_list = []
            tabs = driver.find_elements(By.XPATH, "//div[@aria-label='Store Hours, vertical tabs']//button")
            
            for tab in tabs:
                day_elem = tab.find_element(By.XPATH, ".//span[contains(@class, 'dayTabHeading')]")
                time_elem = tab.find_element(By.XPATH, ".//span[contains(@class, 'secondaryText')]")
                
                day_full = day_elem.text.strip()
                day_clean = day_full.split(",")[0].strip() # Keep only the day name
                time_text = time_elem.text.strip()
                
                hours_list.append(f"{day_clean}: {time_text}")
            
            if hours_list:
                hours_str = " | ".join(hours_list)
        except:
            pass

        store_data = {
            "Business Name": business_name,
            "Address": address,
            "Phone": phone,
            "Operating Hours": hours_str,
            "Email": None,
            "Website": driver.current_url,
            "Latitude": None,
            "Longitude": None,
            "Business Category": "Retail"
        }

        # Append data to CSV instantly
        df = pd.DataFrame([store_data])
        file_exists = os.path.isfile(CSV_FILE)
        df.to_csv(CSV_FILE, mode='a', header=not file_exists, index=False, encoding='utf-8')

        print(f"Scraped: {business_name}")

    except Exception as ex:
        print(f"Error scraping {store_url}. Logging to {ERROR_CSV_FILE}")
        
        # Log errors to error.csv
        error_data = {
            "Failed URL": store_url,
            "Error Message": str(ex)
        }
        err_df = pd.DataFrame([error_data])
        err_file_exists = os.path.isfile(ERROR_CSV_FILE)
        err_df.to_csv(ERROR_CSV_FILE, mode='a', header=not err_file_exists, index=False, encoding='utf-8')
        
        continue

driver.quit()

# ===========================================================
# Step 4: Convert CSV to Excel at the End
# ===========================================================
if os.path.exists(CSV_FILE):
    print("\nConverting live-appended CSV to Excel format...")
    final_df = pd.read_csv(CSV_FILE)
    # Safety drop duplicates just in case
    final_df = final_df.drop_duplicates(subset=["Website"])
    final_df.to_excel(EXCEL_FILE, index=False)
    print(f"Scraping complete! Final Excel file saved as {EXCEL_FILE}")
else:
    print("No data was scraped.")
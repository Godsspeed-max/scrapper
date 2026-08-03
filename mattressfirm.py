import os
import json
import time
import pandas as pd
from openpyxl import Workbook, load_workbook
from curl_cffi import requests

import re
 
from html import unescape
from bs4 import BeautifulSoup

INPUT_FILE = "uszips.xlsx"
OUTPUT_FILE = "output_mattress.xlsx"

# ---------------------------
# Session
# ---------------------------

session = requests.Session(
    impersonate="chrome136"
)

session.headers.update({
    "accept": "application/json, text/plain, */*",
    "user-agent": "Mozilla/5.0",
    "referer": "https://www.mattressfirm.com/",
    "origin": "https://www.mattressfirm.com"
})

def format_hours(store):

    hours_json = store.get("hours_sets:primary", "")

    if not hours_json:
        return ""

    try:
        hours = json.loads(hours_json)
    except Exception:
        return hours_json

    days = hours.get("days", {})

    result = []

    ordered_days = [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday"
    ]

    for day in ordered_days:

        periods = days.get(day, [])

        if not periods:
            result.append(f"{day}: Closed")
            continue

        values = []

        for p in periods:

            # Case 1: already a string
            if isinstance(p, str):
                values.append(p)

            # Case 2: dictionary
            elif isinstance(p, dict):
                open_time = p.get("open") or p.get("start") or p.get("start_time", "")
                close_time = p.get("close") or p.get("end") or p.get("end_time", "")

                if open_time and close_time:
                    values.append(f"{open_time}-{close_time}")

        if values:
            result.append(f"{day}: {', '.join(values)}")
        else:
            result.append(f"{day}: Closed")

    return " | ".join(result)

# ---------------------------
# Create output
# ---------------------------

if not os.path.exists(OUTPUT_FILE):

    wb = Workbook()
    ws = wb.active

    ws.append([
        "SearchZip",
        "StoreID",
        "lid",
        "StoreName",
        "Address",
        "City",
        "State",
        "Country",
        "Zip",
        "Phone",
        "Latitude",
        "Longitude",
        "Website",
        "Hours",
        "RawJSON"
    ])

    wb.save(OUTPUT_FILE)

wb = load_workbook(OUTPUT_FILE)
ws = wb.active

# ---------------------------
# Existing IDs
# ---------------------------

existing = set()

for row in ws.iter_rows(min_row=2, values_only=True):

    if row[1]:
        existing.add(str(row[1]))

print("Existing Stores:", len(existing))

# ---------------------------
# Read ZIPs
# ---------------------------

df = pd.read_excel(INPUT_FILE, dtype={0: str})

zipcodes = (
    df.iloc[:, 0]
      .fillna("")
      .astype(str)
      .str.split(".").str[0]
      .str.strip()
      .str.zfill(5)
)

zipcodes = [
    z for z in zipcodes
    if len(z) == 5 and z.isdigit()
]

print("ZIP Codes:", len(zipcodes))

# ---------------------------
# Process
# ---------------------------

for zipcode in zipcodes:

    print("Searching:", zipcode)

    try:

        response = session.get(

            "https://maps.stores.mattressfirm.com.prod.rioseo.com/api/getAsyncLocations",

            params={
                "template": "search",
                "level": "search",
                "search": f"{zipcode}, US"
            },

            timeout=60

        )

        response.raise_for_status()

        data = response.json()

    except Exception as ex:

        print(ex)
        continue

    maplist = data.get("maplist", "")

    if not maplist:
        print("No maplist found.")
        continue

    # Decode HTML entities
    maplist = unescape(maplist).strip()

    # Remove wrapper DIV
    maplist = re.sub(r'^<div[^>]*>', '', maplist)
    maplist = re.sub(r'</div>\s*$', '', maplist)

    # Remove trailing comma before end
    maplist = re.sub(r',\s*$', '', maplist)

    # Remove comma before ] (if present)
    maplist = re.sub(r',\s*]', ']', maplist)

    # Build JSON array
    json_text = "[" + maplist + "]"

    try:
        stores = json.loads(json_text)
    except Exception as ex:

        print(ex)

        # with open("debug.json", "w", encoding="utf-8") as f:
        #     f.write(json_text)

        continue

    print("Stores Parsed:", len(stores))

    if not stores:
        continue


    for store in stores:

        fid = str(store.get("fid", "")).strip()

        if not fid:
            continue

        if fid in existing:
            #print("Duplicate:", fid)
            continue

        existing.add(fid)
 
        ws.append([

    zipcode,

    fid,

    store.get("lid"),

    store.get("location_name"),

    store.get("address_1") + " " + store.get("city") + " " +  store.get("region") + " " + store.get("post_code"),

    store.get("city"),

    store.get("region"),
    store.get("country"),

    store.get("post_code"),

    store.get("local_phone"),

    store.get("lat"),

    store.get("lng"),

    store.get("url"),

    format_hours(store),

    json.dumps(store, ensure_ascii=False)

])
     
    wb.save(OUTPUT_FILE)

    print("Saved")

    time.sleep(5)

wb.save(OUTPUT_FILE)

print("Completed")
import pandas as pd
import csv
import os
from google import genai
from google.genai import types

# ==========================================
# CONFIGURATION
# ==========================================
API_KEY = "YOUR_GEMINI_API_KEY" # Replace with your actual API key
INPUT_EXCEL = "store_urls.xlsx" # Ensure this file exists in your directory
OUTPUT_CSV = "extracted_store_data.csv"
URL_COLUMN_NAME = "URL" # The header name in your Excel file containing the links

# Initialize the AI Client
client = genai.Client(api_key=API_KEY)

def process_urls():
    # 1. Read URLs from Excel
    try:
        df = pd.read_excel(INPUT_EXCEL)
        urls = df[URL_COLUMN_NAME].dropna().tolist()
    except Exception as e:
        print(f"Error reading Excel file: {e}")
        return

    # 2. Prepare the output CSV
    file_exists = os.path.isfile(OUTPUT_CSV)
    with open(OUTPUT_CSV, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        
        # Write headers if it's a new file
        if not file_exists:
            writer.writerow(['Source_URL', 'Extracted_Data'])

        # 3. Loop through each URL and send directly to the AI
        for url in urls:
            print(f"\nProcessing: {url}")
            
            prompt = f"""
            You are a data extraction agent. I am providing you with a URL for a store.
            Please extract the store information (such as Store Name, Address, Phone Number, 
            and Operating Hours) from this URL. If any info is missing, just state "Not found".
            
            URL: {url}
            """
            
            try:
                # We enable Google Search grounding so the model can fetch info about the URL
                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        tools=[{"google_search": {}}]
                    )
                )
                
                extracted_info = response.text.strip()
                
                # 4. Save to CSV immediately
                writer.writerow([url, extracted_info])
                print(f"Success! Data appended to {OUTPUT_CSV}")
                
            except Exception as e:
                print(f"AI Extraction failed for {url}: {e}")
                writer.writerow([url, f"ERROR: AI extraction failed - {e}"])

if __name__ == "__main__":
    process_urls()
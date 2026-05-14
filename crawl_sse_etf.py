import requests
import csv
import json
import os

def crawl_sse_etfs():
    """
    Crawls list of ETFs from Shanghai Stock Exchange (SSE).
    API: https://yunhq.sse.com.cn:32042/v1/sh1/list/exchange/ebs
    """
    url = "https://yunhq.sse.com.cn:32042/v1/sh1/list/exchange/ebs"
    params = {
        "select": "code,name,open,high,low,last,prev_close,chg_rate,volume,amount,cpxxextendname,tradephase",
        # "callback": "jsonpCallback" # SSE uses JSONP often, but usually supports raw JSON if callback is omitted
    }
    headers = {
        "Referer": "https://www.sse.com.cn/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    print(f"Fetching ETF list from {url}...")
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        
        # SSE sometimes returns data with a callback prefix even if not requested, but usually not this one.
        # If it's pure JSON:
        data = response.json()
        etf_list = data.get("list", [])
        
        print(f"Successfully fetched {len(etf_list)} ETFs.")
        return etf_list
    except Exception as e:
        print(f"Error fetching data: {e}")
        return []

def save_to_csv(etf_list, output_file):
    """
    Saves the ETF list to a CSV file in the format: ts_code,name
    """
    print(f"Saving to {output_file}...")
    with open(output_file, mode='w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(["ts_code", "name"])
        for item in etf_list:
            # item[0] is code, item[10] is expanded short name (cpxxextendname)
            code = item[0]
            name = item[10]
            writer.writerow([code, name])
    print("Save complete.")

if __name__ == "__main__":
    # Define output path
    # Define output path relative to the script
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(base_dir, "etf_list.csv")
    
    # 1. Fetch data
    etfs = crawl_sse_etfs()
    
    # 2. Save data
    if etfs:
        save_to_csv(etfs, output_path)
        print(f"Total ETFs saved: {len(etfs)}")
    else:
        print("No ETFs found.")

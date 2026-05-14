import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
import os
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import time
import random

# National Team Keywords
NT_KEYWORDS = ["社保", "证金", "中央汇金", "全国社保", "基本养老", "中国证券金融", "社保基金", "汇金资管"]

def fetch_etf_holders(symbol):
    """
    Fetches Top 10 Holders for a given ETF symbol from Sina Finance.
    """
    url = f"https://stock.finance.sina.com.cn/fundInfo/view/FundInfo_JJCYR.php?symbol={symbol}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        # Small random sleep to be polite
        time.sleep(random.uniform(0.1, 0.3))
        response = requests.get(url, headers=headers, timeout=15)
        response.encoding = 'gbk'
        html = response.text
        
        soup = BeautifulSoup(html, 'html.parser')
        target_table = None
        tables = soup.find_all('table', class_='tc')
        if not tables:
            tables = soup.find_all('table')

        for table in tables:
            if '持有人名称' in table.text:
                target_table = table
                break
        
        if target_table is None:
            return []
        
        rows = target_table.find_all('tr')
        data_list = []
        header_found = False
        for row in rows:
            tds = row.find_all('td')
            if not tds: continue
            texts = [td.get_text(strip=True) for td in tds]
            if '持有人名称' in texts:
                header_found = True
                continue
            if header_found and len(texts) >= 4:
                data_list.append({
                    'holder_name': texts[1],
                    'hold_amount': texts[2],
                    'hold_ratio': texts[3]
                })

        # Deduplicate
        seen = set()
        unique_data = []
        for d in data_list:
            t = (d['holder_name'], d['hold_amount'])
            if t not in seen:
                unique_data.append(d)
                seen.add(t)
        
        return unique_data

    except Exception as e:
        # print(f"Error fetching {symbol}: {e}")
        return []

def scan_etf(row):
    ts_code = str(row['ts_code']).zfill(6)
    name = row['name']
    
    holders = fetch_etf_holders(ts_code)
    nt_holdings = []
    
    for h in holders:
        holder_name = h['holder_name']
        if any(kw in holder_name for kw in NT_KEYWORDS):
            nt_holdings.append({
                'ts_code': ts_code,
                'name': name,
                'holder_name': holder_name,
                'hold_amount': h['hold_amount'],
                'hold_ratio': h['hold_ratio']
            })
            
    return nt_holdings

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    input_file = os.path.join(base_dir, "etf_list.csv")
    output_file = os.path.join(base_dir, "national_team_etfs.csv")
    
    if not os.path.exists(input_file):
        print(f"Input file {input_file} not found.")
        return

    df_etf = pd.read_csv(input_file, dtype={'ts_code': str})
    print(f"Scanning {len(df_etf)} ETFs for National Team holdings...")
    
    all_nt_results = []
    
    # Use ThreadPoolExecutor for concurrency
    max_workers = 15  # Adjust based on server tolerance
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(scan_etf, row) for _, row in df_etf.iterrows()]
        
        for future in tqdm(as_completed(futures), total=len(futures)):
            try:
                results = future.result()
                if results:
                    all_nt_results.extend(results)
            except Exception as e:
                print(f"Future error: {e}")

    if all_nt_results:
        df_out = pd.DataFrame(all_nt_results)
        # Reorder columns
        df_out = df_out[['ts_code', 'name', 'holder_name', 'hold_amount', 'hold_ratio']]
        df_out.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"\nScan complete. Found {len(df_out)} National Team positions across various ETFs.")
        print(f"Results saved to {output_file}")
    else:
        print("\nNo National Team holdings found in the sampled ETFs.")

if __name__ == "__main__":
    main()

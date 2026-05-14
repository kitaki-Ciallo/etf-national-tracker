import requests
from bs4 import BeautifulSoup
import pandas as pd
import re

def fetch_etf_top10_holders(symbol):
    """
    Scrapes the Top 10 Holders of an ETF from Sina Finance.
    URL: https://stock.finance.sina.com.cn/fundInfo/view/FundInfo_JJCYR.php?symbol={symbol}
    """
    url = f"https://stock.finance.sina.com.cn/fundInfo/view/FundInfo_JJCYR.php?symbol={symbol}"
    print(f"Fetching data from {url}...")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        # Sina Finance often uses GBK encoding
        # Try to detect or use GBK
        response.encoding = 'gbk'
        html = response.text
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # Find the table containing "持有人名称"
        target_table = None
        # Sina Finance uses class 'tc' for this table
        tables = soup.find_all('table', class_='tc')
        
        if not tables:
            # Fallback to searching all tables
            tables = soup.find_all('table')

        for table in tables:
            if '持有人名称' in table.text:
                target_table = table
                break
        
        if target_table is None:
            print("Error: Could not find 'Top 10 Holders' table on the page.")
            return None
        
        # Manual parsing instead of pandas for more robustness with malformed HTML
        rows = target_table.find_all('tr')
        data_list = []
        
        # Skip the forms and header rows
        # The header row has id="tb-title" or contains "持有人名称"
        header_found = False
        for row in rows:
            tds = row.find_all('td')
            if not tds:
                continue
            
            texts = [td.get_text(strip=True) for td in tds]
            
            if '持有人名称' in texts:
                header_found = True
                continue
            
            if header_found and len(texts) >= 4:
                # 序号, 持有人名称, 持有份额(份), 占总份额比(%)
                data_list.append({
                    '序号': texts[0],
                    '持有人名称': texts[1],
                    '持有份额(份)': texts[2],
                    '占总份额比(%)': texts[3]
                })

        if not data_list:
            print("Error: Could not extract any data rows from the table.")
            return None
            
        df = pd.DataFrame(data_list)
        
        # Deduplicate rows (Sina's malformed HTML can cause BeautifulSoup to see duplicate rows)
        df = df.drop_duplicates().reset_index(drop=True)
        
        # Clean the data
        def clean_val(x):
            if isinstance(x, str):
                return re.sub(r'[^\d.]', '', x)
            return x

        df['持有份额(份)'] = df['持有份额(份)'].apply(clean_val).astype(float)
        df['占总份额比(%)'] = df['占总份额比(%)'].apply(clean_val).astype(float)
            
        return df

    except Exception as e:
        print(f"Error occurred: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    symbol = "510300"
    data = fetch_etf_top10_holders(symbol)
    
    if data is not None:
        print("\n--- Top 10 Holders for 510300 ---")
        # Filter columns to only show Name, Shares, and Percentage
        cols_to_show = ['持有人名称', '持有份额(份)', '占总份额比(%)']
        # Check if they exist to avoid KeyErrors
        existing_cols = [c for c in cols_to_show if c in data.columns]
        
        print(data[existing_cols].to_string(index=False))
        
        # Identify "National Team" holders if any (similar to user's SSF_KEYWORDS)
        SSF_KEYWORDS = ["社保", "养老", "证金", "中央汇金", "全国社保", "基本养老", "中国证券金融", "社保基金", "汇金资管"]
        
        print("\n--- 'National Team' Holders Detection ---")
        nt_holders = data[data['持有人名称'].apply(lambda x: any(k in str(x) for k in SSF_KEYWORDS))]
        if not nt_holders.empty:
            print(nt_holders[existing_cols].to_string(index=False))
        else:
            print("No 'National Team' holders detected in Top 10.")
    else:
        print("Failed to retrieve data.")

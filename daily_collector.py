"""
ETF 国家队量化看板 — 每日数据采集脚本
每个交易日收盘后运行 (建议 19:00 之后)。

用法:
    python daily_collector.py
    python daily_collector.py --date 20260514
"""
import os, sys, time, re, json, argparse
from datetime import datetime, timedelta
import akshare as ak
import pandas as pd
import requests
import psycopg2
from psycopg2.extras import execute_values

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DB_CONFIG, INDEX_ETFS, REQUEST_DELAY

def get_db_conn():
    return psycopg2.connect(**DB_CONFIG)

def get_nt_codes(conn):
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT ts_code FROM nt_etf_list")
    return {row[0] for row in cur.fetchall()}

def fetch_sina_kline(symbol, datalen=10):
    """从新浪获取最近 N 条日K线"""
    url = (
        f"https://quotes.sina.cn/cn/api/jsonp_v2.php/"
        f"var%20_data=/CN_MarketDataService.getKLineData"
        f"?symbol=sh{symbol}&scale=240&ma=no&datalen={datalen}"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://finance.sina.com.cn/",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        match = re.search(r'var\s+_data\s*=\s*\((\[.*?\])\)', resp.text, re.DOTALL)
        if not match: return []
        return json.loads(match.group(1))
    except:
        return []

def collect_daily_shares(conn, date_str, target_codes):
    cur = conn.cursor()
    print(f"[份额] 采集 {date_str} ...")
    try:
        df = ak.fund_etf_scale_sse(date=date_str)
        if df is None or df.empty:
            print(f"[份额] {date_str} 无数据"); return 0
        code_col = share_col = None
        for col in df.columns:
            if "代码" in col: code_col = col
            elif "份额" in col: share_col = col
        if not code_col or not share_col:
            if len(df.columns) >= 6:
                code_col, share_col = df.columns[1], df.columns[5]
            else: return 0
        trade_date = datetime.strptime(date_str, "%Y%m%d").date()
        rows = []
        for _, row in df.iterrows():
            code = str(row[code_col]).strip()
            if code in target_codes:
                try:
                    share = float(row[share_col])
                    if share > 0: rows.append((code, trade_date, share))
                except: continue
        if rows:
            execute_values(cur, """
                INSERT INTO etf_daily_share (ts_code, trade_date, total_share) VALUES %s
                ON CONFLICT (ts_code, trade_date) DO UPDATE SET total_share = EXCLUDED.total_share
            """, rows)
            conn.commit()
            print(f"[份额] 写入 {len(rows)} 条"); return len(rows)
    except Exception as e:
        print(f"[份额] 失败: {e}")
    return 0

def collect_daily_prices(conn, target_codes):
    """使用新浪 K线 API 采集最近价格"""
    cur = conn.cursor()
    print(f"[价格] 从新浪采集 {len(target_codes)} 只 ETF ...")
    count = 0
    for code in target_codes:
        try:
            klines = fetch_sina_kline(code, datalen=10)
            if not klines: continue
            rows = []
            for k in klines:
                try:
                    td = datetime.strptime(k["day"], "%Y-%m-%d").date()
                    rows.append((code, td, float(k["open"]), float(k["high"]),
                                 float(k["low"]), float(k["close"]),
                                 int(k["volume"]), 0))
                except: continue
            if rows:
                execute_values(cur, """
                    INSERT INTO etf_daily_price (ts_code, trade_date, open, high, low, close, volume, amount) VALUES %s
                    ON CONFLICT (ts_code, trade_date) DO UPDATE SET
                        open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                        close=EXCLUDED.close, volume=EXCLUDED.volume, amount=EXCLUDED.amount
                """, rows)
                count += 1
            time.sleep(REQUEST_DELAY)
        except: time.sleep(1)
    conn.commit()
    print(f"[价格] 写入 {count} 只 ETF"); return count

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, default=None)
    args = parser.parse_args()
    date_str = args.date or datetime.now().strftime("%Y%m%d")
    print(f"ETF 每日采集 — {date_str}")
    conn = get_db_conn()
    try:
        nt_codes = get_nt_codes(conn)
        if not nt_codes:
            print("[错误] 无国家队 ETF, 请先运行 init_data.py"); return
        target = nt_codes | set(INDEX_ETFS.keys())
        collect_daily_shares(conn, date_str, target)
        collect_daily_prices(conn, target)
    finally:
        conn.close()

if __name__ == "__main__":
    main()

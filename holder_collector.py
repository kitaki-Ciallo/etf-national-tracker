"""
ETF 国家队量化看板 — 十大持有人采集脚本
半年报/年报披露后运行。

用法:
    python holder_collector.py
"""
import os, sys, re, time, json
from datetime import datetime
import requests
import psycopg2
from bs4 import BeautifulSoup
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DB_CONFIG, NT_KEYWORDS, REQUEST_DELAY

def get_db_conn():
    return psycopg2.connect(**DB_CONFIG)

def fetch_sina_report_dates(symbol):
    """获取新浪财经页面上可用的报告期列表"""
    url = f"https://stock.finance.sina.com.cn/fundInfo/view/FundInfo_JJCYR.php?symbol={symbol}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.encoding = "gbk"
        soup = BeautifulSoup(resp.text, "html.parser")
        select = soup.find("select", id="tc_slt")
        if not select: return []
        return [opt.get("value") for opt in select.find_all("option") if opt.get("value")]
    except:
        return []

def fetch_sina_holders_by_date(symbol, report_date):
    """通过新浪 JSON API 获取指定报告期的十大持有人"""
    url = "https://stock.finance.sina.com.cn/fundInfo/api/openapi.php/CaihuiFundInfoService.getFundHolder"
    params = {"symbol": symbol, "date": report_date}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": f"https://stock.finance.sina.com.cn/fundInfo/view/FundInfo_JJCYR.php?symbol={symbol}",
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        data = resp.json()
        holders_raw = data.get("result", {}).get("data", [])
        result = []
        for i, h in enumerate(holders_raw, 1):
            name = h.get("cyrmc", "")
            amount = float(h.get("cyfe", 0))
            ratio = float(h.get("zfeb", 0))
            is_nt = any(kw in name for kw in NT_KEYWORDS)
            result.append({"rank": i, "holder_name": name, "hold_amount": amount,
                           "hold_ratio": ratio, "is_nt": is_nt})
        return result
    except:
        return []

def get_all_nt_codes(conn):
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT ts_code FROM nt_etf_list")
    return [row[0] for row in cur.fetchall()]

def collect_holders(conn, codes):
    cur = conn.cursor()
    print(f"[持有人] 采集 {len(codes)} 只 ETF 的最新两期持有人数据")

    for code in tqdm(codes, desc="采集持有人"):
        try:
            report_dates = fetch_sina_report_dates(code)
            if not report_dates:
                continue
            latest_date = report_dates[0]
            prev_date = report_dates[1] if len(report_dates) > 1 else None

            # 采集最新期
            holders_latest = fetch_sina_holders_by_date(code, latest_date)
            for h in holders_latest:
                cur.execute("""
                    INSERT INTO etf_holder (ts_code, report_date, rank, holder_name, hold_amount, hold_ratio, is_nt)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (ts_code, report_date, holder_name) DO UPDATE SET
                        rank=EXCLUDED.rank, hold_amount=EXCLUDED.hold_amount,
                        hold_ratio=EXCLUDED.hold_ratio, is_nt=EXCLUDED.is_nt
                """, (code, latest_date, h["rank"], h["holder_name"], h["hold_amount"], h["hold_ratio"], h["is_nt"]))
            time.sleep(REQUEST_DELAY)

            # 采集上一期
            holders_prev = []
            if prev_date:
                holders_prev = fetch_sina_holders_by_date(code, prev_date)
                for h in holders_prev:
                    cur.execute("""
                        INSERT INTO etf_holder (ts_code, report_date, rank, holder_name, hold_amount, hold_ratio, is_nt)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (ts_code, report_date, holder_name) DO UPDATE SET
                            rank=EXCLUDED.rank, hold_amount=EXCLUDED.hold_amount,
                            hold_ratio=EXCLUDED.hold_ratio, is_nt=EXCLUDED.is_nt
                    """, (code, prev_date, h["rank"], h["holder_name"], h["hold_amount"], h["hold_ratio"], h["is_nt"]))
                time.sleep(REQUEST_DELAY)

            # 更新 nt_etf_list 汇总
            nt_latest = [h for h in holders_latest if h["is_nt"]]
            for h in nt_latest:
                prev_ratio = None
                is_new = True
                if prev_date:
                    cur.execute("SELECT hold_ratio FROM etf_holder WHERE ts_code=%s AND report_date=%s AND holder_name=%s",
                                (code, prev_date, h["holder_name"]))
                    pr = cur.fetchone()
                    if pr: prev_ratio = float(pr[0]); is_new = False
                cur.execute("SELECT name FROM etf_info WHERE ts_code=%s", (code,))
                nr = cur.fetchone()
                etf_name = nr[0] if nr else ""
                cur.execute("""
                    INSERT INTO nt_etf_list (ts_code, name, holder_name, latest_hold_amount,
                        latest_hold_ratio, prev_hold_ratio, latest_report_date, prev_report_date, is_new_entry)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (ts_code, holder_name) DO UPDATE SET
                        latest_hold_amount=EXCLUDED.latest_hold_amount,
                        latest_hold_ratio=EXCLUDED.latest_hold_ratio,
                        prev_hold_ratio=EXCLUDED.prev_hold_ratio,
                        latest_report_date=EXCLUDED.latest_report_date,
                        prev_report_date=EXCLUDED.prev_report_date,
                        is_new_entry=EXCLUDED.is_new_entry, updated_at=NOW()
                """, (code, etf_name, h["holder_name"], h["hold_amount"], h["hold_ratio"],
                      prev_ratio, latest_date, prev_date, is_new))

            conn.commit()
        except Exception as e:
            print(f"  {code} 失败: {e}")

    print(f"[持有人] 完成")

def main():
    print(f"ETF 十大持有人采集")
    conn = get_db_conn()
    try:
        codes = get_all_nt_codes(conn)
        if not codes:
            print("[错误] 无国家队 ETF, 请先运行 init_data.py"); return
        collect_holders(conn, codes)
    finally:
        conn.close()

if __name__ == "__main__":
    main()

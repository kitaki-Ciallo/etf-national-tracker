"""
ETF 国家队量化看板 — 历史数据初始化脚本
首次部署时运行, 回溯约 1 年的历史份额和价格数据。

用法:
    python init_data.py
"""
import os, sys, time, re, json, subprocess
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from datetime import datetime, timedelta

import pandas as pd
import requests
import psycopg2
from psycopg2.extras import execute_values
from bs4 import BeautifulSoup
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DB_CONFIG, NT_KEYWORDS, INDEX_ETFS, LOOKBACK_DAYS, REQUEST_DELAY


def get_db_conn():
    return psycopg2.connect(**DB_CONFIG)


# ─── 新浪 K线 API ───
def get_exchange_prefix(code):
    """根据 ETF 代码判断交易所前缀: 深交所 159xxx → sz, 上交所 51xxxx → sh"""
    if code.startswith("159") or code.startswith("16"):
        return "sz"
    return "sh"

def fetch_sina_kline(symbol, datalen=1023):
    """
    从新浪财经获取 ETF 日线数据。
    API: CN_MarketDataService.getKLineData
    返回: list of dict [{day, open, high, low, close, volume}, ...]
    """
    prefix = get_exchange_prefix(symbol)
    url = (
        f"https://quotes.sina.cn/cn/api/jsonp_v2.php/"
        f"var%20_data=/CN_MarketDataService.getKLineData"
        f"?symbol={prefix}{symbol}&scale=240&ma=no&datalen={datalen}"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://finance.sina.com.cn/",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        text = resp.text
        # 解析 JSONP: /*...*/var _data=([{...},...]);
        match = re.search(r'var\s+_data\s*=\s*\((\[.*?\])\)', text, re.DOTALL)
        if not match:
            return []
        data = json.loads(match.group(1))
        return data
    except Exception as e:
        return []


# ─── 新浪持有人 API (支持指定报告期) ───
def fetch_sina_holders_by_date(symbol, report_date):
    """
    从新浪财经 JSON API 获取指定报告期的十大持有人。
    API: CaihuiFundInfoService.getFundHolder
    """
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
            result.append({
                "rank": i,
                "holder_name": name,
                "hold_amount": amount,
                "hold_ratio": ratio,
                "is_nt": is_nt,
            })
        return result
    except Exception as e:
        return []


def fetch_sina_report_dates(symbol):
    """
    从新浪财经页面获取可用的报告期列表。
    解析 <select id="tc_slt"> 中的 <option> 值。
    """
    url = f"https://stock.finance.sina.com.cn/fundInfo/view/FundInfo_JJCYR.php?symbol={symbol}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.encoding = "gbk"
        soup = BeautifulSoup(resp.text, "html.parser")
        select = soup.find("select", id="tc_slt")
        if not select:
            return []
        options = select.find_all("option")
        return [opt.get("value") for opt in options if opt.get("value")]
    except:
        return []


# ─── Step 1: ETF 信息导入 ───
def init_etf_info(conn):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    etf_list_file = os.path.join(base_dir, "etf_list.csv")
    nt_file = os.path.join(base_dir, "national_team_etfs.csv")
    cur = conn.cursor()

    if os.path.exists(etf_list_file):
        df = pd.read_csv(etf_list_file, dtype={"ts_code": str})
        print(f"[ETF 信息] 导入 {len(df)} 只 ETF...")
        for _, row in df.iterrows():
            cur.execute("""
                INSERT INTO etf_info (ts_code, name) VALUES (%s, %s)
                ON CONFLICT (ts_code) DO UPDATE SET name = EXCLUDED.name, updated_at = NOW()
            """, (str(row["ts_code"]).zfill(6), row["name"]))

    nt_codes = set()
    if os.path.exists(nt_file):
        df_nt = pd.read_csv(nt_file, dtype={"ts_code": str})
        for _, row in df_nt.iterrows():
            code = str(row["ts_code"]).zfill(6)
            nt_codes.add(code)
            hold_amount_str = str(row.get("hold_amount", "0"))
            hold_amount = float(re.sub(r"[^\d.]", "", hold_amount_str)) if hold_amount_str else 0
            hold_ratio = float(row.get("hold_ratio", 0))
            cur.execute("""
                INSERT INTO nt_etf_list (ts_code, name, holder_name, latest_hold_amount, latest_hold_ratio)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (ts_code, holder_name) DO UPDATE SET
                    name = EXCLUDED.name, latest_hold_amount = EXCLUDED.latest_hold_amount,
                    latest_hold_ratio = EXCLUDED.latest_hold_ratio, updated_at = NOW()
            """, (code, row["name"], row["holder_name"], hold_amount, hold_ratio))
        if nt_codes:
            cur.execute("UPDATE etf_info SET is_nt_held = TRUE, updated_at = NOW() WHERE ts_code = ANY(%s)", (list(nt_codes),))
        print(f"[国家队] 导入 {len(df_nt)} 条记录, 涉及 {len(nt_codes)} 只 ETF")

    conn.commit()
    return nt_codes


# ─── 上交所 ETF 份额 API (直接调用, 不依赖 AKShare) ───
def fetch_sse_shares(date_str):
    """
    直接从上交所 API 获取 ETF 份额数据 (使用 curl 确保兼容性)。
    date_str: 格式 '20260513'
    返回: list of dict [{SEC_CODE, TOT_VOL, ...}, ...]
    """
    data_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    url = (
        f"https://query.sse.com.cn/commonQuery.do?"
        f"isPagination=true&pageHelp.pageSize=10000&pageHelp.pageNo=1"
        f"&pageHelp.beginPage=1&pageHelp.cacheSize=1&pageHelp.endPage=1"
        f"&sqlId=COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L"
        f"&STAT_DATE={data_str}"
    )
    headers = {
        "Referer": "https://www.sse.com.cn/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    # 先尝试 requests (verify=False: 云服务器 SSL 握手上交所证书会超时)
    try:
        resp = requests.get(url, headers=headers, timeout=60, verify=False)
        data = resp.json()
        return data.get("result", [])
    except Exception as e:
        print(f"  [份额API] requests 失败: {type(e).__name__}: {e}")
    # requests 失败时用 curl (云服务器更稳定)
    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", "60",
             "-H", "Referer: https://www.sse.com.cn/",
             "-H", f"User-Agent: {headers['User-Agent']}",
             url],
            capture_output=True, timeout=65
        )
        if result.returncode != 0:
            return []
        data = json.loads(result.stdout.decode("utf-8", errors="replace"))
        return data.get("result", [])
    except Exception as e:
        print(f"  [份额API] 错误: {e}")
        return []


# ─── Step 2: 每日份额 ───
def init_daily_shares(conn, nt_codes):
    dates = []
    today = datetime.now()
    for i in range(LOOKBACK_DAYS):
        d = today - timedelta(days=i)
        if d.weekday() < 5:
            dates.append(d.strftime("%Y%m%d"))
    dates = sorted(dates)

    cur = conn.cursor()
    target_codes = nt_codes | set(INDEX_ETFS.keys())
    print(f"\n[每日份额] 开始回溯 {len(dates)} 个交易日...")
    success = 0

    for date_str in tqdm(dates, desc="回溯份额"):
        try:
            etf_rows = fetch_sse_shares(date_str)
            if not etf_rows:
                continue
            trade_date = datetime.strptime(date_str, "%Y%m%d").date()
            rows = []
            for item in etf_rows:
                code = str(item.get("SEC_CODE", "")).strip()
                if code in target_codes:
                    try:
                        # TOT_VOL 单位: 万份, 转换为份
                        share = float(item.get("TOT_VOL", 0)) * 10000
                        if share > 0: rows.append((code, trade_date, share))
                    except: continue
            if rows:
                execute_values(cur, """
                    INSERT INTO etf_daily_share (ts_code, trade_date, total_share) VALUES %s
                    ON CONFLICT (ts_code, trade_date) DO UPDATE SET total_share = EXCLUDED.total_share
                """, rows)
                conn.commit()
            success += 1
            time.sleep(REQUEST_DELAY)
        except Exception as e:
            if "频率" in str(e) or "rate" in str(e).lower():
                time.sleep(5)
            continue
    print(f"[每日份额] 完成: 成功 {success} 天")


# ─── Step 3: 历史价格 (新浪 K线) ───
def init_daily_prices(conn, nt_codes):
    target_codes = list(nt_codes | set(INDEX_ETFS.keys()))
    cur = conn.cursor()

    print(f"\n[历史价格] 从新浪获取 {len(target_codes)} 只 ETF 的历史价格...")
    for code in tqdm(target_codes, desc="获取价格"):
        try:
            klines = fetch_sina_kline(code, datalen=1023)
            if not klines:
                print(f"  [价格] {code} 无数据")
                continue
            rows = []
            for k in klines:
                try:
                    trade_date = datetime.strptime(k["day"], "%Y-%m-%d").date()
                    rows.append((
                        code, trade_date,
                        float(k["open"]), float(k["high"]),
                        float(k["low"]), float(k["close"]),
                        int(k["volume"]), 0,
                    ))
                except: continue
            if rows:
                execute_values(cur, """
                    INSERT INTO etf_daily_price (ts_code, trade_date, open, high, low, close, volume, amount) VALUES %s
                    ON CONFLICT (ts_code, trade_date) DO UPDATE SET
                        open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                        close=EXCLUDED.close, volume=EXCLUDED.volume, amount=EXCLUDED.amount
                """, rows)
                conn.commit()
            time.sleep(REQUEST_DELAY)
        except Exception as e:
            print(f"  [价格] {code} 失败: {e}")
            time.sleep(1)
    print(f"[历史价格] 完成")


# ─── Step 4: 十大持有人 (最新两期) ───
def init_holders(conn, nt_codes):
    target_codes = list(nt_codes)
    cur = conn.cursor()

    print(f"\n[十大持有人] 获取 {len(target_codes)} 只国家队 ETF 的持有人数据 (最新两期)...")
    for code in tqdm(target_codes, desc="获取持有人"):
        try:
            # 1. 获取可用报告期列表
            report_dates = fetch_sina_report_dates(code)
            if not report_dates:
                print(f"  [持有人] {code} 无报告期")
                continue

            # 取最新两期
            latest_date = report_dates[0] if report_dates else None
            prev_date = report_dates[1] if len(report_dates) > 1 else None

            # 2. 获取最新期持有人
            if latest_date:
                holders = fetch_sina_holders_by_date(code, latest_date)
                for h in holders:
                    cur.execute("""
                        INSERT INTO etf_holder (ts_code, report_date, rank, holder_name, hold_amount, hold_ratio, is_nt)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (ts_code, report_date, holder_name) DO UPDATE SET
                            rank=EXCLUDED.rank, hold_amount=EXCLUDED.hold_amount,
                            hold_ratio=EXCLUDED.hold_ratio, is_nt=EXCLUDED.is_nt
                    """, (code, latest_date, h["rank"], h["holder_name"], h["hold_amount"], h["hold_ratio"], h["is_nt"]))
                time.sleep(REQUEST_DELAY)

            # 3. 获取上一期持有人
            if prev_date:
                holders_prev = fetch_sina_holders_by_date(code, prev_date)
                for h in holders_prev:
                    cur.execute("""
                        INSERT INTO etf_holder (ts_code, report_date, rank, holder_name, hold_amount, hold_ratio, is_nt)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (ts_code, report_date, holder_name) DO UPDATE SET
                            rank=EXCLUDED.rank, hold_amount=EXCLUDED.hold_amount,
                            hold_ratio=EXCLUDED.hold_ratio, is_nt=EXCLUDED.is_nt
                    """, (code, prev_date, h["rank"], h["holder_name"], h["hold_amount"], h["hold_ratio"], h["is_nt"]))
                time.sleep(REQUEST_DELAY)

            # 4. 更新 nt_etf_list 汇总
            if latest_date:
                nt_latest = [h for h in (holders if latest_date else []) if h["is_nt"]]
                for h in nt_latest:
                    prev_ratio = None
                    is_new = True
                    if prev_date:
                        cur.execute("""
                            SELECT hold_ratio FROM etf_holder
                            WHERE ts_code=%s AND report_date=%s AND holder_name=%s
                        """, (code, prev_date, h["holder_name"]))
                        pr = cur.fetchone()
                        if pr:
                            prev_ratio = float(pr[0])
                            is_new = False
                    cur.execute("SELECT name FROM etf_info WHERE ts_code=%s", (code,))
                    name_row = cur.fetchone()
                    etf_name = name_row[0] if name_row else ""
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
            print(f"  [持有人] {code} 失败: {e}")
    print(f"[十大持有人] 完成")


def main():
    print("=" * 60)
    print("ETF 国家队量化看板 — 历史数据初始化")
    print("=" * 60)
    conn = get_db_conn()
    try:
        print("\n>>> Step 1/4: 导入 ETF 基本信息...")
        nt_codes = init_etf_info(conn)
        if not nt_codes:
            print("[错误] 未找到国家队 ETF 数据, 请先运行 crawl_sse_etf.py 和 find_nt_etfs.py")
            return
        print("\n>>> Step 2/4: 回溯历史每日份额...")
        init_daily_shares(conn, nt_codes)
        print("\n>>> Step 3/4: 回溯历史价格 (新浪K线)...")
        init_daily_prices(conn, nt_codes)
        print("\n>>> Step 4/4: 获取十大持有人 (最新两期)...")
        init_holders(conn, nt_codes)
        print("\n" + "=" * 60)
        print("初始化完成!")
        print("=" * 60)
    except Exception as e:
        print(f"\n[严重错误] {e}")
        import traceback; traceback.print_exc()
    finally:
        conn.close()

if __name__ == "__main__":
    main()

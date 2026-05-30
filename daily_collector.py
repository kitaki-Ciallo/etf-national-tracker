"""
ETF 国家队量化看板 — 每日数据采集脚本
每个交易日收盘后运行 (建议 19:00 之后)。

用法:
    python daily_collector.py
    python daily_collector.py --date 20260514
"""
import os, sys, time, re, json, argparse, subprocess
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from datetime import datetime, timedelta, date
import pandas as pd
import requests
import psycopg2
from psycopg2.extras import execute_values

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DB_CONFIG, INDEX_ETFS, REQUEST_DELAY

MAX_RETRIES = 3       # 最大重试次数
RETRY_DELAY = 30      # 重试间隔 (秒)

def get_db_conn():
    return psycopg2.connect(**DB_CONFIG)

def get_nt_codes(conn):
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT ts_code FROM nt_etf_list")
    return {row[0] for row in cur.fetchall()}

# ─── 查询数据库中最新日期 ───────────────────────────────────────

def get_latest_share_date(conn):
    """获取 etf_daily_share 表中最新的 trade_date"""
    cur = conn.cursor()
    cur.execute("SELECT MAX(trade_date) FROM etf_daily_share")
    row = cur.fetchone()
    return row[0] if row and row[0] else None

def get_latest_price_date(conn):
    """获取 etf_daily_price 表中最新的 trade_date"""
    cur = conn.cursor()
    cur.execute("SELECT MAX(trade_date) FROM etf_daily_price")
    row = cur.fetchone()
    return row[0] if row and row[0] else None

def generate_date_range(start_date, end_date):
    """生成 start_date (不含) 到 end_date (含) 之间的所有日期字符串列表 (YYYYMMDD)"""
    dates = []
    current = start_date + timedelta(days=1)
    while current <= end_date:
        dates.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return dates

# ─── 数据抓取 ──────────────────────────────────────────────────

def get_exchange_prefix(code):
    """根据 ETF 代码判断交易所前缀: 深交所 159xxx → sz, 上交所 51xxxx → sh"""
    if code.startswith("159") or code.startswith("16"):
        return "sz"
    return "sh"

def fetch_sina_kline(symbol, datalen=10):
    """从新浪获取最近 N 条日K线"""
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
        match = re.search(r'var\s+_data\s*=\s*\((\[.*?\])\)', resp.text, re.DOTALL)
        if not match: return []
        return json.loads(match.group(1))
    except:
        return []

def fetch_sse_shares(date_str):
    """直接从上交所 API 获取 ETF 份额数据"""
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
    try:
        resp = requests.get(url, headers=headers, timeout=60, verify=False)
        return resp.json().get("result", [])
    except Exception as e:
        print(f"  [份额API] requests 失败: {type(e).__name__}: {e}")
    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", "60",
             "-H", "Referer: https://www.sse.com.cn/",
             "-H", f"User-Agent: {headers['User-Agent']}",
             url],
            capture_output=True, timeout=65
        )
        if result.returncode != 0: return []
        return json.loads(result.stdout.decode("utf-8", errors="replace")).get("result", [])
    except Exception as e:
        print(f"  [份额API] 错误: {e}")
        return []

# ─── 带重试的采集函数 ──────────────────────────────────────────

def retry_wrapper(func, description, *args, **kwargs):
    """通用重试包装器：失败后等待 30 秒重试，最多 3 次"""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = func(*args, **kwargs)
            return result
        except Exception as e:
            print(f"  [{description}] 第 {attempt}/{MAX_RETRIES} 次尝试失败: {e}")
            if attempt < MAX_RETRIES:
                print(f"  [{description}] {RETRY_DELAY} 秒后重试 ...")
                time.sleep(RETRY_DELAY)
            else:
                print(f"  [{description}] 已达最大重试次数 ({MAX_RETRIES})，跳过")
                raise

def collect_daily_shares(conn, target_date, target_codes):
    """
    采集份额数据。先查库中最新日期，只补采缺失天数的数据。
    target_date: date 对象，目标截止日期
    """
    cur = conn.cursor()
    latest = get_latest_share_date(conn)
    if latest and latest >= target_date:
        print(f"[份额] 库中最新日期 {latest}，已覆盖目标 {target_date}，跳过")
        return 0

    if latest:
        dates_to_fetch = generate_date_range(latest, target_date)
        print(f"[份额] 库中最新: {latest}, 需补采 {len(dates_to_fetch)} 天 → {target_date}")
    else:
        dates_to_fetch = [target_date.strftime("%Y%m%d")]
        print(f"[份额] 库中无数据, 采集 {target_date}")

    total_rows = 0
    for date_str in dates_to_fetch:
        print(f"  [份额] 采集 {date_str} ...")

        def _fetch_and_insert(ds=date_str):
            etf_rows = fetch_sse_shares(ds)
            if not etf_rows:
                print(f"  [份额] {ds} 无数据 (可能非交易日)")
                return 0
            trade_date = datetime.strptime(ds, "%Y%m%d").date()
            rows = []
            for item in etf_rows:
                code = str(item.get("SEC_CODE", "")).strip()
                if code in target_codes:
                    try:
                        share = float(item.get("TOT_VOL", 0)) * 10000
                        if share > 0: rows.append((code, trade_date, share))
                    except: continue
            if rows:
                execute_values(cur, """
                    INSERT INTO etf_daily_share (ts_code, trade_date, total_share) VALUES %s
                    ON CONFLICT (ts_code, trade_date) DO UPDATE SET total_share = EXCLUDED.total_share
                """, rows)
                conn.commit()
                print(f"  [份额] {ds} 写入 {len(rows)} 条")
                return len(rows)
            return 0

        try:
            total_rows += retry_wrapper(_fetch_and_insert, f"份额 {date_str}")
        except Exception:
            pass  # 重试耗尽后跳过该日继续

    print(f"[份额] 共写入 {total_rows} 条")
    return total_rows

def collect_daily_prices(conn, target_date, target_codes):
    """
    采集价格数据。先查库中最新日期，动态计算需要回溯的天数。
    target_date: date 对象，目标截止日期
    """
    cur = conn.cursor()
    latest = get_latest_price_date(conn)
    if latest and latest >= target_date:
        print(f"[价格] 库中最新日期 {latest}，已覆盖目标 {target_date}，跳过")
        return 0

    if latest:
        gap_days = (target_date - latest).days
        # 多取一些以确保覆盖所有交易日 (周末/节假日不算交易日)
        datalen = max(gap_days + 5, 10)
        print(f"[价格] 库中最新: {latest}, 差距 {gap_days} 天, 将获取最近 {datalen} 条K线")
    else:
        datalen = 10
        print(f"[价格] 库中无数据, 获取最近 {datalen} 条K线")

    print(f"[价格] 从新浪采集 {len(target_codes)} 只 ETF ...")
    count = 0
    for code in target_codes:
        def _fetch_price(c=code, dl=datalen):
            klines = fetch_sina_kline(c, datalen=dl)
            if not klines:
                return False
            rows = []
            for k in klines:
                try:
                    td = datetime.strptime(k["day"], "%Y-%m-%d").date()
                    # 只插入库中最新日期之后的数据
                    if latest and td <= latest:
                        continue
                    rows.append((c, td, float(k["open"]), float(k["high"]),
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
                return True
            return False

        try:
            success = retry_wrapper(_fetch_price, f"价格 {code}")
            if success:
                count += 1
            time.sleep(REQUEST_DELAY)
        except Exception:
            time.sleep(1)  # 重试耗尽后继续下一只

    conn.commit()
    print(f"[价格] 写入 {count} 只 ETF"); return count

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, default=None)
    args = parser.parse_args()
    date_str = args.date or datetime.now().strftime("%Y%m%d")
    target_date = datetime.strptime(date_str, "%Y%m%d").date()
    print(f"ETF 每日采集 — 目标日期: {target_date}")
    conn = get_db_conn()
    try:
        nt_codes = get_nt_codes(conn)
        if not nt_codes:
            print("[错误] 无国家队 ETF, 请先运行 init_data.py"); return
        target = nt_codes | set(INDEX_ETFS.keys())
        collect_daily_shares(conn, target_date, target)
        collect_daily_prices(conn, target_date, target)
    finally:
        conn.close()

if __name__ == "__main__":
    main()

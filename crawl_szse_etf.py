# -*- coding: utf-8 -*-
"""
深交所 ETF 数据抓取 + 国家队持仓识别脚本

功能:
  1. 从深交所官网 API 抓取全部 ETF 列表及份额
  2. 通过新浪财经遍历查询每只 ETF 的十大持有人
  3. 识别国家队 (汇金/社保/证金/养老) 持仓
  4. 结果写入 CSV 文件 + 数据库

用法:
    python crawl_szse_etf.py
    python crawl_szse_etf.py --skip-holders   # 仅抓取 ETF 列表, 跳过持有人查询
    python crawl_szse_etf.py --db              # 同时写入数据库
"""
import os, sys, re, json, csv, time, random, argparse
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 尝试导入数据库相关模块 (非必须)
try:
    import psycopg2
    from psycopg2.extras import execute_values
    from config import DB_CONFIG, NT_KEYWORDS, REQUEST_DELAY
    HAS_DB = True
except ImportError:
    HAS_DB = False
    NT_KEYWORDS = ["社保", "证金", "中央汇金", "全国社保", "基本养老",
                   "中国证券金融", "社保基金", "汇金资管"]
    REQUEST_DELAY = 0.3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── 深交所 API ───────────────────────────────────────────────

SZSE_API_URL = "https://www.szse.cn/api/report/ShowReport/data"
SZSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.szse.cn/market/product/list/etfList/index.html",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}


def fetch_szse_etf_list():
    """
    从深交所官网 API 分页获取全部 ETF 列表。
    API: /api/report/ShowReport/data  CATALOGID=1945  TABKEY=tab1
    返回: list of dict [{"code": "159029", "name": "有色ETF广发", "scale": 32912.77, "manager": "..."}, ...]
    """
    all_etfs = []
    page = 1
    total_pages = None

    print("[深交所] 开始获取 ETF 列表 ...")
    while True:
        params = {
            "SHOWTYPE": "JSON",
            "CATALOGID": "1945",
            "TABKEY": "tab1",
            "PAGENO": str(page),
            "random": str(random.random()),
        }
        try:
            resp = requests.get(SZSE_API_URL, params=params, headers=SZSE_HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  [错误] 第 {page} 页请求失败: {e}")
            break

        if not data or not isinstance(data, list):
            break

        block = data[0]
        meta = block.get("metadata", {})
        records = block.get("data", [])

        if total_pages is None:
            total_pages = int(meta.get("pagecount", 0))
            total_records = int(meta.get("recordcount", 0))
            print(f"  共 {total_records} 只 ETF, {total_pages} 页")

        for record in records:
            etf = _parse_szse_record(record)
            if etf:
                all_etfs.append(etf)

        if page % 10 == 0 or page == total_pages:
            print(f"  第 {page}/{total_pages} 页 完成, 累计 {len(all_etfs)} 只")

        if page >= total_pages:
            break
        page += 1
        time.sleep(REQUEST_DELAY)

    print(f"[深交所] 共获取 {len(all_etfs)} 只 ETF")
    return all_etfs


def _parse_szse_record(record):
    """解析深交所 API 返回的单条 ETF 记录 (HTML 字段)"""
    # sys_key: <a href='...'><u>159029</u></a>
    sys_key = record.get("sys_key", "")
    code_match = re.search(r'>(\d{6})<', sys_key)
    if not code_match:
        return None
    code = code_match.group(1)

    # kzjcurl: <a href='...' title='...'><u>有色ETF广发</u></a> ...
    kzjcurl = record.get("kzjcurl", "")
    name_match = re.search(r'<u>(.*?)</u>', kzjcurl)
    name = name_match.group(1) if name_match else ""

    # dqgm: "32,912.77" (万份)
    dqgm = record.get("dqgm", "0")
    try:
        scale = float(str(dqgm).replace(",", "").strip())
    except (ValueError, TypeError):
        scale = 0.0

    # glrmc: 基金管理人名称 (纯文本)
    manager = record.get("glrmc", "").strip()

    return {
        "code": code,
        "name": name,
        "scale_wan": scale,   # 万份
        "manager": manager,
    }


# ─── 新浪持有人查询 ───────────────────────────────────────────

def fetch_sina_holders(symbol):
    """
    从新浪财经获取 ETF 十大持有人。
    兼容 HTML 页面解析 和 JSON API 两种方式。
    """
    # 方式 1: JSON API (更稳定)
    holders = _fetch_sina_holders_json(symbol)
    if holders:
        return holders

    # 方式 2: HTML 页面解析 (后备)
    return _fetch_sina_holders_html(symbol)


def _fetch_sina_holders_json(symbol):
    """新浪 JSON API 获取持有人"""
    url = "https://stock.finance.sina.com.cn/fundInfo/api/openapi.php/CaihuiFundInfoService.getFundHolder"
    params = {"symbol": symbol}
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
            result.append({
                "rank": i,
                "holder_name": name,
                "hold_amount": amount,
                "hold_ratio": ratio,
            })
        return result
    except:
        return []


def _fetch_sina_holders_html(symbol):
    """新浪 HTML 页面解析持有人 (后备方案)"""
    from bs4 import BeautifulSoup
    url = f"https://stock.finance.sina.com.cn/fundInfo/view/FundInfo_JJCYR.php?symbol={symbol}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.encoding = "gbk"
        soup = BeautifulSoup(resp.text, "html.parser")
        target_table = None
        for table in soup.find_all("table"):
            if "持有人名称" in table.text:
                target_table = table
                break
        if not target_table:
            return []
        rows = target_table.find_all("tr")
        data_list = []
        header_found = False
        for row in rows:
            tds = row.find_all("td")
            if not tds:
                continue
            texts = [td.get_text(strip=True) for td in tds]
            if "持有人名称" in texts:
                header_found = True
                continue
            if header_found and len(texts) >= 4:
                try:
                    amount_str = re.sub(r"[^\d.]", "", texts[2])
                    data_list.append({
                        "rank": len(data_list) + 1,
                        "holder_name": texts[1],
                        "hold_amount": float(amount_str) if amount_str else 0,
                        "hold_ratio": float(texts[3]) if texts[3] else 0,
                    })
                except:
                    continue
        return data_list
    except:
        return []


def scan_etf_for_nt(etf):
    """扫描单只 ETF 是否有国家队持仓"""
    code = etf["code"]
    name = etf["name"]

    time.sleep(random.uniform(0.1, 0.3))
    holders = fetch_sina_holders(code)
    nt_holdings = []

    for h in holders:
        holder_name = h["holder_name"]
        if any(kw in holder_name for kw in NT_KEYWORDS):
            nt_holdings.append({
                "ts_code": code,
                "name": name,
                "holder_name": holder_name,
                "hold_amount": h["hold_amount"],
                "hold_ratio": h["hold_ratio"],
            })

    return nt_holdings


# ─── CSV 输出 ─────────────────────────────────────────────────

def save_etf_list_csv(etf_list, output_file, append=True):
    """保存 ETF 列表到 CSV (追加模式)"""
    existing_codes = set()
    if append and os.path.exists(output_file):
        import pandas as pd
        try:
            df_existing = pd.read_csv(output_file, dtype={"ts_code": str})
            existing_codes = set(df_existing["ts_code"].astype(str))
        except:
            pass

    new_rows = []
    for etf in etf_list:
        if etf["code"] not in existing_codes:
            new_rows.append(etf)

    if not new_rows:
        print(f"[CSV] etf_list.csv 中已有全部深交所 ETF, 无需追加")
        return

    mode = "a" if append and os.path.exists(output_file) else "w"
    with open(output_file, mode=mode, newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if mode == "w":
            writer.writerow(["ts_code", "name"])
        for etf in new_rows:
            writer.writerow([etf["code"], etf["name"]])

    print(f"[CSV] 追加 {len(new_rows)} 只深交所 ETF 到 {output_file}")


def save_nt_results_csv(nt_results, output_file, append=True):
    """保存国家队持仓到 CSV"""
    existing_keys = set()
    if append and os.path.exists(output_file):
        import pandas as pd
        try:
            df_existing = pd.read_csv(output_file, dtype={"ts_code": str})
            for _, row in df_existing.iterrows():
                existing_keys.add((str(row["ts_code"]), str(row["holder_name"])))
        except:
            pass

    new_rows = [r for r in nt_results
                if (r["ts_code"], r["holder_name"]) not in existing_keys]

    if not new_rows:
        print(f"[CSV] national_team_etfs.csv 中已有全部数据, 无需追加")
        return

    mode = "a" if append and os.path.exists(output_file) else "w"
    with open(output_file, mode=mode, newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if mode == "w":
            writer.writerow(["ts_code", "name", "holder_name", "hold_amount", "hold_ratio"])
        for r in new_rows:
            writer.writerow([r["ts_code"], r["name"], r["holder_name"],
                             r["hold_amount"], r["hold_ratio"]])

    print(f"[CSV] 追加 {len(new_rows)} 条国家队持仓到 {output_file}")


# ─── 数据库写入 ───────────────────────────────────────────────

def write_to_db(etf_list, nt_results):
    """将 ETF 列表和国家队持仓写入数据库"""
    if not HAS_DB:
        print("[DB] 数据库模块不可用, 跳过")
        return

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
    except Exception as e:
        print(f"[DB] 连接失败: {e}")
        return

    # 写入 etf_info
    print(f"[DB] 写入 {len(etf_list)} 只 ETF 到 etf_info ...")
    for etf in etf_list:
        cur.execute("""
            INSERT INTO etf_info (ts_code, name) VALUES (%s, %s)
            ON CONFLICT (ts_code) DO UPDATE SET name = EXCLUDED.name, updated_at = NOW()
        """, (etf["code"], etf["name"]))

    # 写入 nt_etf_list
    if nt_results:
        print(f"[DB] 写入 {len(nt_results)} 条国家队持仓 ...")
        nt_codes = set()
        for r in nt_results:
            code = r["ts_code"]
            nt_codes.add(code)
            cur.execute("""
                INSERT INTO nt_etf_list (ts_code, name, holder_name, latest_hold_amount, latest_hold_ratio)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (ts_code, holder_name) DO UPDATE SET
                    name = EXCLUDED.name, latest_hold_amount = EXCLUDED.latest_hold_amount,
                    latest_hold_ratio = EXCLUDED.latest_hold_ratio, updated_at = NOW()
            """, (code, r["name"], r["holder_name"], r["hold_amount"], r["hold_ratio"]))

        # 标记国家队持有
        if nt_codes:
            cur.execute(
                "UPDATE etf_info SET is_nt_held = TRUE, updated_at = NOW() WHERE ts_code = ANY(%s)",
                (list(nt_codes),)
            )

    conn.commit()
    conn.close()
    print("[DB] 写入完成")


# ─── 主流程 ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="深交所 ETF 抓取 + 国家队识别")
    parser.add_argument("--skip-holders", action="store_true", help="跳过新浪持有人查询")
    parser.add_argument("--db", action="store_true", help="同时写入数据库")
    parser.add_argument("--workers", type=int, default=10, help="并发线程数 (默认 10)")
    args = parser.parse_args()

    print("=" * 60)
    print("深交所 ETF 数据抓取 + 国家队持仓识别")
    print("=" * 60)

    # ── Step 1: 获取 ETF 列表 ──
    etf_list = fetch_szse_etf_list()
    if not etf_list:
        print("[错误] 未获取到 ETF 数据, 退出")
        return

    # 保存 ETF 列表 CSV
    etf_csv = os.path.join(BASE_DIR, "etf_list.csv")
    save_etf_list_csv(etf_list, etf_csv)

    # ── Step 2: 查询国家队持仓 ──
    all_nt_results = []
    if not args.skip_holders:
        print(f"\n[国家队] 开始扫描 {len(etf_list)} 只深交所 ETF 的十大持有人 ...")
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(scan_etf_for_nt, etf): etf for etf in etf_list}
            for future in tqdm(as_completed(futures), total=len(futures), desc="扫描持有人"):
                try:
                    results = future.result()
                    if results:
                        all_nt_results.extend(results)
                except Exception as e:
                    etf = futures[future]
                    pass  # 静默跳过失败的

        if all_nt_results:
            print(f"\n[国家队] 共发现 {len(all_nt_results)} 条国家队持仓, "
                  f"涉及 {len(set(r['ts_code'] for r in all_nt_results))} 只 ETF")

            # 打印详情
            print("\n" + "-" * 60)
            for r in sorted(all_nt_results, key=lambda x: x["ts_code"]):
                print(f"  {r['ts_code']} {r['name']:<20s} | {r['holder_name']:<30s} | "
                      f"持有比例: {r['hold_ratio']}%")
            print("-" * 60)
        else:
            print("[国家队] 未发现深交所 ETF 的国家队持仓")

        # 保存国家队 CSV
        nt_csv = os.path.join(BASE_DIR, "national_team_etfs.csv")
        save_nt_results_csv(all_nt_results, nt_csv)

    # ── Step 3: 写入数据库 ──
    if args.db:
        write_to_db(etf_list, all_nt_results)

    print(f"\n{'=' * 60}")
    print(f"完成! ETF: {len(etf_list)} 只, 国家队持仓: {len(all_nt_results)} 条")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()

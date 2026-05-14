"""
ETF 国家队量化看板 — Flask 后端 API
启动: python app.py
"""
import os, sys, json
from datetime import datetime, timedelta
from decimal import Decimal
from flask import Flask, jsonify, request, send_from_directory
import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DB_CONFIG, INDEX_ETFS, FLASK_HOST, FLASK_PORT, FLASK_DEBUG

app = Flask(__name__, static_folder="static", static_url_path="")

def get_db():
    return psycopg2.connect(**DB_CONFIG)

class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal): return float(o)
        return super().default(o)

app.json_provider_class = type('P', (), {'dumps': staticmethod(lambda obj, **kw: json.dumps(obj, cls=DecimalEncoder, ensure_ascii=False, **kw)), 'loads': staticmethod(json.loads)})

def decimal_to_float(rows, desc):
    """Convert psycopg2 rows to list of dicts with Decimal→float"""
    cols = [d[0] for d in desc]
    result = []
    for row in rows:
        d = {}
        for i, v in enumerate(row):
            if isinstance(v, Decimal): v = float(v)
            elif hasattr(v, 'isoformat'): v = v.isoformat()
            d[cols[i]] = v
        result.append(d)
    return result

# ─── 静态页面 ───
@app.route("/")
def index_page():
    return send_from_directory("static", "index.html")

@app.route("/detail/<ts_code>")
def detail_page(ts_code):
    return send_from_directory("static", "detail.html")

# ─── API: 主页图表数据 ───
@app.route("/api/overview/chart")
def api_overview_chart():
    days = int(request.args.get("days", 365))
    conn = get_db()
    cur = conn.cursor()
    try:
        since = (datetime.now() - timedelta(days=days)).date()

        # 1. 国家队 ETF 总份额 (按日汇总)
        cur.execute("""
            SELECT s.trade_date, SUM(s.total_share) as total
            FROM etf_daily_share s
            JOIN etf_info e ON e.ts_code = s.ts_code
            WHERE e.is_nt_held = TRUE AND s.trade_date >= %s
            GROUP BY s.trade_date ORDER BY s.trade_date
        """, (since,))
        share_data = [{"date": r[0].isoformat(), "total": float(r[1])} for r in cur.fetchall()]

        # 2. 指数 ETF 价格
        index_prices = {}
        for code, name in INDEX_ETFS.items():
            cur.execute("""
                SELECT trade_date, close FROM etf_daily_price
                WHERE ts_code = %s AND trade_date >= %s ORDER BY trade_date
            """, (code, since))
            index_prices[code] = {
                "name": name,
                "data": [{"date": r[0].isoformat(), "close": float(r[1])} for r in cur.fetchall()]
            }

        return jsonify({"share_total": share_data, "index_prices": index_prices})
    finally:
        conn.close()

# ─── API: 主页表格数据 ───
@app.route("/api/overview/table")
def api_overview_table():
    conn = get_db()
    cur = conn.cursor()
    try:
        # 获取所有国家队 ETF
        cur.execute("SELECT DISTINCT ts_code, name FROM nt_etf_list ORDER BY ts_code")
        etfs = cur.fetchall()

        # 获取最新交易日
        cur.execute("SELECT MAX(trade_date) FROM etf_daily_share")
        latest_date_row = cur.fetchone()
        if not latest_date_row or not latest_date_row[0]:
            return jsonify([])
        latest_date = latest_date_row[0]

        results = []
        for code, name in etfs:
            row = {"ts_code": code, "name": name}

            # 最新份额
            cur.execute("SELECT total_share FROM etf_daily_share WHERE ts_code=%s AND trade_date=%s", (code, latest_date))
            r = cur.fetchone()
            if not r: continue
            latest_share = float(r[0])
            row["latest_share"] = latest_share

            # 各周期份额变化
            for label, days in [("1d", 1), ("1w", 7), ("1m", 30), ("3m", 90), ("1y", 365)]:
                target = latest_date - timedelta(days=days)
                cur.execute("""
                    SELECT total_share FROM etf_daily_share
                    WHERE ts_code=%s AND trade_date <= %s ORDER BY trade_date DESC LIMIT 1
                """, (code, target))
                pr = cur.fetchone()
                if pr and float(pr[0]) > 0:
                    row[f"share_chg_{label}"] = round((latest_share - float(pr[0])) / float(pr[0]) * 100, 4)
                else:
                    row[f"share_chg_{label}"] = None

            # 国家队持仓汇总
            cur.execute("""
                SELECT COALESCE(SUM(latest_hold_ratio), 0),
                       COALESCE(SUM(latest_hold_amount), 0),
                       MAX(latest_report_date), MAX(prev_report_date),
                       BOOL_OR(is_new_entry)
                FROM nt_etf_list WHERE ts_code = %s
            """, (code,))
            nr = cur.fetchone()
            row["nt_hold_ratio"] = float(nr[0]) if nr[0] else 0
            latest_nt_amount = float(nr[1]) if nr[1] else 0
            latest_report = nr[2]
            prev_report = nr[3]
            row["nt_is_new"] = bool(nr[4]) if nr[4] else False
            row["latest_report_date"] = latest_report.isoformat() if latest_report else None
            row["prev_report_date"] = prev_report.isoformat() if prev_report else None

            # 用份额计算持仓变化: 查询上期国家队总持有份额
            if prev_report and latest_nt_amount > 0:
                cur.execute("""
                    SELECT COALESCE(SUM(hold_amount), 0) FROM etf_holder
                    WHERE ts_code = %s AND report_date = %s AND is_nt = TRUE
                """, (code, prev_report))
                prev_amt_row = cur.fetchone()
                prev_nt_amount = float(prev_amt_row[0]) if prev_amt_row and prev_amt_row[0] else 0
                if prev_nt_amount > 0:
                    row["nt_hold_change"] = round((latest_nt_amount - prev_nt_amount) / prev_nt_amount * 100, 2)
                else:
                    row["nt_hold_change"] = None
            else:
                row["nt_hold_change"] = None

            results.append(row)

        return jsonify({
            "data": results,
            "latest_share_date": latest_date.isoformat() if latest_date else None,
        })
    finally:
        conn.close()

# ─── API: ETF 详情 ───
@app.route("/api/detail/<ts_code>")
def api_detail(ts_code):
    days = int(request.args.get("days", 365))
    conn = get_db()
    cur = conn.cursor()
    try:
        since = (datetime.now() - timedelta(days=days)).date()

        # 基本信息
        cur.execute("SELECT ts_code, name FROM etf_info WHERE ts_code = %s", (ts_code,))
        info_row = cur.fetchone()
        if not info_row:
            return jsonify({"error": "ETF not found"}), 404

        info = {"ts_code": info_row[0], "name": info_row[1]}

        # 价格时序
        cur.execute("""
            SELECT trade_date, open, high, low, close, volume
            FROM etf_daily_price WHERE ts_code=%s AND trade_date>=%s ORDER BY trade_date
        """, (ts_code, since))
        prices = [{"date": r[0].isoformat(), "open": float(r[1]), "high": float(r[2]),
                    "low": float(r[3]), "close": float(r[4]), "volume": int(r[5])} for r in cur.fetchall()]

        # 份额时序
        cur.execute("""
            SELECT trade_date, total_share FROM etf_daily_share
            WHERE ts_code=%s AND trade_date>=%s ORDER BY trade_date
        """, (ts_code, since))
        shares = [{"date": r[0].isoformat(), "total_share": float(r[1])} for r in cur.fetchall()]

        # 十大持有人 (最新两期)
        cur.execute("""
            SELECT DISTINCT report_date FROM etf_holder
            WHERE ts_code=%s ORDER BY report_date DESC LIMIT 2
        """, (ts_code,))
        report_dates = [r[0] for r in cur.fetchall()]

        holders_latest = []
        holders_prev = []
        if report_dates:
            cur.execute("""
                SELECT rank, holder_name, hold_amount, hold_ratio, is_nt, report_date
                FROM etf_holder WHERE ts_code=%s AND report_date=%s ORDER BY rank
            """, (ts_code, report_dates[0]))
            for r in cur.fetchall():
                holders_latest.append({
                    "rank": r[0], "holder_name": r[1], "hold_amount": float(r[2]),
                    "hold_ratio": float(r[3]), "is_nt": r[4], "report_date": r[5].isoformat()
                })

        if len(report_dates) > 1:
            cur.execute("""
                SELECT rank, holder_name, hold_amount, hold_ratio, is_nt, report_date
                FROM etf_holder WHERE ts_code=%s AND report_date=%s ORDER BY rank
            """, (ts_code, report_dates[1]))
            for r in cur.fetchall():
                holders_prev.append({
                    "rank": r[0], "holder_name": r[1], "hold_amount": float(r[2]),
                    "hold_ratio": float(r[3]), "is_nt": r[4], "report_date": r[5].isoformat()
                })

        return jsonify({
            "info": info, "prices": prices, "shares": shares,
            "holders_latest": holders_latest, "holders_prev": holders_prev,
            "latest_report_date": report_dates[0].isoformat() if report_dates else None,
            "prev_report_date": report_dates[1].isoformat() if len(report_dates) > 1 else None,
        })
    finally:
        conn.close()

if __name__ == "__main__":
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)

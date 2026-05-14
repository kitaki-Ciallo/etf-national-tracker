-- ============================================================
-- ETF 国家队量化看板 — PostgreSQL 数据库建表脚本
-- 使用方式: psql -U your_user -d your_db -f schema.sql
-- ============================================================

-- 1. ETF 基本信息表
CREATE TABLE IF NOT EXISTS etf_info (
    ts_code       VARCHAR(10) PRIMARY KEY,        -- ETF代码, 如 '510300'
    name          VARCHAR(100) NOT NULL,           -- ETF名称
    is_nt_held    BOOLEAN DEFAULT FALSE,           -- 是否被国家队持有
    created_at    TIMESTAMP DEFAULT NOW(),
    updated_at    TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE etf_info IS 'ETF 基本信息表';
COMMENT ON COLUMN etf_info.is_nt_held IS '是否被国家队（汇金/社保等）持有';

-- 2. ETF 每日份额表 (日频)
CREATE TABLE IF NOT EXISTS etf_daily_share (
    ts_code       VARCHAR(10) NOT NULL,
    trade_date    DATE NOT NULL,
    total_share   NUMERIC(20, 2),                  -- 总份额 (份)
    created_at    TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (ts_code, trade_date)
);

COMMENT ON TABLE etf_daily_share IS 'ETF 每日份额快照 (来源: 上交所)';
COMMENT ON COLUMN etf_daily_share.total_share IS '基金总份额, 单位: 份';

CREATE INDEX IF NOT EXISTS idx_daily_share_date ON etf_daily_share (trade_date);
CREATE INDEX IF NOT EXISTS idx_daily_share_code ON etf_daily_share (ts_code);

-- 3. ETF 每日价格表 (日频)
CREATE TABLE IF NOT EXISTS etf_daily_price (
    ts_code       VARCHAR(10) NOT NULL,
    trade_date    DATE NOT NULL,
    open          NUMERIC(10, 4),
    high          NUMERIC(10, 4),
    low           NUMERIC(10, 4),
    close         NUMERIC(10, 4),
    volume        BIGINT,                           -- 成交量 (手)
    amount        NUMERIC(20, 4),                   -- 成交额 (元)
    created_at    TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (ts_code, trade_date)
);

COMMENT ON TABLE etf_daily_price IS 'ETF 每日价格数据 (来源: 东方财富)';

CREATE INDEX IF NOT EXISTS idx_daily_price_date ON etf_daily_price (trade_date);
CREATE INDEX IF NOT EXISTS idx_daily_price_code ON etf_daily_price (ts_code);

-- 4. ETF 十大持有人表 (半年频)
CREATE TABLE IF NOT EXISTS etf_holder (
    id            SERIAL PRIMARY KEY,
    ts_code       VARCHAR(10) NOT NULL,
    report_date   DATE NOT NULL,                    -- 报告期截止日 (如 2025-12-31)
    rank          INTEGER,                           -- 排名 1-10
    holder_name   VARCHAR(200) NOT NULL,            -- 持有人名称
    hold_amount   NUMERIC(20, 2),                   -- 持有份额 (份)
    hold_ratio    NUMERIC(8, 4),                    -- 占总份额比 (%)
    is_nt         BOOLEAN DEFAULT FALSE,            -- 是否属于国家队
    created_at    TIMESTAMP DEFAULT NOW(),
    UNIQUE (ts_code, report_date, holder_name)
);

COMMENT ON TABLE etf_holder IS 'ETF 十大持有人 (来源: 新浪财经, 半年报/年报)';
COMMENT ON COLUMN etf_holder.report_date IS '报告期截止日, 如 2025-06-30 或 2025-12-31';
COMMENT ON COLUMN etf_holder.is_nt IS '是否为国家队持有人 (汇金/社保/养老/证金)';

CREATE INDEX IF NOT EXISTS idx_holder_code ON etf_holder (ts_code);
CREATE INDEX IF NOT EXISTS idx_holder_report ON etf_holder (report_date);
CREATE INDEX IF NOT EXISTS idx_holder_nt ON etf_holder (is_nt) WHERE is_nt = TRUE;

-- 5. 国家队 ETF 持仓清单 (汇总视图)
CREATE TABLE IF NOT EXISTS nt_etf_list (
    ts_code             VARCHAR(10) NOT NULL,
    name                VARCHAR(100),
    holder_name         VARCHAR(200) NOT NULL,       -- 国家队机构名称
    latest_hold_amount  NUMERIC(20, 2),              -- 最新持有份额
    latest_hold_ratio   NUMERIC(8, 4),               -- 最新占比 (%)
    prev_hold_ratio     NUMERIC(8, 4),               -- 上期占比 (%)
    latest_report_date  DATE,                         -- 最新报告期
    prev_report_date    DATE,                         -- 上期报告期
    is_new_entry        BOOLEAN DEFAULT FALSE,        -- 是否新进
    updated_at          TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (ts_code, holder_name)
);

COMMENT ON TABLE nt_etf_list IS '国家队 ETF 持仓汇总清单';
COMMENT ON COLUMN nt_etf_list.is_new_entry IS '上期不存在而本期新进';

CREATE INDEX IF NOT EXISTS idx_nt_list_code ON nt_etf_list (ts_code);

-- ============================================================
-- 便捷视图: 按 ETF 汇总国家队持仓
-- ============================================================
CREATE OR REPLACE VIEW v_nt_etf_summary AS
SELECT
    n.ts_code,
    n.name,
    SUM(n.latest_hold_ratio)  AS total_nt_ratio,
    SUM(n.prev_hold_ratio)    AS total_prev_nt_ratio,
    SUM(n.latest_hold_ratio) - SUM(n.prev_hold_ratio) AS nt_ratio_change,
    MAX(n.latest_report_date) AS latest_report_date,
    MAX(n.prev_report_date)   AS prev_report_date,
    BOOL_OR(n.is_new_entry)   AS has_new_entry
FROM nt_etf_list n
GROUP BY n.ts_code, n.name;

COMMENT ON VIEW v_nt_etf_summary IS '按 ETF 汇总的国家队持仓视图';

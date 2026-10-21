-- ============================================================
-- Steam 库存管理系统 - D1 建表 SQL
-- 执行方式：
--   npx wrangler d1 execute steam-inventory-db --remote --file=schema.sql
-- ============================================================

-- 1. 物品描述表（静态元数据）
CREATE TABLE IF NOT EXISTS item_descriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    classid TEXT,
    instanceid TEXT,
    market_hash_name TEXT UNIQUE NOT NULL,
    name TEXT,
    icon_url TEXT,
    commodity INTEGER DEFAULT 0,
    tradable INTEGER DEFAULT 0,
    marketable INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(classid, instanceid)
);

-- 2. 资产表（你拥有的每一件独立物品）
CREATE TABLE IF NOT EXISTS assets (
    assetid TEXT PRIMARY KEY,
    description_id INTEGER,
    amount INTEGER DEFAULT 1,
    float_value REAL,
    paint_seed INTEGER,
    paint_index INTEGER,
    def_index INTEGER,
    quality INTEGER,
    tradable INTEGER,
    marketable INTEGER,
    owner_steamid TEXT,
    first_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen_at DATETIME,
    FOREIGN KEY (description_id) REFERENCES item_descriptions(id)
);

CREATE INDEX IF NOT EXISTS idx_assets_float ON assets(float_value);
CREATE INDEX IF NOT EXISTS idx_assets_desc ON assets(description_id);
CREATE INDEX IF NOT EXISTS idx_assets_last_seen ON assets(last_seen_at);

-- 3. 库存快照历史表（追踪变化）
CREATE TABLE IF NOT EXISTS inventory_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    assetid TEXT,
    action TEXT CHECK(action IN ('added', 'removed', 'updated')),
    old_value TEXT,
    new_value TEXT
);

CREATE INDEX IF NOT EXISTS idx_snapshots_asset ON inventory_snapshots(assetid);
CREATE INDEX IF NOT EXISTS idx_snapshots_time ON inventory_snapshots(snapshot_at);

-- 4. 价格历史表（预留，为后续价格追踪用）
CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_hash_name TEXT,
    price_cents INTEGER,
    volume INTEGER,
    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_price_mhn ON price_history(market_hash_name, recorded_at);
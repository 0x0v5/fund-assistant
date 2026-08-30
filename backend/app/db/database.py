"""SQLite database connection and setup."""

import aiosqlite
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager


DB_PATH = Path(__file__).parent.parent.parent.parent / "data" / "fund.db"


async def init_db():
    """Initialize database tables."""
    async with aiosqlite.connect(DB_PATH) as db:
        # QDII 额度表
        await db.execute("""
            CREATE TABLE IF NOT EXISTS qdii_quota (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                premium REAL,
                quota_status TEXT,
                update_time TEXT,
                apply_status TEXT,
                limit_amount TEXT,
                redeem_status TEXT,
                nav_date TEXT,
                manager TEXT,
                scale TEXT,
                m_fee TEXT,
                t_fee TEXT,
                buy_fee TEXT,
                redeem_fee TEXT,
                UNIQUE(code, update_time)
            )
        """)

        # 基金净值历史表
        await db.execute("""
            CREATE TABLE IF NOT EXISTS fund_nav (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                date TEXT NOT NULL,
                nav REAL,
                accumulated_nav REAL,
                UNIQUE(code, date)
            )
        """)

        # 动量计算记录表
        await db.execute("""
            CREATE TABLE IF NOT EXISTS momentum_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                name TEXT,
                short_momentum REAL,
                medium_momentum REAL,
                short_sharpe REAL,
                combined_score REAL,
                signal TEXT,
                calc_time TEXT,
                daily_change REAL,
                current_price REAL,
                above_ma60 INTEGER,
                UNIQUE(code, calc_time)
            )
        """)

        # 行业基金表（按 code + update_time 保留历史，不再按 code 唯一）
        await db.execute("""
            CREATE TABLE IF NOT EXISTS industry_funds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                name TEXT,
                industry TEXT,
                nav REAL,
                ytd_return REAL,
                update_time TEXT
            )
        """)

        # 基金评测历史表
        await db.execute("""
            CREATE TABLE IF NOT EXISTS fund_eval_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                name TEXT,
                score INTEGER,
                return_1y REAL,
                return_3y REAL,
                return_5y REAL,
                sharpe REAL,
                sortino REAL,
                calmar REAL,
                max_drawdown REAL,
                volatility REAL,
                profit_prob REAL,
                return_1y_pct REAL,
                pe REAL,
                pb REAL,
                roe REAL,
                fund_type TEXT,
                eval_time TEXT,
                UNIQUE(code, eval_time)
            )
        """)

        # 基金基本信息表（缓存用，不再从 fund_eval_history 拼凑）
        await db.execute("""
            CREATE TABLE IF NOT EXISTS fund_info (
                code TEXT PRIMARY KEY,
                name TEXT,
                scale TEXT,
                found_date TEXT,
                m_fee TEXT,
                t_fee TEXT,
                manager TEXT,
                manager_exp TEXT,
                fund_type TEXT,
                updated_at TEXT
            )
        """)

        # 用户自选基金表
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_favorite_funds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                created_at TEXT
            )
        """)

        # 回测运行表
        await db.execute("""
            CREATE TABLE IF NOT EXISTS backtest_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                strategy_type TEXT NOT NULL,
                params TEXT NOT NULL,
                universe TEXT NOT NULL,
                benchmark_code TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                initial_capital REAL NOT NULL,
                cash_rate REAL NOT NULL,
                total_return REAL,
                cagr REAL,
                benchmark_total_return REAL,
                alpha REAL,
                max_drawdown REAL,
                sharpe REAL,
                annual_volatility REAL,
                max_consecutive_losing_days INTEGER,
                total_rebalances INTEGER,
                total_trades INTEGER,
                win_rate REAL,
                profit_loss_ratio REAL,
                cash_position_days_ratio REAL,
                created_at TEXT
            )
        """)

        # 回测每日净值表
        await db.execute("""
            CREATE TABLE IF NOT EXISTS backtest_daily_values (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                portfolio_value REAL NOT NULL,
                benchmark_value REAL NOT NULL,
                holding_code TEXT,
                cash REAL NOT NULL,
                drawdown REAL,
                FOREIGN KEY (run_id) REFERENCES backtest_runs(id) ON DELETE CASCADE
            )
        """)

        # 回测交易明细表
        await db.execute("""
            CREATE TABLE IF NOT EXISTS backtest_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                action TEXT NOT NULL,
                code TEXT NOT NULL,
                price REAL NOT NULL,
                shares REAL NOT NULL,
                value REAL NOT NULL,
                FOREIGN KEY (run_id) REFERENCES backtest_runs(id) ON DELETE CASCADE
            )
        """)

        # 索引
        await db.execute("CREATE INDEX IF NOT EXISTS idx_fund_nav_code_date ON fund_nav(code, date DESC)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_fund_eval_code_time ON fund_eval_history(code, eval_time DESC)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_backtest_runs_strategy_created ON backtest_runs(strategy_type, created_at DESC)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_backtest_daily_run_date ON backtest_daily_values(run_id, date)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_backtest_trades_run ON backtest_trades(run_id)")

        await db.commit()

    # 迁移：旧表缺列时补上（幂等）
    migrations = [
        ("fund_eval_history", "sortino", "REAL"),
        ("fund_eval_history", "calmar", "REAL"),
        ("fund_eval_history", "return_1y_pct", "REAL"),
        ("fund_eval_history", "fund_type", "TEXT"),
        ("momentum_history", "short_sharpe", "REAL"),
        ("industry_funds", "data_source", "TEXT"),
    ]
    async with aiosqlite.connect(DB_PATH) as db:
        for table, col, col_type in migrations:
            try:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
                await db.commit()
            except Exception:
                # 列已存在 → 忽略
                pass

    # 迁移：行业基金表从 code 唯一改为 (code, update_time) 唯一，保留历史
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            # 检查是否存在旧版 code 唯一约束（auto-index origin='u'）
            cur = await db.execute("PRAGMA index_list('industry_funds')")
            rows = await cur.fetchall()
            old_autoindex = None
            for row in rows:
                # row: (seq, name, unique, origin, partial)
                if row[2] == 1 and row[3] == 'u':
                    info = await db.execute(f"PRAGMA index_info('{row[1]}')")
                    cols = [r[2] for r in await info.fetchall()]
                    if cols == ['code']:
                        old_autoindex = row[1]
                        break

            if old_autoindex:
                # SQLite 无法直接 drop auto-index，需要重建表
                await db.execute("""
                    CREATE TABLE industry_funds_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        code TEXT NOT NULL,
                        name TEXT,
                        industry TEXT,
                        nav REAL,
                        ytd_return REAL,
                        update_time TEXT
                    )
                """)
                await db.execute("""
                    INSERT INTO industry_funds_new
                        (code, name, industry, nav, ytd_return, update_time)
                    SELECT code, name, industry, nav, ytd_return, update_time
                    FROM industry_funds
                """)
                await db.execute("DROP TABLE industry_funds")
                await db.execute("ALTER TABLE industry_funds_new RENAME TO industry_funds")
                await db.commit()
        except Exception:
            pass

        try:
            await db.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_industry_funds_code_time
                ON industry_funds(code, update_time)
            """)
            await db.commit()
        except Exception:
            pass


@asynccontextmanager
async def get_db():
    """Get database connection as context manager."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(DB_PATH)
    try:
        yield db
    finally:
        await db.close()


async def execute_query(sql: str, params: tuple = ()) -> list:
    """Execute SELECT query and return results."""
    async with get_db() as db:
        cursor = await db.execute(sql, params)
        rows = await cursor.fetchall()
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        return [dict(zip(columns, row)) for row in rows]


async def execute_update(sql: str, params: tuple = ()) -> int:
    """Execute INSERT/UPDATE/DELETE and return cursor.lastrowid for INSERTs
    (or 0 when the table has no INTEGER PRIMARY KEY), else rowcount.
    """
    async with get_db() as db:
        cursor = await db.execute(sql, params)
        await db.commit()
        # lastrowid: 0 if no AUTOINCREMENT column was touched
        return cursor.lastrowid or cursor.rowcount


async def execute_many(sql: str, params: list[tuple]) -> int:
    """Execute INSERT/UPDATE/DELETE with multiple parameter sets.

    Returns the total rowcount.
    """
    if not params:
        return 0
    async with get_db() as db:
        cursor = await db.executemany(sql, params)
        await db.commit()
        return cursor.rowcount

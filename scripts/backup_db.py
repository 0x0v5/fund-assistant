#!/usr/bin/env python3
"""SQLite 热备份：fund.db -> /mnt/usb/fund-assistant/backups/

用 Python stdlib `sqlite3.Connection.backup()` 替代 sqlite3 CLI 二进制：
- 容器/N1 镜像里没装 sqlite3 二进制，但 Python sqlite3 模块足够
- `.backup()` 是 SQLite 官方推荐的 online backup API，期间允许读写
- 失败退出码非 0，方便 cron / systemd 报错

部署位置：/opt/backup_fund_db.py（N1 主机上）
cron:     0 2 * * * /opt/backup_fund_db.py >> /var/log/fund_backup.log 2>&1
"""

import os
import sys
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

SRC = Path("/root/fund-assistant/data/fund.db")
BACKUP_DIR = Path("/mnt/usb/fund-assistant/backups")
LOCAL_BACKUP = Path("/opt/fund_local_backup")  # eMMC 副备份（U盘挂了兜底）
KEEP_DAYS = 7


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def cleanup_old(dirpath: Path) -> None:
    if not dirpath.exists():
        return
    cutoff = datetime.now().timestamp() - KEEP_DAYS * 86400
    for f in dirpath.iterdir():
        if f.is_file() and f.name.startswith("fund_") and f.stat().st_mtime < cutoff:
            f.unlink()
            log(f"清理过期 {f}")


def main() -> int:
    if not SRC.exists():
        log(f"ERROR: 源数据库不存在 {SRC}")
        return 1

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_BACKUP.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst_usb = BACKUP_DIR / f"fund_{ts}.db"
    dst_local = LOCAL_BACKUP / f"fund_{ts}.db"

    # 1. 热备份：src -> dst_usb（在线，源 DB 可读写）
    try:
        src_conn = sqlite3.connect(str(SRC))
        # 临时把源 DB 锁到 backup-safe 状态
        dst_conn = sqlite3.connect(str(dst_usb))
        with dst_conn:
            src_conn.backup(dst_conn)
        dst_conn.close()
        src_conn.close()
        log(f"备份成功 -> {dst_usb} ({dst_usb.stat().st_size} bytes)")
    except Exception as e:
        log(f"ERROR: 热备份失败 {e}")
        return 1

    # 2. 复制一份到 eMMC 本地（U盘挂了能恢复）
    try:
        shutil.copy2(dst_usb, dst_local)
        log(f"本地副本 -> {dst_local} ({dst_local.stat().st_size} bytes)")
    except Exception as e:
        log(f"WARN: 本地副本失败 {e}（U盘备份已成功）")

    # 3. 清理 7 天前旧备份
    cleanup_old(BACKUP_DIR)
    cleanup_old(LOCAL_BACKUP)

    return 0


if __name__ == "__main__":
    sys.exit(main())
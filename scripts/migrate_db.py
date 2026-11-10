#!/usr/bin/env python3
# 数据迁移：把 data/repair.db（SQLite）导出成 EdgeOne Blob 的整表 JSON 格式
# 输出到 data-store/ 目录（与 lib/store.js 的文件后端格式一致）
# 之后可用 scripts/upload-to-blob.mjs 把 data-store/ 上传到云端 Blob
import json
import sqlite3
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "repair.db"
OUT = ROOT / "data-store"

if not DB.exists():
    print("[migrate] 未找到 data/repair.db，跳过")
    raise SystemExit(0)

c = sqlite3.connect(str(DB))
c.row_factory = sqlite3.Row
os.makedirs(OUT / "table", exist_ok=True)
os.makedirs(OUT / "_sys", exist_ok=True)

# 1. records 表按 db 分组
rows = c.execute("SELECT id, db, data, created_at, updated_at FROM records").fetchall()
tables = {}
for r in rows:
    d = json.loads(r["data"])
    d["_id"] = r["id"]
    t = tables.setdefault(r["db"], {"list": [], "created_at": "", "updated_at": ""})
    t["list"].append(d)
    if not t["created_at"]:
        t["created_at"] = r["created_at"]
    t["updated_at"] = r["updated_at"]

for dbid, t in tables.items():
    p = OUT / "table" / (dbid + ".json")
    p.write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    print("[migrate] 表 %s：%d 条" % (dbid, len(t["list"])))

# 2. sessions 表
try:
    srows = c.execute("SELECT token, emp, name, job, exp, rate_ok FROM sessions").fetchall()
except Exception:
    srows = c.execute("SELECT token, emp, name, job, exp FROM sessions").fetchall()
sessions = {}
for r in srows:
    sessions[r["token"]] = {"emp": r["emp"], "name": r["name"], "job": r["job"], "exp": r["exp"]}
    if "rate_ok" in r.keys():
        sessions[r["token"]]["rate_ok"] = int(r["rate_ok"] or 0)
(OUT / "_sys" / "sessions.json").write_text(json.dumps(sessions, ensure_ascii=False), encoding="utf-8")
print("[migrate] 会话：%d 个" % len(sessions))

# 3. meta 表
try:
    mrows = c.execute("SELECT k, v FROM meta").fetchall()
except Exception:
    mrows = []
meta = {r["k"]: r["v"] for r in mrows}
(OUT / "_sys" / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
print("[migrate] 元数据：%d 项" % len(meta))

c.close()
print("[migrate] 完成，输出到 data-store/")

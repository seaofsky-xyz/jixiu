#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
设备快速报修 · 自托管服务端
================================================
- 零第三方依赖，只用 Python 3.8+ 标准库
- SQLite 存业务数据，首次启动自动从 data/seed.json 导入
- 登录：工号 + 工号后四位，服务端校验，默认 30 天免登录
- 同源 /api/wecom/push 代发企业微信群机器人（key 只留在服务端，不进网页源码）
- 可选直接跑 HTTPS（部署简单时用），也可以放 Nginx 后面

启动：
    python3 server.py
    python3 server.py --port 8080

健康检查：
    curl http://127.0.0.1:8080/api/health
"""

import argparse
import gzip
import json
import os
import re
import secrets
import socket
import ssl
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
STATIC = BASE / "static"
DB_PATH = DATA / "repair.db"
SEED_PATH = DATA / "seed.json"
SCHEMA_PATH = DATA / "schema.json"
TOPUP_PATH = DATA / "topup.json"
CFG_PATH = BASE / "config.json"

DEFAULT_CFG = {
    "port": 8080,
    "siteUrl": "",
    "company": "我的工厂",
    "sessionDays": 30,
    "tls": {"cert": "", "key": ""},
    "wecom": {"webhookKey": ""},
    "ai": {"enabled": False, "apiKey": "", "baseUrl": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    "extraUsers": [],
    "adminEmps": [],
    "adminPw": "8888",
}

_lock = threading.Lock()
_schema = {}
CFG = dict(DEFAULT_CFG)


# ---------------------------------------------------------------- 配置 / 数据库

def load_config():
    global CFG
    cfg = json.loads(json.dumps(DEFAULT_CFG))
    if CFG_PATH.exists():
        try:
            user = json.loads(CFG_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            print("[warn] config.json 解析失败，用默认配置：", e)
            user = {}
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    CFG = cfg
    return CFG


def load_schema():
    global _schema
    if SCHEMA_PATH.exists():
        _schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return _schema


def conn():
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    return c


def init_db():
    DATA.mkdir(parents=True, exist_ok=True)
    STATIC.mkdir(parents=True, exist_ok=True)
    with conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS records (
              id TEXT PRIMARY KEY,
              db TEXT NOT NULL,
              data TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_records_db ON records(db);
            CREATE TABLE IF NOT EXISTS sessions (
              token TEXT PRIMARY KEY,
              emp TEXT NOT NULL,
              name TEXT NOT NULL,
              job TEXT NOT NULL,
              exp INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
            """
        )
        # 迁移：本机评分权限开关（0/1），只有通过管理密码校验才置 1
        try:
            c.execute("ALTER TABLE sessions ADD COLUMN rate_ok INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass
    import_seed_if_empty()
    import_topup()


def import_topup():
    """按表补导：topup.json = { 表id: [记录...] }，只导空表，绝不动已有数据。
    用于在已有数据库上补入新功能的初始数据（如设备台账）。"""
    if not TOPUP_PATH.exists():
        return
    try:
        topup = json.loads(TOPUP_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print("[warn] topup.json 解析失败：", e)
        return
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with conn() as c:
        for dbid, rows in topup.items():
            n = c.execute("SELECT COUNT(*) AS n FROM records WHERE db=?", (dbid,)).fetchone()["n"]
            if n:
                print("[info] 表 %s 已有 %d 条记录，跳过补导" % (dbid, n))
                continue
            props = {p.get("name"): p for p in (_schema.get(dbid, {}) or {}).get("properties", [])}
            cnt = 0
            for r in rows or []:
                rid = str(r.get("_id") or secrets.token_hex(12))
                data = {}
                for k, v in r.items():
                    if k == "_id":
                        continue
                    data[k] = norm_value(props.get(k), v)
                c.execute(
                    "INSERT OR REPLACE INTO records(id,db,data,created_at,updated_at) VALUES(?,?,?,?,?)",
                    (rid, dbid, json.dumps(data, ensure_ascii=False), now, now),
                )
                cnt += 1
            if cnt:
                print("[ok] 已补导表 %s：%d 条记录" % (dbid, cnt))


def norm_value(prop, val):
    """把「选项文本」统一换成「选项 id」，与页面写入时的格式保持一致。"""
    if val is None:
        return None
    t = (prop or {}).get("type")
    cfg = (prop or {}).get("config") or {}
    if t == "select":
        opts = cfg.get("options") or []
        ids = {str(o.get("id")) for o in opts}
        if isinstance(val, str) and val in ids:
            return val
        for o in opts:
            if o.get("text") == val:
                return o.get("id")
        return val
    if t == "multi_select":
        if not isinstance(val, list):
            return val
        opts = cfg.get("options") or []
        ids = {str(o.get("id")) for o in opts}
        out = []
        for v in val:
            if isinstance(v, str) and v in ids:
                out.append(v)
                continue
            hit = None
            for o in opts:
                if o.get("text") == v:
                    hit = o.get("id")
                    break
            out.append(hit or v)
        return out
    return val


def import_seed_if_empty():
    if not SEED_PATH.exists():
        print("[info] 没有 data/seed.json，跳过初始化数据")
        return
    with conn() as c:
        n = c.execute("SELECT COUNT(*) AS n FROM records").fetchone()["n"]
    if n:
        print("[info] 数据库已有 %d 条记录，跳过导入" % n)
        return
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    total = 0
    with conn() as c:
        for dbid, rows in seed.items():
            props = {p.get("name"): p for p in (_schema.get(dbid, {}) or {}).get("properties", [])}
            for r in rows or []:
                rid = str(r.get("_id") or r.get("record_id") or secrets.token_hex(12))
                data = {}
                for k, v in r.items():
                    if k in ("_id", "record_id"):
                        continue
                    data[k] = norm_value(props.get(k), v)
                c.execute(
                    "INSERT OR REPLACE INTO records(id,db,data,created_at,updated_at) VALUES(?,?,?,?,?)",
                    (rid, dbid, json.dumps(data, ensure_ascii=False), now, now),
                )
                total += 1
    print("[ok] 已从 seed.json 导入 %d 条记录" % total)


# ---------------------------------------------------------------- 业务工具

def unwrap(v):
    """页面写入格式 {text:...}/{select:...}/{number:...}/{date:...}/... → 裸值"""
    if isinstance(v, dict):
        for k in ("text", "select", "number", "date", "checkbox"):
            if k in v:
                return v[k]
        if "multi_select" in v:
            return v["multi_select"]
        return None
    return v


def merge_props(old, props):
    out = dict(old or {})
    for k, v in (props or {}).items():
        out[k] = unwrap(v)
    return out


def sort_key(v):
    if v is None or v == "":
        return (0, 0, "")
    if isinstance(v, bool):
        return (1, int(v), "")
    if isinstance(v, (int, float)):
        return (1, v, "")
    return (2, 0, str(v))


def get_session(token):
    if not token:
        return None
    with conn() as c:
        row = c.execute("SELECT * FROM sessions WHERE token=?", (token,)).fetchone()
    if not row:
        return None
    if int(row["exp"]) < int(time.time()):
        with conn() as c:
            c.execute("DELETE FROM sessions WHERE token=?", (token,))
        return None
    return {"emp": row["emp"], "name": row["name"], "job": row["job"],
            "rate_ok": int(row["rate_ok"] or 0) if "rate_ok" in row.keys() else 0}


RATE_AUTH_DB = "RateAuthTable001"      # 评分权限名单表
RATE_FIELDS = ("评分", "评分人", "评分日期", "评分备注")


def rate_allowed(sess):
    """谁能看/能打评分：
    1) 本机已通过管理密码（sessions.rate_ok=1）——只有管理员自己会开
    2) 或登录人在「评分权限」名单内
    名单为空且本机未授权 = 谁都看不到（默认对所有人隐藏）"""
    if not sess:
        return False
    if int(sess.get("rate_ok") or 0) == 1:
        return True
    emp = str(sess.get("emp") or "").strip()
    name = str(sess.get("name") or "").strip()
    if not emp and not name:
        return False
    for r in read_all(RATE_AUTH_DB):
        e = str(r.get("工号") or "").strip()
        n = str(r.get("姓名") or "").strip()
        if emp and e and e == emp:
            return True
        if name and n and n == name:
            return True
    return False


def find_member(emp):
    """从「排班管理」表里找工号，取姓名和岗位。"""
    emp = str(emp).strip()
    for u in CFG.get("extraUsers") or []:
        if str(u.get("emp", "")).strip() == emp:
            return {"emp": emp, "name": u.get("name", ""), "job": u.get("job", "")}
    for r in read_all("3JlPfR1040CXW0DT39nyeW"):
        if str(r.get("工号", "")).strip() == emp:
            return {"emp": emp, "name": r.get("姓名", ""), "job": r.get("岗位", "")}
    return None


def read_all(dbid):
    with conn() as c:
        rows = c.execute("SELECT id,data FROM records WHERE db=? ORDER BY created_at, rowid", (dbid,)).fetchall()
    out = []
    for r in rows:
        d = json.loads(r["data"])
        d["_id"] = r["id"]
        out.append(d)
    return out


# ---------------------------------------------------------------- AI 诊断分析
# 不依赖外部服务：用「故障关键词规则库 + 同设备/同部位历史工单统计」生成分析。
# config.json 里配置 ai.apiKey 后，会自动改用大模型（OpenAI 兼容接口）生成，失败自动回落规则引擎。

ORDER_DB_FALLBACK = "bs5R43nhjgXcGROM4m0fpM"      # 工单表
STOCK_DB = "Q5R9iMj4TYVwHRuL6FNR4i"               # 出入库表

AI_RULES = [
    (("轴承", "异响", "噪音", "杂音", "啸叫", "振动", "抖动"),
     "轴承磨损、缺油或联轴器对中不良；长期振动会连锁损伤轴颈与端盖",
     ("停机检查轴承游隙与润滑脂状态，必要时更换轴承并重新对中",
      "复紧地脚螺栓，试机测振动与温升，30 分钟内无异常再交生产"),
     "把润滑和振动值纳入月度点检；同部位 2 次以上建议做对中/动平衡校正"),
    (("电机", "马达", "绕组", "烧", "过热", "发烫", "温度高", "绝缘"),
     "电机过载、散热不良或绕组绝缘老化，也可能由缺相、电压不稳引起",
     ("测三相电流是否平衡，检查风扇与散热风道，测绝缘电阻",
      "确认负载有无卡滞，必要时更换电机或加装过热保护"),
     "定期清灰、测绝缘与运行电流；热继电器/温度报警要投用"),
    (("变频器", "变频", "过流", "过压", "欠压", "故障码", "跳闸", "报警"),
     "变频器参数漂移、负载突变或电网波动触发保护，也可能是散热风扇、电容老化",
     ("记录故障码，检查散热风扇与滤网，复位后先空载试运行",
      "核对加减速时间与电机参数，排查负载卡滞"),
     "建立变频器参数备份；每季度清灰并检查风扇、电容"),
    (("接触器", "继电器", "空开", "断路器", "触点", "烧黑", "打火"),
     "触点氧化烧蚀或线圈老化造成接触不良，频繁启停会加速损坏",
     ("断电验电后检查触点与线圈，更换同规格元件并紧固端子",
      "复测绝缘与回路电阻，通电试机确认无打火异响"),
     "配电柜定期紧固端子、清灰；大电流回路加装浪涌保护"),
    (("皮带", "链条", "链轮", "打滑", "断裂", "脱链", "跑偏"),
     "张紧度不足、皮带/链条磨损或轮系不对中",
     ("更换磨损件并按标准张紧，校正轮系平行度",
      "空载运行观察有无跑偏、打滑与异常磨损"),
     "每周检查张紧度与磨损量；常用规格常备一套"),
    (("气缸", "气动", "漏气", "气压", "电磁阀", "气管"),
     "密封圈老化、气管接头松动或电磁阀卡滞导致气压不足",
     ("肥皂水查漏，更换密封圈/接头，清理或更换电磁阀",
      "确认气源压力与油水分离器，排水后试动作"),
     "每班排水、每月检查气管接头；密封件按周期更换"),
    (("液压", "油压", "漏油", "油缸", "油泵", "油温"),
     "密封件老化、油液污染或油泵磨损导致压力不足/渗漏",
     ("检查油位与油质，更换密封件，清洗或更换滤芯",
      "补油至标线，试压观察是否渗漏、压力是否稳定"),
     "按周期换油与滤芯；记录油温、压力趋势提前预警"),
    (("水泵", "漏水", "水压", "不出水", "堵塞", "流量小"),
     "叶轮磨损或堵塞、机械密封损坏，或管路进气",
     ("清理叶轮与管路，更换机械密封，排空管路空气",
      "试运行测流量与压力，确认无渗漏"),
     "加装并定期清理过滤器；常备机械密封"),
    (("传感器", "感应", "限位", "光电", "接近开关", "信号", "失灵", "不准"),
     "传感器脏污、安装松动或线路接触不良",
     ("清洁感应面，校正安装距离，检查接线与屏蔽层",
      "手动触发验证信号，确认 PLC 输入点状态正常"),
     "定期清洁与紧固；信号线远离动力线单独走线"),
    (("PLC", "程序", "触摸屏", "上位机", "通讯", "通信", "死机", "黑屏"),
     "程序异常、通讯干扰或模块供电不稳",
     ("重启对应模块，检查通讯线与接地，必要时恢复备份程序",
      "逐点验证 I/O 与通讯状态"),
     "定期备份程序与参数；控制柜做等电位接地"),
    (("密封", "垫片", "渗漏", "漏液", "漏料", "法兰"),
     "密封件老化，或法兰螺栓松动、受力不均",
     ("更换密封垫，按对角顺序均匀紧固螺栓",
      "试压/试运行观察渗漏情况"),
     "按介质选型密封材料；检修后定期复紧"),
    (("加热", "热电偶", "温控", "不升温", "温度低"),
     "加热管或热电偶损坏，或温控参数偏差",
     ("测加热管电阻与热电偶信号，更换损坏件并重新整定",
      "空载升温验证温控曲线"),
     "定期校验温控仪表；常备加热管"),
    (("卡死", "卡阻", "不动作", "无法启动", "启动不了", "抱死"),
     "机械卡阻、限位异常或控制回路未满足启动条件",
     ("手动盘车确认是否卡阻，检查限位与安全回路",
      "逐项复位后空载试机，确认动作顺畅"),
     "完善点检与润滑；排查异物、变形来源"),
]

AI_CAT_GENERIC = {
    "机械": ("机械件磨损、松动或润滑不足，需结合拆检确认具体损坏件",
             "拆检磨损部位，更换损坏件并复紧松动螺栓，试机确认",
             "加强润滑与紧固点检，建立易损件更换周期"),
    "电气": ("电气元件老化、接触不良或参数漂移",
             "测量电压/电流与绝缘，替换可疑元件，复位后试运行",
             "定期紧固端子、清灰，重要回路做红外测温"),
    "结构": ("结构件变形、焊缝开裂或紧固件松动",
             "检查变形与焊缝，校正或补强，复紧连接螺栓",
             "避免超载与外力冲击，定期检查焊缝与螺栓力矩"),
    "管道": ("管道堵塞、渗漏或支架松动",
             "疏通/更换管段，处理渗漏点，加固支架",
             "定期巡检压力与渗漏，介质过滤要到位"),
}


def _order_db():
    for did, info in (_schema or {}).items():
        if (info or {}).get("name") == "工单":
            return did
    return ORDER_DB_FALLBACK


def _opt_text(dbid, field, val):
    """select 值（id 或文本）→ 文本"""
    if not val:
        return ""
    for p in ((_schema.get(dbid) or {}).get("properties") or []):
        if p.get("name") == field:
            for o in ((p.get("config") or {}).get("options") or []):
                if str(o.get("id")) == str(val):
                    return str(o.get("text") or "")
    return str(val)


def _parse_day(s):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(s or ""))
    if not m:
        return None
    try:
        return time.mktime(time.strptime("%s-%s-%s" % m.groups(), "%Y-%m-%d"))
    except Exception:
        return None


def _ai_gather(order):
    """汇总同设备/同部位历史与本次领用配件"""
    od = _order_db()
    all_orders = read_all(od)
    dev = str(order.get("设备名称") or "").strip()
    part = str(order.get("故障部位") or "").strip()
    me = order.get("_id")

    same_dev = []
    if dev:
        for r in all_orders:
            if r.get("_id") == me:
                continue
            if str(r.get("设备名称") or "").strip() == dev:
                same_dev.append(r)
    same_part = [r for r in same_dev if part and str(r.get("故障部位") or "").strip() == part]
    done_dev = [r for r in same_dev if str(r.get("完成日期") or "").strip()]

    now = time.time()
    repeat90 = 0
    for r in same_dev:
        d = _parse_day(r.get("报修日期"))
        if d and (now - d) <= 90 * 86400:
            repeat90 += 1

    # 平均故障间隔（同设备，按报修日期排序）
    days = sorted([x for x in (_parse_day(r.get("报修日期")) for r in same_dev) if x])
    avg_gap = None
    if len(days) >= 2:
        gaps = [(days[i + 1] - days[i]) / 86400.0 for i in range(len(days) - 1)]
        gaps = [g for g in gaps if g > 0]
        if gaps:
            avg_gap = sum(gaps) / len(gaps)

    # 最近处理记录
    done_sorted = sorted(done_dev, key=lambda r: (_parse_day(r.get("完成日期")) or 0), reverse=True)
    recent = []
    for r in done_sorted[:3]:
        txt = str(r.get("维修结果") or "").strip()
        if txt:
            recent.append("%s：%s" % (str(r.get("报修日期") or "")[:10], txt[:60]))

    # 本次领用配件
    parts = []
    no = str(order.get("工单号") or "").strip()
    if no:
        for s in read_all(STOCK_DB):
            if str(s.get("关联工单号") or "").strip() == no:
                nm = str(s.get("配件名称") or "").strip()
                if nm:
                    parts.append("%s ×%s%s" % (nm, s.get("数量") or "", s.get("单位") or ""))

    return {
        "sameDev": len(same_dev),
        "samePart": len(same_part),
        "repeat90": repeat90,
        "avgGap": avg_gap,
        "recent": recent,
        "parts": parts,
    }


def _ai_rules(order, hist):
    """规则引擎：按关键词匹配原因/处置/预防"""
    text = " ".join([
        str(order.get("故障描述") or ""),
        str(order.get("故障部位") or ""),
        str(order.get("维修结果") or ""),
        str(order.get("设备名称") or ""),
    ]).lower()

    causes, actions, prevents = [], [], []
    for kws, cause, acts, prev in AI_RULES:
        if any(k.lower() in text for k in kws):
            causes.append(cause)
            actions.extend(acts)
            prevents.append(prev)
            if len(causes) >= 2:
                break

    cat = _opt_text(_order_db(), "故障类别", order.get("故障类别"))
    if not causes:
        g = AI_CAT_GENERIC.get(cat) or AI_CAT_GENERIC["机械"]
        causes = [g[0]]
        actions = [g[1]]
        prevents = [g[2]]

    # 历史维度补充
    if hist["repeat90"] >= 2:
        prevents.append("该设备 90 天内已报修 %d 次（同部位 %d 次），属重复故障，建议安排根因排查或技改，而不是反复换件"
                        % (hist["repeat90"], hist["samePart"]))
    if hist["samePart"] >= 3:
        prevents.append("同部位累计 %d 单，建议核查该部位的选型/工况是否匹配" % hist["samePart"])

    summary = "已结合同设备历史工单与故障关键词给出推断，供维修参考"
    if hist["repeat90"] >= 2:
        summary = "该设备 90 天内已重复报修 %d 次（同部位 %d 次），属重复故障，建议重点做根因排查" % (hist["repeat90"], hist["samePart"])

    return summary, causes[:3], actions[:5], prevents[:4]


def _ai_llm(order, hist):
    ai = CFG.get("ai") or {}
    key = str(ai.get("apiKey") or "").strip()
    if not (ai.get("enabled") and key):
        return None
    base = str(ai.get("baseUrl") or "https://api.openai.com/v1").rstrip("/")
    model = str(ai.get("model") or "gpt-4o-mini")
    ctx = (
        "设备：%s\n部门：%s\n故障部位：%s\n故障类别：%s\n故障描述：%s\n维修结果：%s\n完成人：%s\n"
        "同设备历史工单 %d 单，同部位 %d 单，90 天内重复 %d 次，平均故障间隔 %s 天。\n最近处理：%s\n本次领用配件：%s"
    ) % (
        order.get("设备名称") or "-", order.get("部门") or "-", order.get("故障部位") or "-",
        _opt_text(_order_db(), "故障类别", order.get("故障类别")) or "-",
        order.get("故障描述") or "-", order.get("维修结果") or "-", order.get("完成人") or "-",
        hist["sameDev"], hist["samePart"], hist["repeat90"],
        ("%.1f" % hist["avgGap"]) if hist["avgGap"] else "未知",
        "；".join(hist["recent"]) or "无", "、".join(hist["parts"]) or "无",
    )
    prompt = (
        "你是工厂设备维修专家。根据下面这张已完成的维修工单做故障诊断复盘。\n" + ctx +
        "\n\n只输出 JSON，不要 markdown 代码块，格式："
        '{"summary":"一句话结论","causes":["原因推断1","原因推断2"],'
        '"actions":["后续处置建议1","2"],"prevent":["预防措施1","2"]}'
        "，每条 40 字以内，简体中文，结合历史重复故障给建议。"
    )
    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": "你是严谨的工厂设备维修与预防性维护专家，回答简洁、可执行。"},
            {"role": "user", "content": prompt},
        ],
    }
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            j = json.loads(r.read().decode("utf-8") or "{}")
        txt = (j.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        txt = txt.strip()
        m = re.search(r"\{[\s\S]*\}", txt)
        obj = json.loads(m.group(0) if m else txt)
        if not isinstance(obj, dict) or not obj.get("causes"):
            return None
        return {
            "summary": str(obj.get("summary") or "").strip(),
            "causes": [str(x).strip() for x in (obj.get("causes") or []) if str(x).strip()][:4],
            "actions": [str(x).strip() for x in (obj.get("actions") or []) if str(x).strip()][:6],
            "prevent": [str(x).strip() for x in (obj.get("prevent") or []) if str(x).strip()][:5],
        }
    except Exception as e:
        print("[warn] AI 大模型调用失败，回落规则引擎：", e)
        return None


def _ai_text(order, summary, causes, actions, prevents, hist):
    od = _order_db()
    lines = [
        "【AI 诊断分析】" + time.strftime("%Y-%m-%d %H:%M"),
        "工单：%s ｜ 设备：%s ｜ 部位：%s ｜ 类别：%s" % (
            order.get("工单号") or "-", order.get("设备名称") or "-",
            order.get("故障部位") or "-", _opt_text(od, "故障类别", order.get("故障类别")) or "-"),
        "现象：%s" % (order.get("故障描述") or "-"),
        "",
        "一、原因推断",
    ]
    for i, x in enumerate(causes, 1):
        lines.append("%d. %s" % (i, x))
    lines += ["", "二、处置建议"]
    for i, x in enumerate(actions, 1):
        lines.append("%d. %s" % (i, x))
    lines += ["", "三、预防建议"]
    for i, x in enumerate(prevents, 1):
        lines.append("%d. %s" % (i, x))
    lines += ["", "四、历史参考"]
    lines.append("· 同设备历史 %d 单，同部位 %d 单，90 天内 %d 单" % (hist["sameDev"], hist["samePart"], hist["repeat90"]))
    if hist["avgGap"]:
        lines.append("· 平均故障间隔 %.1f 天" % hist["avgGap"])
    if hist["recent"]:
        lines.append("· 最近处理：" + "；".join(hist["recent"]))
    if hist["parts"]:
        lines.append("· 本次领用：" + "、".join(hist["parts"]))
    return "\n".join(lines)


AI_TUTORIALS = [
    (("轴承", "异响", "噪音", "振动", "抖动", "啸叫"),
     "轴承 / 异响振动 检修教程",
     ["断电挂牌，等设备完全停稳，确认无残余压力或惯性",
      "手动盘车听声音、摸温升，判断异响来自轴承、联轴器还是负载侧",
      "拆防护罩，检查轴承游隙、润滑脂是否发黑干结、密封是否破损",
      "更换轴承：用专用拉马受力在内圈，禁止敲打滚珠；新轴承按型号加注润滑脂（约为空腔 1/3～1/2）",
      "复装后检查联轴器对中（径向/端面偏差 ≤0.05mm），复紧地脚螺栓",
      "空载试机 10 分钟，再带载 30 分钟，测振动与温升（轴承温升 ≤40K）"],
     ["必须断电验电挂牌，禁止带电拆装", "加热安装轴承时温度不超过 120℃，禁止明火直烤", "试机时人员远离旋转部位，防护罩必须复位"]),
    (("电机", "马达", "绕组", "烧", "过热", "发烫", "绝缘"),
     "电机过热 / 烧绕组 检修教程",
     ["断电验电，测三相绕组直流电阻与绝缘电阻（≥0.5MΩ）",
      "检查三相电流是否平衡（偏差 ≤10%），判断是否缺相、过载",
      "清理风扇罩与散热筋积灰，确认风道畅通、风扇完好",
      "检查接线端子有无松动发黑，必要时更换端子并压紧",
      "绝缘不合格或绕组烧损：送修重绕或更换同规格电机",
      "复装后空载试运行，测电流、温升与振动"],
     ["断电验电并放电后再拆线", "禁止用兆欧表测带电回路", "试机时不得触碰接线盒与旋转部件"]),
    (("变频器", "变频", "过流", "过压", "欠压", "故障码", "跳闸"),
     "变频器报警 / 跳闸 处理教程",
     ["记录故障码与运行频率，先断电 5 分钟待母线电容放电",
      "检查散热风扇、滤网与风道，清除粉尘",
      "测量输入电压是否缺相、波动过大，检查电机绝缘",
      "核对电机参数与加减速时间，负载卡滞要先排除机械问题",
      "复位后先空载运行，再逐步带载观察电流",
      "频繁报警时导出参数备份，考虑更换风扇/电容或整机"],
     ["断电后必须等待指示灯全灭再开盖（母线高压）", "禁止带电插拔控制端子", "参数修改前先备份"]),
    (("接触器", "继电器", "空开", "断路器", "触点", "烧黑", "打火"),
     "接触器 / 空开 检修教程",
     ["断电验电挂牌，确认上下桩头无电",
      "检查触点烧蚀、粘连与线圈外观（发黑、异味）",
      "测量线圈阻值与吸合电压，手动按压确认动作顺畅",
      "更换同规格元件，导线按力矩紧固（M4 约 1.2N·m，M6 约 3N·m）",
      "复测绝缘与回路电阻，通电试吸合 3～5 次",
      "带载运行观察有无打火、异响与发热"],
     ["严禁带电作业，电容回路先放电", "必须使用同电压等级、同电流规格的元件", "更换后确认灭弧罩复位"]),
    (("皮带", "链条", "链轮", "打滑", "断裂", "脱链", "跑偏"),
     "皮带 / 链条 更换调整教程",
     ["断电挂牌，松开张紧装置卸载",
      "检查带轮/链轮磨损与平行度，磨损严重需成对更换",
      "装新皮带/链条，禁止用工具硬撬，接头方向按运行方向",
      "按标准张紧：皮带中部下压 10～15mm 为宜，链条留 2%～3% 垂度",
      "手动盘车 2 圈确认无卡阻、无跑偏",
      "空载运行 10 分钟，复查张紧度与跑偏"],
     ["断电挂牌，防止误启动", "更换时戴手套防夹手", "防护罩未复位不得试机"]),
    (("气缸", "气动", "漏气", "气压", "电磁阀", "气管"),
     "气动 / 气缸 漏气处理教程",
     ["关闭气源并泄压至 0，挂牌",
      "用肥皂水逐点查漏：接头、气管、气缸端盖、电磁阀",
      "更换老化气管与快插接头，剪口要平齐、插入到位",
      "拆检气缸更换密封圈，缸筒拉伤需换缸",
      "清理或更换电磁阀，确认线圈电压与阀位动作",
      "通气试动作 5～10 次，检查速度与到位信号"],
     ["泄压后才能拆接头，防止气管甩伤", "禁止用胶带缠漏气接头凑合使用", "调试时手远离夹紧机构"]),
    (("液压", "油压", "漏油", "油缸", "油泵", "油温"),
     "液压系统 压力不足/漏油 教程",
     ["停机泄压，检查油位、油质（发黑乳化需换油）",
      "查渗漏点：油缸密封、管接头、阀块结合面",
      "更换密封件前清理油污，装配时防止划伤密封唇口",
      "清洗或更换吸油/回油滤芯，检查油泵有无异响",
      "补油至标线，排气后空载运行，观察压力表",
      "带载试压至工作压力，保压 10 分钟查压降"],
     ["高压油管禁止用手触摸查漏，用纸板", "泄压后再拆管，防止高压油喷射", "废油集中回收"]),
    (("水泵", "漏水", "水压", "不出水", "堵塞", "流量小"),
     "水泵 不出水/漏水 检修教程",
     ["断电关阀，排空管路余压",
      "检查吸入口是否堵塞、过滤器是否脏堵、管路是否进气",
      "机械密封渗漏：拆泵更换密封，检查轴套磨损",
      "叶轮缠绕异物或磨损严重需清理/更换",
      "复装后先灌泵排气，点动确认转向正确",
      "运行测流量与压力，观察 30 分钟无渗漏"],
     ["断电并关闭进出水阀", "灌泵排气后再启动，禁止干转", "拆泵时注意热水/腐蚀介质防护"]),
    (("传感器", "感应", "限位", "光电", "接近开关", "信号", "失灵", "不准"),
     "传感器 / 限位 失灵排查教程",
     ["确认安全后进入设备，观察传感器指示灯状态",
      "清洁感应面与反光板，清除铁屑、油污、粉尘",
      "校正安装距离（接近开关一般为额定检测距离的 60%～80%）",
      "检查接线端子与电缆有无破皮、进水，屏蔽层单端接地",
      "手动触发验证信号，用万用表测输出或看 PLC 输入点",
      "更换同型号传感器后重新标定位置"],
     ["进入设备内部必须停机挂牌", "禁止短接安全类传感器", "更换前记录原始安装位置"]),
    (("PLC", "程序", "触摸屏", "上位机", "通讯", "通信", "死机", "黑屏"),
     "PLC / 触摸屏 故障排查教程",
     ["确认故障范围：单点、单站还是整线，拍照记录报警",
      "检查供电与接地，测量 24V 电源是否稳定",
      "重启对应模块，观察通讯指示灯",
      "检查通讯线、接头与终端电阻，排除干扰源",
      "对照备份程序核对参数，必要时恢复备份",
      "逐点验证 I/O，确认后恢复生产"],
     ["修改程序前必须备份并做好变更记录", "禁止带电插拔模块", "恢复备份前确认设备处于安全状态"]),
    (("密封", "垫片", "渗漏", "漏液", "漏料", "法兰"),
     "密封 / 法兰 渗漏处理教程",
     ["泄压排空，确认介质温度与危险性",
      "拆卸法兰时对称松开螺栓，防止残余压力喷溅",
      "清理结合面旧垫片与锈蚀，检查平面度与沟槽",
      "按介质选型更换垫片，禁止重复使用旧垫",
      "对角分 2～3 次均匀紧固螺栓至规定力矩",
      "试压/试运行 15 分钟观察渗漏"],
     ["带压带温禁止拆卸", "腐蚀介质需佩戴防护用品", "紧固力矩不得超标"]),
    (("加热", "热电偶", "温控", "不升温", "温度低"),
     "加热 / 温控 异常处理教程",
     ["断电，测加热管电阻（开路即损坏）与绝缘",
      "检查热电偶型号与接线，测毫伏信号是否正常",
      "核对温控表设定值与传感器类型（K/J/PT100）",
      "更换损坏的加热管/热电偶，接线紧固",
      "空载升温观察曲线是否跟随设定值",
      "带料试运行，确认超温保护有效"],
     ["高温部位待冷却后作业", "严禁短接超温保护", "更换元件需匹配电压与功率"]),
    (("卡死", "卡阻", "不动作", "无法启动", "启动不了", "抱死"),
     "设备卡阻 / 无法启动 排查教程",
     ["确认已断电挂牌，手动盘车判断是否机械卡死",
      "检查限位、安全门、急停等安全回路是否满足启动条件",
      "排查异物、变形、导轨缺油与紧固件松脱",
      "清除异物、修复变形部位并补润滑",
      "复位所有保护，点动确认转向与动作",
      "空载连续运行 10 分钟再交生产"],
     ["禁止强行启动力图“顶开”卡阻", "处理前必须断电挂牌", "安全保护不得屏蔽"]),
]

AI_TUT_GENERIC = {
    "机械": ("设备机械故障 通用检修教程",
             ["断电挂牌，观察故障现象并拍照记录", "手动盘车/动作确认卡阻位置", "拆检磨损、松动与润滑状态",
              "更换损坏件、复紧螺栓、补润滑", "空载试机 10 分钟，再带载验证"],
             ["作业前断电挂牌", "拆装使用专用工具", "防护罩复位后再试机"]),
    "电气": ("设备电气故障 通用排查教程",
             ["断电验电，确认无电后作业", "检查电源、空开、接触器与接线端子", "测量电压/电流/绝缘，定位故障回路",
              "更换损坏元件并紧固端子", "送电空载试运行，观察电流与温升"],
             ["严禁带电作业", "验电后再动手", "更换元件规格必须一致"]),
    "结构": ("设备结构故障 通用处理教程",
             ["停机并支撑稳固，确认无坠落风险", "检查变形、裂纹与焊缝", "校正或补强，复紧连接螺栓",
              "检查安全附件与限位", "试运行确认无异常振动"],
             ["高处作业系安全带", "支撑未稳固不得钻入", "焊接作业办理动火票"]),
    "管道": ("管道 / 阀门 通用处理教程",
             ["关闭上下游阀门并泄压", "确认介质性质与温度", "拆检堵塞/渗漏部位",
              "更换管件或密封，按力矩紧固", "试压观察 15 分钟"],
             ["带压带温禁止拆卸", "腐蚀介质做好防护", "试压时人员避开盲板方向"]),
}


def ai_tutorial(order):
    """按故障关键词生成检修教程 + 搜索入口"""
    text = " ".join([
        str(order.get("故障描述") or ""),
        str(order.get("故障部位") or ""),
        str(order.get("设备名称") or ""),
    ]).lower()

    title, steps, safety = "", [], []
    for kws, t, st, sf in AI_TUTORIALS:
        if any(k.lower() in text for k in kws):
            title, steps, safety = t, st, sf
            break
    if not title:
        cat = _opt_text(_order_db(), "故障类别", order.get("故障类别"))
        g = AI_TUT_GENERIC.get(cat) or AI_TUT_GENERIC["机械"]
        title, steps, safety = g

    dev = str(order.get("设备名称") or "").strip()
    part = str(order.get("故障部位") or "").strip()
    desc = str(order.get("故障描述") or "").strip()
    # 搜索词：设备 + 部位 + 现象核心词（去掉标点，截断长度）
    core = re.sub(r"[，。、；：,.;:!?！？\s]+", " ", desc)[:36].strip()
    kw = " ".join([x for x in [dev, part, core, "维修"] if x]).strip()
    if len(kw) > 60:
        kw = kw[:60]
    q = urllib.parse.quote(kw)
    links = [
        {"name": "百度", "url": "https://www.baidu.com/s?wd=" + q},
        {"name": "B 站视频", "url": "https://search.bilibili.com/all?keyword=" + q},
        {"name": "抖音", "url": "https://www.douyin.com/search/" + q},
        {"name": "必应", "url": "https://cn.bing.com/search?q=" + q},
    ]
    return {
        "title": title,
        "keywords": kw,
        "steps": steps,
        "safety": safety,
        "links": links,
        "engine": "rule",
        "engineText": "内置检修教程库",
    }


def ai_analyze(order):
    hist = _ai_gather(order)
    llm = _ai_llm(order, hist)
    if llm:
        engine, engine_text = "llm", "AI 大模型"
        summary = llm["summary"] or "分析完成"
        causes, actions, prevents = llm["causes"], llm["actions"], llm["prevent"]
    else:
        engine, engine_text = "rule", "本地规则引擎（结合历史工单）"
        summary, causes, actions, prevents = _ai_rules(order, hist)
    text = _ai_text(order, summary, causes, actions, prevents, hist)
    return {
        "engine": engine,
        "engineText": engine_text,
        "summary": summary,
        "causes": causes,
        "actions": actions,
        "prevent": prevents,
        "history": {
            "sameDev": hist["sameDev"],
            "samePart": hist["samePart"],
            "repeat90": hist["repeat90"],
            "avgGap": round(hist["avgGap"], 1) if hist["avgGap"] else None,
            "recent": hist["recent"],
            "parts": hist["parts"],
        },
        "text": text,
    }


# ---------------------------------------------------------------- HTTP

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
}

_login_fail = {}


class Handler(BaseHTTPRequestHandler):
    server_version = "RepairSelfHost/1.0"
    protocol_version = "HTTP/1.1"

    # ---------- 基础 ----------
    def log_message(self, fmt, *args):
        sys.stdout.write("%s  %s\n" % (self.log_date_time_string(), fmt % args))
        sys.stdout.flush()

    def _send(self, code, body=b"", ctype="application/json; charset=utf-8", extra=None, cache=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", cache or "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        # 超过 900 字节且客户端支持时压缩：首页 222KB → 约 45KB
        if len(body) > 900 and "gzip" in (self.headers.get("Accept-Encoding") or "").lower():
            body = gzip.compress(body, 6)
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200, extra=None):
        self._send(code, json.dumps(obj, ensure_ascii=False), extra=extra)

    def _read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > 8 * 1024 * 1024:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _cookie(self, name):
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                if k.strip() == name:
                    return v.strip()
        return None

    def _session(self):
        return get_session(self._cookie("rs_token"))

    def _need_login(self):
        self._json({"error": "not login"}, 401)
        return None

    def _is_https(self):
        return isinstance(self.connection, ssl.SSLSocket) or \
            (self.headers.get("X-Forwarded-Proto") or "").lower() == "https"

    # ---------- 路由 ----------
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/health":
            with conn() as c:
                n = c.execute("SELECT COUNT(*) AS n FROM records").fetchone()["n"]
            return self._json({"ok": True, "service": "repair-selfhost", "records": n})
        if path == "/api/session":
            s = self._session()
            if not s:
                return self._json({"error": "not login"}, 401)
            s["rateOk"] = rate_allowed(s)
            return self._json(s)
        if path == "/api/schema":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            dbid = (q.get("databaseId") or [""])[0]
            info = _schema.get(dbid)
            if not info:
                return self._json({"properties": []})
            return self._json({"databaseId": dbid, "name": info.get("name", ""), "properties": info.get("properties", [])})
        return self._serve_static(path)

    def do_HEAD(self):
        return self.do_GET()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        body = self._read_body()

        if path == "/api/login":
            return self._login(body)
        if path == "/api/admin/check":
            # 评分权限管理等管理操作的密码校验；通过后本机获得评分可见/可评权限
            want = str(CFG.get("adminPw") or "").strip()
            got = str(body.get("pw") or "").strip()
            if not want:
                return self._json({"error": "服务端未设置管理密码（config.json 里加 adminPw）"}, 400)
            if got != want:
                return self._json({"error": "管理密码不对"}, 401)
            s = self._session()
            if s:
                tok = self._cookie("rs_token")
                with conn() as c:
                    c.execute("UPDATE sessions SET rate_ok=1 WHERE token=?", (tok,))
            return self._json({"ok": True, "rateOk": True})
        if path == "/api/admin/rate-lock":
            # 取消本机的评分可见/可评权限（只影响这台设备）
            tok = self._cookie("rs_token")
            if tok:
                with conn() as c:
                    c.execute("UPDATE sessions SET rate_ok=0 WHERE token=?", (tok,))
            return self._json({"ok": True, "rateOk": False})
        if path == "/api/logout":
            tok = self._cookie("rs_token")
            if tok:
                with conn() as c:
                    c.execute("DELETE FROM sessions WHERE token=?", (tok,))
            return self._json({"ok": True}, extra={"Set-Cookie": "rs_token=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"})

        if not path.startswith("/api/"):
            return self._json({"error": "not found"}, 404)

        if path == "/api/wecom/push":
            s = self._session()
            if not s:
                return self._need_login()
            return self._wecom(body)

        s = self._session()
        if not s:
            return self._need_login()

        if path == "/api/db/query":
            return self._query(body, s)
        if path == "/api/db/add":
            return self._add(body, s)
        if path == "/api/db/update":
            return self._update(body, s)
        if path == "/api/db/delete":
            return self._delete(body)
        if path == "/api/ai/analyze":
            return self._ai_analyze(body)
        if path == "/api/ai/tutorial":
            return self._ai_tutorial(body)
        return self._json({"error": "not found"}, 404)

    # ---------- AI 搜索教程 ----------
    def _ai_tutorial(self, body):
        rid = str(body.get("recordId") or "").strip()
        if not rid:
            return self._json({"ok": False, "error": "recordId 缺失"}, 400)
        od = _order_db()
        with conn() as c:
            row = c.execute("SELECT data FROM records WHERE id=? AND db=?", (rid, od)).fetchone()
            if not row:
                return self._json({"ok": False, "error": "工单不存在"}, 404)
            order = json.loads(row["data"])
            order["_id"] = rid
        try:
            res = ai_tutorial(order)
        except Exception as e:
            print("[warn] 教程生成失败：", e)
            return self._json({"ok": False, "error": "生成失败：%s" % e}, 500)
        res["ok"] = True
        return self._json(res)

    # ---------- AI 诊断分析 ----------
    def _ai_analyze(self, body):
        rid = str(body.get("recordId") or "").strip()
        if not rid:
            return self._json({"ok": False, "error": "recordId 缺失"}, 400)
        od = _order_db()
        with conn() as c:
            row = c.execute("SELECT data FROM records WHERE id=? AND db=?", (rid, od)).fetchone()
            if not row:
                return self._json({"ok": False, "error": "工单不存在"}, 404)
            order = json.loads(row["data"])
            order["_id"] = rid
        try:
            res = ai_analyze(order)
        except Exception as e:
            print("[warn] AI 分析失败：", e)
            return self._json({"ok": False, "error": "分析失败：%s" % e}, 500)
        # 结果写回工单，换台手机也能看到
        try:
            props = {p.get("name"): p for p in (_schema.get(od) or {}).get("properties", [])}
            if "AI分析" in props:
                order["AI分析"] = res["text"]
                order.pop("_id", None)
                now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                with conn() as c:
                    c.execute("UPDATE records SET data=?, updated_at=? WHERE id=? AND db=?",
                              (json.dumps(order, ensure_ascii=False), now, rid, od))
        except Exception as e:
            print("[warn] AI 分析写回失败：", e)
        res["ok"] = True
        return self._json(res)

    # ---------- 登录 ----------
    def _login(self, body):
        emp = str(body.get("emp") or "").strip()
        pw = str(body.get("pw") or "").strip()
        ip = self.client_address[0]
        now = time.time()
        hits = [t for t in _login_fail.get(ip, []) if now - t < 600]
        if len(hits) >= 30:
            return self._json({"error": "尝试次数过多，请 10 分钟后再试"}, 429)
        if not emp or not pw:
            return self._json({"error": "请填工号和密码"}, 400)
        m = find_member(emp)
        if not m:
            # 未在排班表中的工号：openLogin 为真且形如工号时放行（全员可报修）
            if CFG.get("openLogin", True) and re.fullmatch(r"\d{4,12}", emp):
                m = {"emp": emp, "name": "", "job": ""}
            else:
                _login_fail[ip] = hits + [now]
                return self._json({"error": "工号 " + emp + " 不存在，请联系管理员"}, 400)
        if pw != emp[-4:]:
            _login_fail[ip] = hits + [now]
            return self._json({"error": "密码不对：请填工号的后四位"}, 400)
        token = secrets.token_hex(24)
        days = int(CFG.get("sessionDays") or 30)
        exp = int(now) + days * 86400
        with conn() as c:
            c.execute("INSERT INTO sessions(token,emp,name,job,exp) VALUES(?,?,?,?,?)",
                      (token, m["emp"], m["name"], m["job"], exp))
        _login_fail.pop(ip, None)
        ck = "rs_token=%s; Path=/; Max-Age=%d; HttpOnly; SameSite=Lax" % (token, days * 86400)
        if self._is_https():
            ck += "; Secure"
        return self._json({"ok": True, "emp": m["emp"], "name": m["name"], "job": m["job"]}, extra={"Set-Cookie": ck})

    # ---------- 数据 ----------
    def _query(self, body, sess=None):
        dbid = str(body.get("databaseId") or "")
        if not dbid:
            return self._json({"results": [], "hasMore": False, "nextCursor": None})
        # 评分数据与评分名单：没有权限的人，服务端直接不给（不是前端藏起来）
        if not rate_allowed(sess):
            if dbid == _order_db():
                rows = [{k: v for k, v in r.items() if k not in RATE_FIELDS} for r in read_all(dbid)]
            elif dbid == RATE_AUTH_DB:
                rows = []
            else:
                rows = read_all(dbid)
        else:
            rows = read_all(dbid)
        for s in reversed(body.get("sorts") or []):
            prop = s.get("property")
            desc = (s.get("direction") or "ascending") == "descending"
            rows.sort(key=lambda r: sort_key(r.get(prop)), reverse=desc)
        try:
            off = int(body.get("startCursor") or 0)
        except Exception:
            off = 0
        try:
            size = int(body.get("pageSize") or 100)
        except Exception:
            size = 100
        size = max(1, min(size, 500))
        page = rows[off:off + size]
        more = (off + size) < len(rows)
        return self._json({
            "results": page,
            "hasMore": more,
            "nextCursor": str(off + size) if more else None,
        })

    def _add(self, body, sess):
        dbid = str(body.get("databaseId") or "")
        if not dbid:
            return self._json({"error": "databaseId 缺失"}, 400)
        props = {p.get("name"): p for p in (_schema.get(dbid, {}) or {}).get("properties", [])}
        data = {}
        for k, v in (body.get("properties") or {}).items():
            data[k] = norm_value(props.get(k), unwrap(v))
        rid = secrets.token_hex(12)
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with conn() as c:
            c.execute("INSERT INTO records(id,db,data,created_at,updated_at) VALUES(?,?,?,?,?)",
                      (rid, dbid, json.dumps(data, ensure_ascii=False), now, now))
        return self._json({"id": rid})

    def _update(self, body, sess=None):
        dbid = str(body.get("databaseId") or "")
        rid = str(body.get("recordId") or "")
        if not dbid or not rid:
            return self._json({"error": "databaseId / recordId 缺失"}, 400)
        props_in = body.get("properties") or {}
        if dbid == _order_db() and any(k in props_in for k in RATE_FIELDS) and not rate_allowed(sess):
            return self._json({"error": "没有评分权限"}, 403)
        props = {p.get("name"): p for p in (_schema.get(dbid, {}) or {}).get("properties", [])}
        with conn() as c:
            row = c.execute("SELECT data FROM records WHERE id=? AND db=?", (rid, dbid)).fetchone()
            if not row:
                return self._json({"error": "记录不存在"}, 404)
            old = json.loads(row["data"])
            for k, v in props_in.items():
                old[k] = norm_value(props.get(k), unwrap(v))
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            c.execute("UPDATE records SET data=?, updated_at=? WHERE id=? AND db=?",
                      (json.dumps(old, ensure_ascii=False), now, rid, dbid))
        return self._json({"id": rid})

    def _delete(self, body):
        dbid = str(body.get("databaseId") or "")
        rid = str(body.get("recordId") or "")
        with conn() as c:
            c.execute("DELETE FROM records WHERE id=? AND db=?", (rid, dbid))
        return self._json({"ok": True})

    # ---------- 企微推送 ----------
    def _wecom(self, body):
        key = str((CFG.get("wecom") or {}).get("webhookKey") or "").strip()
        if not key:
            return self._json({"ok": False, "error": "服务端未配置企微机器人 key"}, 400)
        msg = body.get("msg") or body
        payload = json.dumps(msg, ensure_ascii=False).encode("utf-8")
        url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=" + urllib.parse.quote(key)
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=12) as r:
                j = json.loads(r.read().decode("utf-8") or "{}")
        except Exception as e:
            return self._json({"ok": False, "error": "企微接口不可达：%s" % e}, 502)
        if j.get("errcode") == 0:
            return self._json({"ok": True, "wecom": j})
        return self._json({"ok": False, "error": j.get("errmsg") or "企微返回错误", "wecom": j}, 502)

    # ---------- 静态文件 ----------
    def _serve_static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        rel = urllib.parse.unquote(path).lstrip("/")
        if ".." in rel or rel.startswith("/"):
            return self._send(403, "forbidden", "text/plain; charset=utf-8")
        f = (STATIC / rel).resolve()
        if not str(f).startswith(str(STATIC.resolve())) or not f.is_file():
            f = STATIC / "index.html"
            if not f.is_file():
                return self._send(404, "页面未构建，请先运行 python3 build_page.py", "text/plain; charset=utf-8")
        ct = MIME.get(f.suffix.lower(), "application/octet-stream")
        data = f.read_bytes()
        etag = '"%x-%x"' % (int(f.stat().st_mtime), len(data))
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            return
        self._send(200, data, ct, extra={"ETag": etag}, cache="no-cache")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()

    load_config()
    load_schema()
    init_db()

    port = args.port or int(CFG.get("port") or 8080)
    httpd = ThreadingHTTPServer((args.host, port), Handler)
    httpd.daemon_threads = True

    tls = CFG.get("tls") or {}
    scheme = "http"
    if tls.get("cert") and tls.get("key"):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(BASE / tls["cert"]), str(BASE / tls["key"]))
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        scheme = "https"

    print("=" * 56)
    print(" 设备快速报修 · 自托管服务已启动")
    print(" 地址：%s://%s:%d/" % (scheme, args.host, port))
    print(" 数据：%s" % DB_PATH)
    print(" 机器人：%s" % ("已配置" if (CFG.get("wecom") or {}).get("webhookKey") else "未配置（config.json 里填 webhookKey）"))
    print("=" * 56)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()

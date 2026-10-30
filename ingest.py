"""把各平台抓到的原始数据写进 data/videos.db（SQLite），再导出看板用的 dashboard/data.js。

数据结构是「一个作品，多次发布」：同一条视频发到小红书、抖音、视频号，是同一个 work 下的三条 post。
每次运行往 snapshots 追加一行快照（看增长）；留存、来源、画像、趋势只留最新一份。
比率一律存成百分数（10 表示 10%）。
"""
import json
import re
import sqlite3
import statistics
import time
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
DB = ROOT / "data" / "videos.db"
# 自动配对配错时在这里改：{"douyin:7700...": "xhs:6add..."} 把一条发布并到另一条所在的作品
OVERRIDE = ROOT / "data" / "works_override.json"

PLATFORMS = {"xhs": "小红书", "douyin": "抖音", "channels": "视频号"}
SNAP_COLS = ["impressions", "views", "cover_click_rate", "likes", "comments", "collects", "shares", "new_fans",
             "avg_view_sec", "finish_rate", "finish5s_rate", "exit2s_rate", "profile_visits"]

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS posts (platform TEXT, post_id TEXT, title TEXT, post_time INTEGER, duration_sec REAL, tags TEXT,
  PRIMARY KEY (platform, post_id));
CREATE TABLE IF NOT EXISTS snapshots (platform TEXT, post_id TEXT, fetched_at INTEGER, {", ".join(c + " REAL" for c in SNAP_COLS)},
  PRIMARY KEY (platform, post_id, fetched_at));
CREATE TABLE IF NOT EXISTS retention (platform TEXT, post_id TEXT, series TEXT, sec INTEGER, pct REAL, PRIMARY KEY (platform, post_id, series, sec));
CREATE TABLE IF NOT EXISTS traffic_source (platform TEXT, post_id TEXT, source TEXT, share_pct REAL, PRIMARY KEY (platform, post_id, source));
CREATE TABLE IF NOT EXISTS audience (platform TEXT, post_id TEXT, dim TEXT, label TEXT, pct REAL, PRIMARY KEY (platform, post_id, dim, label));
CREATE TABLE IF NOT EXISTS trend (platform TEXT, post_id TEXT, grain TEXT, metric TEXT, ts INTEGER, value REAL, PRIMARY KEY (platform, post_id, grain, metric, ts));
"""

DOUYIN_SOURCE = {"homepage_hot": "推荐", "search": "搜索", "homepage": "个人主页", "message": "私信消息", "familiar": "朋友",
                 "yumme_vv_all": "抖音精选", "follow": "关注", "other": "其他"}
DOUYIN_GENDER = {"female": "女性", "male": "男性"}
CHANNELS_SOURCE = {3: "关注", 4: "推荐", 6: "分享", 20: "主页", 8: "朋友♡", 16: "订阅号消息", 15: "PC微信", 25: "看一看", 0: "其他"}


def num(v, scale=1):
    # 平台对还没出数据的指标返回 -1 或空
    if v is None or v == "" or v == -1:
        return None
    return float(v) * scale


def load(p):
    return json.loads(p.read_text())


def migrate(con):
    # 旧版只有小红书、snapshots 没有 platform 列：改名保留，下面把历史快照搬进新表
    cols = [r[1] for r in con.execute("PRAGMA table_info(snapshots)")]
    if cols and "platform" not in cols:
        for t in ("notes", "snapshots", "retention", "traffic_source", "audience", "trend"):
            con.execute(f"ALTER TABLE {t} RENAME TO v1_{t}")
        con.executescript(SCHEMA)
        con.execute("""INSERT INTO snapshots (platform, post_id, fetched_at, impressions, views, cover_click_rate, likes, comments, collects,
                         shares, new_fans, avg_view_sec, finish_rate, finish5s_rate, exit2s_rate)
                       SELECT 'xhs', s.note_id, s.fetched_at, impressions, views, cover_click_rate, likes, comments, collects, shares, new_fans,
                         avg_view_sec, finish_rate, finish5s_rate, exit2s_rate FROM v1_snapshots s JOIN v1_notes n USING (note_id) WHERE n.type = 2""")


def put_post(con, p, pid, title, post_time, duration, tags, snap, fetched_at, retention=(), benchmark=(), sources=(), audience=None, trends=()):
    con.execute("INSERT OR REPLACE INTO posts VALUES (?,?,?,?,?,?)", (p, pid, title, post_time, duration, tags))
    con.execute(f"INSERT OR REPLACE INTO snapshots VALUES (?,?,?,{','.join('?' * len(SNAP_COLS))})",
                (p, pid, fetched_at, *[snap.get(c) for c in SNAP_COLS]))
    # 这次没抓到的部分（页面偶尔没加载完）保留上次的，不清空
    for t, rows in (("retention", retention), ("traffic_source", sources), ("audience", audience), ("trend", trends)):
        if rows:
            con.execute(f"DELETE FROM {t} WHERE platform=? AND post_id=?", (p, pid))
    con.executemany("INSERT OR REPLACE INTO retention VALUES (?,?,?,?,?)",
                    [(p, pid, "self", s, v) for s, v in retention] + [(p, pid, "benchmark", s, v) for s, v in benchmark])
    con.executemany("INSERT OR REPLACE INTO traffic_source VALUES (?,?,?,?)", [(p, pid, s, v) for s, v in sources if v is not None])
    for dim, rows in (audience or {}).items():
        con.executemany("INSERT OR REPLACE INTO audience VALUES (?,?,?,?,?)", [(p, pid, dim, l, v) for l, v in rows])
    con.executemany("INSERT OR REPLACE INTO trend VALUES (?,?,?,?,?,?)", [(p, pid, *t) for t in trends])


def at(ret, sec):
    return next((v for s, v in ret if s == sec), None)


def ingest_xhs(con):
    f = RAW / "_list.json"
    if not f.exists():
        return
    lst = load(f)
    for n in lst["notes"]:
        raw = RAW / f"{n['id']}.json"
        if n["type"] != 2 or not raw.exists():  # 只要视频笔记
            continue
        d = load(raw)
        b = d["base"]["data"]
        g = lambda k: num(b.get(k))
        tr = d["analyze_audience_trend"]["data"]
        ret = [(x["date"], x["count"]) for x in tr.get("trend_list") or []]
        det = d["audience_source_detail"]["data"]
        info = b.get("note_info") or {}
        put_post(con, "xhs", n["id"], n["title"], n["post_time"], ret[-1][0] if ret else None,
                 ",".join(t["name"] for t in info.get("tags", [])),
                 {"impressions": g("impl_count"), "views": g("view_count"), "cover_click_rate": g("cover_click_rate"), "likes": g("like_count"),
                  "comments": g("comment_count"), "collects": g("collect_count"), "shares": g("share_count"), "new_fans": g("rise_fans_count"),
                  "avg_view_sec": g("view_time_avg_with_double"), "finish_rate": g("full_view_rate"), "finish5s_rate": g("finish5s_rate"),
                  "exit2s_rate": g("exit_view2s_rate")},
                 lst["fetchedAt"], retention=ret,
                 sources=[(s["title"], s.get("value_with_double")) for s in d["audience_source"]["data"].get("source") or []],
                 audience={dim: [(x["title"], x["value"]) for x in det.get(dim) or []] for dim in ("gender", "age", "city", "interest")},
                 trends=[("hour", "views", x["date"], x.get("count_with_double", x["count"])) for x in (b.get("hour") or {}).get("view_list", [])])


def ingest_douyin(con):
    f = RAW / "douyin" / "_list.json"
    if not f.exists():
        return
    lst = load(f)
    for it in lst["items"]:
        raw = RAW / "douyin" / f"{it['id']}.json"
        if not raw.exists():
            continue
        d = load(raw)
        s = (d.get("item_summarize") or {}).get("item_list", [{}])[0]
        st, sd = s.get("statistics") or {}, s.get("summarize_data") or {}
        an = (d.get("analysis_data_center") or {}).get("analysis_trend") or {}
        mmss = lambda k: int(k.split(":")[0]) * 60 + int(k.split(":")[1])
        ret = [(mmss(x["key"]), x["value"] * 100) for x in an.get("current_item") or []]
        bench = [(mmss(x["key"]), x["value"] * 100) for x in an.get("similar_author") or []]
        p = d.get("item_portrait") or {}
        ratio = lambda k: (p.get(k) or {}).get("ratio_list") or []
        top = lambda rows, n=8: sorted(rows, key=lambda x: -x[1])[:n]
        subs = ((d.get("trend_subscribe_count_1") or {}).get("trend_map") or {}).get("subscribe_count", {}).get("0", [])
        hours = ((d.get("trend_view_count_2") or {}).get("trend_map") or {}).get("view_count", {}).get("0", [])
        ts = lambda t: int(time.mktime(time.strptime(t, "%Y-%m-%d %H:%M:%S")) * 1000)
        r2, r5 = at(ret, 2), at(ret, 5)
        put_post(con, "douyin", it["id"], it["description"], int(it["create_time"]) * 1000, num(it["video_info"]["duration"], 0.001),
                 ",".join(c["cha_name"] for c in s.get("cha_list") or []),
                 {"views": num(st.get("play_count")),
                  # 新作品偶尔返回大于 1 的点击率（数据未就绪），当作没有
                  "cover_click_rate": num(sd.get("cover_click_ratio"), 100) if (sd.get("cover_click_ratio") or 0) <= 1 else None, "likes": num(st.get("digg_count")),
                  "comments": num(st.get("comment_count")), "collects": num(st.get("collect_count")), "shares": num(st.get("share_count")),
                  "new_fans": num(sd.get("new_fans_count")), "avg_view_sec": num(sd.get("play_avg_time")),
                  "finish_rate": num(sd.get("play_finish_ratio"), 100), "profile_visits": num(sd.get("home_page_view_count")),
                  # 后台的 5s 完播率 / 2s 跳出率就是留存曲线上第 5 秒、第 2 秒的值
                  "finish5s_rate": r5, "exit2s_rate": None if r2 is None else 100 - r2},
                 d["fetchedAt"], retention=ret, benchmark=bench,
                 sources=[(DOUYIN_SOURCE.get(x["key"], x["key"]), x["value"] * 100) for x in (d.get("play_source") or {}).get("play_source") or []],
                 audience={"gender": [(DOUYIN_GENDER.get(x["key"], x["key"]), x["value"] * 100) for x in ratio("gender")],
                           "age": [(x["key"], x["value"] * 100) for x in ratio("age")],
                           "city": top([(x["key"], x["value"] * 100) for x in ratio("province")])},
                 trends=[("hour", "views", ts(x["date_time"]), float(x["value"])) for x in hours]
                        + [("day", "new_fans", ts(x["date_time"]), float(x["value"])) for x in subs])


def ingest_channels(con):
    f = RAW / "channels" / "_list.json"
    if not f.exists():
        return
    lst = load(f)
    for it in lst["list"]:
        raw = RAW / "channels" / f"{it['objectId']}.json"
        d = load(raw) if raw.exists() else {}
        ret = [(x["sec"], x["rate"] * 100) for x in (d.get("lost_rate") or {}).get("items") or []]
        fd = ((d.get("by_source") or {}).get("feedData") or [{}])[0]
        src = [(CHANNELS_SOURCE.get(x["tabType"], str(x["tabType"])), sum(map(float, x["data"]["browse"]))) for x in fd.get("dataByTabtype") or []]
        total = sum(v for _, v in src) or None
        daily = (fd.get("totalData") or {}).get("browse") or []
        start = d.get("by_source_start")
        media = (it.get("desc") or {}).get("media") or [{}]
        put_post(con, "channels", it["objectId"], (it.get("desc") or {}).get("description", ""), it["createTime"] * 1000, num(media[0].get("videoPlayLen")),
                 "",
                 {"views": num(it.get("readCount")), "likes": (num(it.get("likeCount")) or 0) + (num(it.get("favCount")) or 0),
                  "comments": num(it.get("commentCount")), "shares": num(it.get("forwardCount")), "new_fans": num(it.get("followCount")),
                  "avg_view_sec": num(it.get("avgPlayTimeSec")), "finish_rate": num(it.get("fullPlayRate"), 100),
                  # 视频号的「快速划走率」放在 2s 跳出率这一栏，看板上会标注口径不同
                  "exit2s_rate": num(it.get("fastFlipRate"), 100)},
                 lst["fetchedAt"], retention=ret,
                 sources=[(k, v / total * 100) for k, v in src] if total else [],
                 trends=[("day", "views", (start + i * 86400) * 1000, float(v)) for i, v in enumerate(daily)] if start else [])


def norm_title(t):
    t = re.sub(r"#\S+|\[[^\]]*\]|@\S+", "", t or "")
    return re.sub(r"[^\w一-鿿]", "", t).lower()


def group_works(posts):
    """同一条视频在各平台的发布配成一个作品：发布时间相差 4 天内、去掉话题后的标题相似，或时长几乎一样。"""
    override = load(OVERRIDE) if OVERRIDE.exists() else {}
    key = lambda p: f"{p['platform']}:{p['post_id']}"
    works = []
    for p in sorted(posts, key=lambda p: p["post_time"]):
        if key(p) in override:
            target = override[key(p)]
            w = next((w for w in works if any(key(x) == target for x in w)), None)
            if w is not None:
                w.append(p)
                continue
        best, score = None, 0.0
        for w in works:
            if any(x["platform"] == p["platform"] for x in w) or abs(w[0]["post_time"] - p["post_time"]) > 4 * 86400 * 1000:
                continue
            sim = max(SequenceMatcher(None, norm_title(x["title"]), norm_title(p["title"])).ratio() for x in w)
            if p["duration_sec"] and any(x["duration_sec"] and abs(x["duration_sec"] - p["duration_sec"]) <= 2 for x in w):
                sim = max(sim, 0.6)
            if sim > score:
                best, score = w, sim
        (best.append(p) if best is not None and score >= 0.35 else works.append([p]))
    return works


def export(con):
    con.row_factory = sqlite3.Row
    q = lambda sql, *a: [dict(r) for r in con.execute(sql, a)]
    posts = q("SELECT * FROM posts")
    for p in posts:
        k = (p["platform"], p["post_id"])
        p["latest"] = (q("SELECT * FROM snapshots WHERE platform=? AND post_id=? ORDER BY fetched_at DESC LIMIT 1", *k) or [{}])[0]
        p["history"] = q("SELECT fetched_at, views, new_fans FROM snapshots WHERE platform=? AND post_id=? ORDER BY fetched_at", *k)
        rets = q("SELECT series, sec, pct FROM retention WHERE platform=? AND post_id=? ORDER BY sec", *k)
        p["retention"] = [[r["sec"], r["pct"]] for r in rets if r["series"] == "self"]
        p["benchmark"] = [[r["sec"], r["pct"]] for r in rets if r["series"] == "benchmark"]
        p["sources"] = [[r["source"], r["share_pct"]] for r in q("SELECT source, share_pct FROM traffic_source WHERE platform=? AND post_id=? ORDER BY share_pct DESC", *k)]
        p["audience"] = {}
        for r in q("SELECT dim, label, pct FROM audience WHERE platform=? AND post_id=?", *k):
            p["audience"].setdefault(r["dim"], []).append([r["label"], r["pct"]])
        p["trend"] = {}
        for r in q("SELECT grain, metric, ts, value FROM trend WHERE platform=? AND post_id=? ORDER BY ts", *k):
            p["trend"].setdefault(f"{r['grain']}_{r['metric']}", []).append([r["ts"], r["value"]])
        L = p["latest"]
        inter = sum(L.get(c) or 0 for c in ("likes", "comments", "collects", "shares"))
        p["derived"] = {
            "interaction_rate": inter / L["views"] * 100 if L.get("views") else None,
            "share_rate": (L.get("shares") or 0) / L["views"] * 100 if L.get("views") else None,
            "fans_per_k": (L.get("new_fans") or 0) / L["views"] * 1000 if L.get("views") and L.get("new_fans") is not None else None,
            "view_ratio": L["avg_view_sec"] / p["duration_sec"] * 100 if L.get("avg_view_sec") and p.get("duration_sec") else None,
        }
    # 每个指标和同平台自己的中位数比：1.2 = 比平时高 20%。同平台不到 3 条就不比
    metrics = ["views", "cover_click_rate", "finish5s_rate", "exit2s_rate", "finish_rate", "new_fans"]
    dmetrics = ["interaction_rate", "share_rate", "fans_per_k", "view_ratio"]
    val = lambda p, m: p["latest"].get(m) if m in metrics else p["derived"].get(m)
    baseline = {}
    for pf in PLATFORMS:
        group = [p for p in posts if p["platform"] == pf]
        for m in metrics + dmetrics:
            vals = [val(p, m) for p in group if val(p, m)]
            baseline[f"{pf}.{m}"] = statistics.median(vals) if len(vals) >= 3 else None
    for p in posts:
        p["rel"] = {m: (val(p, m) / baseline[f"{p['platform']}.{m}"]) if val(p, m) is not None and baseline[f"{p['platform']}.{m}"] else None
                    for m in metrics + dmetrics}
    works = []
    for w in group_works(posts):
        w.sort(key=lambda p: list(PLATFORMS).index(p["platform"]))
        lead = min(w, key=lambda p: p["post_time"])
        works.append({"work_id": f"{lead['platform']}:{lead['post_id']}", "title": lead["title"], "first_post_time": lead["post_time"],
                      "duration_sec": next((p["duration_sec"] for p in w if p["duration_sec"]), None),
                      "total_views": sum(p["latest"].get("views") or 0 for p in w), "total_new_fans": sum(p["latest"].get("new_fans") or 0 for p in w),
                      "posts": w})
    works.sort(key=lambda w: -w["first_post_time"])
    out = {"generated_at": int(time.time() * 1000), "platforms": PLATFORMS, "baseline": baseline, "works": works}
    (ROOT / "dashboard").mkdir(exist_ok=True)
    (ROOT / "dashboard" / "data.js").write_text("window.VIDEO_DATA = " + json.dumps(out, ensure_ascii=False) + ";\n")
    # 上传到网站数据库用的同一份数据（update.sh 读它）
    (ROOT / "data" / "video_data.json").write_text(json.dumps(out, ensure_ascii=False))
    return out


if __name__ == "__main__":
    con = sqlite3.connect(DB)
    with con:
        migrate(con)
        con.executescript(SCHEMA)
        ingest_xhs(con)
        ingest_douyin(con)
        ingest_channels(con)
    out = export(con)
    posts = [p for w in out["works"] for p in w["posts"]]
    assert posts and all(p["platform"] in PLATFORMS for p in posts)
    # 自检：同一个作品里每个平台最多一条
    assert all(len({p["platform"] for p in w["posts"]}) == len(w["posts"]) for w in out["works"])
    print(f"写入 {DB.name}: {len(out['works'])} 个作品，{len(posts)} 条发布（" +
          "，".join(f"{n} {sum(p['platform'] == k for p in posts)}" for k, n in PLATFORMS.items()) + "）")

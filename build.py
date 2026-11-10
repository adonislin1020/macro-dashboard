#!/usr/bin/env python3
"""台美總經儀表板：抓資料 → 產生 docs/index.html。

用法：
    python build.py            抓最新資料並產生網頁
    python build.py --offline  不連網，只用 data/cache.json 重新產生網頁（改版面時用）

每個資料來源各自獨立：其中一個抓不到，就沿用 data/cache.json 裡上次成功的資料，
並在網頁最下方列出這次沒更新到的項目。
"""
import csv
import html
import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
CACHE = ROOT / "data" / "cache.json"
MANUAL = ROOT / "data" / "manual.json"
OUT = ROOT / "docs" / "index.html"
TPE = timezone(timedelta(hours=8))
UA = {"User-Agent": "Mozilla/5.0 (macro-dashboard; educational project)"}

# (id, Yahoo 代號, 顯示名稱, 分組, 單位, 小數位)
QUOTES = [
    ("taiex", "^TWII", "加權指數", "idx_tw", "", 2),
    ("otc", "^TWOII", "櫃買指數", "idx_tw", "", 2),
    ("tsmc", "2330.TW", "台積電", "idx_tw", "", 0),
    ("dji", "^DJI", "道瓊工業", "idx_us", "", 0),
    ("spx", "^GSPC", "S&P 500", "idx_us", "", 2),
    ("ixic", "^IXIC", "那斯達克", "idx_us", "", 2),
    ("sox", "^SOX", "費城半導體", "idx_us", "", 2),
    ("rut", "^RUT", "羅素 2000", "idx_us", "", 2),
    ("vix", "^VIX", "VIX 恐慌指數", "idx_us", "", 2),
    ("usdtwd", "TWD=X", "美元／新台幣", "fx", "", 3),
    ("dxy", "DX-Y.NYB", "美元指數 DXY", "fx", "", 2),
    ("usdjpy", "JPY=X", "美元／日圓", "fx", "", 2),
    ("eurusd", "EURUSD=X", "歐元／美元", "fx", "", 4),
    ("usdcny", "CNY=X", "美元／人民幣", "fx", "", 4),
    ("wti", "CL=F", "WTI 原油", "能源", "美元/桶", 2),
    ("brent", "BZ=F", "布蘭特原油", "能源", "美元/桶", 2),
    ("ng", "NG=F", "天然氣", "能源", "美元/MMBtu", 3),
    ("gold", "GC=F", "黃金", "金屬", "美元/盎司", 1),
    ("silver", "SI=F", "白銀", "金屬", "美元/盎司", 2),
    ("copper", "HG=F", "銅", "金屬", "美元/磅", 3),
    ("wheat", "ZW=F", "小麥", "農產品", "美分/英斗", 2),
    ("soy", "ZS=F", "黃豆", "農產品", "美分/英斗", 2),
    ("corn", "ZC=F", "玉米", "農產品", "美分/英斗", 2),
    ("XLK", "XLK", "資訊科技", "sec_us", "", 2),
    ("XLC", "XLC", "通訊服務", "sec_us", "", 2),
    ("XLY", "XLY", "非必需消費", "sec_us", "", 2),
    ("XLP", "XLP", "必需消費", "sec_us", "", 2),
    ("XLE", "XLE", "能源", "sec_us", "", 2),
    ("XLF", "XLF", "金融", "sec_us", "", 2),
    ("XLV", "XLV", "醫療保健", "sec_us", "", 2),
    ("XLI", "XLI", "工業", "sec_us", "", 2),
    ("XLB", "XLB", "原物料", "sec_us", "", 2),
    ("XLRE", "XLRE", "不動產", "sec_us", "", 2),
    ("XLU", "XLU", "公用事業", "sec_us", "", 2),
]


# ───────────────────────── 抓資料 ─────────────────────────

def fetch_quotes():
    """Yahoo Finance：指數、匯率、原物料、美股類股 ETF。"""
    import yfinance as yf

    tickers = [q[1] for q in QUOTES]
    df = yf.download(tickers, period="3mo", interval="1d", group_by="ticker",
                     auto_adjust=False, progress=False, threads=True)
    out = {}
    for qid, tk, *_ in QUOTES:
        try:
            closes = df[tk]["Close"].dropna()
            if len(closes) < 2:
                continue
            last, prev = float(closes.iloc[-1]), float(closes.iloc[-2])
            out[qid] = {
                "close": last,
                "change": last - prev,
                "pct": (last / prev - 1) * 100,
                "date": closes.index[-1].strftime("%Y-%m-%d"),
                "spark": [round(float(v), 4) for v in closes.iloc[-30:]],
            }
        except Exception:
            continue
    if not out:
        raise RuntimeError("Yahoo Finance 沒有回傳任何報價")
    return out


def fred(series, start):
    """FRED 公開 CSV（不需要金鑰）。回傳 [(日期字串, 數值), ...]，略過缺值。"""
    import requests

    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd={start}"
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    rows = []
    for i, row in enumerate(csv.reader(io.StringIO(r.text))):
        if i == 0 or len(row) < 2:
            continue
        try:
            rows.append((row[0], float(row[1])))
        except ValueError:
            continue
    if not rows:
        raise RuntimeError(f"FRED {series} 沒有資料")
    return rows


def yoy(rows):
    """月資料 → 年增率 %。缺月份（例如政府關門）會自動跳過。"""
    by_month = {d[:7]: v for d, v in rows}
    out = []
    for m, v in sorted(by_month.items()):
        y, mo = m.split("-")
        base = by_month.get(f"{int(y) - 1}-{mo}")
        if base:
            out.append([m, round((v / base - 1) * 100, 2)])
    return out


def fetch_us_macro():
    start = (datetime.now(TPE) - timedelta(days=365 * 3)).strftime("%Y-%m-%d")
    recent = (datetime.now(TPE) - timedelta(days=500)).strftime("%Y-%m-%d")
    payems = fred("PAYEMS", start)
    nfp = [[payems[i][0][:7], round(payems[i][1] - payems[i - 1][1])] for i in range(1, len(payems))]
    target = fred("DFEDTARU", recent)
    by_month = {}
    for d, v in target:
        by_month[d[:7]] = v  # 每月最後一筆 = 月底值
    return {
        "cpi": yoy(fred("CPIAUCSL", start))[-14:],
        "core_cpi": yoy(fred("CPILFESL", start))[-14:],
        "nfp": nfp[-12:],
        "unrate": [[d[:7], v] for d, v in fred("UNRATE", recent)][-14:],
        "fed_upper": target[-1][1],
        "fed_monthly": [[m, v] for m, v in sorted(by_month.items())][-14:],
        "dgs2": list(fred("DGS2", recent)[-1]),
        "dgs10": list(fred("DGS10", recent)[-1]),
    }


def roc_date(s):
    """民國年日期 1151110 → 2026-11-10；其他格式原樣回傳。"""
    s = str(s).strip()
    if s.isdigit() and len(s) == 7:
        return f"{int(s[:3]) + 1911}-{s[3:5]}-{s[5:]}"
    if s.isdigit() and len(s) == 8:
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


def fetch_tw_sectors():
    """證交所 OpenAPI：各類股指數當日漲跌幅。"""
    import requests

    r = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX", headers=UA, timeout=30)
    r.raise_for_status()
    rows, date = [], ""
    for it in r.json():
        name = str(it.get("指數", ""))
        if "報酬" in name or not name.endswith("類指數"):
            continue
        try:
            pct = abs(float(str(it.get("漲跌百分比", "")).replace(",", "")))
        except ValueError:
            continue
        if str(it.get("漲跌", "")).strip() == "-":
            pct = -pct
        rows.append([name.replace("類指數", ""), round(pct, 2)])
        date = roc_date(it.get("日期", date))
    if not rows:
        raise RuntimeError("證交所類股指數沒有資料")
    return {"date": date, "rows": rows}


def fetch_institutional():
    """證交所：三大法人買賣超（上市，億元）。"""
    import requests

    r = requests.get("https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json", headers=UA, timeout=30)
    r.raise_for_status()
    j = r.json()
    tot = {"外資": 0.0, "投信": 0.0, "自營商": 0.0, "三大法人合計": 0.0}
    seen = False
    for row in j.get("data", []):
        name, diff = str(row[0]), float(str(row[-1]).replace(",", "")) / 1e8
        seen = True
        if "合計" in name:
            tot["三大法人合計"] = diff
        elif "外資" in name:
            tot["外資"] += diff
        elif "投信" in name:
            tot["投信"] += diff
        elif "自營" in name:
            tot["自營商"] += diff
    if not seen:
        raise RuntimeError("證交所三大法人沒有資料（可能尚未收盤或休市）")
    return {"date": roc_date(j.get("date", "")), "rows": [[k, round(v, 2)] for k, v in tot.items()]}


def fetch_foreign_futures():
    """期交所 OpenAPI：外資台指期未平倉淨額 → 淨空單口數（淨空為正）。"""
    import requests

    url = "https://openapi.taifex.com.tw/v1/MarketDataOfMajorInstitutionalTradersDetailsOfFuturesContractsBytheDate"
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    for it in r.json():
        text = " ".join(str(v) for v in it.values())
        contract = str(it.get("ContractCode", it.get("商品名稱", "")))
        if "外資" not in text or contract not in ("臺股期貨", "TX"):
            continue
        net = None
        for k, v in it.items():
            kk = k.replace(" ", "")
            if kk.startswith("OpenInterest(Net)") or kk == "未平倉口數淨額":
                net = float(str(v).replace(",", ""))
        if net is None:
            continue
        date = roc_date(str(it.get("Date", it.get("日期", ""))).replace("/", "").replace("-", ""))
        return [date, int(-net)]
    raise RuntimeError("期交所資料找不到外資臺股期貨")


def collect(cache):
    """逐一抓各來源；失敗就保留 cache 的舊資料並記下錯誤。"""
    data, errors = dict(cache), []
    jobs = [
        ("quotes", "報價（Yahoo Finance）", fetch_quotes),
        ("us_macro", "美國總經（FRED）", fetch_us_macro),
        ("tw_sectors", "台股類股（證交所）", fetch_tw_sectors),
        ("inst", "三大法人（證交所）", fetch_institutional),
    ]
    for key, label, fn in jobs:
        try:
            new = fn()
            if key == "quotes":  # 個別代號沒抓到的沿用舊值
                merged = dict(cache.get("quotes", {}))
                merged.update(new)
                new = merged
            data[key] = new
        except Exception as e:  # noqa: BLE001
            errors.append(f"{label}：{type(e).__name__} {e}"[:160])
    try:
        d, v = fetch_foreign_futures()
        hist = {x[0]: x[1] for x in cache.get("ff", [])}
        hist[d] = v
        data["ff"] = [[k, hist[k]] for k in sorted(hist)][-30:]
    except Exception as e:  # noqa: BLE001
        errors.append(f"外資台指期（期交所）：{type(e).__name__} {e}"[:160])
    now = datetime.now(TPE)
    data["updated"] = now.strftime("%Y-%m-%d %H:%M")
    data["edition"] = "早盤更新" if now.hour < 12 else "晚盤更新"
    data["errors"] = errors
    return data


# ───────────────────────── 產生網頁 ─────────────────────────

E = html.escape


def tone(v):
    return "flat" if v is None or v == 0 else ("up" if v > 0 else "down")


def sgn(v, nd=2):
    return "—" if v is None else f"{v:+,.{nd}f}"


def num(v, nd=2):
    return "—" if v is None else f"{v:,.{nd}f}"


def spark(vals, pct, w=112, h=30):
    if not vals or len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1
    pts = " ".join(f"{i * w / (len(vals) - 1):.1f},{h - 2 - (v - lo) / rng * (h - 4):.1f}" for i, v in enumerate(vals))
    return f'<svg class="spark {tone(pct)}" viewBox="0 0 {w} {h}" preserveAspectRatio="none" aria-hidden="true"><polyline points="{pts}"/></svg>'


def line_chart(series, labels, ref=None, step=False, fmt="{:.1f}", w=640, h=220):
    """series: [(名稱, 顏色 class, [值或 None, ...])]；labels: x 軸文字。"""
    vals = [v for _, _, vs in series for v in vs if v is not None]
    if not vals:
        return '<p class="ph">暫無資料</p>'
    if ref is not None:
        vals.append(ref)
    lo, hi = min(0, min(vals)), max(vals) * 1.12
    ml, mr, mt, mb = 40, 12, 10, 24
    n = len(labels)
    X = lambda i: ml + (w - ml - mr) * (i / max(1, n - 1))
    Y = lambda v: mt + (h - mt - mb) * (1 - (v - lo) / ((hi - lo) or 1))
    o = [f'<svg class="chart" viewBox="0 0 {w} {h}" role="img">']
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        o.append(f'<line class="grid" x1="{ml}" x2="{w - mr}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>'
                 f'<text class="ax" x="{ml - 6}" y="{Y(v) + 4:.1f}" text-anchor="end">{fmt.format(v)}</text>')
    stride = max(1, round(n / 7))
    for i, lab in enumerate(labels):
        if i % stride == 0 or i == n - 1:
            o.append(f'<text class="ax" x="{X(i):.1f}" y="{h - 6}" text-anchor="middle">{E(lab)}</text>')
    if ref is not None:
        o.append(f'<line class="ref" x1="{ml}" x2="{w - mr}" y1="{Y(ref):.1f}" y2="{Y(ref):.1f}"/>')
    for name, cls, vs in series:
        seg, d = [], []
        prev = None
        for i, v in enumerate(vs):
            if v is None:
                if seg:
                    d.append(seg)
                seg, prev = [], None
                continue
            if step and prev is not None:
                seg.append(f"{X(i):.1f},{Y(prev):.1f}")
            seg.append(f"{X(i):.1f},{Y(v):.1f}")
            prev = v
        if seg:
            d.append(seg)
        for s in d:
            o.append(f'<polyline class="ln {cls}" points="{" ".join(s)}"/>')
        for i, v in enumerate(vs):
            if v is not None:
                r = 4 if i == max(j for j, x in enumerate(vs) if x is not None) else (0 if step else 2.5)
                o.append(f'<circle class="dot {cls}" cx="{X(i):.1f}" cy="{Y(v):.1f}" r="{r}"><title>{E(labels[i])} {E(name)} {fmt.format(v)}</title></circle>')
        last = [(i, v) for i, v in enumerate(vs) if v is not None][-1]
        o.append(f'<text class="endlab {cls}" x="{X(last[0]) - 6:.1f}" y="{Y(last[1]) - 8:.1f}" text-anchor="end">{fmt.format(last[1])}</text>')
    o.append("</svg>")
    return "".join(o)


def col_chart(pairs, w=640, h=220):
    """pairs: [(標籤, 值)]，正值紅、負值綠。"""
    if not pairs:
        return '<p class="ph">暫無資料</p>'
    vals = [v for _, v in pairs]
    lo, hi = min(0, min(vals)) * 1.2, max(0, max(vals)) * 1.2 or 1
    ml, mr, mt, mb = 40, 8, 14, 24
    bw = (w - ml - mr) / len(pairs)
    Y = lambda v: mt + (h - mt - mb) * (1 - (v - lo) / ((hi - lo) or 1))
    o = [f'<svg class="chart" viewBox="0 0 {w} {h}" role="img">']
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        o.append(f'<line class="grid" x1="{ml}" x2="{w - mr}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>'
                 f'<text class="ax" x="{ml - 6}" y="{Y(v) + 4:.1f}" text-anchor="end">{v:.0f}</text>')
    o.append(f'<line class="ref solid" x1="{ml}" x2="{w - mr}" y1="{Y(0):.1f}" y2="{Y(0):.1f}"/>')
    for i, (lab, v) in enumerate(pairs):
        x = ml + i * bw + bw * 0.16
        top, bot = min(Y(v), Y(0)), max(Y(v), Y(0))
        o.append(f'<rect class="bar {tone(v)}" x="{x:.1f}" y="{top:.1f}" width="{bw * 0.68:.1f}" height="{max(1, bot - top):.1f}" rx="2"><title>{E(lab)} {v:+,.0f}</title></rect>')
        ty = top - 4 if v >= 0 else bot + 12
        o.append(f'<text class="ax" x="{x + bw * 0.34:.1f}" y="{ty:.1f}" text-anchor="middle">{v:,.0f}</text>')
        o.append(f'<text class="ax" x="{x + bw * 0.34:.1f}" y="{h - 6}" text-anchor="middle">{E(lab)}</text>')
    o.append("</svg>")
    return "".join(o)


def hbars(rows):
    """類股排行：rows = [(名稱, 漲跌幅%)]，由大到小。"""
    if not rows:
        return '<p class="ph">暫無資料</p>'
    rows = sorted(rows, key=lambda r: -r[1])
    ext = max(abs(v) for _, v in rows) or 1
    o = ['<div class="hb">']
    for name, v in rows:
        wpc = abs(v) / ext * 100
        o.append(f'<div class="hb-row"><span class="hb-n">{E(name)}</span>'
                 f'<span class="hb-track"><i class="hb-fill {tone(v)}" style="width:{wpc:.1f}%"></i></span>'
                 f'<span class="hb-v {tone(v)}">{v:+.2f}%</span></div>')
    o.append("</div>")
    return "".join(o)


def month_label(m):
    y, mo = m.split("-")
    return y if mo == "01" else f"{int(mo)}月"


def latest_two(pairs):
    cur = pairs[-1] if pairs else None
    prev = pairs[-2] if len(pairs) > 1 else None
    return cur, prev


def render(data, manual):
    q = data.get("quotes", {})
    us = data.get("us_macro", {})
    meta = {x[0]: x for x in QUOTES}

    def chip(qid):
        m, d = meta[qid], q.get(qid)
        if not d:
            return ""
        t = tone(d["pct"])
        return (f'<div class="chip"><div class="chip-n">{E(m[2])}</div>'
                f'<div class="chip-v {t}">{num(d["close"], m[5])}</div>'
                f'<div class="chip-c {t}"><span>{sgn(d["change"], m[5])}</span><span>{sgn(d["pct"])}%</span></div>'
                f'{spark(d.get("spark"), d["pct"])}<div class="chip-d">{E(d["date"])}</div></div>')

    def qrow(qid, show_unit=True):
        m, d = meta[qid], q.get(qid)
        if not d:
            return ""
        unit = f'<small>{E(m[4])}</small>' if show_unit and m[4] else ""
        return (f'<tr><td>{E(m[2])}</td><td class="r">{num(d["close"], m[5])}{unit}</td>'
                f'<td class="r {tone(d["pct"])}">{sgn(d["pct"])}</td><td class="mut">{E(d["date"])}</td></tr>')

    def grp_rows(group):
        return "".join(qrow(x[0]) for x in QUOTES if x[3] == group)

    # ── 總經表 ──
    def ind_row(name, cur, prev, unit, period, prev_period, better, nd=2):
        ch = None if cur is None or prev is None else cur - prev
        cls = tone(ch)
        return (f'<tr><td>{E(name)}</td><td class="r">{num(cur, nd)}<small>{E(unit)}</small></td>'
                f'<td class="mut">{E(period)}</td><td class="r mut">{num(prev, nd)}</td>'
                f'<td class="r {cls}">{"—" if ch is None else ("0" if ch == 0 else sgn(ch, nd))}</td></tr>')

    us_rows = []
    if us:
        c, p = latest_two(us.get("cpi", []))
        if c:
            us_rows.append(ind_row("CPI 年增率", c[1], p[1] if p else None, "%", c[0], p[0] if p else "", "down"))
        c, p = latest_two(us.get("core_cpi", []))
        if c:
            us_rows.append(ind_row("核心 CPI 年增率", c[1], p[1] if p else None, "%", c[0], p[0] if p else "", "down"))
        c, p = latest_two(us.get("nfp", []))
        if c:
            us_rows.append(ind_row("非農就業新增", c[1], p[1] if p else None, "千人", c[0], p[0] if p else "", "up", 0))
        c, p = latest_two(us.get("unrate", []))
        if c:
            us_rows.append(ind_row("失業率", c[1], p[1] if p else None, "%", c[0], p[0] if p else "", "down", 1))
        if us.get("fed_upper") is not None:
            fm = us.get("fed_monthly", [])
            prev_rate = fm[-2][1] if len(fm) > 1 else None
            us_rows.append(ind_row("聯邦基金利率（目標上限）", us["fed_upper"], prev_rate, "%", "現行", "上月底", "neutral"))
    tw_rows = [ind_row(x["name"], x.get("value"), x.get("prev"), x.get("unit", ""), x.get("period", ""),
                       x.get("prev_period", ""), x.get("better", "neutral"), x.get("decimals", 2))
               for x in manual.get("tw_indicators", [])]

    # ── CPI 圖 ──
    us_cpi = dict(map(tuple, us.get("cpi", [])))
    us_cpi.update(dict(map(tuple, manual.get("us_cpi_override", []))))  # FRED 缺月份時手動補
    tw_cpi = dict(map(tuple, manual.get("tw_cpi", [])))
    months = sorted(set(us_cpi) | set(tw_cpi))[-14:]
    cpi_svg = line_chart([("美國", "us", [us_cpi.get(m) for m in months]),
                          ("台灣", "tw", [tw_cpi.get(m) for m in months])],
                         [month_label(m) for m in months], ref=2)
    nfp_svg = col_chart([(month_label(m), v) for m, v in us.get("nfp", [])[-10:]])

    # ── 利率 ──
    fedm = dict(map(tuple, us.get("fed_monthly", [])))
    twm = dict(map(tuple, manual.get("tw_rate_monthly", [])))
    rate_now = manual.get("tw_rediscount")
    rmonths = sorted(fedm)[-14:]
    last_tw = None
    tw_series = []
    for m in rmonths:
        last_tw = twm.get(m, last_tw if last_tw is not None else rate_now)
        tw_series.append(last_tw)
    rate_svg = line_chart([("Fed 上限", "us", [fedm.get(m) for m in rmonths]), ("台灣重貼現率", "tw", tw_series)],
                          [month_label(m) for m in rmonths], step=True, fmt="{:.2f}")
    fed, d2, d10 = us.get("fed_upper"), us.get("dgs2"), us.get("dgs10")
    gap = None if fed is None or rate_now is None else fed - rate_now
    curve = None if not d2 or not d10 else d10[1] - d2[1]
    rate_rows = "".join([
        f'<tr><td>Fed 目標利率上限</td><td class="r">{num(fed)}<small>%</small></td><td class="mut">現行</td></tr>' if fed is not None else "",
        f'<tr><td>台灣央行重貼現率</td><td class="r">{num(rate_now)}<small>%</small></td><td class="mut">{E(manual.get("tw_rediscount_date", ""))}</td></tr>' if rate_now is not None else "",
        f'<tr><td>美債 2 年期殖利率</td><td class="r">{num(d2[1])}<small>%</small></td><td class="mut">{E(d2[0])}</td></tr>' if d2 else "",
        f'<tr><td>美債 10 年期殖利率</td><td class="r">{num(d10[1])}<small>%</small></td><td class="mut">{E(d10[0])}</td></tr>' if d10 else "",
    ])

    # ── 籌碼 ──
    ff = data.get("ff", [])
    if ff:
        cur = ff[-1]
        chg = cur[1] - ff[-2][1] if len(ff) > 1 else None
        chg_txt = "" if chg is None else f'<span class="{"down" if chg > 0 else "up" if chg < 0 else "flat"}">較前日 {chg:+,} 口</span>'
        ff_big = f'<div class="big"><span class="big-v">{cur[1]:,}</span>{chg_txt}<span class="mut">{E(cur[0])}</span></div>'
        ff_svg = ff_chart(ff)
    else:
        ff_big, ff_svg = "", '<p class="ph">暫無資料</p>'
    inst = data.get("inst", {})
    inst_rows = "".join(f'<tr><td>{E(n)}</td><td class="r {tone(v)}">{sgn(v)}</td><td class="mut">{E(inst.get("date", ""))}</td></tr>'
                        for n, v in inst.get("rows", []))

    # ── 類股 ──
    tws = data.get("tw_sectors", {})
    us_sec = [(meta[x[0]][2], q[x[0]]["pct"]) for x in QUOTES if x[3] == "sec_us" and x[0] in q]
    us_sec_date = next((q[x[0]]["date"] for x in QUOTES if x[3] == "sec_us" and x[0] in q), "")

    # ── 行事曆 ──
    today = datetime.now(TPE).strftime("%Y-%m-%d")
    cal = sorted((c for c in manual.get("calendar", []) if c.get("date", "") >= today), key=lambda c: (c["date"], c.get("time", "")))
    cal_rows = "".join(
        f'<tr><td>{E(c["date"])}</td><td class="mut">{E(c.get("time", ""))}</td><td>{E(c.get("country", ""))}</td>'
        f'<td>{E(c["event"])}</td><td class="mut">{E(c.get("prior", "") or "—")}</td>'
        f'<td><span class="tag {"hi" if c.get("importance") == "高" else ""}">{E(c.get("importance", "中"))}</span></td></tr>' for c in cal
    ) or '<tr><td colspan="6" class="mut">目前沒有登記的事件，請更新 data/manual.json</td></tr>'

    # ── 今日重點（依數據自動組句）──
    bits = []
    for qid in ("taiex", "spx"):
        d = q.get(qid)
        if d:
            bits.append(f'{meta[qid][2]}{"漲" if d["pct"] >= 0 else "跌"} {abs(d["pct"]):.2f}% 收 {num(d["close"], 0)}')
    fr = next((v for n, v in inst.get("rows", []) if n == "外資"), None)
    if fr is not None:
        bits.append(f'外資現貨{"買超" if fr >= 0 else "賣超"} {abs(fr):,.0f} 億')
    if ff:
        bits.append(f'台指期淨空單 {ff[-1][1]:,} 口')
    if cal:
        bits.append(f'下一個重點：{cal[0]["date"][5:].replace("-", "/")} {cal[0]["event"]}')
    headline = "；".join(bits) + "。" if bits else "資料更新中。"

    err = data.get("errors", [])
    err_html = ("<p class=\"warn\">這次有來源沒更新到，下列項目沿用上次資料：</p><ul class=\"warn\">" +
                "".join(f"<li>{E(e)}</li>" for e in err) + "</ul>") if err else ""

    strip = "".join(chip(x[0]) for x in QUOTES if x[3] in ("idx_tw", "idx_us"))
    com_rows = "".join(f'<tr class="grp"><td colspan="4">{g}</td></tr>' + grp_rows(g) for g in ("能源", "金屬", "農產品"))

    return TEMPLATE.format(
        updated=E(data.get("updated", "")), edition=E(data.get("edition", "")), headline=E(headline), strip=strip,
        us_rows="".join(us_rows) or '<tr><td colspan="5" class="mut">暫無資料</td></tr>',
        tw_rows="".join(tw_rows) or '<tr><td colspan="5" class="mut">暫無資料</td></tr>',
        cpi_svg=cpi_svg, nfp_svg=nfp_svg, fx_rows=grp_rows("fx"), rate_rows=rate_rows, rate_svg=rate_svg,
        gap=num(gap), curve=num(curve), com_rows=com_rows, ff_big=ff_big, ff_svg=ff_svg, inst_rows=inst_rows or '<tr><td colspan="3" class="mut">暫無資料</td></tr>',
        tw_sec=hbars([tuple(r) for r in tws.get("rows", [])]), tw_sec_date=E(tws.get("date", "")),
        us_sec=hbars(us_sec), us_sec_date=E(us_sec_date), cal_rows=cal_rows, err_html=err_html,
    )


def ff_chart(ff, w=640, h=220):
    """外資淨空單走勢（y 軸不從 0 開始，才看得出每日變化）。"""
    vals = [v for _, v in ff]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.15 or max(abs(hi) * 0.02, 1)
    lo, hi = lo - pad, hi + pad
    ml, mr, mt, mb = 58, 16, 14, 24
    n = len(ff)
    X = lambda i: ml + (w - ml - mr) * (i / max(1, n - 1)) if n > 1 else (ml + w - mr) / 2
    Y = lambda v: mt + (h - mt - mb) * (1 - (v - lo) / (hi - lo))
    o = [f'<svg class="chart" viewBox="0 0 {w} {h}" role="img" aria-label="外資台指期淨空單走勢">']
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        o.append(f'<line class="grid" x1="{ml}" x2="{w - mr}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>'
                 f'<text class="ax" x="{ml - 6}" y="{Y(v) + 4:.1f}" text-anchor="end">{v:,.0f}</text>')
    stride = max(1, round(n / 7))
    for i, (d, v) in enumerate(ff):
        if i % stride == 0 or i == n - 1:
            o.append(f'<text class="ax" x="{X(i):.1f}" y="{h - 6}" text-anchor="middle">{int(d[5:7])}/{int(d[8:10])}</text>')
    o.append(f'<polyline class="ln short" points="{" ".join(f"{X(i):.1f},{Y(v):.1f}" for i, (_, v) in enumerate(ff))}"/>')
    for i, (d, v) in enumerate(ff):
        o.append(f'<circle class="dot short" cx="{X(i):.1f}" cy="{Y(v):.1f}" r="{4 if i == n - 1 else 2.5}"><title>{d} {v:,} 口</title></circle>')
    o.append(f'<text class="endlab short" x="{X(n - 1) - 6:.1f}" y="{Y(vals[-1]) - 8:.1f}" text-anchor="end">{vals[-1]:,}</text></svg>')
    return "".join(o)


TEMPLATE = """<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>台美總經儀表板</title>
<style>
:root {{ --bg:#f4f5f7; --panel:#fff; --fg:#1d2129; --muted:#86909c; --line:#e5e6eb; --soft:#f2f3f5; --up:#f53f3f; --down:#00a854; --accent:#1664ff; --us:#1664ff; --tw:#ff7d00; --ref:#c9cdd4; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg); font-family:-apple-system,BlinkMacSystemFont,"PingFang TC","Noto Sans TC","Microsoft JhengHei",sans-serif; font-variant-numeric:tabular-nums; font-size:14px; }}
.wrap {{ max-width:1180px; margin:0 auto; padding:14px 16px 40px; display:flex; flex-direction:column; gap:14px; }}
.top {{ display:flex; flex-wrap:wrap; align-items:baseline; justify-content:space-between; gap:8px 16px; }}
h1 {{ margin:0; font-size:22px; letter-spacing:.02em; }}
.stamp {{ font-size:12px; color:var(--muted); display:flex; gap:6px; align-items:center; flex-wrap:wrap; }}
.badge {{ background:#e8f3ff; color:var(--accent); border-radius:4px; padding:2px 8px; font-weight:600; }}
.headline {{ margin:0; background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:10px 12px; line-height:1.6; }}
.headline b {{ color:var(--accent); margin-right:6px; }}
.strip {{ display:flex; gap:10px; overflow-x:auto; padding-bottom:4px; }}
.chip {{ flex:0 0 auto; min-width:138px; background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:10px 12px; display:flex; flex-direction:column; gap:2px; }}
.chip-n {{ font-size:12px; color:var(--muted); white-space:nowrap; }}
.chip-v {{ font-size:19px; font-weight:700; line-height:1.25; }}
.chip-c {{ font-size:12px; display:flex; gap:8px; white-space:nowrap; }}
.chip-d {{ font-size:11px; color:var(--muted); }}
.spark {{ width:100%; height:30px; margin-top:2px; }}
.spark polyline {{ fill:none; stroke-width:1.6; stroke:var(--muted); vector-effect:non-scaling-stroke; }}
.spark.up polyline {{ stroke:var(--up); }} .spark.down polyline {{ stroke:var(--down); }}
nav {{ position:sticky; top:0; z-index:3; display:flex; gap:6px; overflow-x:auto; background:var(--bg); padding:6px 0; }}
nav a {{ flex:0 0 auto; border:1px solid var(--line); background:var(--panel); color:var(--fg); border-radius:999px; padding:5px 14px; font-size:13px; text-decoration:none; }}
nav a:hover, nav a:focus-visible {{ border-color:var(--accent); color:var(--accent); outline:none; }}
section {{ display:flex; flex-direction:column; gap:10px; scroll-margin-top:52px; }}
h2 {{ margin:0; font-size:16px; display:flex; align-items:center; gap:8px; }}
h2::before {{ content:""; width:3px; height:14px; border-radius:2px; background:var(--accent); }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr)); gap:10px; }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:12px; display:flex; flex-direction:column; gap:8px; min-width:0; }}
h3 {{ margin:0; font-size:14px; }}
.note {{ margin:0; font-size:12px; color:var(--muted); line-height:1.5; }}
.tw {{ overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th {{ text-align:left; font-weight:500; color:var(--muted); font-size:12px; padding:6px 8px; background:var(--soft); white-space:nowrap; }}
td {{ padding:7px 8px; border-bottom:1px solid var(--line); }}
tr:last-child td {{ border-bottom:0; }}
.r {{ text-align:right; white-space:nowrap; }}
td small {{ color:var(--muted); font-size:11px; margin-left:3px; }}
.grp td {{ color:var(--muted); font-size:12px; padding-top:10px; border-bottom:0; }}
.mut {{ color:var(--muted); font-size:12px; }}
td.mut, td:first-child {{ white-space:nowrap; }}
#macro td:first-child {{ white-space:normal; }}
.up {{ color:var(--up); }} .down {{ color:var(--down); }} .flat {{ color:var(--muted); }}
.tag {{ display:inline-block; font-size:11px; border-radius:3px; padding:1px 6px; background:var(--soft); color:var(--muted); }}
.tag.hi {{ background:#ffece8; color:var(--up); }}
.big {{ display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; }}
.big-v {{ font-size:28px; font-weight:700; }}
.legend {{ display:flex; flex-wrap:wrap; gap:12px; font-size:12px; color:var(--muted); }}
.legend i {{ display:inline-block; width:12px; height:3px; border-radius:2px; margin-right:6px; vertical-align:middle; }}
.chart {{ display:block; width:100%; height:auto; }}
.chart .grid {{ stroke:var(--line); stroke-width:1; display:initial; }}
.chart .ax {{ fill:var(--muted); font-size:11px; }}
.chart .ref {{ stroke:var(--ref); stroke-dasharray:4 4; }} .chart .ref.solid {{ stroke-dasharray:none; }}
.chart .ln {{ fill:none; stroke-width:2; }}
.chart .us {{ stroke:var(--us); }} .chart .tw {{ stroke:var(--tw); }} .chart .short {{ stroke:var(--down); }}
.chart .dot.us, .chart .endlab.us {{ fill:var(--us); stroke:none; }} .chart .dot.tw, .chart .endlab.tw {{ fill:var(--tw); stroke:none; }} .chart .dot.short, .chart .endlab.short {{ fill:var(--down); stroke:none; }}
.chart .endlab {{ font-size:11px; font-weight:600; }}
.chart .bar.up {{ fill:var(--up); }} .chart .bar.down {{ fill:var(--down); }} .chart .bar.flat {{ fill:var(--muted); }}
.hb {{ display:flex; flex-direction:column; gap:5px; }}
.hb-row {{ display:grid; grid-template-columns:minmax(72px,auto) 1fr 62px; gap:8px; align-items:center; font-size:12px; }}
.hb-track {{ background:var(--soft); border-radius:3px; height:14px; overflow:hidden; }}
.hb-fill {{ display:block; height:100%; border-radius:3px; }}
.hb-fill.up {{ background:var(--up); }} .hb-fill.down {{ background:var(--down); }} .hb-fill.flat {{ background:var(--muted); }}
.hb-v {{ text-align:right; font-weight:600; }}
.ph {{ color:var(--muted); margin:0; padding:12px 0; }}
footer {{ font-size:12px; color:var(--muted); line-height:1.7; }}
.warn {{ color:#b25e00; }}
@media (max-width:480px) {{ .wrap {{ padding:10px 12px 32px; }} .big-v {{ font-size:24px; }} }}
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <h1>台美總經儀表板</h1>
    <div class="stamp"><span class="badge">{edition}</span><span>更新於 {updated}（台北時間）</span></div>
  </div>
  <p class="headline"><b>今日重點</b>{headline}</p>
  <div class="strip" aria-label="台美主要指數">{strip}</div>
  <nav aria-label="區塊導覽"><a href="#macro">總經</a><a href="#fxrates">匯率利率</a><a href="#commod">原物料</a><a href="#chips">籌碼</a><a href="#sectors">族群輪動</a><a href="#cal">行事曆</a></nav>

  <section id="macro">
    <h2>總經數據</h2>
    <div class="grid">
      <div class="card"><h3>美國</h3><div class="tw"><table><thead><tr><th>指標</th><th class="r">最新</th><th>期間</th><th class="r">前值</th><th class="r">變化</th></tr></thead><tbody>{us_rows}</tbody></table></div></div>
      <div class="card"><h3>台灣</h3><div class="tw"><table><thead><tr><th>指標</th><th class="r">最新</th><th>期間</th><th class="r">前值</th><th class="r">變化</th></tr></thead><tbody>{tw_rows}</tbody></table></div><p class="note">台灣數據為手動維護（data/manual.json）。</p></div>
      <div class="card"><h3>CPI 年增率（%）</h3><div class="legend"><span><i style="background:var(--us)"></i>美國</span><span><i style="background:var(--tw)"></i>台灣</span><span><i style="background:var(--ref)"></i>2% 目標／警戒線</span></div>{cpi_svg}</div>
      <div class="card"><h3>美國非農就業新增（千人）</h3>{nfp_svg}<p class="note">紅色為增加、綠色為減少。</p></div>
    </div>
  </section>

  <section id="fxrates">
    <h2>匯率與利率</h2>
    <div class="grid">
      <div class="card"><h3>匯率</h3><div class="tw"><table><thead><tr><th>項目</th><th class="r">報價</th><th class="r">漲跌 %</th><th>日期</th></tr></thead><tbody>{fx_rows}</tbody></table></div><p class="note">美元／新台幣數字變大代表新台幣貶值。</p></div>
      <div class="card"><h3>利率</h3><div class="tw"><table><thead><tr><th>項目</th><th class="r">利率</th><th>日期</th></tr></thead><tbody>{rate_rows}</tbody></table></div><p class="note">美台政策利差 <b>{gap}</b> 個百分點；美債 10 年減 2 年 <b>{curve}</b> 個百分點，負值代表殖利率曲線倒掛。</p></div>
      <div class="card"><h3>政策利率走勢（%，月底）</h3><div class="legend"><span><i style="background:var(--us)"></i>Fed 目標上限</span><span><i style="background:var(--tw)"></i>台灣重貼現率</span></div>{rate_svg}</div>
    </div>
  </section>

  <section id="commod">
    <h2>原物料</h2>
    <div class="card"><div class="tw"><table><thead><tr><th>品項（近月期貨）</th><th class="r">價格</th><th class="r">漲跌 %</th><th>日期</th></tr></thead><tbody>{com_rows}</tbody></table></div></div>
  </section>

  <section id="chips">
    <h2>籌碼：外資動向</h2>
    <div class="grid">
      <div class="card"><h3>外資台指期淨空單（口）</h3>{ff_big}{ff_svg}<p class="note">淨空單＝外資台指期空單減多單的未平倉口數，數字越大代表避險或看空部位越重。每個交易日累加一筆。</p></div>
      <div class="card"><h3>三大法人現貨買賣超（億元）</h3><div class="tw"><table><thead><tr><th>法人</th><th class="r">買賣超</th><th>日期</th></tr></thead><tbody>{inst_rows}</tbody></table></div><p class="note">紅色為買超、綠色為賣超，上市股票。</p></div>
    </div>
  </section>

  <section id="sectors">
    <h2>族群輪動</h2>
    <div class="grid">
      <div class="card"><h3>台股類股漲跌幅</h3>{tw_sec}<p class="note">資料日期 {tw_sec_date}，證交所類股指數。</p></div>
      <div class="card"><h3>美股 S&amp;P 500 類股漲跌幅</h3>{us_sec}<p class="note">資料日期 {us_sec_date}，以 SPDR 類股 ETF 代表。</p></div>
    </div>
  </section>

  <section id="cal">
    <h2>財經行事曆</h2>
    <div class="card"><div class="tw"><table><thead><tr><th>日期</th><th>台北時間</th><th>地區</th><th>事件</th><th>前值</th><th>重要性</th></tr></thead><tbody>{cal_rows}</tbody></table></div><p class="note">行事曆為手動維護（data/manual.json），過期事件會自動隱藏。</p></div>
  </section>

  <footer>
    {err_html}
    <p>資料來源：Yahoo Finance（指數、匯率、原物料、類股 ETF）、FRED（美國 CPI、非農、失業率、利率、殖利率）、臺灣證券交易所（類股指數、三大法人）、臺灣期貨交易所（外資台指期未平倉）。每週一至週五台北時間約 07:30 與 21:35 自動更新。紅漲綠跌。本頁僅供學習參考，不構成投資建議。</p>
  </footer>
</div>
</body>
</html>
"""


def main():
    offline = "--offline" in sys.argv
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    manual = json.loads(MANUAL.read_text(encoding="utf-8")) if MANUAL.exists() else {}
    data = cache if offline else collect(cache)
    if not offline:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(data, manual), encoding="utf-8")
    print(f"已產生 {OUT}（{data.get('updated', '')}）")
    for e in data.get("errors", []):
        print("沒更新到：", e)


if __name__ == "__main__":
    main()

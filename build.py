#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
朝のダッシュボード ビルドスクリプト（ステップ1：為替＋ニュース）

やること:
  1. 為替（USD/JPY, CNY/JPY）を Frankfurter（欧州中銀ECBベース）から取得し、
     前日比とミニ折れ線（Sparkline）を作る
  2. ニュースを Google ニュース RSS から3カテゴリ取得
  3. template.html に流し込んで index.html を生成
  4. data/history.json に当日の為替を記録（将来のグラフ用バックアップ）

ポイント:
  - 取得に失敗してもページは「—」表示で必ず生成される（壊れない）
  - 金属・原油・SOXは今はサンプル（第2ステップで実データ化）
"""

import os
import sys
import json
import html
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import requests
import feedparser

ROOT = os.path.dirname(os.path.abspath(__file__))
CN = timezone(timedelta(hours=8))          # 中国標準時（UTC+8）
NOW = datetime.now(CN)
DASH_URL = "https://karatsu07-commits.github.io/morning-dashboard/"

# ───────────────────────────────────────────────
#  アイコン（Lucide風SVG・外部読み込みなし）
# ───────────────────────────────────────────────
_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{}</svg>')
ICONS = {
    "dollar":  _SVG.format('<line x1="12" y1="2" x2="12" y2="22"/>'
                           '<path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>'),
    "yen":     _SVG.format('<path d="m9 3 3 6 3-6"/><path d="M9 9h6"/>'
                           '<path d="M9 13h6"/><path d="M12 9v12"/>'),
    "hexagon": _SVG.format('<path d="M21 16.05V7.95a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4a2 '
                           '2 0 0 0-1 1.73v8.1a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4a2 2 0 0 0 1-1.73Z"/>'),
    "droplet": _SVG.format('<path d="M12 22a7 7 0 0 0 7-7c0-2-1-3.9-3-5.5s-3.5-4-4-6.5c-.5 2.5-2 '
                           '4.9-4 6.5C6 11.1 5 13 5 15a7 7 0 0 0 7 7z"/>'),
    "activity": _SVG.format('<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>'),
}


# ───────────────────────────────────────────────
#  小道具
# ───────────────────────────────────────────────
def _get(url, headers=None, tries=3):
    """GETに失敗したら少し待って数回やり直す（一時的な通信エラー対策）。"""
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, timeout=20,
                             headers=headers or {"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            return r
        except Exception as e:
            last = e
            if i < tries - 1:
                time.sleep(2)
    raise last


def change_class(pct):
    """増減率から (CSSクラス, 矢印, 色) を返す。上昇＝赤 / 下落＝青。"""
    if pct > 0:
        return ("up", "▲", "#EF4444")
    if pct < 0:
        return ("down", "▼", "#3B82F6")
    return ("flat", "―", "#8A93A0")


def spark_points(values, w=100, h=40, pad=6):
    """数値のリストを Sparkline 用の座標文字列に変換。"""
    if not values:
        return "0,20 100,20"
    if len(values) == 1:
        values = values * 2
    lo, hi = min(values), max(values)
    rng = (hi - lo) or 1
    n = len(values)
    pts = []
    for i, v in enumerate(values):
        x = i * (w / (n - 1))
        y = h - pad - (v - lo) / rng * (h - 2 * pad)
        pts.append(f"{x:.1f},{y:.1f}")
    return " ".join(pts)


def render_kpi(icon, title, sub, value, chg_class, chg_text, spark_color, points, value_style=""):
    """KPIカード1枚分のHTMLを作る。"""
    return f'''
    <div class="kpi">
      <div class="head"><span class="ico">{ICONS[icon]}</span>
        <div><div class="ttl">{title}</div><div class="sub">{sub}</div></div></div>
      <div class="val"{value_style}>{value}</div>
      <div class="chg {chg_class}">{chg_text}</div>
      <div class="spark"><svg viewBox="0 0 100 40" preserveAspectRatio="none"><polyline fill="none" stroke="{spark_color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" points="{points}"/></svg></div>
    </div>'''


# ───────────────────────────────────────────────
#  為替（Frankfurter）
# ───────────────────────────────────────────────
def fetch_fx(base):
    """base/JPY の直近時系列を取得。値リスト（古い→新しい）を返す。失敗時 None。"""
    end = NOW.date()
    start = end - timedelta(days=18)
    url = f"https://api.frankfurter.app/{start}..{end}?from={base}&to=JPY"
    try:
        r = _get(url)
        rates = r.json().get("rates", {})
        vals = [rates[d]["JPY"] for d in sorted(rates.keys()) if "JPY" in rates[d]]
        return vals or None
    except Exception as e:
        print(f"[FX] 取得失敗 {base}/JPY: {e}", file=sys.stderr)
        return None


def fx_card(title, sub, icon, vals):
    """為替カードのHTMLと当日値を返す。"""
    if not vals:
        return render_kpi(icon, title, sub, "—", "flat", "取得できませんでした",
                          "#8A93A0", spark_points([])), None
    cur = vals[-1]
    prev = vals[-2] if len(vals) >= 2 else cur
    diff = cur - prev
    pct = (diff / prev * 100) if prev else 0
    cls, arrow, color = change_class(pct)
    chg = f"{arrow} {diff:+.2f} ({pct:+.2f}%)" if len(vals) >= 2 else "前日比なし"
    return render_kpi(icon, title, sub, f"{cur:,.2f}", cls, chg, color,
                      spark_points(vals[-10:])), round(cur, 4)


# ───────────────────────────────────────────────
#  金属・原油・SOX（実データ）
# ───────────────────────────────────────────────
def fetch_yahoo(ticker):
    """Yahoo Finance から日次の終値リスト（古い→新しい）を取得。失敗時 None。"""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?range=1mo&interval=1d")
    try:
        r = _get(url)
        res = r.json()["chart"]["result"][0]
        closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
        return closes or None
    except Exception as e:
        print(f"[Yahoo] 取得失敗 {ticker}: {e}", file=sys.stderr)
        return None


def fetch_sina_kline(sym):
    """新浪財経の内盤期貨（SHFE等）日足から終値リストを取得。失敗時 None。
    sym 例: NI0=沪镍, AL0=沪铝, CU0=沪铜（0=主力連続）。値は 元/トン。"""
    url = (f"https://stock2.finance.sina.com.cn/futures/api/jsonp.php/"
           f"var%20_{sym}=/InnerFuturesNewService.getDailyKLine?symbol={sym}")
    try:
        r = _get(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.sina.com.cn",
        })
        txt = r.text
        i, j = txt.find("["), txt.rfind("]")
        arr = json.loads(txt[i:j + 1])
        closes = [float(x["c"]) for x in arr if x.get("c")]
        return closes or None
    except Exception as e:
        print(f"[Sina] 取得失敗 {sym}: {e}", file=sys.stderr)
        return None


def market_card(icon, title, sub, series, val_fmt, diff_fmt):
    """終値リストから KPIカードを作る。前日比は終値どうしで計算。"""
    if not series:
        return render_kpi(icon, title, sub, "—", "flat", "取得できませんでした",
                          "#8A93A0", spark_points([]))
    cur = series[-1]
    prev = series[-2] if len(series) >= 2 else cur
    diff = cur - prev
    pct = (diff / prev * 100) if prev else 0
    cls, arrow, color = change_class(pct)
    chg = (f"{arrow} {diff_fmt(diff)} ({pct:+.2f}%)" if len(series) >= 2 else "前日比なし")
    return render_kpi(icon, title, sub, val_fmt(cur), cls, chg, color,
                      spark_points(series[-12:]))


def moly_card():
    """モリブデン：無料の安定相場が無いため参考ページへのリンク。"""
    link = ('<a href="https://www.metal.com/Molybdenum" target="_blank" rel="noopener" '
            'style="color:var(--body);text-decoration:none;'
            'border-bottom:1px solid var(--border-strong);">参考ページ →</a>')
    return render_kpi("hexagon", "モリブデン", "钼 ・ 参考(無料相場少)", link,
                      "flat", "週次・手動で確認", "#8A93A0", "0,20 100,20",
                      value_style=' style="font-size:16px;"')


# ───────────────────────────────────────────────
#  ニュース（Google ニュース RSS）
# ───────────────────────────────────────────────
FEEDS = {
    # キーワードは自由に調整できます（OR と () が使えます）
    "SEMI":    "半導体 OR 半導体製造装置 OR TSMC OR ASML OR 東京エレクトロン OR ラピダス",
    "CHINA":   "中国 (輸出規制 OR 輸出管理 OR 通関 OR 半導体 OR レアアース OR 関税)",
    "AUTO":    "(産業用ロボット OR ファクトリーオートメーション OR 協働ロボット OR 自動化設備 OR 生産自動化) (中国 OR 工場 OR 導入)",
    "GLOBAL":  "サプライチェーン OR 海運 OR 物流混乱 OR コンテナ船",
    "FREIGHT": "SCFI OR コンテナ運賃 OR 海上運賃",
}


def fetch_news(query, n=5):
    """Google ニュース RSS から記事を取得。(タイトル, リンク, 時刻) のリスト。"""
    url = (f"https://news.google.com/rss/search?q={quote(query)}"
           f"&hl=ja&gl=JP&ceid=JP:ja")
    try:
        feed = feedparser.parse(url)
        items = []
        for e in feed.entries[:n]:
            t = e.get("published_parsed")
            if t:
                dt = datetime(*t[:6], tzinfo=timezone.utc).astimezone(CN)
                tstr = dt.strftime("%m/%d %H:%M")
            else:
                tstr = ""
            items.append((e.get("title", "（無題）"), e.get("link", "#"), tstr))
        return items
    except Exception as e:
        print(f"[NEWS] 取得失敗: {e}", file=sys.stderr)
        return []


def render_news(items):
    if not items:
        return ('<li><a href="#">ニュースを取得できませんでした</a>'
                '<div class="time">—</div></li>')
    out = []
    for title, link, tstr in items:
        title = html.escape(title)
        link = html.escape(link, quote=True)
        out.append(f'<li><a href="{link}" target="_blank" rel="noopener">{title}</a>'
                   f'<div class="time">{tstr}</div></li>')
    return "\n".join(out)


# ───────────────────────────────────────────────
#  WeChat配信（Server酱）— 鍵 SERVERCHAN_KEY があるときだけ送る
# ───────────────────────────────────────────────
# 重要度マーク用キーワード（営業に効きそうな語＝🔴重要、その他＝🟡注目）
HIGH_KW = ["規制", "輸出管理", "禁輸", "制裁", "関税", "急騰", "急落",
           "値上げ", "供給", "停止", "レアアース", "ストライキ", "減産", "増産"]


def _mark(title):
    return "🔴" if any(k in title for k in HIGH_KW) else "🟡"


def _news_block(items, n=4):
    """重要度マーク付き・🔴優先で並べ替えた見出しリスト。無ければ該当なし。"""
    if not items:
        return ["・本日は該当なし"]
    ranked = sorted(items, key=lambda it: 0 if _mark(it[0]) == "🔴" else 1)[:n]
    return [f"{_mark(t)} {t}" for (t, _l, _ts) in ranked]


def _fx_line(label, vals):
    """為替1行：前日比＋前週比。"""
    if not vals:
        return f"{label}：取得失敗"
    cur = vals[-1]
    prev = vals[-2] if len(vals) >= 2 else cur
    wk = vals[-6] if len(vals) >= 6 else vals[0]
    d = ((cur - prev) / prev * 100) if prev else 0
    w = ((cur - wk) / wk * 100) if wk else 0
    a = lambda p: "▲" if p > 0 else ("▼" if p < 0 else "―")
    return f"{label} {cur:,.2f}　前日{a(d)}{d:+.2f}% / 前週{a(w)}{w:+.2f}%"


def _metal_line(label, series, unit="元/t", dollar=False):
    if not series:
        return f"{label}：取得失敗"
    cur = series[-1]
    prev = series[-2] if len(series) >= 2 else cur
    p = ((cur - prev) / prev * 100) if prev else 0
    a = "▲" if p > 0 else ("▼" if p < 0 else "―")
    val = f"${cur:,.2f}" if dollar else f"{cur:,.0f}{unit}"
    return f"{label} {val}　{a}{p:+.2f}%"


def _pct(series):
    if not series or len(series) < 2 or not series[-2]:
        return 0.0
    return (series[-1] - series[-2]) / series[-2] * 100


def metals_comment(nickel, alu):
    """営業視点の一言（ルールベース。AIではなく値動きから自動生成）。"""
    parts = []
    pn = _pct(nickel)
    if pn < -0.3:
        parts.append("ニッケル下落→SUS材は弱含み（仕入れ交渉に追い風）")
    elif pn > 0.3:
        parts.append("ニッケル上昇→SUS材は強含み（早めの発注検討）")
    else:
        parts.append("ニッケル横ばい→SUS材は様子見")
    pa = _pct(alu)
    if pa > 0.3:
        parts.append("アルミ上昇")
    elif pa < -0.3:
        parts.append("アルミ下落")
    return "👉 一言：" + " ／ ".join(parts)


def build_summary(usd_vals, cny_vals, nickel, alu, oil, sox, raw_news):
    """WeChatへ送る朝のまとめ（タイトル, 本文markdown）を新フォーマットで作る。"""
    week = "月火水木金土日"[NOW.weekday()]
    b = []

    # 主な見出し（全カテゴリから🔴優先で上位3）
    allnews = []
    for k in ("SEMI", "CHINA", "AUTO", "GLOBAL"):
        allnews += raw_news.get(k, [])
    tops = [t for (t, _l, _ts) in allnews if _mark(t) == "🔴"][:3]
    if not tops:
        tops = [t for (t, _l, _ts) in allnews][:3]
    b.append("**【主な見出し】**")
    b += [f"・{t}" for t in tops] if tops else ["・本日は該当なし"]

    # 為替
    b.append("**【為替】**")
    b.append(_fx_line("USD/JPY", usd_vals))
    b.append(_fx_line("CNY/JPY", cny_vals))

    # 金属・市況（商材順）
    b.append("**【金属・市況】**")
    b.append(_metal_line("ニッケル 沪镍", nickel))
    b.append("モリブデン：無料相場なし（参考→ metal.com/Molybdenum）")
    b.append(_metal_line("アルミ 沪铝", alu))
    b.append(_metal_line("原油WTI", oil, dollar=True))
    b.append(_metal_line("SOX指数", sox, unit=""))
    b.append(metals_comment(nickel, alu))

    # ニュース各セクション（件数はセクションごとに調整）
    for key, label, cnt in [("SEMI", "半導体", 4), ("CHINA", "中国・輸出管理", 4),
                            ("AUTO", "自動化・設備", 3), ("GLOBAL", "世界・物流", 3)]:
        b.append(f"**【{label}】**")
        b += _news_block(raw_news.get(key, []), cnt)

    # コンテナ運賃＋祝日
    fr = raw_news.get("FREIGHT", [])
    if fr:
        b.append(f"**【コンテナ運賃】** {fr[0][0]}（詳細→ sse.net.cn）")
    nh = next_holiday()
    if nh:
        days = (nh[0] - NOW.date()).days
        b.append(f"📅 次の中国連休：{nh[1]} まであと {days} 日")

    b.append(f"🧧 春節 {spring_festival()}")
    b.append(f"▶ {DASH_URL}")
    title = f"🌅 朝のまとめ {NOW.month}/{NOW.day}（{week}）"
    return title, "\n\n".join(b)


def send_wechat(title, desp):
    """SERVERCHAN_KEY に複数の鍵をカンマ区切りで入れると、全員に送信できる。
    例: SERVERCHAN_KEY = "SCTあなたの鍵,SCT同僚の鍵" """
    raw = os.environ.get("SERVERCHAN_KEY", "")
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        print("[WeChat] SERVERCHAN_KEY 未設定のため送信スキップ")
        return
    for key in keys:
        try:
            r = requests.post(f"https://sctapi.ftqq.com/{key}.send",
                              data={"title": title, "desp": desp}, timeout=20)
            ok = (r.json().get("code") == 0)
            print(f"[WeChat] {key[:6]}… 送信{'成功' if ok else '失敗: ' + r.text[:120]}")
        except Exception as e:
            print(f"[WeChat] {key[:6]}… 送信失敗: {e}", file=sys.stderr)


# ───────────────────────────────────────────────
#  春節カウントダウン
# ───────────────────────────────────────────────
CNY_DATES = ["2027-02-06", "2028-01-26", "2029-02-13", "2030-02-03", "2031-01-23"]


def spring_festival():
    today = NOW.date()
    for d in CNY_DATES:
        cny = datetime.strptime(d, "%Y-%m-%d").date()
        if cny >= today:
            days = (cny - today).days
            return f"あと {days} 日（{cny.strftime('%Y-%m-%d')}）"
    return "—"


# ───────────────────────────────────────────────
#  業務カレンダー（中国の祝日・連休／展示会）
#  ※日付は编集して追加・修正できます。連休範囲は年により调休で前後します。
# ───────────────────────────────────────────────
CN_HOLIDAYS = [
    ("2026-09-25", "中秋節"),
    ("2026-10-01", "国慶節（物流停止注意・約1週間）"),
    ("2027-01-01", "元旦"),
    ("2027-02-06", "春節（物流停止注意・大型連休）"),
    ("2027-04-05", "清明節"),
    ("2027-05-01", "労働節"),
]
EVENTS = [
    ("2026-09", "中国国際工業博覧会(CIIF) 上海 ※予定"),
    ("2026-12", "SEMICON Japan 東京 ※予定"),
    ("2027-03", "SEMICON China 上海 ※予定"),
]
_CLOCK = _SVG.format('<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>')
_BUILDING = _SVG.format('<path d="M2 20h20M4 20V8l8-5 8 5v12M9 20v-6h6v6"/>')


def next_holiday():
    """次に来る中国の祝日 (date, 名前) を返す。無ければ None。"""
    today = NOW.date()
    for d, name in CN_HOLIDAYS:
        hd = datetime.strptime(d, "%Y-%m-%d").date()
        if hd >= today:
            return hd, name
    return None


def render_calendar():
    """ダッシュボードの業務カレンダー欄（<li> の並び）を作る。"""
    today = NOW.date()
    rows = []
    upcoming = [(datetime.strptime(d, "%Y-%m-%d").date(), n) for d, n in CN_HOLIDAYS]
    upcoming = [(hd, n) for hd, n in upcoming if hd >= today][:3]
    for i, (hd, name) in enumerate(upcoming):
        days = (hd - today).days
        if i == 0:
            tail = f'<span class="pill">あと {days} 日</span>'
        else:
            tail = (f'<span style="margin-left:auto;color:var(--muted);'
                    f'font-size:12px;">{hd.strftime("%m/%d")}</span>')
        rows.append(f'<li><span class="ico">{_CLOCK}</span>{name}{tail}</li>')
    ym_now = NOW.strftime("%Y-%m")
    for ym, name in EVENTS:
        if ym >= ym_now:
            rows.append(f'<li><span class="ico">{_BUILDING}</span>{html.escape(name)}</li>')
    if not rows:
        rows.append('<li>予定なし</li>')
    return "\n".join(rows)


# ───────────────────────────────────────────────
#  共有メモ（memo.md を読み込んで表示）
# ───────────────────────────────────────────────
def load_memo():
    """memo.md を読み、最低限のmarkdownでHTML化。全員が同じ内容を見る共有メモ。"""
    try:
        with open(os.path.join(ROOT, "memo.md"), encoding="utf-8") as f:
            txt = f.read().strip()
    except Exception:
        txt = ""
    if not txt:
        return '<span style="color:var(--muted);">（メモはまだありません。「編集」から書けます）</span>'
    out = []
    for ln in txt.splitlines():
        s = html.escape(ln).strip()
        if s.startswith("- "):
            s = "・" + s[2:]
        out.append(s if s else "&nbsp;")
    return "<br>".join(out)


# ───────────────────────────────────────────────
#  履歴の保存（将来のグラフ用バックアップ）
# ───────────────────────────────────────────────
def save_history(snapshot):
    """その日の値を data/history.json に記録（将来のグラフ用バックアップ）。"""
    path = os.path.join(ROOT, "data", "history.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, encoding="utf-8") as f:
            hist = json.load(f)
    except Exception:
        hist = []
    today = NOW.strftime("%Y-%m-%d")
    hist = [h for h in hist if h.get("date") != today]
    hist.append({"date": today, **snapshot})
    hist = hist[-500:]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)


# ───────────────────────────────────────────────
#  メイン
# ───────────────────────────────────────────────
def main():
    # --- 為替 ---
    usd_vals = fetch_fx("USD")
    cny_vals = fetch_fx("CNY")
    usd_html, usd_now = fx_card("USD / JPY", "美元 / 日元", "dollar", usd_vals)
    cny_html, cny_now = fx_card("CNY / JPY", "人民币 / 日元", "yen", cny_vals)

    # --- 金属・原油・SOX（実データ）---
    nickel = fetch_sina_kline("NI0")   # 沪镍（元/t）
    alu = fetch_sina_kline("AL0")      # 沪铝（元/t）
    oil = fetch_yahoo("CL=F")          # WTI原油（$/bbl）
    sox = fetch_yahoo("^SOX")          # 費城半導体指数

    cny0 = lambda v: f"{v:,.0f}"       # 元・整数
    cnyd = lambda d: f"{d:+,.0f}"
    kpis = [
        usd_html,
        cny_html,
        market_card("hexagon", "ニッケル", "沪镍 ・ 元/t (CNY)", nickel, cny0, cnyd),
        market_card("hexagon", "アルミ", "沪铝 ・ 元/t (CNY)", alu, cny0, cnyd),
        moly_card(),
        market_card("droplet", "原油 WTI", "原油 ・ $/bbl", oil,
                    lambda v: f"${v:,.2f}", lambda d: f"{d:+.2f}"),
        market_card("activity", "SOX指数", "费城半导体 ・ pt", sox, cny0, cnyd),
    ]

    # --- ニュース ---
    raw_news = {k: fetch_news(q, 8) for k, q in FEEDS.items()}
    news = {k: render_news(v) for k, v in raw_news.items()}

    # --- テンプレートに流し込み ---
    with open(os.path.join(ROOT, "template.html"), encoding="utf-8") as f:
        out = f.read()
    out = out.replace("<!--UPDATED-->", NOW.strftime("%Y-%m-%d %H:%M"))
    out = out.replace("<!--KPIS-->", "\n".join(kpis))
    out = out.replace("<!--NEWS_SEMI-->", news["SEMI"])
    out = out.replace("<!--NEWS_CHINA-->", news["CHINA"])
    out = out.replace("<!--NEWS_GLOBAL-->", news["GLOBAL"])
    out = out.replace("<!--SPRINGFESTIVAL-->", spring_festival())
    out = out.replace("<!--CALENDAR-->", render_calendar())
    out = out.replace("<!--MEMO-->", load_memo())

    with open(os.path.join(ROOT, "index.html"), "w", encoding="utf-8") as f:
        f.write(out)

    # --- 履歴保存 ---
    save_history({
        "usdjpy": usd_now,
        "cnyjpy": cny_now,
        "nickel": round(nickel[-1], 1) if nickel else None,
        "alu": round(alu[-1], 1) if alu else None,
        "wti": round(oil[-1], 2) if oil else None,
        "sox": round(sox[-1], 2) if sox else None,
    })

    print(f"[OK] index.html を生成しました（{NOW:%Y-%m-%d %H:%M} 中国時間）")
    print(f"      USD/JPY={usd_now}  CNY/JPY={cny_now}")
    print(f"      沪镍={nickel[-1] if nickel else None}  沪铝={alu[-1] if alu else None}  "
          f"WTI={oil[-1] if oil else None}  SOX={sox[-1] if sox else None}")

    # --- WeChat配信（SERVERCHAN_KEY があるときだけ送信）---
    title, desp = build_summary(usd_vals, cny_vals, nickel, alu, oil, sox, raw_news)
    send_wechat(title, desp)


if __name__ == "__main__":
    main()

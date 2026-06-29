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
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import requests
import feedparser

ROOT = os.path.dirname(os.path.abspath(__file__))
CN = timezone(timedelta(hours=8))          # 中国標準時（UTC+8）
NOW = datetime.now(CN)

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
        r = requests.get(url, timeout=20)
        r.raise_for_status()
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
#  サンプルKPI（金属・原油・SOX：第2ステップで実データ化）
# ───────────────────────────────────────────────
def sample_cards():
    return [
        render_kpi("hexagon", "ニッケル", "镍 ・ Nickel", "¥128,300", "up", "▲ +1.2%",
                   "#EF4444", "0,28 14,24 28,27 42,20 56,22 70,16 84,13 100,9"),
        render_kpi("hexagon", "アルミ", "铝 ・ Aluminum", "¥20,450", "down", "▼ -0.6%",
                   "#3B82F6", "0,14 14,12 28,16 42,15 56,20 70,18 84,24 100,26"),
        render_kpi("hexagon", "モリブデン", "钼 ・ Molybdenum", "参考値", "flat", "― 週次更新",
                   "#8A93A0", "0,20 14,19 28,21 42,20 56,18 70,19 84,18 100,17",
                   value_style=' style="font-size:22px;color:var(--body);"'),
        render_kpi("droplet", "原油 WTI", "原油 ・ Crude", "$72.40", "up", "▲ +0.8%",
                   "#EF4444", "0,24 14,22 28,25 42,18 56,20 70,15 84,17 100,11"),
        render_kpi("activity", "SOX指数", "费城半导体 ・ SOX", "5,180", "up", "▲ +1.1%",
                   "#EF4444", "0,26 14,20 28,23 42,17 56,14 70,16 84,10 100,8"),
    ]


# ───────────────────────────────────────────────
#  ニュース（Google ニュース RSS）
# ───────────────────────────────────────────────
FEEDS = {
    # キーワードは自由に調整できます（OR と () が使えます）
    "SEMI":   "半導体 OR 半導体製造装置 OR TSMC OR ASML OR 東京エレクトロン",
    "CHINA":  "中国 (輸出規制 OR 輸出管理 OR 通関 OR 半導体)",
    "GLOBAL": "サプライチェーン OR 海運 OR 物流混乱 OR 半導体 供給",
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
#  履歴の保存（将来のグラフ用バックアップ）
# ───────────────────────────────────────────────
def save_history(usdjpy, cnyjpy):
    path = os.path.join(ROOT, "data", "history.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, encoding="utf-8") as f:
            hist = json.load(f)
    except Exception:
        hist = []
    today = NOW.strftime("%Y-%m-%d")
    hist = [h for h in hist if h.get("date") != today]
    hist.append({"date": today, "usdjpy": usdjpy, "cnyjpy": cnyjpy})
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

    kpis = [usd_html, cny_html] + sample_cards()

    # --- ニュース ---
    news = {k: render_news(fetch_news(q)) for k, q in FEEDS.items()}

    # --- テンプレートに流し込み ---
    with open(os.path.join(ROOT, "template.html"), encoding="utf-8") as f:
        out = f.read()
    out = out.replace("<!--UPDATED-->", NOW.strftime("%Y-%m-%d %H:%M"))
    out = out.replace("<!--KPIS-->", "\n".join(kpis))
    out = out.replace("<!--NEWS_SEMI-->", news["SEMI"])
    out = out.replace("<!--NEWS_CHINA-->", news["CHINA"])
    out = out.replace("<!--NEWS_GLOBAL-->", news["GLOBAL"])
    out = out.replace("<!--SPRINGFESTIVAL-->", spring_festival())

    with open(os.path.join(ROOT, "index.html"), "w", encoding="utf-8") as f:
        f.write(out)

    # --- 履歴保存 ---
    save_history(usd_now, cny_now)

    print(f"[OK] index.html を生成しました（{NOW:%Y-%m-%d %H:%M} 中国時間）")
    print(f"      USD/JPY={usd_now}  CNY/JPY={cny_now}")


if __name__ == "__main__":
    main()

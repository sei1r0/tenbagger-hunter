import os
import sys
import json
import re
import time
import datetime

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from google import genai
from google.genai import types
from jinja2 import Template
from src.utils.notifier import send_flex_carousel
from src.utils.market_overview import fetch_market_indices
from src.utils.market_calendar import get_jst_now
from src.utils.track_record import archive_weekly_results, calculate_track_record

CANDIDATES_FILE = os.path.join(PROJECT_ROOT, "data", "screened_candidates.json")
OUTPUT_HTML_DIR = os.path.join(PROJECT_ROOT, "docs")
OUTPUT_HTML_PATH = os.path.join(OUTPUT_HTML_DIR, "index.html")

MAX_AI_ANALYZE = 20
MAX_TRANSIENT_ERRORS = 2

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Tenbagger Hunter Pro - 週末厳選AIレポート</title>
  <!-- TradingView Chart Widget Script -->
  <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
  <style>
    :root {
      --bg: #0b0f19;
      --card-bg: #151d30;
      --text-main: #f8fafc;
      --text-sub: #94a3b8;
      --accent-green: #10b981;
      --accent-blue: #38bdf8;
      --accent-red: #ef4444;
      --accent-gold: #f59e0b;
      --accent-purple: #a855f7;
      --border: #243049;
    }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      background-color: var(--bg);
      color: var(--text-main);
      margin: 0;
      padding: 1.25rem;
    }
    .container { max-width: 1040px; margin: 0 auto; }
    header { border-bottom: 1px solid var(--border); padding-bottom: 1.2rem; margin-bottom: 1.5rem; }
    h1 { margin: 0 0 0.4rem 0; font-size: 1.6rem; display: flex; align-items: center; gap: 0.5rem; }
    .updated { color: var(--text-sub); font-size: 0.85rem; }

    /* 主要指数パネル */
    .market-panel {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 0.75rem;
      margin-bottom: 1.75rem;
    }
    .market-card {
      background: rgba(30, 41, 59, 0.7);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.75rem;
    }
    .market-title { font-size: 0.85rem; font-weight: bold; color: var(--accent-blue); margin-bottom: 0.2rem; }
    .market-val { font-size: 1.1rem; font-weight: bold; margin-bottom: 0.3rem; }
    .market-change { font-size: 0.75rem; }
    .pos { color: var(--accent-green); }
    .neg { color: var(--accent-red); }

    /* 資金管理・ポジションサイジング計算機 */
    .calc-panel {
      background: linear-gradient(135deg, rgba(16, 185, 129, 0.08), rgba(56, 189, 248, 0.08));
      border: 1px solid rgba(16, 185, 129, 0.3);
      border-radius: 10px;
      padding: 0.85rem 1.1rem;
      margin-bottom: 1.5rem;
      display: flex;
      flex-wrap: wrap;
      gap: 1rem;
      align-items: center;
      justify-content: space-between;
    }
    .calc-inputs {
      display: flex;
      flex-wrap: wrap;
      gap: 0.75rem;
      align-items: center;
    }
    .calc-group {
      display: flex;
      align-items: center;
      gap: 0.4rem;
      font-size: 0.85rem;
    }
    .calc-input {
      background: var(--card-bg);
      border: 1px solid var(--border);
      color: var(--text-main);
      padding: 0.35rem 0.6rem;
      border-radius: 6px;
      font-size: 0.88rem;
      width: 110px;
      font-weight: bold;
    }
    .calc-badge {
      background: rgba(16, 185, 129, 0.15);
      color: var(--accent-green);
      padding: 0.35rem 0.75rem;
      border-radius: 6px;
      font-size: 0.82rem;
      border: 1px solid rgba(16, 185, 129, 0.4);
    }
    .pos-size-box {
      background: rgba(16, 185, 129, 0.06);
      border: 1px dashed rgba(16, 185, 129, 0.35);
      border-radius: 6px;
      padding: 0.45rem 0.75rem;
      font-size: 0.84rem;
      color: #e2e8f0;
      margin-top: 0.6rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 0.4rem;
    }

    /* コントロールバー */
    .controls {
      display: flex;
      flex-wrap: wrap;
      gap: 0.75rem;
      margin-bottom: 1.5rem;
      align-items: center;
      background: rgba(255,255,255,0.03);
      padding: 0.75rem;
      border-radius: 8px;
      border: 1px solid var(--border);
    }
    .controls input, .controls select {
      background: var(--card-bg);
      border: 1px solid var(--border);
      color: var(--text-main);
      padding: 0.4rem 0.75rem;
      border-radius: 6px;
      font-size: 0.9rem;
    }

    .card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 1.25rem;
      margin-bottom: 1.5rem;
      box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
    }
    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 0.75rem;
      border-bottom: 1px solid rgba(255, 255, 255, 0.07);
      padding-bottom: 0.6rem;
    }
    .stock-title-wrap { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
    .stock-title { font-size: 1.25rem; font-weight: bold; }
    
    /* 確信度バッジ */
    .tier-badge { font-size: 0.75rem; font-weight: bold; padding: 3px 8px; border-radius: 4px; display: inline-flex; align-items: center; }
    .tier-badge-s { background: linear-gradient(135deg, #7e22ce, #eab308); color: #ffffff; border: 1px solid #facc15; }
    .tier-badge-a { background: rgba(16, 185, 129, 0.2); color: var(--accent-green); border: 1px solid var(--accent-green); }
    .tier-badge-b { background: rgba(56, 189, 248, 0.2); color: var(--accent-blue); border: 1px solid var(--accent-blue); }

    .badge-stay { background: #3b82f6; color: white; font-size: 0.7rem; font-weight: bold; padding: 2px 6px; border-radius: 4px; }
    .badge-new { background: #f59e0b; color: white; font-size: 0.7rem; font-weight: bold; padding: 2px 6px; border-radius: 4px; }
    
    /* クオンツ・需給タグ */
    .quant-tags { display: flex; gap: 0.4rem; flex-wrap: wrap; margin-top: 0.35rem; }
    .pill { font-size: 0.72rem; padding: 2px 6px; border-radius: 4px; font-weight: 500; }
    .pill-theme { background: rgba(56, 189, 248, 0.12); color: var(--accent-blue); }
    .pill-moat { background: rgba(168, 85, 247, 0.15); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.4); }
    .pill-vcp { background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.5); font-weight: bold; }
    .pill-rs { background: rgba(16, 185, 129, 0.12); color: var(--accent-green); }
    .pill-founder { background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.4); }
    .pill-cash { background: rgba(16, 185, 129, 0.18); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.4); }
    .pill-turnaround { background: rgba(234, 179, 8, 0.18); color: #facc15; border: 1px solid rgba(234, 179, 8, 0.4); }
    .pill-light { background: rgba(244, 114, 182, 0.18); color: #f472b6; border: 1px solid rgba(244, 114, 182, 0.4); }
    .pill-ipo { background: rgba(52, 211, 153, 0.18); color: #34d399; border: 1px solid rgba(52, 211, 153, 0.4); }
    .pill-accel { background: rgba(249, 115, 22, 0.18); color: #fb923c; border: 1px solid rgba(249, 115, 22, 0.4); }
    .pill-inst { background: rgba(147, 197, 253, 0.18); color: #60a5fa; border: 1px solid rgba(147, 197, 253, 0.4); }
    .pill-stage2 { background: rgba(59, 130, 246, 0.2); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.5); font-weight: bold; }
    .pill-gc { background: rgba(234, 179, 8, 0.2); color: #facc15; border: 1px solid rgba(234, 179, 8, 0.5); font-weight: bold; }
    .pill-base { background: rgba(168, 85, 247, 0.18); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.4); }
    .pill-macd { background: rgba(16, 185, 129, 0.18); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.4); }
    .pill-earnings-warn { background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.5); font-weight: bold; }
    .pill-earnings-post { background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.5); font-weight: bold; }
    .pill-clean-margin { background: rgba(14, 165, 233, 0.18); color: #38bdf8; border: 1px solid rgba(14, 165, 233, 0.4); }

    .score-badge {
      background: rgba(16, 185, 129, 0.15);
      color: var(--accent-green);
      font-weight: bold;
      font-size: 1.25rem;
      padding: 0.3rem 0.8rem;
      border-radius: 6px;
      border: 1px solid var(--accent-green);
      text-align: center;
      min-width: 70px;
    }

    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
      gap: 0.6rem;
      margin-bottom: 0.85rem;
    }
    .stat-item { background: rgba(0, 0, 0, 0.25); padding: 0.5rem 0.65rem; border-radius: 6px; }
    .stat-label { font-size: 0.72rem; color: var(--text-sub); margin-bottom: 0.2rem; }
    .stat-val { font-size: 0.95rem; font-weight: bold; }

    .tam-bar {
      background: rgba(255, 255, 255, 0.03);
      border: 1px dashed var(--border);
      padding: 0.5rem 0.75rem;
      border-radius: 6px;
      font-size: 0.82rem;
      color: #cbd5e1;
      margin-bottom: 0.75rem;
    }

    .debate-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 0.75rem;
      margin-bottom: 0.85rem;
    }
    @media (max-width: 700px) {
      .debate-grid { grid-template-columns: 1fr; }
    }
    .bull-box {
      background: rgba(16, 185, 129, 0.05);
      border-left: 3px solid var(--accent-green);
      padding: 0.75rem;
      font-size: 0.86rem;
      line-height: 1.55;
      border-radius: 0 6px 6px 0;
    }
    .bear-box {
      background: rgba(239, 68, 68, 0.05);
      border-left: 3px solid var(--accent-red);
      padding: 0.75rem;
      font-size: 0.86rem;
      line-height: 1.55;
      border-radius: 0 6px 6px 0;
    }

    .plan-box {
      display: flex;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 0.75rem;
      font-size: 0.85rem;
      background: rgba(0, 0, 0, 0.3);
      padding: 0.6rem 0.85rem;
      border-radius: 6px;
      align-items: center;
    }
    .action-links { display: flex; gap: 0.5rem; margin-top: 0.3rem; align-items: center; flex-wrap: wrap; }
    .btn-link {
      font-size: 0.75rem;
      color: #94a3b8;
      text-decoration: none;
      background: rgba(255,255,255,0.06);
      padding: 0.3rem 0.6rem;
      border-radius: 4px;
      border: 1px solid var(--border);
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 0.25rem;
    }
    .btn-link:hover { color: #fff; background: rgba(255,255,255,0.12); border-color: var(--accent-blue); }
    
    /* TradingView チャートコンテナ */
    .tv-chart-wrap {
      display: none;
      height: 380px;
      margin-top: 0.75rem;
      border-radius: 8px;
      overflow: hidden;
      border: 1px solid var(--border);
      background: #131722;
    }

    /* トラックレコード パネル */
    .track-panel {
      background: linear-gradient(135deg, rgba(30, 41, 59, 0.9), rgba(15, 23, 42, 0.95));
      border: 1px solid rgba(56, 189, 248, 0.3);
      border-radius: 10px;
      padding: 1.1rem;
      margin-bottom: 1.75rem;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    }
    .track-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 0.85rem;
      flex-wrap: wrap;
      gap: 0.5rem;
    }
    .track-title {
      font-size: 1.05rem;
      font-weight: bold;
      color: #38bdf8;
      display: flex;
      align-items: center;
      gap: 0.4rem;
    }
    .track-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
      gap: 0.6rem;
      margin-bottom: 0.85rem;
    }
    .track-stat {
      background: rgba(0, 0, 0, 0.3);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 0.6rem;
      text-align: center;
    }
    .track-label { font-size: 0.72rem; color: var(--text-sub); margin-bottom: 0.2rem; }
    .track-val { font-size: 1.15rem; font-weight: bold; }
    .track-table-wrap {
      overflow-x: auto;
      margin-top: 0.6rem;
    }
    .track-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.78rem;
    }
    .track-table th, .track-table td {
      padding: 0.45rem 0.6rem;
      text-align: left;
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    }
    .track-table th { color: var(--text-sub); font-weight: 500; background: rgba(0,0,0,0.2); }
    .badge-win { color: var(--accent-green); font-weight: bold; }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 0.75rem;">
        <div>
          <h1>🎯 Tenbagger Hunter Pro 厳選AIレポート</h1>
          <div class="updated">生成日時: <span id="headerGeneratedAt">{{ generated_at }}</span> | 厳選プール: <span id="headerPoolSize">{{ total_screened }}件</span></div>
        </div>
        {% if archive_dates and archive_dates|length > 1 %}
        <div style="background: rgba(255,255,255,0.05); padding: 0.4rem 0.75rem; border-radius: 6px; border: 1px solid var(--border);">
          <label style="font-size: 0.75rem; color: var(--text-sub); display: block; margin-bottom: 2px;">📅 レポート履歴 (即時切替)</label>
          <select id="archiveSelect" style="background: var(--card-bg); color: var(--text-main); border: 1px solid var(--border); border-radius: 4px; padding: 2px 6px; font-size: 0.8rem;">
            {% for d in archive_dates %}
              <option value="{{ d }}" {% if loop.first %}selected{% endif %}>{{ d }}{% if loop.first %} (最新週){% endif %}</option>
            {% endfor %}
          </select>
        </div>
        {% endif %}
      </div>
    </header>

    <!-- 主要指数パネル -->
    <div class="market-panel">
      {% for m in market_indices %}
      <div class="market-card">
        <div class="market-title">{{ m.icon }} {{ m.name }} <span style="font-size: 0.72rem; color: var(--text-sub); font-weight: normal;">({{ m.desc }})</span></div>
        <div class="market-val">{{ m.display_val }}</div>
        <div class="market-change">
          <div>前週比: <span class="{% if m.week_diff >= 0 %}pos{% else %}neg{% endif %}">{% if m.week_diff > 0 %}+{% endif %}{{ m.week_pct }}% ({{ m.display_week_diff }})</span></div>
          <div>年初来: <span class="{% if m.ytd_diff >= 0 %}pos{% else %}neg{% endif %}">{% if m.ytd_diff > 0 %}+{% endif %}{{ m.ytd_pct }}% ({{ m.display_ytd_diff }})</span></div>
        </div>
      </div>
      {% endfor %}
    </div>

    <!-- 🏆 トラックレコード & 勝率実績パネル -->
    {% if track_record and track_record.total_recommended > 0 %}
    <div class="track-panel">
      <div class="track-header">
        <div class="track-title">🏆 過去推奨銘柄の実績・トラックレコード</div>
        <div style="font-size: 0.75rem; color: var(--text-sub);">直近推奨銘柄の追跡＆パフォーマンス集計</div>
      </div>
      <div class="track-grid">
        <div class="track-stat">
          <div class="track-label">累計推奨銘柄数</div>
          <div class="track-val">{{ track_record.total_recommended }}件</div>
        </div>
        <div class="track-stat">
          <div class="track-label">利確達成・勝率</div>
          <div class="track-val" style="color: var(--accent-green);">{{ track_record.win_rate_pct }}%</div>
        </div>
        <div class="track-stat">
          <div class="track-label">平均最高上昇率</div>
          <div class="track-val" style="color: var(--accent-gold);">+{{ track_record.avg_max_gain_pct }}%</div>
        </div>
        <div class="track-stat">
          <div class="track-label">+50%超大化け株</div>
          <div class="track-val" style="color: #c084fc;">{{ track_record.tenbagger_candidates }}銘柄</div>
        </div>
      </div>
      {% if track_record.records %}
      <div class="track-table-wrap">
        <table class="track-table">
          <thead>
            <tr>
              <th>推奨日</th>
              <th>銘柄</th>
              <th>推奨時価格</th>
              <th>最高到達値</th>
              <th>最高上昇率</th>
              <th>ステータス</th>
            </tr>
          </thead>
          <tbody>
            {% for r in track_record.records %}
            <tr>
              <td style="color: var(--text-sub);">{{ r.date }}</td>
              <td><strong>{{ r.code }} {{ r.name }}</strong> <span style="font-size: 0.7rem; color: var(--text-sub);">({{ r.conviction_tier }})</span></td>
              <td>{{ r.recommend_price }}円</td>
              <td>{{ r.high_price }}円</td>
              <td class="{% if r.max_gain_pct > 0 %}badge-win{% else %}neg{% endif %}">{% if r.max_gain_pct > 0 %}+{% endif %}{{ r.max_gain_pct }}%</td>
              <td>
                <span class="pill {% if '利確' in r.status %}pill-cash{% elif '損切' in r.status %}pill-vcp{% else %}pill-theme{% endif %}">{{ r.status }}</span>
              </td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
      {% endif %}
    </div>
    {% endif %}

    <!-- 📊 セクター分散・構成比バー -->
    {% if sector_dist %}
    <div id="sectorDistBar" style="display: flex; gap: 0.4rem; flex-wrap: wrap; margin-bottom: 1.25rem; align-items: center; background: rgba(255,255,255,0.03); padding: 0.5rem 0.75rem; border-radius: 6px; border: 1px solid var(--border);">
      <span style="font-size: 0.75rem; color: var(--text-sub); font-weight: bold;">📊 セクター分散:</span>
      {% for sec, count in sector_dist.items() %}
        <span class="pill pill-theme" style="font-size: 0.72rem;">{{ sec }} ({{ count }}件)</span>
      {% endfor %}
    </div>
    {% endif %}

    <!-- 💰 資金管理・適正ポジションサイジング計算機 (Risk Management & Sizing Calculator) -->
    <div class="calc-panel">
      <div style="display: flex; align-items: center; gap: 0.5rem;">
        <span style="font-size: 1.2rem;">💰</span>
        <div>
          <strong style="font-size: 0.95rem; color: #38bdf8;">資金管理・適正ポジションサイジング計算機</strong>
          <div style="font-size: 0.75rem; color: var(--text-sub);">1トレードの許容リスク（2%ルール）に基づき、各銘柄の推奨ロット数と概算投資額を即時計算します</div>
        </div>
      </div>
      <div class="calc-inputs">
        <div class="calc-group">
          <label style="color: var(--text-sub); font-size: 0.8rem;">総投資資金:</label>
          <input type="number" id="calcCapital" class="calc-input" value="1000000" step="100000" min="100000" oninput="updatePositionSizes()">
          <span style="font-size: 0.8rem; color: var(--text-sub);">円</span>
        </div>
        <div class="calc-group">
          <label style="color: var(--text-sub); font-size: 0.8rem;">許容リスク率:</label>
          <input type="number" id="calcRiskPct" class="calc-input" value="2.0" step="0.5" min="0.5" max="10.0" style="width: 65px;" oninput="updatePositionSizes()">
          <span style="font-size: 0.8rem; color: var(--text-sub);">%</span>
        </div>
        <div class="calc-badge">
          1銘柄の許容損失: <strong id="calcRiskBudgetDisplay" style="color: #fff;">20,000 円</strong>
        </div>
      </div>
    </div>

    <div class="controls">
      <div>
        <label style="font-size: 0.85rem; color: var(--text-sub);">並び替え:</label>
        <select id="sortSelect" onchange="sortCards()">
          <option value="score">AIスコア順</option>
          <option value="conviction">確信度順 (S > A > B)</option>
          <option value="rs">RS（市場相対力）順</option>
          <option value="market_cap">時価総額が小さい順</option>
          <option value="surge">出来高急増率順</option>
          <option value="growth">売上成長率順</option>
        </select>
      </div>
      <div>
        <input type="text" id="filterInput" onkeyup="filterCards()" placeholder="銘柄名・コード・テーマ検索...">
      </div>
    </div>

    <div id="cardsContainer">
      {% for stock in analyzed_stocks %}
      <div class="card" 
           data-score="{{ stock.analysis.score }}" 
           data-conviction="{{ stock.analysis.conviction_tier }}"
           data-rs="{{ stock.rs_rating or 0 }}"
           data-market-cap="{{ stock.market_cap_oku }}"
           data-surge="{{ stock.vol_surge }}"
           data-growth="{{ stock.rev_growth_pct }}"
           data-text="{{ stock.code }} {{ stock.name }} {{ stock.sector }} {{ stock.analysis.conviction_tier }} {{ ' '.join(stock.analysis.theme_tags) }}">
        
        <div class="card-header">
          <div>
            <div class="stock-title-wrap">
              <span class="stock-title">{{ stock.code }} {{ stock.name }}</span>
              <span style="font-size: 0.85rem; color: var(--text-sub);">({{ stock.market }} / {{ stock.sector }})</span>
              
              <!-- 確信度バッジ -->
              {% if stock.analysis.conviction_tier == 'S' %}
                <span class="tier-badge tier-badge-s">★Sランク超本命</span>
              {% elif stock.analysis.conviction_tier == 'A' %}
                <span class="tier-badge tier-badge-a">Aランク有力</span>
              {% else %}
                <span class="tier-badge tier-badge-b">Bランク監視</span>
              {% endif %}

              {% if stock.badge == 'STAY' %}
                <span class="badge-stay">2週連続</span>
              {% else %}
                <span class="badge-new">今週初</span>
              {% endif %}
            </div>

            <!-- クオンツ・需給・Moatタグ -->
            <div class="quant-tags">
              {% if stock.is_earnings_imminent %}
                <span class="pill pill-earnings-warn">⚠️ 決算直前 (あと{{ stock.days_to_earnings }}日・ガチャ警戒)</span>
              {% elif stock.is_post_earnings %}
                <span class="pill pill-earnings-post">⚡ 決算通過直後 (好決算初動)</span>
              {% endif %}
              {% if stock.is_clean_margin %}
                <span class="pill pill-clean-margin">💎 需給クリーン (しこり玉小)</span>
              {% endif %}
              {% if stock.is_ultra_light %}
                <span class="pill pill-light">🎈 浮動株 {{ stock.float_mcap_oku }}億 (超軽量)</span>
              {% endif %}
              {% if stock.is_vcp %}
                <span class="pill pill-vcp">🔥 VCP売り枯れ点灯</span>
              {% endif %}
              <span class="pill pill-rs">RS: +{{ stock.rs_rating }}%</span>
              <span class="pill pill-moat">🏰 参入障壁: {{ stock.analysis.moat_rating }}</span>
              {% if stock.insider_held_pct and stock.insider_held_pct >= 20 %}
                <span class="pill pill-founder">👑 創業者等: {{ stock.insider_held_pct }}%</span>
              {% endif %}
              {% if stock.is_stage2 %}
                <span class="pill pill-stage2">🌊 Stage 2 (本格上昇トレンド)</span>
              {% endif %}
              {% if stock.is_golden_cross %}
                <span class="pill pill-gc">✨ GC初動ブレイク</span>
              {% endif %}
              {% if stock.is_sound_base %}
                <span class="pill pill-base">📐 健全ベース形成</span>
              {% endif %}
              {% if stock.is_macd_bullish %}
                <span class="pill pill-macd">⚡ MACD好転</span>
              {% endif %}
              {% if stock.is_fresh_ipo %}
                <span class="pill pill-ipo">🌱 上場黄金期 (IPO1〜5年)</span>
              {% endif %}
              {% if stock.is_accelerating %}
                <span class="pill pill-accel">🚀 成長加速 (Acceleration)</span>
              {% endif %}
              {% if stock.is_early_inst %}
                <span class="pill pill-inst">💎 機関保有初期 ({{ stock.inst_held_pct }}%)</span>
              {% endif %}
              {% if stock.is_net_cash %}
                <span class="pill pill-cash">💰 実質無借金 (NetCash)</span>
              {% endif %}
              {% if stock.is_turnaround %}
                <span class="pill pill-turnaround">⚡ 黒字成長モメンタム</span>
              {% endif %}
              {% for tag in stock.analysis.theme_tags %}
                <span class="pill pill-theme">#{{ tag }}</span>
              {% endfor %}
            </div>
          </div>

          <div class="score-badge">
            <div style="font-size: 0.72rem; color: var(--text-sub); font-weight: normal;">潜在スコア</div>
            {{ stock.analysis.score }}点
          </div>
        </div>

        <div class="stats-grid">
          <div class="stat-item">
            <div class="stat-label">現在株価</div>
            <div class="stat-val">{{ stock.close }}円</div>
          </div>
          <div class="stat-item">
            <div class="stat-label">時価総額</div>
            <div class="stat-val">{{ stock.market_cap_oku }}億円</div>
          </div>
          <div class="stat-item">
            <div class="stat-label">売上高YoY</div>
            <div class="stat-val" style="color: {% if stock.rev_growth_pct > 15 %}var(--accent-green){% else %}inherit{% endif %}">+{{ stock.rev_growth_pct }}%</div>
          </div>
          <div class="stat-item">
            <div class="stat-label">営業利益率</div>
            <div class="stat-val" style="color: {% if stock.op_margin_pct > 10 %}var(--accent-green){% else %}inherit{% endif %}">+{{ stock.op_margin_pct }}%</div>
          </div>
          <div class="stat-item">
            <div class="stat-label">創業者保有比率</div>
            <div class="stat-val" style="color: {% if stock.insider_held_pct >= 30 %}var(--accent-gold){% else %}inherit{% endif %}">{% if stock.insider_held_pct %}{{ stock.insider_held_pct }}%{% else %}-{% endif %}</div>
          </div>
          <div class="stat-item">
            <div class="stat-label">PER / PSR</div>
            <div class="stat-val" style="font-size: 0.85rem;">{% if stock.trailing_pe %}{{ stock.trailing_pe }}倍{% else %}-{% endif %} / {% if stock.psr %}{{ stock.psr }}倍{% else %}-{% endif %}</div>
          </div>
          <div class="stat-item">
            <div class="stat-label">買値目安 / 損切り</div>
            <div class="stat-val" style="font-size: 0.85rem;">{{ stock.analysis.entry_price }} / <span style="color: var(--accent-red);">{{ stock.analysis.stop_loss }}</span></div>
          </div>
          <div class="stat-item">
            <div class="stat-label">リスクリワード比</div>
            <div class="stat-val" style="color: var(--accent-green);">1 : {{ stock.analysis.risk_reward_ratio }}</div>
          </div>
        </div>

        <!-- 推奨ポジションサイジング表示 -->
        <div class="pos-size-box">
          <div>
            <span>📐 <strong>推奨ポジション:</strong> </span>
            <span class="calc-shares" data-entry="{{ stock.analysis.entry_price or stock.close }}" data-stop="{{ stock.analysis.stop_loss or (stock.close * 0.92)|round(1) }}">-</span> 株
            <span style="color: var(--text-sub); margin-left: 4px;">(投資概算: <span class="calc-amount">-</span>万円)</span>
          </div>
          <div style="font-size: 0.72rem; color: var(--text-sub);">※損切りライン到達時の損失を許容リスク内に抑制</div>
        </div>

        <!-- TAM 市場規模表示 -->
        <div class="tam-bar" style="margin-top: 0.75rem;">
          <strong>🌐 獲得可能市場 (TAM):</strong> {{ stock.analysis.tam_scale }}
        </div>

        <!-- Bull/Bear ディベートボックス -->
        <div class="debate-grid">
          <div class="bull-box">
            <strong style="color: var(--accent-green);">🚀【強気シナリオ＆カタリスト】</strong><br>
            {{ stock.analysis.growth_story }}
          </div>
          <div class="bear-box">
            <strong style="color: var(--accent-red);">🛡️【弱気・落とし穴リスク監査】</strong><br>
            {{ stock.analysis.risk_factors }}
          </div>
        </div>

        <div class="plan-box">
          <div style="font-size: 0.8rem; color: var(--text-sub);">
            25MA: {{ stock.sma25 }}円 (乖離: +{{ stock.deviation_25_pct }}%) | 52週高値: {{ stock.high_52w }}円 | 大口比: {{ stock.up_down_ratio }}倍
          </div>
          <div class="action-links">
            <button type="button" class="btn-link tv-toggle-btn" id="tv-btn-{{ stock.code }}" onclick="toggleTvChart('{{ stock.code }}')">📈 チャート展開</button>
            <a class="btn-link" href="https://kabutan.jp/stock/chart?code={{ stock.code }}" target="_blank">📊 株探チャート</a>
            <a class="btn-link" href="https://jp.tradingview.com/symbols/TSE-{{ stock.code }}/" target="_blank">↗ TradingView</a>
          </div>
        </div>

        <!-- TradingView インラインチャート領域 -->
        <div id="tv-container-wrap-{{ stock.code }}" class="tv-chart-wrap">
          <div id="tv-container-{{ stock.code }}" style="height: 100%; width: 100%;"></div>
        </div>
      </div>
      {% endfor %}
    </div>
  </div>

  <!-- 過去履歴 JSON 埋め込み (SPA即時切り替え用) -->
  <script id="historyData" type="application/json">
{{ all_history_json | safe }}
  </script>

  <script>
    const activeTvWidgets = {};

    function toggleTvChart(code) {
      const wrap = document.getElementById(`tv-container-wrap-${code}`);
      const btn = document.getElementById(`tv-btn-${code}`);
      if (!wrap) return;

      if (wrap.style.display === "none" || !wrap.style.display) {
        wrap.style.display = "block";
        if (btn) btn.textContent = "📉 チャート閉じる";
        if (!activeTvWidgets[code] && window.TradingView) {
          activeTvWidgets[code] = new TradingView.widget({
            "autosize": true,
            "symbol": `TSE:${code}`,
            "interval": "D",
            "timezone": "Asia/Tokyo",
            "theme": "dark",
            "style": "1",
            "locale": "ja",
            "toolbar_bg": "#151d30",
            "enable_publishing": false,
            "allow_symbol_change": false,
            "container_id": `tv-container-${code}`
          });
        }
      } else {
        wrap.style.display = "none";
        if (btn) btn.textContent = "📈 チャート展開";
      }
    }

    function updatePositionSizes() {
      const capitalInput = document.getElementById("calcCapital");
      const riskPctInput = document.getElementById("calcRiskPct");
      const capital = parseFloat(capitalInput ? capitalInput.value : 1000000) || 1000000;
      const riskPct = (parseFloat(riskPctInput ? riskPctInput.value : 2.0) || 2.0) / 100.0;
      const riskBudget = capital * riskPct;
      const riskBudgetDisplay = document.getElementById("calcRiskBudgetDisplay");
      if (riskBudgetDisplay) {
        riskBudgetDisplay.textContent = Math.round(riskBudget).toLocaleString() + " 円";
      }

      document.querySelectorAll(".card").forEach(card => {
        const sharesEl = card.querySelector(".calc-shares");
        const amountEl = card.querySelector(".calc-amount");
        if (!sharesEl) return;
        
        const entry = parseFloat(sharesEl.dataset.entry) || 0;
        const stop = parseFloat(sharesEl.dataset.stop) || (entry * 0.92);
        
        if (entry <= 0) {
          sharesEl.textContent = "-";
          if (amountEl) amountEl.textContent = "-";
          return;
        }

        const riskPerShare = Math.max(entry - stop, entry * 0.05);
        let shares = Math.floor(riskBudget / riskPerShare / 100) * 100;
        if (shares < 100) shares = 100;
        
        const totalCostMan = (shares * entry) / 10000;
        sharesEl.textContent = shares.toLocaleString();
        if (amountEl) amountEl.textContent = totalCostMan.toFixed(1);
      });
    }

    function sortCards() {
      const criteria = document.getElementById("sortSelect").value;
      const container = document.getElementById("cardsContainer");
      const cards = Array.from(container.getElementsByClassName("card"));

      const tierRank = {"S": 3, "A": 2, "B": 1};

      cards.sort((a, b) => {
        if (criteria === "score") return Number(b.dataset.score) - Number(a.dataset.score);
        if (criteria === "conviction") return (tierRank[b.dataset.conviction] || 0) - (tierRank[a.dataset.conviction] || 0);
        if (criteria === "rs") return Number(b.dataset.rs) - Number(a.dataset.rs);
        if (criteria === "market_cap") return Number(a.dataset.marketCap) - Number(b.dataset.marketCap);
        if (criteria === "surge") return Number(b.dataset.surge) - Number(a.dataset.surge);
        if (criteria === "growth") return Number(b.dataset.growth) - Number(a.dataset.growth);
        return 0;
      });

      cards.forEach(c => container.appendChild(c));
    }

    function filterCards() {
      const q = document.getElementById("filterInput").value.toLowerCase();
      const cards = document.getElementsByClassName("card");
      for (let card of cards) {
        const text = card.dataset.text.toLowerCase();
        card.style.display = text.includes(q) ? "block" : "none";
      }
    }

    function renderStockCard(stock) {
      const a = stock.analysis || {};
      const score = a.score || stock.score || 80;
      const conviction = a.conviction_tier || stock.conviction_tier || "A";
      const entry = a.entry_price || stock.entry_price || stock.close || stock.recommend_price || 0;
      const stop = a.stop_loss || stock.stop_loss || Math.round(entry * 0.92);
      const rr = a.risk_reward_ratio || stock.risk_reward_ratio || 3.0;
      const tags = a.theme_tags || stock.theme_tags || [stock.sector || "新興"];
      const moat = a.moat_rating || stock.moat_rating || "MEDIUM";
      const tam = a.tam_scale || stock.tam_scale || (stock.sector + "市場");
      const story = a.growth_story || stock.growth_story || "";
      const risk = a.risk_factors || stock.risk_factors || "";
      const rs = stock.rs_rating || 0;
      const mcap = stock.market_cap_oku || 0;
      const surge = stock.vol_surge || 1.0;
      const growth = stock.rev_growth_pct || 0;
      const opMargin = stock.op_margin_pct || 0;
      const insider = stock.insider_held_pct ? `${stock.insider_held_pct}%` : "-";
      const pe = stock.trailing_pe ? `${stock.trailing_pe}倍` : "-";
      const psr = stock.psr ? `${stock.psr}倍` : "-";

      let tierBadge = `<span class="tier-badge tier-badge-b">Bランク監視</span>`;
      if (conviction === "S") tierBadge = `<span class="tier-badge tier-badge-s">★Sランク超本命</span>`;
      else if (conviction === "A") tierBadge = `<span class="tier-badge tier-badge-a">Aランク有力</span>`;

      let stayBadge = stock.badge === "STAY" 
        ? `<span class="badge-stay">2週連続</span>` 
        : `<span class="badge-new">今週初</span>`;

      let quantTagsHtml = "";
      if (stock.is_earnings_imminent) quantTagsHtml += `<span class="pill pill-earnings-warn">⚠️ 決算直前 (あと${stock.days_to_earnings || 0}日)</span>`;
      else if (stock.is_post_earnings) quantTagsHtml += `<span class="pill pill-earnings-post">⚡ 決算通過直後</span>`;
      if (stock.is_clean_margin) quantTagsHtml += `<span class="pill pill-clean-margin">💎 需給クリーン</span>`;
      if (stock.is_ultra_light) quantTagsHtml += `<span class="pill pill-light">🎈 浮動株 ${stock.float_mcap_oku || mcap}億 (超軽量)</span>`;
      if (stock.is_vcp) quantTagsHtml += `<span class="pill pill-vcp">🔥 VCP売り枯れ点灯</span>`;
      quantTagsHtml += `<span class="pill pill-rs">RS: +${rs}%</span>`;
      quantTagsHtml += `<span class="pill pill-moat">🏰 参入障壁: ${moat}</span>`;
      if (stock.insider_held_pct && stock.insider_held_pct >= 20) quantTagsHtml += `<span class="pill pill-founder">👑 創業者等: ${stock.insider_held_pct}%</span>`;
      if (stock.is_stage2) quantTagsHtml += `<span class="pill pill-stage2">🌊 Stage 2</span>`;
      if (stock.is_golden_cross) quantTagsHtml += `<span class="pill pill-gc">✨ GC初動</span>`;
      if (stock.is_sound_base) quantTagsHtml += `<span class="pill pill-base">📐 健全ベース</span>`;
      if (stock.is_macd_bullish) quantTagsHtml += `<span class="pill pill-macd">⚡ MACD好転</span>`;
      if (stock.is_fresh_ipo) quantTagsHtml += `<span class="pill pill-ipo">🌱 上場黄金期</span>`;
      if (stock.is_accelerating) quantTagsHtml += `<span class="pill pill-accel">🚀 成長加速</span>`;
      if (stock.is_early_inst) quantTagsHtml += `<span class="pill pill-inst">💎 機関保有初期 (${stock.inst_held_pct || 0}%)</span>`;
      if (stock.is_net_cash) quantTagsHtml += `<span class="pill pill-cash">💰 実質無借金</span>`;
      if (stock.is_turnaround) quantTagsHtml += `<span class="pill pill-turnaround">⚡ 黒字成長</span>`;
      tags.forEach(t => { quantTagsHtml += `<span class="pill pill-theme">#${t}</span>`; });

      return `
        <div class="card" 
             data-score="${score}" 
             data-conviction="${conviction}"
             data-rs="${rs}"
             data-market-cap="${mcap}"
             data-surge="${surge}"
             data-growth="${growth}"
             data-text="${stock.code} ${stock.name} ${stock.sector || ''} ${conviction} ${tags.join(' ')}">
          
          <div class="card-header">
            <div>
              <div class="stock-title-wrap">
                <span class="stock-title">${stock.code} ${stock.name}</span>
                <span style="font-size: 0.85rem; color: var(--text-sub);">(${stock.market || ''} / ${stock.sector || ''})</span>
                ${tierBadge}
                ${stayBadge}
              </div>
              <div class="quant-tags">
                ${quantTagsHtml}
              </div>
            </div>
            <div class="score-badge">
              <div style="font-size: 0.72rem; color: var(--text-sub); font-weight: normal;">潜在スコア</div>
              ${score}点
            </div>
          </div>

          <div class="stats-grid">
            <div class="stat-item">
              <div class="stat-label">現在株価</div>
              <div class="stat-val">${stock.close || stock.recommend_price || 0}円</div>
            </div>
            <div class="stat-item">
              <div class="stat-label">時価総額</div>
              <div class="stat-val">${mcap}億円</div>
            </div>
            <div class="stat-item">
              <div class="stat-label">売上高YoY</div>
              <div class="stat-val" style="color: ${growth > 15 ? 'var(--accent-green)' : 'inherit'};">+${growth}%</div>
            </div>
            <div class="stat-item">
              <div class="stat-label">営業利益率</div>
              <div class="stat-val" style="color: ${opMargin > 10 ? 'var(--accent-green)' : 'inherit'};">+${opMargin}%</div>
            </div>
            <div class="stat-item">
              <div class="stat-label">創業者保有比率</div>
              <div class="stat-val" style="color: ${stock.insider_held_pct >= 30 ? 'var(--accent-gold)' : 'inherit'};">${insider}</div>
            </div>
            <div class="stat-item">
              <div class="stat-label">PER / PSR</div>
              <div class="stat-val" style="font-size: 0.85rem;">${pe} / ${psr}</div>
            </div>
            <div class="stat-item">
              <div class="stat-label">買値目安 / 損切り</div>
              <div class="stat-val" style="font-size: 0.85rem;">${entry} / <span style="color: var(--accent-red);">${stop}</span></div>
            </div>
            <div class="stat-item">
              <div class="stat-label">リスクリワード比</div>
              <div class="stat-val" style="color: var(--accent-green);">1 : ${rr}</div>
            </div>
          </div>

          <div class="pos-size-box">
            <div>
              <span>📐 <strong>推奨ポジション:</strong> </span>
              <span class="calc-shares" data-entry="${entry}" data-stop="${stop}">-</span> 株
              <span style="color: var(--text-sub); margin-left: 4px;">(投資概算: <span class="calc-amount">-</span>万円)</span>
            </div>
            <div style="font-size: 0.72rem; color: var(--text-sub);">※損切りライン到達時の損失を許容リスク内に抑制</div>
          </div>

          ${tam ? `<div class="tam-bar" style="margin-top: 0.75rem;"><strong>🌐 獲得可能市場 (TAM):</strong> ${tam}</div>` : ''}

          ${story || risk ? `
          <div class="debate-grid">
            <div class="bull-box">
              <strong style="color: var(--accent-green);">🚀【強気シナリオ＆カタリスト】</strong><br>
              ${story || 'モメンタムと需給構造を維持。'}
            </div>
            <div class="bear-box">
              <strong style="color: var(--accent-red);">🛡️【弱気・落とし穴リスク監査】</strong><br>
              ${risk || 'テクニカル急変・市場全体の下落に注意。'}
            </div>
          </div>` : ''}

          <div class="plan-box">
            <div style="font-size: 0.8rem; color: var(--text-sub);">
              25MA: ${stock.sma25 || '-'}円 (乖離: +${stock.deviation_25_pct || 0}%) | 52週高値: ${stock.high_52w || '-'}円 | 大口比: ${stock.up_down_ratio || 1.0}倍
            </div>
            <div class="action-links">
              <button type="button" class="btn-link tv-toggle-btn" id="tv-btn-${stock.code}" onclick="toggleTvChart('${stock.code}')">📈 チャート展開</button>
              <a class="btn-link" href="https://kabutan.jp/stock/chart?code=${stock.code}" target="_blank">📊 株探チャート</a>
              <a class="btn-link" href="https://jp.tradingview.com/symbols/TSE-${stock.code}/" target="_blank">↗ TradingView</a>
            </div>
          </div>

          <div id="tv-container-wrap-${stock.code}" class="tv-chart-wrap">
            <div id="tv-container-${stock.code}" style="height: 100%; width: 100%;"></div>
          </div>
        </div>
      `;
    }

    function initArchiveSwitcher() {
      const select = document.getElementById("archiveSelect");
      if (!select) return;

      const initialContainerHtml = document.getElementById("cardsContainer").innerHTML;
      const historyDataEl = document.getElementById("historyData");
      let historyMap = {};
      if (historyDataEl && historyDataEl.textContent.trim()) {
        try {
          historyMap = JSON.parse(historyDataEl.textContent);
        } catch (e) {
          console.error("履歴データ解析エラー:", e);
        }
      }

      select.addEventListener("change", (e) => {
        const chosenDate = e.target.value;
        const container = document.getElementById("cardsContainer");
        const headerGenAt = document.getElementById("headerGeneratedAt");
        const headerPool = document.getElementById("headerPoolSize");

        if (select.selectedIndex === 0) {
          container.innerHTML = initialContainerHtml;
          updatePositionSizes();
          sortCards();
          return;
        }

        const list = historyMap[chosenDate];
        if (list && list.length > 0) {
          container.innerHTML = list.map(renderStockCard).join("");
          if (headerGenAt) headerGenAt.textContent = `${chosenDate} (アーカイブ)`;
          if (headerPool) headerPool.textContent = `${list.length}件`;
          updatePositionSizes();
          sortCards();
        }
      });
    }

    window.addEventListener("DOMContentLoaded", () => {
      updatePositionSizes();
      initArchiveSwitcher();
    });
  </script>
</body>
</html>
"""

def clean_and_parse_json(text):
    try:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            return json.loads(match.group(0))
        cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)
        return json.loads(cleaned)
    except Exception:
        return None

def analyze_stock_with_gemini(client, stock_info, macro_context=""):
    vcp_status = "点灯中（売り圧力枯渇・ブレイクアウト直前）" if stock_info.get("is_vcp") else "通常推移"
    psr_str = f"{stock_info.get('psr')}倍" if stock_info.get("psr") else "算出外"
    pe_str = f"{stock_info.get('trailing_pe')}倍" if stock_info.get("trailing_pe") else "算出外"
    insider_str = f"{stock_info.get('insider_held_pct')}%" if stock_info.get("insider_held_pct") else "未開示/微小"
    summary_str = stock_info.get("business_summary") or "新興成長企業"
    float_str = f"{stock_info.get('float_mcap_oku')}億円（超軽量需給）" if stock_info.get("is_ultra_light") else f"{stock_info.get('float_mcap_oku', stock_info['market_cap_oku'])}億円"
    cash_str = "実質無借金（現預金 > 有利子負債、希薄化リスク極小）" if stock_info.get("is_net_cash") else "通常"
    turnaround_str = "高成長・営業黒字定着" if stock_info.get("is_turnaround") else "通常推移"
    ipo_str = "上場1〜5年の黄金成長期（IPO初動）" if stock_info.get("is_fresh_ipo") else "通常期"
    accel_str = "売上・利益成長が加速中（Acceleration）" if stock_info.get("is_accelerating") else "通常成長"
    inst_str = f"{stock_info.get('inst_held_pct', 0)}%（機関投資家の青田買い・本格買い余地大）" if stock_info.get("is_early_inst") else f"{stock_info.get('inst_held_pct', 0)}%"
    trend_str = []
    if stock_info.get("is_stage2"):
        trend_str.append("Stage 2（200MA上向き・本格上昇トレンド）")
    if stock_info.get("is_golden_cross"):
        trend_str.append("直近ゴールデンクロス初動点灯")
    if stock_info.get("is_sound_base"):
        trend_str.append("高値圏の浅い健全ベース形成")
    trend_summary_str = " / ".join(trend_str) if trend_str else "上昇パーフェクトオーダー推移"

    # 決算ステータス ＆ 信用需給構造
    if stock_info.get("is_earnings_imminent"):
        days = stock_info.get("days_to_earnings", 0)
        earnings_str = f"次回決算発表まであと約{days}日（決算直前のギャンブル買い回避・発表後の内容確認推奨）"
    elif stock_info.get("is_post_earnings"):
        earnings_str = "決算発表通過直後（好業績カタリスト初動局面）"
    else:
        earnings_str = "通常期"

    margin_str = "個人投資家の信用しこり玉が極めて少なく、大口の買い集めが進行（需給良好）" if stock_info.get("is_clean_margin") else "通常需給"
    macro_info = macro_context if macro_context else "新興市場・マクロ相場は通常サイクル推移"

    prompt = f"""
あなたはお急成長小型株（テンバガー）投資のトップクオンツ＆ファンダメンタルズスペシャリストです。
以下のマクロ市場環境、企業スペック、需給指標（RS/VCP/浮動株）、トレンド構造（Stage 2/GC）、創業者比率、決算スケジュールに基づき、厳格なレッドチーム（強気・弱気ディベート）分析を実施し、売買プランを策定してください。

【現在のマクロ市場環境】
{macro_info}

【対象銘柄スペック】
銘柄コード: {stock_info['code']}
銘柄名: {stock_info['name']}
市場・業種: {stock_info['market']} / {stock_info['sector']}
公式事業概要: {summary_str}
トレンド構造: {trend_summary_str} (52週安値から+{stock_info.get('low_rebound_pct', 0)}%リバウンド)
決算ステータス: {earnings_str}
信用・需給構造: {margin_str}
上場ステージ: {ipo_str}
現在株価: {stock_info['close']}円
25日移動平均線: {stock_info.get('sma25')}円 (乖離: +{stock_info.get('deviation_25_pct')}%)
52週最高値: {stock_info.get('high_52w')}円 / 52週最安値: {stock_info.get('low_52w')}円
時価総額: {stock_info['market_cap_oku']}億円 (推定浮動株時価: {float_str})
財務健全性（ネットキャッシュ）: {cash_str}
収益モメンタム: {turnaround_str} / 成長加速度: {accel_str}
直近売上高成長率: +{stock_info.get('rev_growth_pct', 0)}%
直近営業利益率: +{stock_info.get('op_margin_pct', 0)}%
創業者・役員保有比率: {insider_str} / 機関投資家保有: {inst_str}
PER: {pe_str} / PSR: {psr_str}
マルチタイムRS（対グロース250加重超過リターン）: +{stock_info.get('rs_rating', 0)}%
出来高枯渇VCPシグナル: {vcp_status}
出来高急増比: {stock_info.get('vol_surge', 1.0)}倍

【分析・出力要件】
1. score: テンバガー潜在力総合スコア（0〜100）
2. conviction_tier: 確信度ランク（"S": 超本命・条件完全合致, "A": 有力成長株, "B": 監視・短期モメンタム型）
3. theme_tags: 合致する市場テーマ（最大3つ。例: ["AI", "DX", "次世代インフラ"]）
4. tam_scale: 獲得可能市場規模（TAM）の規模感（30字以内。例: 「国内5,000億円超のDX市場」「世界メガトレンド領域」）
5. moat_rating: 参入障壁・競争優位性（"HIGH": 独自特許/強固なスイッチングコスト, "MEDIUM": 先行者優位/高シェア, "LOW": 価格競争リスク）
6. growth_story: 10倍化への起爆シナリオ（強気視点、業績モメンタムやTAM展開を130〜150字程度で明瞭に記述）
7. risk_factors: 最大の警戒リスク・落とし穴（弱気監査視点、競合参入や一過性特需などを80字程度で厳格に記述）
8. entry_price: 押し目(25MA {stock_info.get('sma25')}円 付近)またはブレイク買い(52週高値 {stock_info.get('high_52w')}円 超)の目安価格
9. stop_loss: 厳格な損切りライン（買値または25MA割れ基準で約 -7%〜-8%）
10. risk_reward_ratio: リスクリワード比（数値のみ。例: 3.5）

以下のJSONフォーマットのみを返してください。
{{
  "score": 88,
  "conviction_tier": "S",
  "theme_tags": ["テーマ1", "テーマ2"],
  "tam_scale": "国内3,000億円超の市場",
  "moat_rating": "HIGH",
  "growth_story": "...",
  "risk_factors": "...",
  "entry_price": 0,
  "stop_loss": 0,
  "risk_reward_ratio": 3.5
}}
"""
    try:
        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=prompt,
            config={"response_mime_type": "application/json"}
        )
        res_json = clean_and_parse_json(response.text)
        if res_json and "score" in res_json and "growth_story" in res_json:
            if "theme_tags" not in res_json or not res_json["theme_tags"]:
                res_json["theme_tags"] = [stock_info["sector"]]
            if "conviction_tier" not in res_json or res_json["conviction_tier"] not in ("S", "A", "B"):
                res_json["conviction_tier"] = "A" if res_json["score"] >= 80 else "B"
            if "moat_rating" not in res_json:
                res_json["moat_rating"] = "MEDIUM"
            if "tam_scale" not in res_json:
                res_json["tam_scale"] = f"{stock_info['sector']}関連市場"
            if "risk_reward_ratio" not in res_json:
                res_json["risk_reward_ratio"] = 3.0
            return res_json, "SUCCESS"
    except Exception as e:
        err_msg = str(e).upper()
        print(f"[WARN] Gemini分析エラー ({stock_info['code']}): {e}")
        fatal_keywords = ["429", "RESOURCE_EXHAUSTED", "QUOTA", "401", "403", "UNAUTHORIZED", "PERMISSION"]
        if any(kw in err_msg for kw in fatal_keywords):
            return None, "FATAL_ERROR"
        return None, "RETRY_ERROR"

    return None, "RETRY_ERROR"

def main():
    print(f"[INFO] 候補ファイル確認: {CANDIDATES_FILE}")
    if not os.path.exists(CANDIDATES_FILE):
        print(f"[ERROR] {CANDIDATES_FILE} が見つかりません。")
        sys.exit(1)

    with open(CANDIDATES_FILE, "r", encoding="utf-8") as f:
        candidates = json.load(f)

    print(f"[INFO] スクリーニング候補: {len(candidates)}件")
    if not candidates:
        print("[INFO] 候補が0件のため終了します。")
        return

    if len(candidates) > MAX_AI_ANALYZE:
        candidates = candidates[:MAX_AI_ANALYZE]

    # 指数データの取得
    print("[INFO] 主要マクロ指数のパフォーマンスを取得中...")
    market_indices = fetch_market_indices()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("[CRITICAL ERROR] GEMINI_API_KEY が設定されていません。")
        sys.exit(1)

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=15000)
    )

    # 主要マクロ指数のサマリーコンテキスト生成
    macro_parts = []
    for m in market_indices:
        sign = "+" if m.get("week_diff", 0) > 0 else ""
        macro_parts.append(f"{m['name']}: {m['display_val']} (前週比: {sign}{m.get('week_pct', 0)}%)")
    macro_context = " / ".join(macro_parts)

    analyzed_stocks = []
    consecutive_transient_errors = 0
    print(f"[INFO] 厳選 {len(candidates)} 銘柄のGemini詳細分析（マクロ連動Red-Teamディベート）を開始...")

    for item in candidates:
        print(f"  -> 分析中: {item['code']} {item['name']}")
        analysis, status = analyze_stock_with_gemini(client, item, macro_context)
        
        if status == "FATAL_ERROR":
            print("[FATAL] クォータ枯渇または認証エラーを検知。緊急遮断します。")
            sys.exit(1)

        if status == "RETRY_ERROR":
            consecutive_transient_errors += 1
            print(f"[WARN] 一時的APIエラー (連続 {consecutive_transient_errors}/{MAX_TRANSIENT_ERRORS})")
            if consecutive_transient_errors >= MAX_TRANSIENT_ERRORS:
                print("[FATAL] 連続API障害のため緊急遮断します。")
                sys.exit(1)
            
            stop = round(float(item['close']) * 0.92, 1)
            analysis = {
                "score": 75,
                "conviction_tier": "B",
                "theme_tags": [item["sector"]],
                "tam_scale": f"{item['sector']}関連領域",
                "moat_rating": "MEDIUM",
                "growth_story": f"{item['name']}はモメンタムと出来高水準を維持。独自事業の進捗が注目点。",
                "risk_factors": "一時的な通信エラーのためテクニカル算定値を暫定表示。",
                "entry_price": item['close'],
                "stop_loss": stop,
                "risk_reward_ratio": 3.0
            }
        else:
            consecutive_transient_errors = 0

        item['analysis'] = analysis
        analyzed_stocks.append(item)
        time.sleep(0.3)

    analyzed_stocks.sort(key=lambda x: x['analysis']['score'], reverse=True)

    # セクター分布集計
    sector_dist = {}
    for s in analyzed_stocks:
        sec = s.get("sector", "その他")
        sector_dist[sec] = sector_dist.get(sec, 0) + 1

    # 週次アーカイブ保存 ＆ トラックレコード集計
    try:
        archive_weekly_results(analyzed_stocks)
        track_record = calculate_track_record()
    except Exception as e:
        print(f"[WARN] トラックレコード処理エラー: {e}")
        track_record = None

    # 過去アーカイブ日付一覧および全履歴データの取得
    import glob
    history_files = glob.glob(os.path.join(PROJECT_ROOT, "data", "history", "*.json"))
    archive_dates = sorted([os.path.splitext(os.path.basename(f))[0] for f in history_files], reverse=True)
    today_str = get_jst_now().strftime("%Y-%m-%d")
    if today_str not in archive_dates:
        archive_dates.insert(0, today_str)

    all_history_map = {}
    for hf in history_files:
        d_name = os.path.splitext(os.path.basename(hf))[0]
        try:
            with open(hf, "r", encoding="utf-8") as f:
                all_history_map[d_name] = json.load(f)
        except Exception:
            pass
    all_history_json = json.dumps(all_history_map, ensure_ascii=False)

    # HTML出力
    os.makedirs(OUTPUT_HTML_DIR, exist_ok=True)
    template = Template(HTML_TEMPLATE, autoescape=True)
    now_str = get_jst_now().strftime("%Y-%m-%d %H:%M JST")
    html_output = template.render(
        generated_at=now_str,
        today_date=today_str,
        total_screened=len(candidates),
        analyzed_stocks=analyzed_stocks,
        market_indices=market_indices,
        track_record=track_record,
        sector_dist=sector_dist,
        archive_dates=archive_dates,
        all_history_json=all_history_json
    )

    with open(OUTPUT_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html_output)

    file_size = os.path.getsize(OUTPUT_HTML_PATH)
    print(f"[INFO] レポート出力完了: {OUTPUT_HTML_PATH} ({file_size} bytes)")

    # LINE Flex Message 送信（指数カード ＋ 厳選個別株）
    repo_name = os.getenv("GITHUB_REPOSITORY", "sei1r0/tenbagger-hunter")
    pages_url = f"https://{repo_name.split('/')[0]}.github.io/{repo_name.split('/')[1]}/"

    send_flex_carousel("週末マーケット＆テンバガー厳選TOP", analyzed_stocks, pages_url, market_data=market_indices)
    print("[INFO] 全パイプライン処理が正常に完了しました。")

if __name__ == "__main__":
    main()
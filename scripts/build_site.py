#!/usr/bin/env python3
"""
Build a static HTML dashboard from markdown report files.
Generates docs/index.html with all historical data embedded.
"""
import json, re, os, glob
from datetime import datetime

REPORTS_DIR = "reports"
OUTPUT_DIR = "docs"
DATA_FILE = os.path.join(OUTPUT_DIR, "data.json")
HTML_FILE = os.path.join(OUTPUT_DIR, "index.html")

def parse_report(filepath):
    """Parse a markdown report into structured data."""
    with open(filepath) as f:
        text = f.read()

    data = {
        "date": "",
        "market": "",
        "summary": "",
        "stocks": [],
        "raw_md": text
    }

    # Extract date from first line: # 🎯 2026-06-26 决策仪表盘
    m = re.search(r'(\d{4}-\d{2}-\d{2})', text.split('\n')[0])
    if m:
        data["date"] = m.group(1)

    # Extract overall summary line
    # > 共分析 **N** 只股票 | 🟢买入:X 🟡观望:Y 🔴卖出:Z
    m = re.search(r'共分析 \*\*(\d+)\*\* 只股票.*?买入:(\d+).*?观望:(\d+).*?卖出:(\d+)', text)
    if m:
        data["summary"] = {
            "total": int(m.group(1)),
            "buy": int(m.group(2)),
            "hold": int(m.group(3)),
            "sell": int(m.group(4))
        }

    # Market state
    m = re.search(r'市场状态：(.+)', text)
    if m:
        data["market"] = m.group(1).strip()

    # Parse individual stocks
    # Stock blocks start with ## 🟠/🟢/🔴/🟡/⚪
    stock_blocks = re.split(r'\n## (?=[🟢🔴🟠🟡⚪])', text)

    # First, extract scores from summary section (the block before first stock)
    # 🟠 **XD贵州茅(600519)**: 减仓 | 评分 30 | 看空
    summary_scores = {}
    if stock_blocks:
        for m in re.finditer(r'([🟢🔴🟠🟡⚪])\s*\*\*(.+?)\((\d+)\)\*\*:\s*(.+?)\s*\|\s*评分\s*(\d+)\s*\|\s*(.+)', stock_blocks[0]):
            code = m.group(3)
            summary_scores[code] = {
                "signal": m.group(1),
                "action": m.group(4).strip(),
                "score": int(m.group(5)),
                "trend": m.group(6).strip()
            }

    for block in stock_blocks[1:]:  # skip the header/summary block
        stock = parse_stock_block(block, summary_scores)
        if stock:
            data["stocks"].append(stock)

    # Get model info
    m = re.search(r'\*分析模型：(.+)\*', text)
    if m:
        data["model"] = m.group(1).strip()

    return data

def parse_stock_block(block, summary_scores=None):
    """Parse a single stock section."""
    stock = {}
    lines = block.split('\n')

    # Header: 🟠 XD贵州茅 (600519)
    first = lines[0] if lines else ""
    m = re.match(r'([🟢🔴🟠🟡⚪])\s*(.+?)\s*\((\d+)\)', first)
    if m:
        stock["signal"] = m.group(1)
        stock["name"] = m.group(2).strip()
        stock["code"] = m.group(3)

    # Action/trend from core conclusion: **🟠 减仓** | 看空
    m = re.search(r'\*\*([🟢🔴🟠🟡⚪])\s*(.+?)\*\*\s*\|\s*(.+)', block)
    if m:
        stock["action"] = m.group(2).strip()
        stock["trend"] = m.group(3).strip()

    # Score from summary line
    m = re.search(r'评分\s*(\d+)', block)
    if m:
        stock["score"] = int(m.group(1))
    elif summary_scores and stock.get("code") in summary_scores:
        ss = summary_scores[stock["code"]]
        stock["score"] = ss.get("score", 0)
        if not stock.get("action"):
            stock["action"] = ss.get("action", "")
        if not stock.get("trend"):
            stock["trend"] = ss.get("trend", "")
    else:
        stock["score"] = 0

    # One-line decision
    m = re.search(r'一句话决策\*\*:\s*(.+)', block)
    if m:
        stock["decision"] = m.group(1).strip()

    # Price info from table
    for line in lines:
        m = re.match(r'\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([+\-][\d.]+%)\s*\|', line)
        if m:
            stock["price"] = {
                "close": m.group(1),
                "prev_close": m.group(2),
                "open": m.group(3),
                "high": m.group(4),
                "low": m.group(5),
                "change_pct": m.group(6)
            }
            break

    # Extract risk alerts
    risks = []
    in_risks = False
    for line in lines:
        if '风险警报' in line:
            in_risks = True
            continue
        if in_risks and line.startswith('- '):
            risks.append(line[2:].strip())
        elif in_risks and line.startswith('##'):
            break
    stock["risks"] = risks

    # Support/resistance
    for line in lines:
        m = re.match(r'\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|', line)
        # This matches MA rows too, but we catch them differently
        pass

    m = re.search(r'支撑位\s*\|\s*([\d.]+)', block)
    if m: stock["support"] = m.group(1)
    m = re.search(r'压力位\s*\|\s*([\d.]+)', block)
    if m: stock["resistance"] = m.group(1)
    m = re.search(r'止损位\s*\|\s*(.+?)(?:\||$)', block)
    if m: stock["stop_loss"] = m.group(1).strip()

    return stock if stock.get("code") else None

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Collect all reports sorted by date (newest first)
    report_files = sorted(glob.glob(f"{REPORTS_DIR}/report_*.md"), reverse=True)
    
    all_data = []
    for f in report_files:
        data = parse_report(f)
        if data["date"]:
            all_data.append(data)
            print(f"  Parsed: {f} -> {data['date']} ({len(data['stocks'])} stocks)")

    # Save data.json
    with open(DATA_FILE, 'w') as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)
    print(f"\nData saved to {DATA_FILE} ({len(all_data)} reports)")

    # Generate HTML
    generate_html(all_data)
    print(f"HTML saved to {HTML_FILE}")

def generate_html(all_data):
    data_json = json.dumps(all_data, ensure_ascii=False)

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>📈 股票智能分析仪表盘</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f1117; color: #e1e4e8; min-height: 100vh; }}
.header {{ background: linear-gradient(135deg, #1a1f2e 0%, #161b22 100%); border-bottom: 1px solid #30363d; padding: 20px 0; position: sticky; top: 0; z-index: 100; }}
.header h1 {{ text-align: center; font-size: 1.5em; }}
.container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
.date-selector {{ display: flex; gap: 10px; justify-content: center; margin: 20px 0; flex-wrap: wrap; }}
.date-btn {{ padding: 8px 16px; border: 1px solid #30363d; border-radius: 6px; background: #21262d; color: #c9d1d9; cursor: pointer; font-size: 0.9em; transition: all 0.2s; }}
.date-btn:hover {{ background: #30363d; }}
.date-btn.active {{ background: #1f6feb; border-color: #1f6feb; color: #fff; }}
.summary-bar {{ display: flex; gap: 20px; justify-content: center; margin: 20px 0; flex-wrap: wrap; }}
.summary-item {{ background: #21262d; border: 1px solid #30363d; border-radius: 10px; padding: 16px 24px; text-align: center; min-width: 100px; }}
.summary-item .num {{ font-size: 2em; font-weight: bold; }}
.summary-item .label {{ font-size: 0.85em; color: #8b949e; margin-top: 4px; }}
.buy .num {{ color: #3fb950; }}
.hold .num {{ color: #d29922; }}
.sell .num {{ color: #f85149; }}
.stock-card {{ background: #21262d; border: 1px solid #30363d; border-radius: 12px; padding: 24px; margin: 16px 0; }}
.stock-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 10px; }}
.stock-name {{ font-size: 1.3em; font-weight: bold; }}
.stock-code {{ color: #8b949e; font-size: 0.9em; }}
.stock-score {{ font-size: 1.1em; padding: 4px 12px; border-radius: 20px; }}
.score-buy {{ background: #1a3a1a; color: #3fb950; }}
.score-hold {{ background: #3a2e1a; color: #d29922; }}
.score-sell {{ background: #3a1a1a; color: #f85149; }}
.decision {{ background: #161b22; border-left: 3px solid #1f6feb; padding: 12px 16px; border-radius: 0 8px 8px 0; margin: 12px 0; font-style: italic; color: #8b949e; }}
.price-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; margin: 16px 0; }}
.price-item {{ background: #161b22; padding: 10px; border-radius: 8px; text-align: center; }}
.price-item .val {{ font-size: 1.2em; font-weight: bold; color: #58a6ff; }}
.price-item .lbl {{ font-size: 0.75em; color: #8b949e; margin-top: 4px; }}
.risks {{ margin: 12px 0; }}
.risks h4 {{ color: #f85149; margin-bottom: 8px; }}
.risks li {{ list-style: none; padding: 4px 0; color: #c9d1d9; font-size: 0.9em; }}
.risks li::before {{ content: "⚠️ "; }}
.levels {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin: 12px 0; }}
.level-item {{ background: #161b22; padding: 12px; border-radius: 8px; text-align: center; }}
.level-item .val {{ font-size: 1.1em; font-weight: bold; }}
.level-item .lbl {{ font-size: 0.75em; color: #8b949e; }}
.support {{ color: #3fb950; }}
.resistance {{ color: #f85149; }}
.stop {{ color: #d29922; }}
.market-info {{ text-align: center; color: #8b949e; font-size: 0.9em; margin: 10px 0; }}
.empty {{ text-align: center; padding: 60px 20px; color: #8b949e; }}
.empty h3 {{ font-size: 1.5em; margin-bottom: 10px; }}
.footer {{ text-align: center; padding: 20px; color: #484f58; font-size: 0.8em; border-top: 1px solid #30363d; margin-top: 40px; }}
</style>
</head>
<body>
<div class="header">
  <h1>📈 股票智能分析仪表盘</h1>
</div>
<div class="container">
  <div class="date-selector" id="dateSelector"></div>
  <div class="market-info" id="marketInfo"></div>
  <div class="summary-bar" id="summaryBar"></div>
  <div id="content"></div>
</div>
<div class="footer">
  报告由 AI 自动生成 · 仅供参考，不构成投资建议<br>
  Generated by Daily Stock Analysis System
</div>

<script>
const DATA = {data_json};

// Signal emoji mapping
const SIGNALS = {{'🟢': 'buy', '🟡': 'hold', '🟠': 'hold', '🔴': 'sell'}};

function renderDateSelector() {{
    const el = document.getElementById('dateSelector');
    el.innerHTML = DATA.map((d, i) => 
        `<button class="date-btn ${{i === 0 ? 'active' : ''}}" onclick="showReport(${{i}})">${{d.date}}</button>`
    ).join('');
}}

function showReport(idx) {{
    // Update active button
    document.querySelectorAll('.date-btn').forEach((b, i) => b.classList.toggle('active', i === idx));
    
    const d = DATA[idx];
    if (!d) return;
    
    // Market info
    document.getElementById('marketInfo').innerHTML = d.market ? `📅 ${{d.date}} · ${{d.market}}` : '';
    
    // Summary bar
    const s = d.summary;
    if (s) {{
        document.getElementById('summaryBar').innerHTML = `
            <div class="summary-item"><div class="num">${{s.total}}</div><div class="label">分析股票</div></div>
            <div class="summary-item buy"><div class="num">${{s.buy}}</div><div class="label">🟢 买入</div></div>
            <div class="summary-item hold"><div class="num">${{s.hold}}</div><div class="label">🟡 观望</div></div>
            <div class="summary-item sell"><div class="num">${{s.sell}}</div><div class="label">🔴 卖出</div></div>
        `;
    }} else {{
        document.getElementById('summaryBar').innerHTML = '';
    }}
    
    // Stock cards
    if (d.stocks.length === 0) {{
        document.getElementById('content').innerHTML = '<div class="empty"><h3>暂无数据</h3><p>等待分析完成...</p></div>';
        return;
    }}
    
    const scoreClass = (sc) => sc >= 70 ? 'score-buy' : sc >= 40 ? 'score-hold' : 'score-sell';
    
    document.getElementById('content').innerHTML = d.stocks.map(st => `
        <div class="stock-card">
            <div class="stock-header">
                <div>
                    <span class="stock-name">${{st.signal || ''}} ${{st.name || ''}}</span>
                    <span class="stock-code">(${{st.code || ''}})</span>
                </div>
                <span class="stock-score ${{scoreClass(st.score || 0)}}">
                    ${{st.action || ''}} · 评分 ${{st.score || '?'}} · ${{st.trend || ''}}
                </span>
            </div>
            ${{st.decision ? `<div class="decision">💡 ${{st.decision}}</div>` : ''}}
            ${{st.price ? `
            <div class="price-grid">
                <div class="price-item"><div class="val ${{st.price.change_pct.startsWith('+') ? 'support' : 'resistance'}}">${{st.price.change_pct}}</div><div class="lbl">涨跌幅</div></div>
                <div class="price-item"><div class="val">${{st.price.close}}</div><div class="lbl">收盘价</div></div>
                <div class="price-item"><div class="val">${{st.price.open}}</div><div class="lbl">开盘价</div></div>
                <div class="price-item"><div class="val">${{st.price.high}}</div><div class="lbl">最高</div></div>
                <div class="price-item"><div class="val">${{st.price.low}}</div><div class="lbl">最低</div></div>
            </div>` : ''}}
            ${{(st.support || st.resistance || st.stop_loss) ? `
            <div class="levels">
                ${{st.support ? `<div class="level-item"><div class="val support">${{st.support}}</div><div class="lbl">🟢 支撑位</div></div>` : ''}}
                ${{st.resistance ? `<div class="level-item"><div class="val resistance">${{st.resistance}}</div><div class="lbl">🔴 压力位</div></div>` : ''}}
                ${{st.stop_loss ? `<div class="level-item"><div class="val stop">${{st.stop_loss}}</div><div class="lbl">🛑 止损位</div></div>` : ''}}
            </div>` : ''}}
            ${{st.risks && st.risks.length ? `
            <div class="risks">
                <h4>🚨 风险提醒</h4>
                ${{st.risks.map(r => `<li>${{r}}</li>`).join('')}}
            </div>` : ''}}
        </div>
    `).join('');
}}

// Init
showReport(0);
renderDateSelector();
</script>
</body>
</html>'''

    with open(HTML_FILE, 'w') as f:
        f.write(html)

if __name__ == "__main__":
    main()

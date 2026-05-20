#!/usr/bin/env python3
"""
每日邮件简报生成器
────────────────────────────────────────────
后续要加功能，改这个文件：
  - 新增合并逻辑   → 修改 merge_topics()
  - 新增展示字段   → 修改 render_html() 的模板
  - 新增数据来源   → 修改 fetch_emails()
  - 调整 AI prompt → 修改 generate_briefing()
────────────────────────────────────────────
"""

import os
import re
import json
import datetime
import anthropic
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 配置
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SCOPES      = ["https://www.googleapis.com/auth/gmail.readonly"]
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config.json")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "index.html")

TZ          = datetime.timezone(datetime.timedelta(hours=8))   # 北京时间
TODAY       = datetime.datetime.now(TZ)
WEEKDAYS    = ["星期一","星期二","星期三","星期四","星期五","星期六","星期日"]
DATE_LABEL  = TODAY.strftime("%-m月%-d日")
DATE_FULL   = f"{TODAY.year}年{DATE_LABEL} · {WEEKDAYS[TODAY.weekday()]}"
DATE_QUERY  = TODAY.strftime("%Y/%m/%d")
DATE_NEXT   = (TODAY + datetime.timedelta(days=1)).strftime("%Y/%m/%d")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. 读取配置
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. Gmail 认证
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_gmail_service():
    token_data  = os.environ["GMAIL_TOKEN"]
    creds_info  = json.loads(token_data)
    creds = Credentials(
        token         = creds_info.get("token"),
        refresh_token = creds_info["refresh_token"],
        token_uri     = creds_info["token_uri"],
        client_id     = creds_info["client_id"],
        client_secret = creds_info["client_secret"],
        scopes        = SCOPES,
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. 拉取当日邮件
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def fetch_emails(service, config):
    """
    拉取当日收件箱邮件，过滤掉已退订的来源。
    如需修改过滤规则（如排除 label），在此处调整 query。
    """
    unsubbed = {k for k, v in config["sources"].items() if v.get("unsubbed")}

    query  = f"in:inbox after:{DATE_QUERY} before:{DATE_NEXT}"
    result = service.users().messages().list(
        userId="me", q=query, maxResults=50
    ).execute()
    messages = result.get("messages", [])

    emails = []
    for msg in messages:
        data = service.users().messages().get(
            userId="me", id=msg["id"], format="metadata",
            metadataHeaders=["Subject", "From", "Date"]
        ).execute()
        headers = {h["name"]: h["value"] for h in data["payload"]["headers"]}
        sender  = headers.get("From", "")
        subject = headers.get("Subject", "(无主题)")
        snippet = data.get("snippet", "")

        # 解析发件人昵称
        name_match = re.match(r'^"?([^"<]+)"?\s*<', sender)
        display_name = name_match.group(1).strip() if name_match else sender.split("@")[0]

        # 过滤已退订来源
        if any(u.lower() in display_name.lower() or u.lower() in sender.lower()
               for u in unsubbed):
            continue

        emails.append({
            "id":      msg["id"],
            "subject": subject,
            "sender":  display_name,
            "raw_from": sender,
            "date":    headers.get("Date", ""),
            "snippet": snippet,
        })

    return emails


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. Claude 生成简报 JSON
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def generate_briefing(emails, config):
    """
    调用 Claude API，返回结构化简报 JSON。

    如需调整输出字段或新增功能（如频率标注、热度分），
    修改 prompt 中的 JSON schema 和说明即可。
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # 把 config.json 中的优先级配置传给 Claude
    source_cfg = json.dumps(config["sources"], ensure_ascii=False, indent=2)
    merge_enabled = config["settings"].get("merge_topics", True)

    email_list = "\n\n".join([
        f"ID: {e['id']}\n发件人: {e['sender']}\n主题: {e['subject']}\n摘要: {e['snippet']}"
        for e in emails
    ])

    merge_instruction = """
同一事件如被多个来源报道，将其合并为一个 merged_entry（不超过3组）：
- merged_entry 有独立合成的摘要，不是拼接
- sources 列表包含各来源的 id、source、time、priority
- 合并判断依据：实体名称重叠（人名/地名/公司名）+ 摘要语义相近
""" if merge_enabled else "不合并，每封邮件独立输出。"

    prompt = f"""你是中文邮件简报助手。今日（{DATE_FULL}）收件箱邮件如下：

{email_list}

订阅来源优先级配置（请严格按此评级）：
{source_cfg}

{merge_instruction}

请输出严格 JSON，不要有任何 markdown 或多余文字，结构：
{{
  "date": "{DATE_FULL}",
  "total": <邮件总数>,
  "sections": [
    {{
      "label": "<分类名，中文>",
      "items": [
        // 普通条目：
        {{
          "type": "single",
          "tag": "<标签2-4字>",
          "title": "<主题中文>",
          "gmail_id": "<邮件ID>",
          "source": "<来源简称>",
          "time": "<HH:MM>",
          "priority": "<core|bg|noise>",
          "summary": "<30-60字摘要>"
        }},
        // 合并条目：
        {{
          "type": "merged",
          "title": "<合并后标题>",
          "priority": "core",
          "summary": "<合并后摘要，60-100字>",
          "sources": [
            {{"gmail_id":"...","source":"...","title":"...","time":"...","priority":"..."}}
          ]
        }}
      ]
    }}
  ],
  "promotions_note": "<促销邮件汇总，无则空字符串>"
}}

分类建议：地缘政治与时事、财经与科技、AI与创业、时事通讯与平台、事务性邮件。
促销广告统一放 promotions_note，不进 sections。
"""

    msg = client.messages.create(
        model      = "claude-sonnet-4-20250514",
        max_tokens = 4000,
        messages   = [{"role": "user", "content": prompt}]
    )
    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. 渲染 HTML
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def render_entry_single(item):
    gurl = f"https://mail.google.com/mail/u/0/#inbox/{item['gmail_id']}"
    p    = item.get("priority", "noise")
    return f"""
    <div class="entry{' is-noise' if p=='noise' else ''}">
      <div class="entry-row1">
        <div class="entry-left">
          <div class="pdot pdot-{p}"></div>
          <a class="entry-title-link" href="{gurl}" target="_blank">{item['title']}</a>
        </div>
        <span class="entry-meta">{item['source']} · {item['time']}</span>
      </div>
      <div class="entry-row2">
        <p class="entry-summary">{item['summary']}</p>
        <div class="entry-controls">
          <select class="ctrl-select" onchange="setPriority('{item['gmail_id']}',this.value)">
            <option value="core"{'  selected' if p=='core'  else ''}>🔴 核心</option>
            <option value="bg"{'    selected' if p=='bg'    else ''}>🟡 背景</option>
            <option value="noise"{{' selected' if p=='noise' else ''}}>⚪ 噪音</option>
          </select>
          <a class="unsub-btn" href="{gurl}" target="_blank" onclick="markUnsub('{item['source']}')">退订</a>
        </div>
      </div>
    </div>"""


def render_entry_merged(item, idx):
    drawer_id = f"drawer-{idx}"
    src_rows  = "".join([
        f'<div class="source-row">'
        f'<a class="source-link" href="https://mail.google.com/mail/u/0/#inbox/{s["gmail_id"]}" target="_blank">{s["title"]}</a>'
        f'<span class="source-tag stag-{s.get("priority","noise")}">{s["source"]} · {s["time"]}</span>'
        f'</div>'
        for s in item["sources"]
    ])
    n = len(item["sources"])
    return f"""
    <div class="entry-merged">
      <div class="merged-top">
        <div class="merged-left">
          <div class="pdot pdot-core"></div>
          <a class="merged-title" href="https://mail.google.com/mail/u/0/#inbox/{item['sources'][0]['gmail_id']}" target="_blank">{item['title']}</a>
        </div>
        <button class="merged-badge" onclick="toggleDrawer('{drawer_id}')">
          <span class="merged-dot"></span>{n} 个来源 ▾
        </button>
      </div>
      <div class="merged-row2">
        <p class="merged-summary">{item['summary']}</p>
        <div class="merged-controls">
          <select class="ctrl-select">
            <option value="core" selected>🔴 核心</option>
            <option value="bg">🟡 背景</option>
            <option value="noise">⚪ 噪音</option>
          </select>
        </div>
      </div>
      <div class="sources-drawer" id="{drawer_id}">{src_rows}</div>
    </div>"""


def render_html(data, config):
    # 统计
    merged_count = sum(
        1 for sec in data["sections"]
        for item in sec["items"] if item["type"] == "merged"
    )
    noise_count = sum(
        1 for sec in data["sections"]
        for item in sec["items"]
        if item["type"] == "single" and item.get("priority") == "noise"
    )

    # 生成 sections HTML
    sections_html = ""
    merged_idx = 0
    for sec in data["sections"]:
        items_html = ""
        for item in sec["items"]:
            if item["type"] == "merged":
                items_html += render_entry_merged(item, merged_idx)
                merged_idx += 1
            else:
                items_html += render_entry_single(item)
        sections_html += f"""
  <div class="section">
    <div class="section-header">
      <span class="section-label">{sec['label']}</span>
      <span class="section-rule"></span>
    </div>
    {items_html}
  </div>"""

    if data.get("promotions_note"):
        sections_html += f"""
  <div class="section">
    <div class="section-header"><span class="section-label">促销邮件</span><span class="section-rule"></span></div>
    <p class="promo-row">{data['promotions_note']}</p>
  </div>"""

    # 把 config sources 序列化注入 JS（供前端保存修改用）
    config_js = json.dumps(config["sources"], ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="zh-Hans">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>每日简报 — {data['date']}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;600&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{--ink:#1a1814;--ink-soft:#4a4743;--ink-muted:#8a8682;--paper:#faf8f4;--rule:#d8d2c8;--accent:#b5451b;--red:#c0392b;--amber:#d97706;--green:#2d6a4f}}
body{{background:var(--paper);color:var(--ink);font-family:'DM Sans','PingFang SC',sans-serif;font-weight:300;line-height:1.7}}
.masthead{{border-bottom:3px double var(--ink);padding:1.75rem 0 1.1rem;text-align:center}}
.masthead-eyebrow{{font-size:10px;font-weight:500;letter-spacing:.2em;text-transform:uppercase;color:var(--ink-muted);margin-bottom:.6rem}}
.masthead-title{{font-family:'Playfair Display',serif;font-size:clamp(28px,5vw,54px);font-weight:600;line-height:1;color:var(--ink)}}
.masthead-rule{{display:flex;align-items:center;gap:1rem;margin:.9rem auto 0;max-width:360px;padding:0 2rem}}
.masthead-rule span{{flex:1;height:1px;background:var(--rule)}}
.masthead-date{{font-size:11px;font-weight:500;letter-spacing:.1em;color:var(--ink-soft);white-space:nowrap}}
.container{{max-width:720px;margin:0 auto;padding:0 1.25rem}}
.intro{{border-bottom:1px solid var(--rule);padding:1rem 0;display:flex;align-items:center;justify-content:space-between;gap:1rem;flex-wrap:wrap}}
.intro-text{{font-size:13px;color:var(--ink-muted)}}
.intro-pills{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}
.pill{{font-size:11px;font-weight:500;padding:2px 10px;border-radius:20px;border:1px solid var(--rule);color:var(--ink-muted)}}
.pill-merged{{background:#fff8f0;border-color:#e8c89a;color:#92400e}}
.legend{{display:flex;align-items:center;gap:14px;padding:.75rem 0;border-bottom:1px solid var(--rule);flex-wrap:wrap}}
.legend-label{{font-size:11px;color:var(--ink-muted)}}
.legend-item{{display:flex;align-items:center;gap:5px;font-size:11px;color:var(--ink-soft)}}
.ldot{{width:7px;height:7px;border-radius:50%}}
.section{{padding:1.25rem 0 0}}
.section-header{{display:flex;align-items:center;gap:.75rem;margin-bottom:.75rem}}
.section-label{{font-size:10px;font-weight:500;letter-spacing:.16em;text-transform:uppercase;color:var(--ink-muted);white-space:nowrap}}
.section-rule{{flex:1;height:1px;background:var(--rule)}}
.entry{{padding:.7rem 0;border-bottom:1px solid var(--rule);display:grid;gap:.2rem}}
.entry:last-child{{border-bottom:none}}
.entry.is-noise{{opacity:.5}}
.entry-row1{{display:flex;align-items:baseline;justify-content:space-between;gap:8px}}
.entry-left{{display:flex;align-items:baseline;gap:7px;flex:1;min-width:0}}
.pdot{{width:7px;height:7px;border-radius:50%;flex-shrink:0;margin-top:5px}}
.pdot-core{{background:var(--red)}}.pdot-bg{{background:var(--amber)}}.pdot-noise{{background:var(--ink-muted)}}
.entry-title-link{{text-decoration:none;color:var(--ink);font-family:'Playfair Display',serif;font-size:14.5px;font-weight:400;line-height:1.35;transition:color .15s;min-width:0}}
.entry-title-link:hover{{color:var(--accent)}}
.entry-title-link::after{{content:' ↗';font-size:10px;color:var(--ink-muted);opacity:0;transition:opacity .15s}}
.entry-title-link:hover::after{{opacity:1}}
.entry-meta{{font-size:11px;color:var(--ink-muted);white-space:nowrap;flex-shrink:0}}
.entry-row2{{display:flex;align-items:flex-start;justify-content:space-between;gap:8px;flex-wrap:wrap}}
.entry-summary{{font-size:12.5px;color:var(--ink-soft);line-height:1.55;font-weight:300;flex:1;min-width:0;padding-left:14px}}
.entry-controls{{display:flex;align-items:center;gap:6px;flex-shrink:0;padding-top:2px}}
.ctrl-select{{font-size:11px;padding:2px 20px 2px 6px;border:1px solid var(--rule);border-radius:5px;background:var(--paper);color:var(--ink);cursor:pointer;appearance:none;-webkit-appearance:none;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='8' height='5'%3E%3Cpath d='M0 0l4 5 4-5z' fill='%238a8682'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 5px center;height:24px}}
.unsub-btn{{font-size:11px;padding:2px 9px;height:24px;border-radius:5px;border:1px solid var(--rule);background:none;color:var(--ink-muted);cursor:pointer;transition:all .15s;white-space:nowrap;text-decoration:none;display:inline-flex;align-items:center}}
.unsub-btn:hover{{border-color:var(--red);color:var(--red)}}
.entry-merged{{padding:.75rem 0;border-bottom:1px solid var(--rule);display:grid;gap:.3rem}}
.entry-merged:last-child{{border-bottom:none}}
.merged-top{{display:flex;align-items:baseline;justify-content:space-between;gap:8px}}
.merged-left{{display:flex;align-items:baseline;gap:7px;flex:1;min-width:0}}
.merged-badge{{display:inline-flex;align-items:center;gap:4px;font-size:10px;font-weight:500;padding:2px 8px;border-radius:20px;background:#fff3e0;color:#92400e;border:1px solid #e8c89a;white-space:nowrap;flex-shrink:0;cursor:pointer;transition:background .15s}}
.merged-badge:hover{{background:#ffe0b0}}
.merged-dot{{width:6px;height:6px;border-radius:50%;background:#d97706}}
.merged-title{{text-decoration:none;color:var(--ink);font-family:'Playfair Display',serif;font-size:14.5px;font-weight:400;line-height:1.35;transition:color .15s}}
.merged-title:hover{{color:var(--accent)}}
.merged-row2{{display:flex;align-items:flex-start;gap:8px;flex-wrap:wrap}}
.merged-summary{{font-size:12.5px;color:var(--ink-soft);line-height:1.55;font-weight:300;flex:1;padding-left:14px}}
.merged-controls{{display:flex;align-items:center;gap:6px;flex-shrink:0}}
.sources-drawer{{display:none;margin:6px 0 2px 14px;border-left:2px solid #e8c89a;padding-left:12px}}
.sources-drawer.open{{display:grid}}
.source-row{{display:flex;align-items:baseline;justify-content:space-between;gap:8px;padding:4px 0;border-bottom:1px solid #f0e8d8}}
.source-row:last-child{{border-bottom:none}}
.source-link{{font-size:12px;text-decoration:none;color:var(--ink-soft);transition:color .15s;flex:1}}
.source-link:hover{{color:var(--accent)}}
.source-link::after{{content:' ↗';font-size:10px;opacity:0;transition:opacity .15s}}
.source-link:hover::after{{opacity:1}}
.source-tag{{font-size:10px;font-weight:500;padding:1px 7px;border-radius:10px;white-space:nowrap;flex-shrink:0}}
.stag-core{{background:#fdf2f0;color:var(--red)}}.stag-bg{{background:#fffbeb;color:#92400e}}.stag-noise{{background:#f3f4f6;color:var(--ink-muted)}}
.promo-row{{padding:.75rem 0;font-size:12.5px;color:var(--ink-muted);font-style:italic}}
.stats-bar{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:2rem 0 0;padding-top:1.5rem;border-top:3px double var(--ink)}}
.stat-card{{background:#f2ede4;border-radius:8px;padding:.75rem 1rem}}
.stat-num{{font-size:20px;font-weight:500;line-height:1;margin-bottom:3px}}
.stat-label{{font-size:11px;color:var(--ink-muted)}}
footer{{margin-top:2rem;border-top:3px double var(--ink);padding:1.25rem 0 2.5rem;text-align:center}}
.footer-name{{font-family:'Playfair Display',serif;font-size:16px;font-weight:600;margin-bottom:.4rem}}
.footer-note{{font-size:11px;color:var(--ink-muted);line-height:1.8}}
.footer-note a{{color:var(--accent);text-decoration:none}}
</style>
</head>
<body>
<header class="masthead">
  <p class="masthead-eyebrow">每日个人邮件摘要</p>
  <h1 class="masthead-title">每日简报</h1>
  <div class="masthead-rule"><span></span><span class="masthead-date">{data['date']}</span><span></span></div>
</header>
<div class="container">
  <div class="intro">
    <p class="intro-text">相同事件已合并，点击来源徽章展开各渠道原文。</p>
    <div class="intro-pills">
      <span class="pill">{data['total']} 封邮件</span>
      {'<span class="pill pill-merged">● ' + str(merged_count) + ' 组热点合并</span>' if merged_count > 0 else ''}
    </div>
  </div>
  <div class="legend">
    <span class="legend-label">优先级：</span>
    <div class="legend-item"><div class="ldot" style="background:var(--red)"></div>核心必读</div>
    <div class="legend-item"><div class="ldot" style="background:var(--amber)"></div>背景了解</div>
    <div class="legend-item"><div class="ldot" style="background:var(--ink-muted)"></div>噪音</div>
    <div class="legend-item" style="margin-left:8px"><div class="ldot" style="background:#d97706;border:1px solid #e8c89a"></div>热点合并</div>
  </div>
  {sections_html}
  <div class="stats-bar">
    <div class="stat-card"><div class="stat-num" style="color:var(--red)" id="s-core">—</div><div class="stat-label">核心必读</div></div>
    <div class="stat-card"><div class="stat-num" style="color:#d97706">{merged_count}</div><div class="stat-label">热点合并组</div></div>
    <div class="stat-card"><div class="stat-num" style="color:var(--ink-muted)">{noise_count}</div><div class="stat-label">噪音条目</div></div>
  </div>
</div>
<footer>
  <div class="container">
    <p class="footer-name">每日简报</p>
    <p class="footer-note">根据 Gmail 收件箱整理，{data['date']}。<br>由 Claude 生成 · <a href="https://claude.ai">claude.ai</a></p>
  </div>
</footer>
<script>
/* ── 前端交互 ──────────────────────────────
   如需新增前端功能（筛选、收藏、暗色模式等），在此扩展。
   setPriority / markUnsub 的修改会保存到 localStorage，
   但不会自动写回 config.json（需手动或通过 PR 同步）。
───────────────────────────────────────────── */
const CFG_KEY = 'briefing_cfg_v1';
let localCfg = JSON.parse(localStorage.getItem(CFG_KEY) || '{{}}');
const serverCfg = {config_js};

function toggleDrawer(id) {{
  const el = document.getElementById(id);
  const btn = el.closest('.entry-merged').querySelector('.merged-badge');
  const open = el.classList.toggle('open');
  btn.textContent = btn.textContent.replace(open ? '▾' : '▴', open ? '▴' : '▾');
}}

function setPriority(gmailId, value) {{
  localCfg[gmailId] = localCfg[gmailId] || {{}};
  localCfg[gmailId].priority = value;
  localStorage.setItem(CFG_KEY, JSON.stringify(localCfg));
}}

function markUnsub(source) {{
  localCfg[source] = localCfg[source] || {{}};
  localCfg[source].unsubbed = true;
  localStorage.setItem(CFG_KEY, JSON.stringify(localCfg));
}}

// 统计核心条目数
document.addEventListener('DOMContentLoaded', () => {{
  const coreCount = document.querySelectorAll('.pdot-core').length;
  const el = document.getElementById('s-core');
  if (el) el.textContent = coreCount;
}});
</script>
</body>
</html>"""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 6. 主流程
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def main():
    print(f"📅 生成日期：{DATE_FULL}")

    config  = load_config()
    print("✅ 配置读取完成")

    service = get_gmail_service()
    print("✅ Gmail 认证成功")

    emails  = fetch_emails(service, config)
    print(f"✅ 拉取邮件：{len(emails)} 封")

    if not emails:
        print("⚠️  今日无邮件，跳过生成")
        return

    data    = generate_briefing(emails, config)
    print(f"✅ Claude 生成完成，{data['total']} 封，{len(data['sections'])} 个分类")

    html    = render_html(data, config)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ HTML 已写入：{OUTPUT_PATH}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
每日简报生成脚本
每晚 22:00 自动拉取 Gmail 当日邮件，调用 Claude API 生成中文简报 HTML
"""

import os
import json
import base64
import datetime
import re
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import anthropic

# ── 配置 ──────────────────────────────────────────────────────────────────────
GMAIL_TOKEN_JSON   = os.environ["GMAIL_TOKEN_JSON"]   # GitHub Secret
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]  # GitHub Secret
OUTPUT_FILE        = "index.html"
MAX_EMAILS         = 30


# ── Gmail 认证 ────────────────────────────────────────────────────────────────
def get_gmail_service():
    token_data = json.loads(GMAIL_TOKEN_JSON)
    creds = Credentials(
        token=token_data.get("token"),
        refresh_token=token_data["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=token_data["client_id"],
        client_secret=token_data["client_secret"],
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds)


# ── 拉取今日邮件 ──────────────────────────────────────────────────────────────
def fetch_today_emails(service):
    # 用上海时区的"今天"
    tz_offset = datetime.timezone(datetime.timedelta(hours=8))
    today = datetime.datetime.now(tz_offset).date()
    after  = today.strftime("%Y/%m/%d")
    before = (today + datetime.timedelta(days=1)).strftime("%Y/%m/%d")

    result = service.users().messages().list(
        userId="me",
        q=f"in:inbox after:{after} before:{before}",
        maxResults=MAX_EMAILS,
    ).execute()

    messages = result.get("messages", [])
    emails = []
    for msg in messages:
        detail = service.users().messages().get(
            userId="me", id=msg["id"], format="metadata",
            metadataHeaders=["Subject", "From", "Date"],
        ).execute()

        headers = {h["name"]: h["value"] for h in detail["payload"]["headers"]}
        snippet = detail.get("snippet", "")
        # 清理 snippet 中的乱码空白
        snippet = re.sub(r"[\u200c\u200b\ufeff\u00a0]+", " ", snippet).strip()
        snippet = re.sub(r"\s{2,}", " ", snippet)

        emails.append({
            "id":      msg["id"],
            "subject": headers.get("Subject", "(无主题)"),
            "sender":  headers.get("From", ""),
            "date":    headers.get("Date", ""),
            "snippet": snippet[:300],
        })
    return emails, today


# ── 调用 Claude 生成简报 HTML ──────────────────────────────────────────────────
def generate_html(emails, today):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    date_cn = today.strftime("%-m月%-d日")
    weekdays = ["星期一","星期二","星期三","星期四","星期五","星期六","星期日"]
    weekday_cn = weekdays[today.weekday()]

    emails_json = json.dumps(emails, ensure_ascii=False, indent=2)

    prompt = f"""你是一个每日邮件简报生成助手。
今天是 {today.year}年{date_cn}，{weekday_cn}。

以下是用户今日收件箱的邮件列表（JSON格式，包含id、subject、sender、snippet）：

{emails_json}

请完成以下任务：
1. 将邮件按内容分类（如：地缘政治与时事、财经与科技、AI与创业、时事通讯、事务性邮件、促销邮件等）
2. 为每封重要邮件写一句中文摘要（促销类可合并略过）
3. 输出一个完整的 HTML 页面，风格参考如下要求：
   - 报纸排版风格，使用 Playfair Display 字体作为标题
   - 顶部大标题"每日简报"，副标题显示日期
   - 每个分类有分隔线和小标签
   - 每封邮件标题为可点击链接，链接格式：https://mail.google.com/mail/u/0/#inbox/{{邮件id}}
   - 悬浮时标题变橙红色并出现 ↗
   - 底部注明"由 Claude 生成"
   - 配色：纸张色 #faf8f4，墨水色 #1a1814，强调色 #b5451b
   - 字体：从 Google Fonts 加载 Playfair Display 和 DM Sans
   - 加入 fadeUp 动画
   - 促销邮件统一折叠为一行斜体说明

只输出 HTML 代码，不要任何解释或 markdown 代码块标记。
"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


# ── 主流程 ────────────────────────────────────────────────────────────────────
def main():
    print("📧 连接 Gmail…")
    service = get_gmail_service()

    print("📬 拉取今日邮件…")
    emails, today = fetch_today_emails(service)
    print(f"   共找到 {len(emails)} 封邮件")

    if not emails:
        print("⚠️  今日无邮件，跳过生成")
        return

    print("✍️  调用 Claude 生成简报…")
    html = generate_html(emails, today)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅  简报已写入 {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

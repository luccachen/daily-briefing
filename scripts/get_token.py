#!/usr/bin/env python3
"""
运行一次，生成 Gmail OAuth token。
把输出的 JSON 复制到 GitHub Secrets 的 GMAIL_TOKEN。
"""
import json
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

flow = InstalledAppFlow.from_client_secrets_file("scripts/credentials.json", SCOPES)
creds = flow.run_local_server(port=0)

token_data = {
    "token":         creds.token,
    "refresh_token": creds.refresh_token,
    "token_uri":     creds.token_uri,
    "client_id":     creds.client_id,
    "client_secret": creds.client_secret,
}

print("\n✅ 复制以下 JSON，粘贴到 GitHub Secrets → GMAIL_TOKEN：\n")
print(json.dumps(token_data, indent=2))

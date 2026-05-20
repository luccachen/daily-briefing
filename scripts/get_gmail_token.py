#!/usr/bin/env python3
"""
本地运行一次，完成 Gmail OAuth 授权，输出 token JSON。
把输出内容完整复制，粘贴到 GitHub Secret GMAIL_TOKEN_JSON。

运行前先安装依赖：
  pip3 install google-auth-oauthlib google-auth-httplib2 google-api-python-client
"""

import json
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CREDS_FILE = "credentials.json"   # 从 Google Cloud Console 下载的文件


def main():
    flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
    creds = flow.run_local_server(port=0)

    token_data = {
        "token":         creds.token,
        "refresh_token": creds.refresh_token,
        "client_id":     creds.client_id,
        "client_secret": creds.client_secret,
        "token_uri":     creds.token_uri,
    }

    output = json.dumps(token_data, ensure_ascii=False)
    print("\n" + "="*60)
    print("✅ 授权成功！请把下面这段 JSON 完整复制到 GitHub Secret：")
    print("   Secret 名称：GMAIL_TOKEN_JSON")
    print("="*60)
    print(output)
    print("="*60 + "\n")

    # 同时保存到本地文件（可选）
    with open("gmail_token.json", "w") as f:
        f.write(output)
    print("（已同时保存到 gmail_token.json）")


if __name__ == "__main__":
    main()

# 每日简报 · 自动更新配置指南

每晚 22:00 自动拉取 Gmail 邮件，用 Claude 生成中文简报，发布为 GitHub Pages 网页。

---

## 第一步：创建 GitHub 仓库

1. 登录 [github.com](https://github.com)
2. 点击右上角 **+** → **New repository**
3. 填写：
   - Repository name：`daily-briefing`（或任意名称）
   - 选 **Public**
   - 勾选 **Add a README file**
4. 点击 **Create repository**

---

## 第二步：上传项目文件

把本项目的所有文件上传到仓库：
- `.github/workflows/daily_briefing.yml`
- `scripts/generate_briefing.py`
- `scripts/get_gmail_token.py`

上传方法：在仓库页面点击 **Add file → Upload files**，把文件夹拖进去即可。

---

## 第三步：开启 Google Gmail API

1. 打开 [Google Cloud Console](https://console.cloud.google.com)
2. 新建项目（左上角下拉 → New Project）
3. 搜索并启用 **Gmail API**
4. 左侧菜单 → **APIs & Services → OAuth consent screen**
   - User Type 选 **External** → Create
   - App name 随意填，邮箱填你自己的
   - 保存并继续，其余步骤直接点继续
5. 左侧菜单 → **Credentials → Create Credentials → OAuth client ID**
   - Application type 选 **Desktop app**
   - 点击创建，然后 **Download JSON**
   - 把下载的文件改名为 `credentials.json`

---

## 第四步：获取 Gmail Token（在 Mac 上运行一次）

打开终端（Terminal），依次运行：

```bash
# 安装依赖
pip3 install google-auth-oauthlib google-auth-httplib2 google-api-python-client

# 把 credentials.json 放到 scripts 文件夹，然后进入该目录
cd ~/Downloads/daily-briefing/scripts

# 运行授权脚本
python3 get_gmail_token.py
```

浏览器会自动打开，登录你的 Gmail 账号并授权。
授权完成后，终端会打印一段 JSON，**完整复制**这段内容备用。

---

## 第五步：获取 Claude API Key

1. 打开 [console.anthropic.com](https://console.anthropic.com)
2. 注册/登录后，点击 **API Keys → Create Key**
3. 复制生成的 Key（以 `sk-ant-` 开头）

---

## 第六步：添加 GitHub Secrets

1. 打开你的 GitHub 仓库页面
2. 点击 **Settings → Secrets and variables → Actions**
3. 点击 **New repository secret**，添加以下两个：

| Secret 名称 | 值 |
|---|---|
| `GMAIL_TOKEN_JSON` | 第四步复制的那段 JSON |
| `ANTHROPIC_API_KEY` | 第五步复制的 API Key |

---

## 第七步：开启 GitHub Pages

1. 仓库页面 → **Settings → Pages**
2. Source 选 **Deploy from a branch**
3. Branch 选 **main**，目录选 **/ (root)**
4. 点击 **Save**

几分钟后，你的简报网页地址会显示在页面上，格式为：
`https://你的用户名.github.io/daily-briefing/`

---

## 第八步：测试运行

1. 仓库页面 → **Actions** 标签
2. 左侧点击 **每日简报自动更新**
3. 右侧点击 **Run workflow → Run workflow**
4. 等待约1分钟，刷新仓库，看到 `index.html` 更新即为成功

---

## 之后每晚 22:00，简报自动更新 ✅

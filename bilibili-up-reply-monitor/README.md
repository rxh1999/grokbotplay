# bilibili-up-reply-monitor

监控指定 B 站视频评论区里 **UP 主本人的评论 / 回复**，一旦出现新内容，通过 **Webhook**（飞书 / 钉钉 / 自定义 URL）尽快推送给你。

默认示例视频（可用短链）：

- 短链：https://b23.tv/KGXJu1o  
- BV：`BV1pXHS6iEZQ`  
- UP：`Re重生的炒股生活`（mid `3493130286402061`）

## 功能

- 解析 `b23.tv` 等短链 → 真实 `bilibili.com/video/BVxxxx`，提取 BV / aid
- 用公开接口拉取主楼评论与楼中楼，按 UP 的 `mid` 过滤
- 可配置轮询间隔（默认约 45 秒）
- SQLite 持久化已见 `rpid`：首次运行只做 **baseline**（不推送历史），之后只推送新回复
- 通知通道：
  - **主通道**：通用 Webhook（`WEBHOOK_URL` + `WEBHOOK_STYLE`）
  - 可选：Telegram Bot
- `--dry-run` / `--once` / `--show-all` 便于本地调试

## 使用的公开 API（实测）

| 用途 | 方法 | URL |
|------|------|-----|
| 视频信息 | GET | `https://api.bilibili.com/x/web-interface/wbi/view?bvid=...` |
| 主楼评论（按时间） | GET | `https://api.bilibili.com/x/v2/reply/main?type=1&oid={aid}&mode=2&next=...` |
| 楼中楼 | GET | `https://api.bilibili.com/x/v2/reply/reply?type=1&oid={aid}&root={rpid}&pn=&ps=20` |
| 短链跳转 | GET | `https://b23.tv/...`（跟随重定向） |

说明：

- `type=1` 表示稿件（视频）评论区，`oid` 为稿件 `aid`
- `mode=2` 按时间排序，更适合“盯新回复”
- 部分机房 IP 访问 `/x/web-interface/view` 会遇到 **HTTP 412** 风控页；本项目优先使用 **`wbi/view`**，实测更稳
- 评论接口在公开视频上通常 **无需登录**；若返回 `-352` / 412，可在环境变量里配置浏览器 Cookie（见下）
- 请控制频率、遵守 B 站用户协议与 robots / 反爬策略，**不要用于骚扰或绕过限制**

## 安装

```bash
cd bilibili-up-reply-monitor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# 开发 / 跑测试
pip install pytest
```

也可：`pip install -e ".[dev]"`

## 配置

```bash
cp .env.example .env
# 编辑 .env：至少填 WEBHOOK_URL；VIDEO_URL 默认已指向示例视频
```

### Webhook（推荐）

| 变量 | 含义 |
|------|------|
| `WEBHOOK_URL` | 机器人完整 Webhook 地址 |
| `WEBHOOK_STYLE` | `feishu` / `lark` / `dingtalk` / `custom`（默认 `custom`） |

**飞书 / Lark 自定义机器人**（`WEBHOOK_STYLE=feishu`）发送体示例：

```json
{
  "msg_type": "text",
  "content": {
    "text": "[B站 UP主新回复]\n视频: ...\n内容: ...\n链接: ..."
  }
}
```

在飞书群 → 设置 → 群机器人 → 自定义机器人，复制 Webhook 地址填入 `WEBHOOK_URL`。

**钉钉自定义机器人**（`WEBHOOK_STYLE=dingtalk`）发送体示例：

```json
{
  "msgtype": "text",
  "text": {
    "content": "[B站 UP主新回复]\n..."
  }
}
```

若钉钉机器人开启了加签 / 关键词，请在机器人安全设置里放行，或自行扩展签名逻辑。

**自定义 URL**（`WEBHOOK_STYLE=custom`）会 POST 结构化 JSON，字段含 `text`、`title`、`video`、`reply`（含 `rpid`、`message`、`link` 等），方便接到自建服务。

### 可选 Telegram

```env
TELEGRAM_BOT_TOKEN=123:ABC
TELEGRAM_CHAT_ID=你的chat_id
```

与 Webhook 可同时启用。

### 可选 Cookie

```env
BILIBILI_COOKIE=buvid3=...; SESSDATA=...; bili_jct=...
```

仅在公开接口被风控时需要；**不要把 Cookie 提交进仓库**。

## 运行

```bash
# 打印当前所有 UP 回复（不写 baseline、不发 Webhook）
python -m bilibili_monitor --show-all --dry-run

# 只跑一轮：首次会 baseline，不推送历史
python -m bilibili_monitor --once

# 持续监控（配置好 WEBHOOK_URL 后）
python -m bilibili_monitor

# dry-run：发现“新”回复时只打印到终端
python -m bilibili_monitor --dry-run --once
```

环境变量也可覆盖：`VIDEO_URL`、`POLL_INTERVAL`、`DB_PATH`。

## 换一个视频

把 `VIDEO_URL` 或 `--video` 改成任意短链 / 完整链接 / BV 号即可，例如：

```bash
python -m bilibili_monitor --video BV1xxxxxxxx --once --dry-run --show-all
```

每个 BV 的 baseline / 已见 `rpid` 分开存，换视频不会和旧视频互相干扰。

## 测试

```bash
pytest -q
```

## 项目结构

```
bilibili-up-reply-monitor/
├── bilibili_monitor/
│   ├── __main__.py      # python -m bilibili_monitor
│   ├── cli.py           # 命令行入口
│   ├── client.py        # 短链解析 + 公开 API
│   ├── monitor.py       # 轮询 / baseline / 去重
│   ├── notify.py        # Webhook / Telegram / 打印
│   ├── store.py         # SQLite 已见 rpid
│   ├── models.py
│   └── url.py
├── tests/
├── .env.example
├── requirements.txt
├── pyproject.toml
└── README.md
```

## 限制与免责声明

- B 站接口与风控策略会变化；本项目按公开接口尽力而为，不保证长期稳定
- 过快轮询可能导致限流（如 `-352`）；请使用合理间隔
- 仅用于个人提醒自己关心的 UP 回复，请遵守当地法律与平台服务条款
- 仓库内不含任何密钥；密钥只放在本地 `.env`

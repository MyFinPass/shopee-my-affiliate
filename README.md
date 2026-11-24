# Shopee MY → Telegram · 约 5 分钟上线
开始前准备好已开通马来西亚 Affiliate Open API 的 App ID 和 Secret。审批、GitHub 排队与首次安装时间另计。已有 Shopee 联盟账号可先登录 [MY Affiliate 后台](https://affiliate.shopee.com.my/dashboard)，查看 Open API / API Access 入口和应用凭证。若未获权限，先在后台申请或联系联盟支持。Seller Centre 的 Partner Key 和普通推广短链不能代替这两项。

## 1　准备 Telegram 收件处
1. 在 Telegram 搜索官方 [@BotFather](https://t.me/BotFather)，发送 `/newbot`，按提示填写显示名称和以 bot 结尾的用户名，保存返回的 Token。
2. **自己先收测试卡**：打开新机器人，点 Start，发送一条普通消息。用下方 PowerShell 在自己的电脑查询 ID。把弹窗中的输入作为密码输入；命令历史不会保存 Token 明文。
3. **公开频道**：把机器人加入自己的频道，设为管理员并允许发布消息。Chat ID 可直接填 `@你的频道用户名`。
4. **私有频道**：授予同样权限后，以频道身份发布一条新帖，再运行下方命令，选目标频道对应的一行，复制完整负数 ID（含负号）。群组可先把机器人加入群并发送给它一条命令，再看群组那一行。

```powershell
$botToken = [System.Net.NetworkCredential]::new('', (Read-Host 'Bot Token' -AsSecureString)).Password
$updates = Invoke-RestMethod -Uri ("https://api.telegram.org/bot{0}/getUpdates" -f $botToken)
foreach ($u in $updates.result) {
    foreach ($msg in @($u.message, $u.channel_post)) {
        if ($msg) { $msg.chat | Select-Object id,type,title,username,first_name }
    }
}
Remove-Variable botToken,updates
```
空结果时先确认消息是刚发给这一个机器人的，再查一次。getUpdates 与 webhook 互斥。初次配置优先使用新建的专用机器人。私聊测试与频道共用一份防重记录，切换后下一次会选不同商品。

## 2　建仓库，放入文件
在 GitHub 点 New repository，创建独立仓库。公开仓库配标准 Ubuntu runner 可免运行分钟费；仓库里的商品 ID、发布时间、SubID、回执也会公开。私有仓库请核对账户共享的剩余额度，并在 Billing 设置 Actions 支出上限、启用到限停止，或使用无付费超额能力的账户。Gemini 可完全留空；若启用，请用 AI Studio 免费层且未启用付费结算的项目。系统运行无需自有服务器，订单与收入取决于实际成交和联盟结算。

解压 ZIP。将 main.py、requirements.txt、posted_items.json 放在仓库根目录，将 shopee_bot.yml 放在 **.github/workflows/shopee_bot.yml**。不要把 ZIP 本身或外层文件夹当成源码上传。网页上传时若隐藏目录被跳过，点 Add file → Create new file，在文件名输入完整工作流路径，粘贴 YAML 并提交到默认分支。posted_items.json 初始内容为 `{}`，上线后保留已有记录。README 可一并上传。

## 3　填写密钥、开启写权限
仓库 Settings → Secrets and variables → Actions → Secrets → New repository secret。逐项创建，值不加引号。

| Secret 名称 | 值 |
|---|---|
| SHOPEE_APP_ID | 马来西亚 Affiliate Open API App ID |
| SHOPEE_SECRET | 同一应用的 Secret |
| TELEGRAM_BOT_TOKEN | BotFather 提供的 Token |
| TELEGRAM_CHAT_ID | 私聊/私有频道的数字 ID，或公开频道的 @username |
| GEMINI_API_KEY | 可选，来自 Google AI Studio 免费层项目 |

Settings → Actions → General，确保仓库允许工作流运行并允许 GITHUB_TOKEN 写入内容。工作流已声明 contents: write，无需个人访问令牌。如果默认分支有仅允许 PR 的规则，请选用允许机器人直接提交状态文件的专用仓库。先配置密钥，再启用工作流即可避免首次空跑。

## 4　手动发第一条
打开 Actions → Shopee MY Telegram → Run workflow，选默认分支，点绿色 Run workflow。若页面提示启用 Actions，先点启用。打开本次运行的 post 日志，核对商品 ID、SubIDs 与 message_id；打开 Telegram 核对主图、RM 价格、推广披露、短链。在仓库查看 posted_items.json，成功对应 status=sent。若显示“发送 0 条”，说明扫描范围内没有符合条件的新商品；可提高 MAX_PAGES，或按业务需求调整销量/额外佣金门槛再运行。请勿为测试清空生产防重记录。

## 5　排程、选品与对账
| 马来西亚时间 | Actions UTC cron | subIds 第二项 |
|---|---|---|
| 12:00 | 0 4 * * * | 1200 |
| 20:00 | 0 12 * * * | 2000 |
| 23:45 | 45 15 * * * | 2345 |

每次最多发一件。排队可能延迟，整点尤其明显；时段标签来自 cron，按最近一个计划时段的马来西亚日期归因。手动测试使用 manual。例如 20261124 / 2000 / telegram。到 Affiliate 报表中按 Sub ID 对应列分组，剔除 manual。对同一归因窗口，以该时段归因订单数除以该时段有效点击数计算转化率。只看到订单而没有分时段点击数时，可先比较订单和已确认佣金，无法仅用订单计算转化率。公开仓库长期无活动，GitHub 可能停用定时任务；在 Actions 页面重新启用。

同一设置页面的 Variables → New repository variable 可覆盖以下默认值（可选）。

| 名称 | 默认 | 作用 |
|---|---|---|
| COPY_LANG | zh-en | 中英混排；ms 切换为马来语 |
| MIN_SALES | 500 | Shopee 返回的 sales 指标最低门槛，统计窗口以站点口径为准 |
| MIN_SELLER_RATE | 0.05 | 卖家额外佣金率至少 5%，0.10 表示 10% |
| MAX_PAGES | 3 | 每页 50 件，最多 20 页 |
| GEMINI_MODEL | gemini-3.1-flash-lite | 填自己免费层支持的 generateContent 模型 ID |

评分固定 ≥4.8。先过滤额外佣金率、销量、有效期和已发 ID，再在扫描结果中按总佣金率、卖家佣金率、销量、评分排序。佣金字段按小数解析。多规格只标起价；单一售价有可信区间内的折扣率时，按 现价 ÷ (1 − 折扣率) 估算原价。免运和优惠券均提示结账时核实。Gemini 负责从本地化候选句中选配开头；价格、折扣、披露和短链均由程序填写。缺 key、超时、限额或模型不可用时自动使用本地正则模板。若商品图不符合 Telegram 接收要求，任务会显示拒收。

## 失败如何处理
- **Shopee 鉴权错误**：核对 MY Affiliate 凭证、访问权限、系统时间。签名为十六进制 SHA256(AppId + Unix 秒 + 原始 JSON + Secret)，发送完全相同的 UTF-8 字节。GraphQL 字段错误会保留 API 的诊断消息。MY 后台若对账号开放的字段不同，请以该账号文档为准。
- **Git push 被拒**：检查默认分支写权限或分支规则。预留未成功推回时不会发图。不要同时在两个仓库向同一频道跑同一套状态。
- **Telegram 401/403/400**：核对 Token、数字 ID、频道发帖权限和图片 URL。明确拒收会释放预留，下次可再选。收到 429 时等限流解除后再运行。
- **pending**：系统先提交 pending，再发图，最后提交 sent。网络超时或工作流中断时，保留 pending 七天加十分钟，优先避免重复，代价是该件可能漏发。先核对频道，确认确实未发后才可手动移除该 ID。成功发送的商品按回执时间满 168 小时恢复资格。旧记录在下一次预留时清理。请让同一仓库专用于一个频道。
- **本地运行**：在 Python 3.11+ 环境安装 `python -m pip install -r requirements.txt`，将同名 Secrets 设为当前进程的环境变量，从仓库根目录执行 `python main.py`。这会真实发送并更新本地状态；请不要与线上工作流并行向同一频道分发。Actions 才会自动提交 Git。
- **验证范围**：交付前使用模拟 API 测试，无真实账号鉴权和频道发送。首次 Run workflow 是账号级联调。

参考：[GitHub Actions 计费](https://docs.github.com/en/actions/concepts/billing-and-usage) · [GitHub 调度](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule) · [Telegram Bot API](https://core.telegram.org/bots/api) · [Gemini 定价](https://ai.google.dev/gemini-api/docs/pricing) · [Shopee MY Affiliate](https://affiliate.shopee.com.my/)。

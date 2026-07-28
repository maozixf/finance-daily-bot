# Finance Daily Bot

通过 GitHub Actions 定时抓取财联社专题和 DXX 热点聚焦，并使用
[`all-pusher-api`](https://github.com/maozixf/all-pusher-api) 推送到一个或多个渠道。

## 内容与时间

| Workflow | 北京时间 | 内容 |
|---|---:|---|
| `morning.yml` | 工作日 07:01 | 财联社有声早报标题、摘要、正文、音频和原文链接 |
| `close.yml` | 工作日 17:20、17:35、17:50、18:10；18:30 兜底 | 财联社焦点复盘 + DXX 今日热点 |
| `daily-review.yml` | 不设定时，仅支持手动运行 | 财联社每日收评 + DXX 今日热点（保留但不自动推送） |
| `weekly.yml` | 周一 07:00 | DXX 本周及下周 14 天财经日历 |
| `weekend.yml` | 每天 15:50、16:20、16:50、17:20、17:55；18:30 兜底 | 财联社周末/节假日要闻汇总，当天文章及文章 ID 去重 |

财联社栏目：

- 有声早报：<https://www.cls.cn/subject/1151>
- 焦点复盘（自动）：<https://www.cls.cn/subject/1135>
- 每日收评（仅手动）：<https://www.cls.cn/subject/1139>
- 周末要闻汇总：<https://www.cls.cn/subject/12471>

所有日期按 `Asia/Shanghai` 解释。焦点复盘、每日收评和周末汇总只接受发布日期为当天的文章。
状态键为 `栏目 + 北京日期`，成功渠道当天不会再次推送；窗口内后续 Actions 会立即退出。

## 部署

1. 将本目录提交到 GitHub 仓库。
2. 在仓库 `Settings -> Secrets and variables -> Actions` 新建 Secret：
   `ALL_PUSH_CONFIG`。
3. Secret 内容参考 [`config/pushers.example.json`](config/pushers.example.json)，可以配置多个渠道。
4. 在 Actions 页面手工运行任一 workflow，第一次保留 `dry_run=true` 检查内容。
5. 确认后使用 `dry_run=false` 测试真实推送。

示例配置：

```json
{
  "channels": [
    {
      "id": "dingtalk-main",
      "name": "DingTalk",
      "format": "markdown",
      "config": {
        "key": {
          "token": "钉钉 access_token",
          "secret": "钉钉加签 secret"
        }
      }
    }
  ]
}
```

`id` 是机器人内部的唯一投递目标标识；`name`、`config` 遵循
`all-pusher-api` 的配置。`format` 支持 `text`、`markdown`、`html`。

## 消息排版和长消息

- 不推送栏目封面或文章封面；正文内嵌图片按原位置保留。
- 保留财联社原文的段落、小标题、列表、加粗和链接结构。
- 主标题使用 `日期 · 文章标题`，随后依次展示摘要、正文、音频链接和原文链接。
- 焦点复盘和手动每日收评末尾附加当天全部 DXX 今日热点，不做条数截断。
- 每条热点独立展示标题、关键词和原始热度值。
- Telegram/QQ 默认按 3500 字符拆分，其他文本渠道默认按 12000 字符拆分。
- 每个分段会单独记录成功状态，重试时跳过已经成功的分段。

## 本地运行

```powershell
python -m pip install -e .
npm install

python -m finance_bot --job morning --date 2026-07-28 --dry-run
python -m finance_bot --job focus --date 2026-07-28 --dry-run
python -m finance_bot --job close --date 2026-07-27 --dry-run
python -m finance_bot --job weekly --date 2026-07-28 --dry-run
python -m finance_bot --job weekend --date 2026-07-26 --dry-run
```

真实推送前设置 `ALL_PUSH_CONFIG`。`--force` 会忽略成功状态并重新投递，日常定时任务不会使用该参数。

## 验证

```powershell
python -m unittest discover -s tests -v
```

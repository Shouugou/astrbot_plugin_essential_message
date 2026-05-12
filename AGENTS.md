# AGENTS.md

## 项目概览

这是一个适用于 AstrBot 的插件项目，插件名为 `astrbot_plugin_essential_message`。

当前功能：每天在固定时间向已订阅的 QQ 群随机发送若干条群精华消息，并将精华内容渲染为图片卡片后发送。

当前目录：

```text
/Users/shouugou/AstrBot/data/plugins/astrbot_plugin_essential_message
```

## 当前文件结构

```text
.
├── main.py            # 插件主入口，包含注册、指令、调度、群精华获取、图片渲染和数据持久化
├── metadata.yaml      # 插件元数据
├── _conf_schema.json  # AstrBot WebUI 插件配置 schema
├── README.md          # 用户侧说明文档
├── LICENSE            # 开源许可证
└── AGENTS.md          # 当前协作说明
```

本地环境中可能存在 `.venv/`、`.idea/`、`.DS_Store` 等文件或目录。除非用户明确要求，不应修改、清理或提交这些本地环境文件。

## 插件身份信息

`metadata.yaml` 当前内容：

```yaml
name: astrbot_plugin_essential_message
display_name: 随机发送群精华
desc: 每天固定时间发送几条 QQ 群精华消息。
version: v0.2.0
author: shouugou
repo: https://github.com/Shouugou/astrbot_plugin_essential_message
```

`main.py` 中的注册信息：

```python
@register(
    "astrbot_plugin_essential_message",
    "shouugou",
    "每天固定时间发送 QQ 群精华消息",
    "0.2.0",
)
class EssentialMessagePlugin(Star):
    ...
```

维护插件身份信息时，需要同步检查 `metadata.yaml` 与 `@register(...)`，尤其是插件名、作者、描述和版本号。

## 核心功能

当前插件已经不是 Hello World 模板，而是实际功能插件。

主要能力：

- 支持群内开启或关闭每日群精华订阅。
- 支持为每个群设置每日发送时间。
- 支持为每个群设置每次发送条数。
- 到达固定时间后自动随机选择群精华消息发送。
- 支持手动立即发送群精华用于测试。
- 使用 aiocqhttp / OneBot 的 `get_essence_msg_list` 获取 QQ 群精华。
- 使用 `StarTools.send_message_by_id(...)` 主动向群发送消息。
- 使用 `html_render(...)` 将精华消息渲染为 PNG 图片卡片。
- 当天内通过内存中的 `_sent_message_ids` 尽量避免重复发送同一条精华。

## 用户指令

当前已注册的指令：

```text
/精华开启 [条数] [时间]
/精华关闭
/精华条数 <条数>
/精华时间 <HH:MM>
/群精华 [条数]
/精华状态
```

说明：

- `/精华开启 [条数] [时间]`：在当前群开启每日群精华。例如 `/精华开启 3 09:30`，也支持 `/精华开启 09:30`。
- `/精华关闭`：关闭当前群每日群精华。
- `/精华条数 3`：设置当前群每次发送 3 条群精华。
- `/精华时间 09:30`：设置当前群每日固定发送时间。
- `/群精华 [条数]`：立即在当前群发送群精华图片。
- `/精华状态`：查看当前群订阅状态。

权限约定：

- 订阅开关、条数、时间等管理指令需要群主、群管理员或机器人管理员权限。
- `/群精华` 和 `/精华状态` 需要在群聊中使用。

## 配置项

配置 schema 位于 `_conf_schema.json`，供 AstrBot WebUI 展示和编辑。

当前配置项：

```json
{
  "enabled": true,
  "default_daily_count": 1,
  "default_send_time": "09:00",
  "check_interval_seconds": 30,
  "platform": "aiocqhttp",
  "message_prefix": "今日群精华",
  "subscription_group_ids": [],
  "subscription_overview": "暂无订阅群聊"
}
```

配置说明：

- `enabled`：是否启用自动调度。关闭后不会自动发送。
- `default_daily_count`：群订阅默认发送条数，实际会限制在 1 到 10。
- `default_send_time`：默认每日发送时间，格式为 `HH:MM`。
- `check_interval_seconds`：调度循环检查间隔，代码中最低按 10 秒处理。
- `platform`：主动发送消息时使用的平台名，目前只配置 `aiocqhttp`。
- `message_prefix`：图片卡片标题，默认 `今日群精华`。
- `subscription_group_ids`：订阅群聊 QQ 群号列表，可在配置页面增删；新增群使用默认条数和默认时间。
- `subscription_overview`：当前订阅群聊概览，由插件自动同步到配置页面，仅用于查看。

## 数据持久化

订阅数据通过 AstrBot 插件 KV 存储保存，同时镜像保存到本地 JSON 文件，便于本地持久化和查看。

存储 key：

```python
SUBSCRIPTIONS_KEY = "group_subscriptions"
```

本地文件：

```text
data/plugin_data/astrbot_plugin_essential_message/group_subscriptions.json
```

每个群的订阅数据大致结构：

```python
{
    "enabled": True,
    "count": 1,
    "time": "09:00",
    "last_sent_date": "",
}
```

相关方法：

- `_load_subscriptions()`：插件初始化时读取订阅数据。
- `_save_subscriptions()`：订阅变更或发送完成后保存 KV、本地 JSON，并同步配置页订阅概览。
- `_load_local_subscriptions()`：读取本地 JSON 订阅镜像。
- `_save_local_subscriptions()`：写入本地 JSON 订阅镜像。
- `_apply_config_subscription_changes()`：运行期间检测配置页面群号列表变化，并同步订阅数据。
- `_sync_subscription_config()`：将订阅群号列表和订阅概览同步到插件配置对象。
- `_ensure_subscription()`：确保群订阅结构存在。
- `_normalize_subscription()`：归一化订阅数据。

## 调度逻辑

插件启动时，如果配置 `enabled` 为真，会创建后台任务：

```python
self._task = asyncio.create_task(self._daily_loop())
```

`_daily_loop()` 会循环检查所有已订阅群：

- 跳过未启用订阅的群。
- 跳过当天已经自动发送过的群。
- 将当前时间和群订阅时间转换为分钟比较。
- 到达或超过目标时间后发送群精华。
- 发送成功后写入 `last_sent_date`，避免当天重复自动发送。

插件停用时，`terminate()` 会设置停止事件并取消后台任务。

## 平台依赖

当前插件依赖 aiocqhttp / OneBot 能力。

关键依赖点：

- `AiocqhttpAdapter`：用于查找当前 aiocqhttp 平台实例。
- `bot.call_action("get_essence_msg_list", group_id=...)`：获取群精华列表。
- `StarTools.send_message_by_id("GroupMessage", group_id, MessageChain([...]), platform=...)`：主动向群发送图片消息。

如果运行环境没有 aiocqhttp 适配器，插件无法获取或发送 QQ 群精华。

## 图片卡片渲染

图片卡片模板常量为 `ESSENCE_CARD_TEMPLATE`，位于 `main.py`。

渲染流程：

- `_render_essence_card(item)` 整理精华消息数据。
- `_content_to_text(...)` 将群精华内容转换为文本。
- `_avatar_url(user_id)` 生成 QQ 头像 URL。
- `_format_timestamp(...)` 格式化加精时间。
- `html_render(...)` 将 HTML/CSS 模板渲染为 PNG，使用 `full_page: True` 以自适应内容高度，避免高内容卡片被裁切。
- 最终通过 `Image(file=image_url)` 发送。

修改卡片样式时，主要编辑 `ESSENCE_CARD_TEMPLATE` 中的 HTML 和 CSS。注意保持 `full_page: True`，否则内容过高时图片会被裁切。

## 重要实现约定

- 时间格式使用 `HH:MM`，由 `TIME_PATTERN` 和 `_normalize_time(...)` 校验。
- 发送条数通过 `_normalize_count(...)` 限制在 1 到 10。
- 群精华候选列表会优先排除当前运行期间已经发送过的消息 ID。
- 如果候选数量不足，会回退到完整精华列表中随机抽样。
- 指令回复统一通过 `_reply(event, text)` 构造。
- 日志统一使用 `astrbot.api.logger`。
- 新增指令时优先使用 `@filter.command(...)`。

## 当前 Git 状态提醒

截至本文件更新时，工作区中 `AGENTS.md` 是未跟踪文件；`.DS_Store` 和 `.idea/` 也处于未跟踪状态。

处理版本控制时：

- 不要主动提交 `.DS_Store`。
- 不要主动提交 `.idea/`，除非用户明确要求保留 IDE 配置。
- 若需要提交项目说明，应只暂存 `AGENTS.md` 及用户明确要求的代码文件。
- 提交时 commit message 使用中文编写，描述应简洁说明本次改动内容。

## 后续维护建议

- 如果新增配置项，需要同步更新 `_conf_schema.json`、`README.md` 和本文件。
- 如果新增或修改指令，需要同步更新 `README.md` 和本文件的“用户指令”部分。
- 如果调整插件版本，需要同步更新 `metadata.yaml` 和 `@register(...)`。
- 如果支持其他平台，需要隔离 aiocqhttp 相关逻辑，避免平台适配代码散落在业务逻辑中。
- 如果增强去重能力，可考虑将已发送消息记录持久化，而不是只保存在内存中。

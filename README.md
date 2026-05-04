# Essential Message

每天随机向 QQ 群发送几条群精华消息的 AstrBot 插件。

## 功能

- 通过 `get_essence_msg_list` 获取指定 QQ 群的精华消息列表。
- 每天在配置的时间范围内随机生成发送时间。
- 每个发送槽位会为每个目标群随机挑选一条精华消息。
- 当天内尽量避免重复发送同一条精华。
- 支持手动立即测试发送。

## 配置

在 AstrBot WebUI 的插件配置中设置：

- `enabled`: 是否启用每日随机发送。
- `group_ids`: 目标 QQ 群号列表，例如 `[123456, 234567]`。
- `daily_count_min` / `daily_count_max`: 每天随机发送条数范围。
- `start_hour` / `end_hour`: 每天随机发送的时间范围，取值 `0-23`。
- `message_prefix`: 发送消息标题。

当前获取群精华和主动发群消息依赖 `aiocqhttp` / OneBot 适配器。

## 指令

- `/essence_now`: 立即随机发送一条群精华。不配置 `group_ids` 时，可在群内使用当前群作为目标。
- `/essence_now 群号`: 立即向指定群发送一条随机精华。
- `/essence_status`: 查看插件启用状态、目标群和今日计划。

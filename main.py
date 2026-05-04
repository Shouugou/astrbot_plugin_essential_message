from __future__ import annotations

import asyncio
import random
import re
from datetime import datetime
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Image
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_platform_adapter import (
    AiocqhttpAdapter,
)


DEFAULT_CONFIG = {
    "enabled": True,
    "default_daily_count": 1,
    "default_send_time": "09:00",
    "check_interval_seconds": 30,
    "platform": "aiocqhttp",
    "message_prefix": "今日群精华",
}

SUBSCRIPTIONS_KEY = "group_subscriptions"
TIME_PATTERN = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


ESSENCE_CARD_TEMPLATE = """
<article class="card">
  <header class="header">
    <div class="avatar-wrap">
      <img class="avatar" src="{{ avatar_url }}" />
    </div>
    <div class="sender">
      <div class="label">{{ title }}</div>
      <div class="name">{{ sender_nick }}</div>
      <div class="meta">QQ {{ sender_id }}</div>
    </div>
  </header>

  <section class="content">{{ content }}</section>

  <footer class="footer">
    <div>
      <span class="footer-label">加精者</span>
      <span class="footer-value">{{ operator_nick }}</span>
    </div>
    <div>
      <span class="footer-label">加精时间</span>
      <span class="footer-value">{{ operated_at }}</span>
    </div>
  </footer>
</article>

<style>
  * {
    box-sizing: border-box;
  }

  /* 关键修复：让页面铺满整个画布，不再自动收缩 */
  html,
  body {
    margin: 0;
    padding: 0;
    width: 100%;
    height: 100%;
    /* 居中卡片，让它在画布中间，四周留白均匀 */
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
      "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    color: #202a33;
    background: transparent;
  }

  .card {
    width: 100%;
    height: 100%;
    padding: 32px 36px 30px;
    border: 1px solid rgba(70, 90, 108, 0.14);
    border-radius: 24px;
    background: linear-gradient(135deg, #ffffff 0%, #f8fbfa 72%, #fbf7ed 100%);
    box-shadow: 0 18px 42px rgba(31, 41, 51, 0.14);
    /* 防止卡片被压缩 */
    flex-shrink: 0;
  }

  .header {
    display: flex;
    align-items: center;
    gap: 20px;
    padding-bottom: 22px;
    border-bottom: 1px solid #d9e3e8;
  }

  .avatar-wrap {
    width: 102px;
    height: 102px;
    padding: 5px;
    border-radius: 26px;
    background: linear-gradient(135deg, #348a7c, #d5af42);
    flex: 0 0 auto;
  }

  .avatar {
    display: block;
    width: 92px;
    height: 92px;
    border: 4px solid #ffffff;
    border-radius: 22px;
    object-fit: cover;
    background: #dbe5ea;
  }

  .sender {
    min-width: 0;
  }

  .label {
    width: fit-content;
    margin-bottom: 8px;
    padding: 5px 12px;
    border-radius: 999px;
    color: #2f756b;
    background: #dff1ec;
    font-size: 22px;
    font-weight: 750;
    line-height: 1.2;
  }

  .name {
    max-width: 620px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 42px;
    font-weight: 850;
    line-height: 1.15;
    letter-spacing: 0;
  }

  .meta {
    margin-top: 7px;
    color: #687985;
    font-size: 21px;
    line-height: 1.3;
  }

  .content {
    margin-top: 28px;
    color: #202a33;
    font-size: 34px;
    font-weight: 700;
    line-height: 1.55;
    letter-spacing: 0;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  .footer {
    display: flex;
    justify-content: space-between;
    gap: 20px;
    margin-top: 30px;
    padding-top: 20px;
    border-top: 1px solid #d9e3e8;
    color: #52616b;
    font-size: 21px;
    line-height: 1.35;
  }

  .footer-label {
    margin-right: 8px;
    color: #82919b;
    font-weight: 750;
  }

  .footer-value {
    font-weight: 800;
  }
</style>
"""


@register(
    "astrbot_plugin_essential_message",
    "shouugou",
    "每天固定时间发送 QQ 群精华消息",
    "0.2.0",
)
class EssentialMessagePlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or DEFAULT_CONFIG
        self._task: asyncio.Task | None = None
        self._stopped = asyncio.Event()
        self._subscriptions: dict[str, dict[str, Any]] = {}
        self._sent_message_ids: dict[str, set[str]] = {}

    async def initialize(self):
        self._subscriptions = await self._load_subscriptions()
        if self._cfg_bool("enabled"):
            self._task = asyncio.create_task(self._daily_loop())
            logger.info("Essential Message 插件已启动固定时间群精华调度。")
        else:
            logger.info("Essential Message 插件未启用。请在插件配置中打开 enabled。")

    @filter.command("精华开启")
    async def subscribe_group(
        self,
        event: AstrMessageEvent,
        count_or_time: str | None = None,
        send_time: str | None = None,
    ):
        """在当前群开启每日群精华发送，可选参数：条数 时间，如 /精华开启 3 09:30"""
        group_id, error = await self._require_group_operator(event)
        if error:
            yield self._reply(event, error)
            return

        count, parsed_time = self._parse_count_time(count_or_time, send_time)
        normalized_time = self._normalize_time(
            parsed_time or self._cfg_str("default_send_time")
        )
        if not normalized_time:
            yield self._reply(event, "时间格式不正确，请使用 HH:MM，例如 09:30。")
            return

        daily_count = self._normalize_count(count or self._cfg_int("default_daily_count"))
        self._subscriptions[group_id] = {
            "enabled": True,
            "count": daily_count,
            "time": normalized_time,
            "last_sent_date": "",
        }
        await self._save_subscriptions()
        yield self._reply(
            event,
            f"已开启本群每日群精华：每天 {normalized_time} 发送 {daily_count} 条。",
        )

    @filter.command("精华关闭")
    async def unsubscribe_group(self, event: AstrMessageEvent):
        """在当前群关闭每日群精华发送。"""
        group_id, error = await self._require_group_operator(event)
        if error:
            yield self._reply(event, error)
            return

        sub = self._subscriptions.setdefault(group_id, {})
        sub["enabled"] = False
        await self._save_subscriptions()
        yield self._reply(event, "已关闭本群每日群精华。")

    @filter.command("精华条数")
    async def set_group_count(self, event: AstrMessageEvent, count: int):
        """设置当前群每次固定发送的精华条数。"""
        group_id, error = await self._require_group_operator(event)
        if error:
            yield self._reply(event, error)
            return

        sub = self._ensure_subscription(group_id)
        sub["count"] = self._normalize_count(count)
        await self._save_subscriptions()
        yield self._reply(event, f"已设置本群每次发送 {sub['count']} 条群精华。")

    @filter.command("精华时间")
    async def set_group_time(self, event: AstrMessageEvent, send_time: str):
        """设置当前群每日固定发送时间，格式 HH:MM。"""
        group_id, error = await self._require_group_operator(event)
        if error:
            yield self._reply(event, error)
            return

        normalized_time = self._normalize_time(send_time)
        if not normalized_time:
            yield self._reply(event, "时间格式不正确，请使用 HH:MM，例如 09:30。")
            return

        sub = self._ensure_subscription(group_id)
        sub["time"] = normalized_time
        await self._save_subscriptions()
        yield self._reply(event, f"已设置本群每日 {normalized_time} 发送群精华。")

    @filter.command("精华测试")
    async def send_now(self, event: AstrMessageEvent, count: int | None = None):
        """立即在当前群发送群精华图片。"""
        self._stop_llm(event)
        group_id = event.get_group_id()
        if not group_id:
            yield self._reply(event, "请在群聊中使用该指令。")
            return

        sub = self._ensure_subscription(group_id)
        send_count = self._normalize_count(count or int(sub["count"]))
        ok = await self._send_random_essences(group_id, send_count)
        if not ok:
            yield self._reply(event, "发送失败：没有找到可发送的精华消息，或平台接口调用失败。")
            return
        event.stop_event()

    @filter.command("精华状态")
    async def status(self, event: AstrMessageEvent):
        """查看当前群精华订阅状态。"""
        self._stop_llm(event)
        group_id = event.get_group_id()
        if not group_id:
            yield self._reply(event, "请在群聊中使用该指令。")
            return

        sub = self._subscriptions.get(group_id)
        if not sub or not sub.get("enabled"):
            yield self._reply(event, "本群未开启每日群精华。")
            return

        yield self._reply(
            event,
            f"本群已开启每日群精华：每天 {sub.get('time')} 发送 {sub.get('count')} 条。",
        )

    async def terminate(self):
        self._stopped.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _daily_loop(self):
        while not self._stopped.is_set():
            try:
                if self._cfg_bool("enabled"):
                    now = datetime.now()
                    today = now.strftime("%Y-%m-%d")
                    now_minutes = now.hour * 60 + now.minute
                    for group_id, sub in list(self._subscriptions.items()):
                        if not sub.get("enabled"):
                            continue
                        if sub.get("last_sent_date") == today:
                            continue
                        target_minutes = self._time_to_minutes(str(sub.get("time", "")))
                        if target_minutes is None or now_minutes < target_minutes:
                            continue
                        count = self._normalize_count(sub.get("count", 1))
                        if await self._send_random_essences(group_id, count):
                            sub["last_sent_date"] = today
                            await self._save_subscriptions()

                await asyncio.wait_for(
                    self._stopped.wait(),
                    timeout=max(10, self._cfg_int("check_interval_seconds")),
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Essential Message 调度循环异常: %r", exc)
                await asyncio.sleep(60)

    async def _send_random_essences(self, group_id: str, count: int) -> bool:
        try:
            essences = await self._fetch_essences(group_id)
            if not essences:
                logger.warning("群 %s 没有可发送的精华消息。", group_id)
                return False

            sent_ids = self._sent_message_ids.setdefault(group_id, set())
            candidates = [
                item
                for item in essences
                if str(item.get("message_id") or item.get("msg_seq") or "")
                not in sent_ids
            ]
            if len(candidates) < count:
                candidates = essences

            selected = random.sample(candidates, k=min(count, len(candidates)))
            for item in selected:
                message_id = str(item.get("message_id") or item.get("msg_seq") or "")
                if message_id:
                    sent_ids.add(message_id)

                image_url = await self._render_essence_card(item)
                await StarTools.send_message_by_id(
                    "GroupMessage",
                    str(group_id),
                    MessageChain([Image(file=image_url)]),
                    platform=self._cfg_str("platform") or "aiocqhttp",
                )
                await asyncio.sleep(0.6)

            logger.info("已向群 %s 发送 %s 条随机精华消息。", group_id, len(selected))
            return bool(selected)
        except Exception as exc:
            logger.exception("向群 %s 发送随机精华失败: %r", group_id, exc)
            return False

    async def _fetch_essences(self, group_id: str) -> list[dict[str, Any]]:
        bot = self._get_aiocqhttp_bot()
        raw_group_id: str | int = int(group_id) if str(group_id).isdigit() else group_id
        result = await bot.call_action("get_essence_msg_list", group_id=raw_group_id)

        data = result.get("data") if isinstance(result, dict) else result
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def _get_aiocqhttp_bot(self):
        for platform in self.context.platform_manager.get_insts():
            if isinstance(platform, AiocqhttpAdapter):
                return platform.bot
        raise RuntimeError("未找到 aiocqhttp 适配器，无法获取或发送 QQ 群精华消息。")

    async def _render_essence_card(self, item: dict[str, Any]) -> str:
        sender_id = str(item.get("sender_id") or "")
        data = {
            "title": self._cfg_str("message_prefix") or "今日群精华",
            "sender_id": sender_id or "未知",
            "sender_nick": item.get("sender_nick") or sender_id or "未知用户",
            "operator_nick": item.get("operator_nick")
            or item.get("operator_id")
            or "未知管理员",
            "operated_at": self._format_timestamp(item.get("operator_time")),
            "content": self._content_to_text(item.get("content")).strip() or "(空内容)",
            "avatar_url": self._avatar_url(sender_id),
        }
        return await self.html_render(
            ESSENCE_CARD_TEMPLATE,
            data,
            options={
                "full_page": True,
                "type": "png",
                "omit_background": True,
            },
        )

    async def _require_group_operator(
        self,
        event: AstrMessageEvent,
    ) -> tuple[str, str | None]:
        self._stop_llm(event)
        group_id = event.get_group_id()
        if not group_id:
            return "", "请在群聊中使用该指令。"

        if event.is_admin():
            return group_id, None

        sender_id = self._event_sender_id(event)
        try:
            group = await event.get_group(group_id)
        except Exception as exc:
            logger.exception("获取群 %s 信息失败: %r", group_id, exc)
            return "", "无法获取群权限信息，请稍后再试。"

        owner_id = str(getattr(group, "group_owner", "") or "")
        admin_ids = {
            str(admin_id) for admin_id in (getattr(group, "group_admins", None) or [])
        }
        if sender_id and (sender_id == owner_id or sender_id in admin_ids):
            return group_id, None
        return "", "只有群主、群管理员或机器人管理员可以使用该指令。"

    async def _load_subscriptions(self) -> dict[str, dict[str, Any]]:
        raw = await self.get_kv_data(SUBSCRIPTIONS_KEY, {})
        if isinstance(raw, dict):
            return {
                str(group_id): self._normalize_subscription(sub)
                for group_id, sub in raw.items()
                if isinstance(sub, dict)
            }

        return {}

    async def _save_subscriptions(self):
        await self.put_kv_data(SUBSCRIPTIONS_KEY, self._subscriptions)

    def _ensure_subscription(self, group_id: str) -> dict[str, Any]:
        sub = self._subscriptions.get(group_id)
        if not sub:
            sub = self._normalize_subscription({})
            self._subscriptions[group_id] = sub
        return sub

    def _normalize_subscription(self, sub: dict[str, Any]) -> dict[str, Any]:
        return {
            "enabled": bool(sub.get("enabled", True)),
            "count": self._normalize_count(
                sub.get("count", self._cfg_int("default_daily_count"))
            ),
            "time": self._normalize_time(
                str(sub.get("time") or self._cfg_str("default_send_time"))
            )
            or self._cfg_str("default_send_time")
            or "09:00",
            "last_sent_date": str(sub.get("last_sent_date") or ""),
        }

    @staticmethod
    def _parse_count_time(
        count_or_time: str | None,
        send_time: str | None,
    ) -> tuple[int | None, str | None]:
        count = None
        parsed_time = None
        first = str(count_or_time).strip() if count_or_time is not None else ""
        second = str(send_time).strip() if send_time is not None else ""

        if first:
            if EssentialMessagePlugin._normalize_time(first):
                parsed_time = first
            else:
                try:
                    count = int(first)
                except ValueError:
                    parsed_time = first
        if second:
            parsed_time = second
        return count, parsed_time

    @staticmethod
    def _event_sender_id(event: AstrMessageEvent) -> str:
        sender_id = event.get_sender_id()
        if sender_id:
            return str(sender_id)
        sender = getattr(getattr(event, "message_obj", None), "sender", None)
        raw_sender_id = getattr(sender, "user_id", "")
        return str(raw_sender_id) if raw_sender_id else ""

    @staticmethod
    def _avatar_url(user_id: str) -> str:
        if not user_id:
            user_id = "10000"
        return f"https://q4.qlogo.cn/headimg_dl?dst_uin={user_id}&spec=640"

    @staticmethod
    def _content_to_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    data = item.get("data", {})
                    if item.get("type") == "text" and isinstance(data, dict):
                        parts.append(str(data.get("text", "")))
                    elif item.get("type"):
                        parts.append(f"[{item.get('type')}]")
                    else:
                        parts.append(str(item))
                else:
                    parts.append(str(item))
            return "".join(parts)
        return str(content) if content is not None else ""

    @staticmethod
    def _format_timestamp(value: Any) -> str:
        try:
            return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError, OSError):
            return "未知"

    @staticmethod
    def _normalize_time(value: str | None) -> str | None:
        if not value:
            return None
        value = value.strip()
        match = TIME_PATTERN.match(value)
        if not match:
            return None
        hour, minute = match.groups()
        return f"{int(hour):02d}:{int(minute):02d}"

    @staticmethod
    def _time_to_minutes(value: str) -> int | None:
        normalized = EssentialMessagePlugin._normalize_time(value)
        if not normalized:
            return None
        hour, minute = normalized.split(":", maxsplit=1)
        return int(hour) * 60 + int(minute)

    @staticmethod
    def _normalize_count(value: Any) -> int:
        try:
            count = int(value)
        except (TypeError, ValueError):
            count = 1
        return min(10, max(1, count))

    def _reply(self, event: AstrMessageEvent, text: str):
        self._stop_llm(event)
        return event.plain_result(text).stop_event()

    @staticmethod
    def _stop_llm(event: AstrMessageEvent):
        event.should_call_llm(True)

    def _cfg_bool(self, key: str) -> bool:
        return bool(self.config.get(key, DEFAULT_CONFIG.get(key, False)))

    def _cfg_int(self, key: str) -> int:
        try:
            return int(self.config.get(key, DEFAULT_CONFIG.get(key, 0)))
        except (TypeError, ValueError):
            return int(DEFAULT_CONFIG.get(key, 0))

    def _cfg_str(self, key: str) -> str:
        return str(self.config.get(key, DEFAULT_CONFIG.get(key, ""))).strip()

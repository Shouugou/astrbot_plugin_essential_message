from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Image
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_platform_adapter import (
    AiocqhttpAdapter,
)


DEFAULT_CONFIG = {
    "enabled": False,
    "group_ids": [],
    "daily_count_min": 1,
    "daily_count_max": 3,
    "start_hour": 9,
    "end_hour": 22,
    "check_interval_seconds": 30,
    "platform": "aiocqhttp",
    "message_prefix": "今日随机群精华",
}


ESSENCE_CARD_TEMPLATE = """
<div class="page">
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
</div>

<style>
  * {
    box-sizing: border-box;
  }

  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
      "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    color: #1f2933;
    background: #eef4f8;
  }

  .page {
    width: 900px;
    min-height: 520px;
    padding: 46px;
    background:
      radial-gradient(circle at 12% 10%, rgba(82, 153, 140, 0.18), transparent 32%),
      linear-gradient(135deg, #f7fbfb 0%, #edf4f8 46%, #f9f6ef 100%);
  }

  .card {
    width: 100%;
    min-height: 428px;
    padding: 38px 42px 34px;
    border: 1px solid rgba(66, 84, 102, 0.12);
    border-radius: 24px;
    background: rgba(255, 255, 255, 0.92);
    box-shadow: 0 22px 60px rgba(31, 41, 51, 0.13);
  }

  .header {
    display: flex;
    align-items: center;
    gap: 22px;
    padding-bottom: 26px;
    border-bottom: 1px solid #d9e3e8;
  }

  .avatar-wrap {
    width: 104px;
    height: 104px;
    padding: 5px;
    border-radius: 28px;
    background: linear-gradient(135deg, #3f8f83, #e3b657);
    flex: 0 0 auto;
  }

  .avatar {
    display: block;
    width: 94px;
    height: 94px;
    border: 4px solid #ffffff;
    border-radius: 24px;
    object-fit: cover;
    background: #dbe5ea;
  }

  .sender {
    min-width: 0;
  }

  .label {
    width: fit-content;
    margin-bottom: 10px;
    padding: 5px 12px;
    border-radius: 999px;
    color: #2f6f66;
    background: #e4f3ef;
    font-size: 22px;
    font-weight: 700;
    line-height: 1.2;
  }

  .name {
    max-width: 650px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 44px;
    font-weight: 800;
    line-height: 1.16;
    letter-spacing: 0;
  }

  .meta {
    margin-top: 8px;
    color: #687985;
    font-size: 22px;
    line-height: 1.3;
  }

  .content {
    margin-top: 32px;
    color: #1f2933;
    font-size: 34px;
    font-weight: 650;
    line-height: 1.6;
    letter-spacing: 0;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  .footer {
    display: flex;
    justify-content: space-between;
    gap: 24px;
    margin-top: 34px;
    padding-top: 22px;
    border-top: 1px solid #d9e3e8;
    color: #52616b;
    font-size: 21px;
    line-height: 1.35;
  }

  .footer-label {
    margin-right: 8px;
    color: #82919b;
    font-weight: 700;
  }

  .footer-value {
    font-weight: 750;
  }
</style>
"""


@register(
    "astrbot_plugin_essential_message",
    "shouugou",
    "每天随机发送几条 QQ 群精华消息",
    "0.1.0",
)
class EssentialMessagePlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or DEFAULT_CONFIG
        self._task: asyncio.Task | None = None
        self._stopped = asyncio.Event()
        self._schedule_date = ""
        self._schedule: list[datetime] = []
        self._sent_slots: set[int] = set()
        self._sent_message_ids: dict[str, set[str]] = {}

    async def initialize(self):
        if self._cfg_bool("enabled"):
            self._task = asyncio.create_task(self._daily_loop())
            logger.info("Essential Message 插件已启动每日精华调度。")
        else:
            logger.info("Essential Message 插件未启用。请在插件配置中打开 enabled。")

    @filter.command("essence_now")
    async def essence_now(self, event: AstrMessageEvent, group_id: str | None = None):
        """立即随机发送一条群精华。可传入群号；不传则使用当前群或配置中的群。"""
        groups = [str(group_id)] if group_id else self._target_groups(event)
        if not groups:
            yield event.plain_result("未找到目标群号。请在群内使用，或在配置中填写 group_ids。")
            return

        ok = 0
        for gid in groups:
            if await self._send_random_essence(gid):
                ok += 1
        if ok == 0:
            yield event.plain_result("发送失败：没有找到可发送的精华消息，或平台接口调用失败。")

    @filter.command("essence_status")
    async def essence_status(self, event: AstrMessageEvent):
        """查看群精华每日随机发送插件状态。"""
        groups = self._target_groups(event)
        status = "启用" if self._cfg_bool("enabled") else "未启用"
        schedule = ", ".join(dt.strftime("%H:%M") for dt in self._schedule) or "尚未生成"
        yield event.plain_result(
            f"Essential Message: {status}\n"
            f"目标群: {', '.join(groups) if groups else '未配置'}\n"
            f"今日计划: {schedule}\n"
            f"已发送槽位: {len(self._sent_slots)}"
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
                self._ensure_today_schedule()
                now = datetime.now()
                groups = self._target_groups()
                if groups:
                    for slot, run_at in enumerate(self._schedule):
                        if slot in self._sent_slots or now < run_at:
                            continue
                        for group_id in groups:
                            await self._send_random_essence(group_id)
                        self._sent_slots.add(slot)
                await asyncio.wait_for(
                    self._stopped.wait(),
                    timeout=max(10, self._cfg_int("check_interval_seconds")),
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception(f"Essential Message 调度循环异常: {exc!r}")
                await asyncio.sleep(60)

    def _ensure_today_schedule(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if self._schedule_date == today:
            return

        self._schedule_date = today
        self._sent_slots.clear()
        self._sent_message_ids.clear()

        count_min = max(0, self._cfg_int("daily_count_min"))
        count_max = max(count_min, self._cfg_int("daily_count_max"))
        count = random.randint(count_min, count_max) if count_max > 0 else 0

        start_hour = min(23, max(0, self._cfg_int("start_hour")))
        end_hour = min(23, max(0, self._cfg_int("end_hour")))
        if end_hour < start_hour:
            end_hour = start_hour

        start = datetime.now().replace(
            hour=start_hour, minute=0, second=0, microsecond=0
        )
        end = datetime.now().replace(
            hour=end_hour, minute=59, second=59, microsecond=0
        )
        span_seconds = max(0, int((end - start).total_seconds()))
        self._schedule = sorted(
            start + timedelta(seconds=random.randint(0, span_seconds))
            for _ in range(count)
        )
        logger.info(
            "Essential Message 今日计划: %s",
            ", ".join(dt.strftime("%H:%M:%S") for dt in self._schedule) or "无",
        )

    async def _send_random_essence(self, group_id: str) -> bool:
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
            if not candidates:
                candidates = essences

            item = random.choice(candidates)
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
            logger.info("已向群 %s 发送一条随机精华消息。", group_id)
            return True
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

    def _target_groups(self, event: AstrMessageEvent | None = None) -> list[str]:
        configured = self.config.get("group_ids", [])
        groups: list[str] = []
        if isinstance(configured, list):
            groups.extend(str(item).strip() for item in configured if str(item).strip())
        elif isinstance(configured, str):
            groups.extend(
                item.strip()
                for item in configured.replace("，", ",").split(",")
                if item.strip()
            )

        if not groups and event:
            group_id = event.get_group_id()
            if group_id:
                groups.append(str(group_id))
        return list(dict.fromkeys(groups))

    async def _render_essence_card(self, item: dict[str, Any]) -> str:
        sender_id = str(item.get("sender_id") or "")
        data = {
            "title": self._cfg_str("message_prefix") or "今日随机群精华",
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
            options={"full_page": True, "type": "png"},
        )

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

    def _cfg_bool(self, key: str) -> bool:
        return bool(self.config.get(key, DEFAULT_CONFIG.get(key, False)))

    def _cfg_int(self, key: str) -> int:
        try:
            return int(self.config.get(key, DEFAULT_CONFIG.get(key, 0)))
        except (TypeError, ValueError):
            return int(DEFAULT_CONFIG.get(key, 0))

    def _cfg_str(self, key: str) -> str:
        return str(self.config.get(key, DEFAULT_CONFIG.get(key, ""))).strip()

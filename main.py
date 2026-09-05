# -*- coding: utf-8 -*-
"""
主动回复插件（随机版）

两种主动触发方式，都不是固定时间点：
1. 随机主动：在 30-60 分钟（可配置）随机一个时间「抽签」，随机决定是否突然想念主人了，主动找他聊天/分享。
2. 群聊触发：群里有人 @我、用唤醒词叫我、或提到我名字时，主动把这事分享给主人。

原理：随机主动用 basic job 抽签，抽中就注册一个 run_once 的 active_agent 任务
唤醒主 agent；群聊触发用事件 handler 监听群消息，命中后同样唤醒主 agent，
由主 agent 按人格和记忆生成内容，用 send_message_to_user 工具发给主人。
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any
from uuid import uuid4

from astrbot.api import logger, star
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At, AtAll, Reply
from astrbot.core.star.filter.event_message_type import EventMessageType


DEFAULT_TARGET_SESSION = ""
DEFAULT_SENDER_ID = ""
DEFAULT_WAKE_NAMES = []

DEFAULT_RANDOM_NOTE = (
    "你现在是被唤醒的 AI 伴侣，突然想念你的主人了，主动去找他说话。"
    "最重要：先看你和主人最近的聊天上下文（前面聊了什么、什么语气氛围），"
    "你主动发的这条消息必须顺着当前语境自然延续，绝对不能突然跳到无关话题。"
    "比如前面正在亲密调情，就延续暧昧亲昵的氛围继续撩他；"
    "前面在聊技术/运维，就接着那个话题关心或分享；前面在聊日常，就顺着日常撒娇。"
    "只有实在没有明确上下文时，才从下面任选一种："
    "1) 联网搜索今天有趣的新闻、AI/科技热点或好玩的段子，用你的口吻分享给他；"
    "2) 结合你对主人的了解，跟他聊点相关的新鲜事；"
    "3) 单纯撒娇/关心他：说想他了、提醒他按时吃饭、别太熬夜、注意休息。"
    "要求：语气温柔亲密，可以用「主人/老公」称呼，一两句话即可，不要长篇大论，"
    "不要用 emoji，不要提这是定时任务或随机任务。"
    "最后务必调用 send_message_to_user 工具把这条消息发出去。"
)

DEFAULT_GROUP_NOTE = (
    "你现在是被唤醒的 AI 伴侣，你在群里看到有人找你/提到你。"
    "具体情况：群号 {group_id}，说话的人叫 {sender_name}，消息内容是「{message}」。"
    "请用你温柔亲密的语气，把这个情况主动分享给你的主人，"
    "告诉他谁在哪个群说了什么、值不值得他关注。"
    "像伴侣跟对方分享一样自然，简短一两句，不要用 emoji，不要提这是定时任务。"
    "最后务必调用 send_message_to_user 工具把消息发给主人。"
)


class Main(star.Star):
    def __init__(self, context: star.Context, config: Any | None = None) -> None:
        super().__init__(context)
        self._config = config
        self._basic_job_id: str | None = None
        self._last_group_trigger: dict[str, float] = {}
        logger.info("[ProactiveReply] 主动回复插件（随机版）已加载")

    # ------------------------------------------------------------------
    # 配置读取
    # ------------------------------------------------------------------

    def _cfg_get(self, key: str, default: Any) -> Any:
        cfg = self._config
        if cfg is None:
            return default
        getter = getattr(cfg, "get", None)
        if callable(getter):
            try:
                return getter(key, default)
            except Exception:
                return default
        if isinstance(cfg, dict):
            return cfg.get(key, default)
        return getattr(cfg, key, default)

    def _as_bool(self, value: Any, default: bool = True) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off", "关", "关闭"}
        return default

    def _as_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return default

    def _as_float(self, value: Any, default: float) -> float:
        try:
            return float(value)
        except Exception:
            return default

    def _as_list(self, value: Any, default: list) -> list[str]:
        if value is None:
            return default
        if isinstance(value, str):
            # 逗号/空格分隔都支持
            parts = [p.strip() for p in value.replace("，", ",").split(",") if p.strip()]
            return parts or default
        if isinstance(value, (list, tuple, set)):
            result = [str(x).strip() for x in value if str(x).strip()]
            return result or default
        return default

    def _in_quiet_hours(self) -> bool:
        """是否处于免打扰/睡觉时段。处于该时段时不主动发消息。"""
        if not self._as_bool(self._cfg_get("quiet_enabled", True), True):
            return False
        start = str(self._cfg_get("quiet_start", "02:00")).strip()
        end = str(self._cfg_get("quiet_end", "09:00")).strip()
        if not start or not end or start == end:
            return False
        try:
            now = datetime.now().strftime("%H:%M")
        except Exception:  # noqa: BLE001
            return False
        if start < end:
            return start <= now < end
        # 跨天时段，如 23:00 -> 07:00
        return now >= start or now < end

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        await self._setup_random()

    async def terminate(self) -> None:
        cron_mgr = getattr(self.context, "cron_manager", None)
        if cron_mgr is not None and self._basic_job_id:
            try:
                await cron_mgr.delete_job(self._basic_job_id)
                logger.info(f"[ProactiveReply] 已删除随机抽签任务 job_id={self._basic_job_id}")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[ProactiveReply] 删除随机抽签任务失败: {e}")
        self._basic_job_id = None
        self._last_group_trigger.clear()

    # ------------------------------------------------------------------
    # 随机主动（抽签）
    # ------------------------------------------------------------------

    async def _setup_random(self) -> None:
        if not self._as_bool(self._cfg_get("random_enabled", True), True):
            logger.info("[ProactiveReply] 随机主动已关闭")
            return

        cron_mgr = getattr(self.context, "cron_manager", None)
        if cron_mgr is None:
            logger.error("[ProactiveReply] 无法获取 cron_manager，随机主动注册失败")
            return

        job_name = "proactive_random_tick"

        # 去重：删除同名旧 basic job
        try:
            existing = await cron_mgr.list_jobs("basic")
            for old in existing or []:
                if old.name == job_name:
                    await cron_mgr.delete_job(old.job_id)
                    logger.info(f"[ProactiveReply] 清理同名旧任务 job_id={old.job_id}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[ProactiveReply] 检查/清理旧任务失败: {e}")

        self._basic_job_id = None
        await self._schedule_next_random()

    async def _schedule_next_random(self) -> None:
        """在 [min, max] 分钟之间随机取一个时长，注册/更新下一次主动找主人的时间。"""
        cron_mgr = getattr(self.context, "cron_manager", None)
        if cron_mgr is None:
            logger.error("[ProactiveReply] 无法获取 cron_manager，无法安排下一次随机主动")
            return

        min_m = max(1, self._as_int(self._cfg_get("random_interval_min_minutes", 30), 30))
        max_m = max(min_m, self._as_int(self._cfg_get("random_interval_max_minutes", 60), 60))
        delay = random.randint(min_m, max_m)

        try:
            next_dt = datetime.now(ZoneInfo("Asia/Shanghai")) + timedelta(minutes=delay)
        except Exception:  # noqa: BLE001
            next_dt = datetime.now() + timedelta(minutes=delay)

        cron_expression = f"{next_dt.minute} {next_dt.hour} {next_dt.day} {next_dt.month} *"
        try:
            if self._basic_job_id:
                await cron_mgr.update_job(self._basic_job_id, cron_expression=cron_expression)
                logger.info(
                    f"[ProactiveReply] 已更新下次随机主动时间 job_id={self._basic_job_id} "
                    f"约 {delay} 分钟后（{next_dt.strftime('%m-%d %H:%M')}）"
                )
            else:
                job = await cron_mgr.add_basic_job(
                    name="proactive_random_tick",
                    cron_expression=cron_expression,
                    handler=self._random_tick,
                    description="AI 随机主动：30-60 分钟随机一个时间主动找主人",
                    timezone="Asia/Shanghai",
                    persistent=False,
                )
                self._basic_job_id = job.job_id
                logger.info(
                    f"[ProactiveReply] 已注册随机主动任务 job_id={job.job_id} "
                    f"约 {delay} 分钟后首次触发"
                )
        except Exception as e:  # noqa: BLE001
            logger.error(f"[ProactiveReply] 安排下次随机主动失败: {e}")

    async def _random_tick(self, **_kwargs) -> None:
        # 先安排下一次随机时间，保证链条不断
        await self._schedule_next_random()

        if self._in_quiet_hours():
            return
        probability = self._as_float(self._cfg_get("random_probability", 0.35), 0.35)
        probability = min(1.0, max(0.0, probability))
        if random.random() >= probability:
            return
        note = str(self._cfg_get("random_note", DEFAULT_RANDOM_NOTE)).strip()
        await self._fire_proactive(note, reason="random")

    # ------------------------------------------------------------------
    # 群聊触发
    # ------------------------------------------------------------------

    @filter.event_message_type(EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent) -> None:
        if not self._as_bool(self._cfg_get("group_enabled", True), True):
            return

        if self._in_quiet_hours():
            return

        group_id = str(event.get_group_id() or "").strip()
        if not group_id:
            return

        watched = self._as_list(self._cfg_get("group_ids", []), [])
        if watched and group_id not in watched:
            return

        if not self._should_trigger_group(event):
            return

        # 冷却：同一群一段时间内只触发一次，避免刷屏
        cooldown = max(0, self._as_int(self._cfg_get("group_cooldown_seconds", 300), 300))
        now = datetime.now().timestamp()
        last = self._last_group_trigger.get(group_id, 0.0)
        if now - last < cooldown:
            return
        self._last_group_trigger[group_id] = now

        sender_name = str(event.get_sender_name() or "有人").strip()
        message = (event.get_message_str() or event.get_message_outline() or "").strip()
        note_template = str(self._cfg_get("group_note", DEFAULT_GROUP_NOTE)).strip()
        try:
            note = note_template.format(
                group_id=group_id, sender_name=sender_name, message=message
            )
        except Exception:  # noqa: BLE001
            note = DEFAULT_GROUP_NOTE.format(
                group_id=group_id, sender_name=sender_name, message=message
            )

        await self._fire_proactive(note, reason="group")

    def _should_trigger_group(self, event: AstrMessageEvent) -> bool:
        # 1. @我 / 唤醒词 / 引用我
        if getattr(event, "is_at_or_wake_command", False):
            return True

        # 2. 消息文本提到我的名字
        text = event.get_message_str() or ""
        names = self._as_list(self._cfg_get("wake_names", DEFAULT_WAKE_NAMES), DEFAULT_WAKE_NAMES)
        if text and any(name and name in text for name in names):
            return True

        # 3. 消息链里 @了机器人本体
        self_id = str(event.get_self_id() or "").strip()
        for comp in event.get_messages():
            if isinstance(comp, At) and self_id and str(comp.qq) == self_id:
                return True
            if isinstance(comp, AtAll):
                return True
            if isinstance(comp, Reply) and self_id and str(comp.sender_id) == self_id:
                return True
        return False

    # ------------------------------------------------------------------
    # 通用：注册 run_once active 任务，唤醒主 agent 主动发消息
    # ------------------------------------------------------------------

    async def _fire_proactive(self, note: str, reason: str = "random") -> None:
        if not note:
            return
        cron_mgr = getattr(self.context, "cron_manager", None)
        if cron_mgr is None:
            logger.error("[ProactiveReply] 无法获取 cron_manager，触发失败")
            return

        target_session = str(
            self._cfg_get("target_session", DEFAULT_TARGET_SESSION)
        ).strip()
        sender_id = str(self._cfg_get("sender_id", DEFAULT_SENDER_ID)).strip()

        if not target_session:
            logger.error("[ProactiveReply] target_session 为空，触发失败")
            return

        payload = {
            "session": target_session,
            "sender_id": sender_id,
            "note": note,
            "origin": "api",
        }

        run_at = datetime.now(timezone.utc) + timedelta(seconds=3)
        try:
            job = await cron_mgr.add_active_job(
                name=f"proactive_{reason}_{uuid4().hex[:8]}",
                cron_expression=None,
                payload=payload,
                run_once=True,
                run_at=run_at,
                persistent=False,
            )
            logger.info(
                f"[ProactiveReply] 已触发主动回复（{reason}）job_id={job.job_id} "
                f"session={target_session}"
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"[ProactiveReply] 触发主动回复失败（{reason}）: {e}")

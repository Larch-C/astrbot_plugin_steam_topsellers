import re
import aiohttp
import json
from pathlib import Path
from bs4 import BeautifulSoup
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# 导入 AstrBot 核心 API
from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register, StarTools
from astrbot.core.config.astrbot_config import AstrBotConfig


@register(
    "astrbot_plugin_steam_topsellers",
    "bushikq&danfong1104",
    "一个获取Steam热销榜排名,支持定时发送的astrbot插件。",
    "2.0.0",
)
class SteamTopSellers(Star):
    """
    一个用于从 Steam 获取热销榜排名的插件。
    输出经过美化，并强制使用人民币(CNY)作为价格单位。
    """

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.remind_time = self.config.get("remind_time", "08:00")
        self.manually_added_groups = self.config.get("manually_added_groups", [])
        self.manually_added_senders = self.config.get("manually_added_senders", [])
        self.default_top_num = self.config.get("default_top_num", 5)
        self.data_dir = Path(StarTools.get_data_dir("astrbot_plugin_steam_topsellers"))
        self.SUBSCRIPTIONS_FILE = Path(
            self.data_dir / "astrbot_plugin_steam_topsellers.json"
        )
        self.scheduler = None
        self._subscribed_groups = set()
        self._load_subscribed_groups()
        if self.remind_time:
            self._start_scheduler()

        logger.info("插件 [astrbot_plugin_steam_topsellers] 已初始化。")

    def _load_subscribed_groups(self):
        if self.SUBSCRIPTIONS_FILE.exists():
            try:
                with open(self.SUBSCRIPTIONS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._subscribed_groups = set(data.get("subscribed_groups", []))
                if self.manually_added_groups:
                    for group_id in self.manually_added_groups:
                        self._subscribed_groups.add(
                            f"aiocqhttp:GroupMessage:{group_id}"
                        )
                if self.manually_added_senders:
                    for sender_id in self.manually_added_senders:
                        self._subscribed_groups.add(
                            f"aiocqhttp:FriendMessage:{sender_id}"
                        )
                self._save_subscribed_groups()
                logger.info(f"已加载 {len(self._subscribed_groups)} 个订阅群组。")
            except (IOError, json.JSONDecodeError) as e:
                logger.error(f"加载订阅群组文件失败: {e}")
        else:
            logger.warning("未找到订阅群组文件，将创建一个新的。")
            self._save_subscribed_groups()

    def _save_subscribed_groups(self):
        try:
            with open(self.SUBSCRIPTIONS_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {"subscribed_groups": list(self._subscribed_groups)}, f, indent=4
                )
            logger.info("已保存订阅群组到文件。")
        except IOError as e:
            logger.error(f"保存订阅群组文件失败: {e}")

    def _start_scheduler(self):
        hour, minute = self.parse_time_string(self.remind_time)
        if not self.scheduler:
            self.scheduler = AsyncIOScheduler()
            self.scheduler.add_job(
                self._send_daily_report,
                trigger="cron",
                hour=hour,
                minute=minute,
                id="daily_steam_report",
            )
            self.scheduler.start()
            logger.info(
                f"日报定时任务已使用 AsyncIOScheduler 调度，每日{self.remind_time}执行。"
            )

    def _format_price(self, price_text: str) -> str:
        price_text = price_text.strip().replace(",", ".")

        if "免费" in price_text or "Free" in price_text:
            return "免费开玩"

        discount_pattern = re.compile(r"(-(\d+)%)\s*(¥\s*[\d\.]+)\s*(¥\s*[\d\.]+)")
        match = discount_pattern.search(price_text)

        if match:
            discount = f"-{match.group(2)}%"
            original_price = match.group(3).strip()
            final_price = match.group(4).strip()
            return f"{final_price} (原价: {original_price}, {discount})"

        return price_text

    # 每日播报任务的核心逻辑
    async def _send_daily_report(self):
        if not self._subscribed_groups:
            logger.info("没有已订阅的群组，跳过日报播报。")
            return

        logger.info("开始生成日报并发送到所有订阅群组。")
        try:
            report_text = await self._generate_report_text()
            logger.info(f"report_text: {report_text}")
            if not report_text:
                logger.warning("未能成功生成日报内容。")
                return
            for group_id in self._subscribed_groups:
                await self.context.send_message(
                    group_id,
                    report_text,
                )
                logger.info(f"已向群组 {group_id} 发送日报。")

        except aiohttp.ClientError as e:
            logger.error(f"请求 Steam API 时发生网络错误: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"解析 Steam API 响应失败: {e}")
            return None
        except Exception as e:
            logger.error(f"生成日报文本时发生未知错误: {e}", exc_info=True)
            return None

    async def _generate_report_text(self, num: int = None):
        """异步获取数据并生成热销榜文本"""
        num = num or self.default_top_num
        num = max(1, min(num, 25))  # 限制最大数量为 25
        async with aiohttp.ClientSession(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": "https://store.steampowered.com/search/?filter=topsellers&l=schinese",
            },
            cookies={
                "birthtime": "568022401",
                "steamCountry": "CN%7C",
                "wants_mature_content": "1",
            },
        ) as session:
            api_url = "https://store.steampowered.com/search/results/?query&start=0&count=10&dynamic_data=&sort_by=_ASC&filter=topsellers&l=schinese&cc=CN&infinite=1"

            try:
                async with session.get(api_url, timeout=15) as response:
                    response.raise_for_status()
                    data = await response.json()
                    html_content = data.get("results_html")
                    if not html_content:
                        return None

                soup = BeautifulSoup(html_content, "html.parser")
                top_sellers = soup.select("a.search_result_row")
                if not top_sellers:
                    return None

                reply_text = f"Steam 实时热销榜 Top {num} 🐲\n" + ("-" * 20)
                count = 0
                for item in top_sellers:
                    if count >= num:
                        break

                    title = item.select_one("span.title").get_text(strip=True)
                    price_div = item.select_one(
                        ".search_price_discount_combined"
                    ) or item.select_one(".search_price")

                    raw_price = price_div.get_text(strip=True) if price_div else "--"
                    formatted_price = self._format_price(raw_price) or "--"

                    reply_text += (
                        f"\n\n{count + 1}. 🎮 {title}\n   💰 价格: {formatted_price}"
                    )
                    count += 1
                return reply_text

            except (aiohttp.client_exceptions.ClientError, Exception) as e:
                logger.error(f"生成日报文本时发生错误: {e}")
                return None

    @filter.command("steam热销", alias={"steam热销榜", "steam热销排行"})
    async def get_steam_top_sellers(self, event: AstrMessageEvent, args: str = ""):
        """输出 Steam 实时热销榜排名。空格后加数量参数可指定输出数量，默认为 5。"""
        report_text = await self._generate_report_text(num=int(args) if args else 5)
        if report_text:
            yield event.plain_result(report_text)
        else:
            yield event.plain_result("获取Steam热销榜失败，请稍后再试。")

    @filter.command("订阅steam日报", alias={"steam订阅日报", "steam日报"})
    async def add_daily_report_group(self, event: AstrMessageEvent, args: str = ""):
        """在当前会话/群组订阅每日日报。"""
        subscribe_id = self.format_group_origin(event.unified_msg_origin)
        if subscribe_id in self._subscribed_groups:
            yield event.plain_result("本会话已订阅每日日报。")
            return

        self._subscribed_groups.add(subscribe_id)
        self._save_subscribed_groups()
        yield event.plain_result("本会话已成功订阅每日Steam日报！")

    @filter.command(
        "取消steam日报",
        alias={"steam取消订阅日报", "steam取消日报", "取消订阅steam日报"},
    )
    async def remove_daily_report_group(self, event: AstrMessageEvent, args: str = ""):
        """在当前会话/群组取消订阅每日日报。"""
        subscribe_id = self.format_group_origin(event.unified_msg_origin)

        if subscribe_id not in self._subscribed_groups:
            yield event.plain_result("本群未订阅每日日报。")
            return

        self._subscribed_groups.remove(subscribe_id)
        self._save_subscribed_groups()
        yield event.plain_result("本群已成功取消订阅每日Steam日报。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("steam日报订阅列表", alias={"steam日报全局订阅列表"})
    async def list_daily_report_groups(self, event: AstrMessageEvent, args: str = ""):
        """查看全局订阅列表（管理员权限）"""
        if not self._subscribed_groups:
            yield event.plain_result("当前没有已订阅每日日报的群组或私聊会话。")
            return
        multi_list: dict[str, dict[str, list]] = {}

        for origin_id in self._subscribed_groups:
            parsed_info = self._parse_unified_origin(origin_id)
            platform = parsed_info.get("platform")
            message_type = parsed_info.get("message_type")
            if not platform or not message_type:
                continue

            if platform not in multi_list:
                multi_list[platform] = {"GroupMessage": [], "FriendMessage": []}

            if message_type == "GroupMessage":
                group_id = parsed_info.get("group_id")
                if group_id:
                    multi_list[platform]["GroupMessage"].append(group_id)
            elif message_type == "FriendMessage":
                user_id = parsed_info.get("user_id")
                if user_id:
                    multi_list[platform]["FriendMessage"].append(user_id)

        reply_text = "已订阅每日日报的群组/私聊会话列表：\n\n"
        platform_count = 1
        for platform, types in multi_list.items():
            reply_text += f"{platform_count}. 平台：{platform}\n"

            group_list = types["GroupMessage"]
            if group_list:
                reply_text += f"  群组：{', '.join(group_list)}\n"

            friend_list = types["FriendMessage"]
            if friend_list:
                reply_text += f"  私聊：{', '.join(friend_list)}\n"

            platform_count += 1

        yield event.plain_result(reply_text.strip())

    @staticmethod
    def _parse_unified_origin(origin: str):
        parts = origin.split(":")
        platform = parts[0]
        message_type = parts[1]
        identifiers = parts[2]

        user_id = None
        group_id = None

        if message_type == "FriendMessage":
            user_id = identifiers
        elif message_type == "GroupMessage":
            if "_" in identifiers:
                user_id, group_id = identifiers.split("_")
            else:
                group_id = identifiers

        return {
            "platform": platform,
            "message_type": message_type,
            "user_id": user_id,
            "group_id": group_id,
        }

    @staticmethod
    def parse_time_string(time_str: str) -> tuple[int, int] | None:
        """
        解析多种格式的时间字符串，并返回小时和分钟。
        支持的格式包括: "0835", "08:35", "8:35", "08：35", "8：35" 等。
        """
        # 将全角冒号替换为半角，以简化正则表达式
        time_str = time_str.replace("：", ":")
        pattern = re.compile(r"(\d{1,2}):?(\d{2})")

        match = pattern.match(time_str)

        if match:
            try:
                hour = int(match.group(1))
                minute = int(match.group(2))
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    return hour, minute
                else:
                    return None
            except ValueError:
                return None
        return None

    @staticmethod
    def format_group_origin(origin_id: str) -> str:
        """
        将带有用户ID的群组会话ID转换为不带用户ID的格式
        """
        parts = origin_id.rsplit(":", 1)
        if len(parts) < 2 or "GroupMessage" not in parts[0]:
            return origin_id

        prefix = parts[0]
        identifiers = parts[1]

        # 从右侧开始分割identifiers，只分割一次，取最后一部分（即群组ID）
        group_id = identifiers.rsplit("_", 1)[-1]

        return f"{prefix}:{group_id}"

    async def terminate(self):
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown()

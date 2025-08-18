# -----------------------------------------------------------------------------
# AstrBot Steam Top Sellers Plugin (Formatted & Localized)
#
# 文件名: main.py
# 功能: 从 Steam 获取热销榜前5名游戏，并以美化格式显示人民币价格
# 作者: danfong1104
# 版本: 1.1.0
# 依赖: requests, beautifulsoup4
# -----------------------------------------------------------------------------

import re
import requests
from bs4 import BeautifulSoup

# 导入 AstrBot 新版核心 API
from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register

@register("steam_topsellers", "您的名字", "获取Steam热销榜前5名游戏(美化版)", "1.1.0")
class SteamTopSellers(Star):
    """
    一个用于从 Steam 获取热销榜前5名游戏的插件。
    输出经过美化，并强制使用人民币(CNY)作为价格单位。
    """

    def __init__(self, context: Context):
        super().__init__(context)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': 'https://store.steampowered.com/search/?filter=topsellers&l=schinese'
        })
        cookie_domain = '.steampowered.com' 
        self.session.cookies.set('birthtime', '568022401', domain=cookie_domain)
        self.session.cookies.set('steamCountry', 'CN%7C', domain=cookie_domain)
        self.session.cookies.set('wants_mature_content', '1', domain=cookie_domain) 
        logger.info("插件 [SteamTopSellers] 已初始化。")

    def _format_price(self, price_text: str) -> str:
        """
        智能解析并格式化从Steam获取的原始价格字符串。
        示例输入:
        - "免费" -> "免费开玩"
        - "¥ 419,00" -> "¥ 419.00"
        - "-10%¥ 28,49¥ 25,64" -> "¥ 25.64 (原价: ¥ 28.49, -10%)"
        """
        price_text = price_text.strip().replace(',', '.') # 将逗号小数点替换为句点
        
        if "免费" in price_text or "Free" in price_text:
            return "免费开玩"

        # 正则表达式，用于匹配折扣、原价和现价
        # 例如: (-10%) (¥ 28.49) (¥ 25.64)
        discount_pattern = re.compile(r"(-(\d+)%)\s*(¥\s*[\d\.]+)\s*(¥\s*[\d\.]+)")
        match = discount_pattern.search(price_text)

        if match:
            discount = f"-{match.group(2)}%"
            original_price = match.group(3).strip()
            final_price = match.group(4).strip()
            return f"{final_price} (原价: {original_price}, {discount})"
        
        # 如果没有折扣，直接返回清理后的价格
        return price_text

    @filter.command("steam热销", "steam")
    async def get_steam_top_sellers(self, event: AstrMessageEvent, args: str = ""):
        """处理 'steam热销' 和 'steam' 命令"""
        response = None
        try:
            # --- 决定性修正：添加 cc=CN 参数以获取人民币价格 ---
            api_url = "https://store.steampowered.com/search/results/?query&start=0&count=10&dynamic_data=&sort_by=_ASC&filter=topsellers&l=schinese&cc=CN&infinite=1"
            
            logger.info(f"插件 [SteamTopSellers] 正在请求API: {api_url}")
            response = self.session.get(api_url, timeout=15)
            response.raise_for_status()

            data = response.json()
            html_content = data.get('results_html')
            if not html_content:
                yield event.plain_result("成功获取API数据，但内容格式不正确。")
                return

            soup = BeautifulSoup(html_content, 'html.parser')
            top_sellers = soup.select('a.search_result_row')
            if not top_sellers:
                yield event.plain_result("API数据中未找到热销榜条目。")
                return

            # --- 美化排版 ---
            reply_text = "Steam 实时热销榜 Top 5 🐲\n" + ("-" * 20)
            count = 0
            for item in top_sellers:
                if count >= 5:
                    break
                
                title = item.select_one('span.title').get_text(strip=True)
                price_div = item.select_one('.search_price_discount_combined') or item.select_one('.search_price')
                
                raw_price = price_div.get_text(strip=True)
                formatted_price = self._format_price(raw_price)

                reply_text += f"\n\n{count + 1}. 🎮 {title}\n   💰 价格: {formatted_price}"
                count += 1
            
            yield event.plain_result(reply_text)

        except requests.exceptions.JSONDecodeError:
            logger.error("插件 [SteamTopSellers] 解析JSON失败。Steam返回的不是有效的JSON。")
            response_text = response.text if response else "No response object"
            logger.error(f"收到的HTML响应开头: {response_text[:500]}")
            yield event.plain_result("无法解析Steam返回的数据，服务器可能返回了HTML页面。")
        except requests.exceptions.RequestException as e:
            logger.error(f"插件 [SteamTopSellers] 请求Steam API失败: {e}")
            yield event.plain_result(f"网络请求失败，无法获取Steam热销榜。")
        except Exception as e:
            logger.error(f"插件 [SteamTopSellers] 处理数据时发生未知错误: {e}", exc_info=True)
            yield event.plain_result(f"处理数据时发生未知错误，请联系管理员。")

    async def terminate(self):
        self.session.close()
        logger.info("插件 [SteamTopSellers] 已终止。")

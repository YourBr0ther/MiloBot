from __future__ import annotations

import logging
from xml.etree import ElementTree

import aiohttp
import discord
from discord.ext import commands, tasks

from bot.services.nanogpt import NanoGPTService

log = logging.getLogger("milo.wow_patch_notes")

WOWHEAD_RSS = "https://www.wowhead.com/news/rss/all"

# Keywords that indicate a patch/hotfix article (matched case-insensitively)
PATCH_KEYWORDS = ("hotfix", "patch notes", "content update notes", "update notes")


def _is_patch_article(title: str) -> bool:
    lower = title.lower()
    return any(kw in lower for kw in PATCH_KEYWORDS)


def _parse_rss(xml_text: str) -> list[dict]:
    root = ElementTree.fromstring(xml_text)
    items: list[dict] = []
    for item in root.iter("item"):
        title = item.findtext("title", "")
        if not _is_patch_article(title):
            continue
        link = item.findtext("link", "")
        guid = item.findtext("guid", link)
        pub_date = item.findtext("pubDate", "")
        description = item.findtext("description", "")
        items.append({
            "title": title,
            "link": link,
            "guid": guid,
            "pub_date": pub_date,
            "description": description.strip(),
        })
    return items


SUMMARY_PROMPT = """\
You are summarizing World of Warcraft patch notes / hotfixes for a Discord gaming community.

Rules:
- Focus on: class changes, new content, dungeon/raid changes, PvP changes, and notable gameplay updates.
- IGNORE minor bug fixes unless they significantly affect gameplay.
- Keep it concise (bullet points).
- Group by category if there are multiple types of changes (e.g. Classes, Dungeons, Items).
- Use Discord markdown formatting (bold, bullet points).
- Do NOT include the patch title in your summary (it will be in the embed title).
- If there is essentially nothing noteworthy, say "Minor bug fixes and stability improvements."

Patch notes to summarize:
{content}"""


class WoWPatchNotes(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        settings = bot.settings  # type: ignore[attr-defined]
        self.channel_id = settings.wow_channel_id
        self.nanogpt = NanoGPTService(settings.nanogpt_api_key)
        self.seen_guids: set[str] = set()
        self.seen_links: set[str] = set()
        self._first_run = True
        self.check_wow_patches.start()

    def cog_unload(self) -> None:
        self.check_wow_patches.cancel()

    @tasks.loop(minutes=10)
    async def check_wow_patches(self) -> None:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    WOWHEAD_RSS,
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    resp.raise_for_status()
                    xml_text = await resp.text()

            items = _parse_rss(xml_text)
            if not items:
                return

            if self._first_run:
                self.seen_guids = {item["guid"] for item in items}
                self.seen_links = {item["link"] for item in items}
                self._first_run = False
                log.info("WoW patch notes: seeded %d existing article GUIDs and %d links", len(self.seen_guids), len(self.seen_links))
                return

            new_items = [
                item for item in items
                if item["guid"] not in self.seen_guids
                and item["link"] not in self.seen_links
            ]
            if not new_items:
                return

            channel = self.bot.get_channel(self.channel_id)
            if not channel:
                log.error("WoW patch notes channel %s not found", self.channel_id)
                return

            for item in new_items:
                success = await self._post_summary(channel, item)
                if success:
                    self.seen_guids.add(item["guid"])
                    self.seen_links.add(item["link"])

        except Exception:
            log.exception("Error checking WoW patch notes")

    async def _post_summary(self, channel: discord.abc.Messageable, item: dict) -> bool:
        """Post a summary of patch notes. Returns True on success."""
        link = item["link"]

        # Fetch the full article from Wowhead for better content
        full_content = await self._fetch_article(link)
        content_to_summarize = full_content or item["description"]

        if not content_to_summarize:
            log.warning("Empty content for WoW article: %s", item["title"])
            return False

        try:
            async with aiohttp.ClientSession() as session:
                summary = await self.nanogpt.ask(
                    session,
                    SUMMARY_PROMPT.format(content=content_to_summarize[:6000]),
                )
        except Exception:
            log.exception("Failed to summarize WoW patch notes: %s", item["title"])
            return False

        embed = discord.Embed(
            title=item["title"],
            url=link,
            description=summary[:4096],
            color=discord.Color.from_rgb(255, 140, 0),  # WoW orange
        )
        embed.set_footer(text="World of Warcraft Patch Notes")

        await channel.send(embed=embed)
        return True

    async def _fetch_article(self, url: str) -> str | None:
        """Fetch article page and extract text content."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    resp.raise_for_status()
                    html = await resp.text()
            return self._extract_article_text(html)
        except Exception:
            log.exception("Failed to fetch WoW article: %s", url)
            return None

    @staticmethod
    def _extract_article_text(html: str) -> str:
        """Extract readable text from Wowhead article HTML."""
        import re
        # Find the article body — Wowhead uses a div with class containing "text"
        # Try to find the main content area
        match = re.search(r'<div[^>]*class="[^"]*news-post-body[^"]*"[^>]*>(.*?)</div>\s*</div>', html, re.DOTALL)
        if not match:
            match = re.search(r'<div[^>]*id="news-post-body"[^>]*>(.*?)</div>', html, re.DOTALL)
        if not match:
            # Fallback: look for noscript content or main article
            match = re.search(r'<article[^>]*>(.*?)</article>', html, re.DOTALL)
        if not match:
            return ""
        content = match.group(1)
        # Strip HTML tags
        text = re.sub(r'<br\s*/?>', '\n', content)
        text = re.sub(r'<li[^>]*>', '- ', text)
        text = re.sub(r'<h[1-6][^>]*>', '\n## ', text)
        text = re.sub(r'</h[1-6]>', '\n', text)
        text = re.sub(r'<[^>]+>', '', text)
        # Clean up whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    @check_wow_patches.before_loop
    async def before_check(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WoWPatchNotes(bot))

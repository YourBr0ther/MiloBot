from __future__ import annotations

import logging
import re
from xml.etree import ElementTree

import aiohttp
import discord
from discord.ext import commands, tasks

log = logging.getLogger("milo.rsi_status")

RSS_URL = "https://status.robertsspaceindustries.com/index.xml"


def _strip_html(text: str) -> str:
    """Remove HTML tags and comments, collapse whitespace."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    # Collapse runs of blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_rss(xml_text: str) -> list[dict]:
    """Parse the RSS feed and return items newest-first."""
    root = ElementTree.fromstring(xml_text)
    items: list[dict] = []
    for item in root.iter("item"):
        title = item.findtext("title", "")
        link = item.findtext("link", "")
        guid = item.findtext("guid", "")
        pub_date = item.findtext("pubDate", "")
        description = _strip_html(item.findtext("description", ""))
        items.append({
            "title": title,
            "link": link,
            "guid": guid,
            "pub_date": pub_date,
            "description": description,
        })
    return items


def _status_from_title(title: str) -> tuple[str, discord.Color]:
    """Extract the status tag and pick an embed color."""
    lower = title.lower()
    if "[resolved]" in lower:
        return "Resolved", discord.Color.green()
    if "[monitoring]" in lower:
        return "Monitoring", discord.Color.blue()
    if "[identified]" in lower:
        return "Identified", discord.Color.orange()
    if "[scheduled]" in lower:
        return "Scheduled", discord.Color.light_grey()
    # Investigating or new incident
    return "Investigating", discord.Color.red()


class RSIStatus(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        settings = bot.settings  # type: ignore[attr-defined]
        self.channel_id = settings.patch_notes_channel_id
        self.seen_guids: dict[str, str] = {}  # guid -> last title (to detect status changes)
        self._first_run = True
        self.check_status.start()

    def cog_unload(self) -> None:
        self.check_status.cancel()

    @tasks.loop(minutes=5)
    async def check_status(self) -> None:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(RSS_URL, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    resp.raise_for_status()
                    xml_text = await resp.text()

            items = _parse_rss(xml_text)
            if not items:
                return

            if self._first_run:
                self.seen_guids = {item["guid"]: item["title"] for item in items}
                self._first_run = False
                log.info("RSI status: seeded %d existing incidents", len(self.seen_guids))
                return

            channel = self.bot.get_channel(self.channel_id)
            if not channel:
                log.error("RSI status channel %s not found", self.channel_id)
                return

            for item in items:
                guid = item["guid"]
                title = item["title"]
                prev_title = self.seen_guids.get(guid)

                if prev_title is None:
                    # Brand new incident
                    self.seen_guids[guid] = title
                    await self._post_update(channel, item)
                elif prev_title != title:
                    # Status changed (e.g. [Investigating] -> [Resolved])
                    self.seen_guids[guid] = title
                    await self._post_update(channel, item)

        except Exception:
            log.exception("Error checking RSI status")

    def _role_mention(self) -> str:
        role = discord.utils.get(self.bot.guilds[0].roles, name="RSI Status")
        return role.mention if role else ""

    async def _post_update(self, channel: discord.abc.Messageable, item: dict) -> None:
        status_label, color = _status_from_title(item["title"])

        # Strip the status prefix from the title for a cleaner look
        clean_title = item["title"]
        for prefix in ("[Resolved]", "[Monitoring]", "[Identified]", "[Investigating]", "[Scheduled]"):
            clean_title = clean_title.replace(prefix, "").strip()

        embed = discord.Embed(
            title=f"{clean_title}",
            url=item["link"],
            description=item["description"][:4096] if item["description"] else "No details yet.",
            color=color,
        )
        embed.add_field(name="Status", value=status_label, inline=True)
        if item["pub_date"]:
            embed.add_field(name="Updated", value=item["pub_date"], inline=True)
        embed.set_footer(text="RSI Service Status")

        mention = self._role_mention()
        await channel.send(content=mention, embed=embed)

    @check_status.before_loop
    async def before_check(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RSIStatus(bot))

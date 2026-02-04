from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import aiohttp
import discord
from discord.ext import commands, tasks

log = logging.getLogger("milo.minecraft_news")

DATA_FILE = Path("data/minecraft_news.json")

MINECRAFT_NEWS_URL = "https://www.minecraft.net/en-us/articles"

# Keywords that indicate game updates (not marketplace, community events, etc.)
UPDATE_KEYWORDS = [
    "snapshot",
    "preview",
    "release",
    "patch",
    "update",
    "hotfix",
    "pre-release",
    "beta",
    "changelog",
]

# Keywords to exclude (marketplace, events, sales, etc.)
EXCLUDE_KEYWORDS = [
    "marketplace",
    "sale",
    "rewards",
    "community",
    "spotlight",
    "creator",
    "realms plus",
]


def _load_seen() -> list[str]:
    if not DATA_FILE.exists():
        return []
    try:
        with DATA_FILE.open() as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        log.exception("Failed to load minecraft_news data")
        return []


def _save_seen(seen: list[str]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with DATA_FILE.open("w") as f:
        json.dump(seen, f, indent=2)


def _is_game_update(title: str) -> bool:
    """Check if article title indicates a game update."""
    title_lower = title.lower()

    # Exclude marketplace/community content
    for keyword in EXCLUDE_KEYWORDS:
        if keyword in title_lower:
            return False

    # Include if it matches update keywords
    for keyword in UPDATE_KEYWORDS:
        if keyword in title_lower:
            return True

    # Also include versioned titles like "Minecraft 1.21" or "Minecraft 26.1"
    if re.search(r"minecraft\s+\d+\.\d+", title_lower):
        return True

    return False


class MinecraftNews(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        settings = bot.settings  # type: ignore[attr-defined]
        self.channel_id = settings.minecraft_news_channel_id
        self.seen: list[str] = _load_seen()
        self._first_run = not self.seen
        self.check_minecraft_news.start()

    def cog_unload(self) -> None:
        self.check_minecraft_news.cancel()

    @tasks.loop(minutes=30)
    async def check_minecraft_news(self) -> None:
        try:
            articles = await self._fetch_articles()
        except Exception:
            log.exception("Error fetching Minecraft news")
            return

        new_articles = [
            a for a in articles
            if a["url"] not in self.seen and _is_game_update(a["title"])
        ]

        if self._first_run:
            # Seed all current articles as seen
            for article in articles:
                if article["url"] not in self.seen:
                    self.seen.append(article["url"])
            _save_seen(self.seen)
            self._first_run = False
            log.info("Minecraft news: seeded %d existing articles", len(self.seen))
            return

        if not new_articles:
            return

        channel = self.bot.get_channel(self.channel_id)
        if not channel:
            log.error("Minecraft news channel %s not found", self.channel_id)
            return

        for article in new_articles:
            try:
                await self._post_article(channel, article)
            except Exception:
                log.exception("Error posting article: %s", article["title"])
            self.seen.append(article["url"])

        _save_seen(self.seen)

    @check_minecraft_news.before_loop
    async def before_check(self) -> None:
        await self.bot.wait_until_ready()

    async def _fetch_articles(self) -> list[dict]:
        """Fetch articles from Minecraft news page."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                MINECRAFT_NEWS_URL,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"
                    ),
                },
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                resp.raise_for_status()
                html = await resp.text()

        return self._parse_articles(html)

    @staticmethod
    def _parse_articles(html: str) -> list[dict]:
        """Extract article links from the Minecraft news page."""
        articles: list[dict] = []
        seen_urls: set[str] = set()

        # Look for article links - minecraft.net uses /en-us/article/<slug> pattern
        for match in re.finditer(
            r'<a[^>]*href="(/en-us/article/[^"]+)"[^>]*>',
            html,
            re.DOTALL,
        ):
            path = match.group(1)
            url = f"https://www.minecraft.net{path}"
            if url in seen_urls:
                continue
            seen_urls.add(url)

            # Extract title from the slug
            slug = path.split("/")[-1]
            title = slug.replace("-", " ").title()

            articles.append({
                "title": title,
                "url": url,
            })

        # Also try to find titles in nearby elements
        # Pattern: title often in heading or span near the link
        for match in re.finditer(
            r'href="(/en-us/article/[^"]+)"[^>]*>.*?'
            r'(?:<[^>]*class="[^"]*title[^"]*"[^>]*>|<h\d[^>]*>)'
            r'\s*([^<]+)',
            html,
            re.DOTALL | re.IGNORECASE,
        ):
            path = match.group(1)
            title = match.group(2).strip()
            url = f"https://www.minecraft.net{path}"

            # Update title if we found a better one
            for article in articles:
                if article["url"] == url and title:
                    article["title"] = title
                    break

        return articles

    def _role_mention(self) -> str:
        """Get Minecraft News role mention if it exists."""
        if not self.bot.guilds:
            return ""
        role = discord.utils.get(self.bot.guilds[0].roles, name="Minecraft News")
        return role.mention if role else ""

    async def _post_article(
        self,
        channel: discord.abc.Messageable,
        article: dict,
    ) -> None:
        embed = discord.Embed(
            title=article["title"][:256],
            url=article["url"],
            color=discord.Color.green(),  # Minecraft green
        )
        embed.set_footer(text="Minecraft.net")
        embed.set_thumbnail(
            url="https://www.minecraft.net/etc.clientlibs/minecraft/clientlibs/main/resources/favicon-96x96.png"
        )

        mention = self._role_mention()
        await channel.send(content=mention, embed=embed)
        log.info("Posted Minecraft news: %s", article["title"])

    @commands.command(name="testminecraftnews")
    @commands.is_owner()
    async def test_minecraft_news(self, ctx: commands.Context) -> None:
        """Force-check Minecraft news and show results."""
        async with ctx.typing():
            try:
                articles = await self._fetch_articles()
            except Exception as exc:
                await ctx.send(f"Error fetching articles: {exc}")
                return

            game_updates = [a for a in articles if _is_game_update(a["title"])]

            await ctx.send(
                f"Found {len(articles)} total articles, "
                f"{len(game_updates)} are game updates."
            )

            # Show first 5 game updates
            for article in game_updates[:5]:
                new_marker = "(NEW)" if article["url"] not in self.seen else "(seen)"
                await ctx.send(f"{new_marker} **{article['title']}**\n{article['url']}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MinecraftNews(bot))

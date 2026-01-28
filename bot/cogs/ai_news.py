from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from xml.etree import ElementTree

import aiohttp
import discord
from discord.ext import commands, tasks

log = logging.getLogger("milo.ai_news")

DATA_FILE = Path("data/ai_news.json")

# RSS / source URLs
OPENAI_RSS = "https://openai.com/blog/rss.xml"
GOOGLE_RSS = "https://blog.google/technology/ai/rss/"
ANTHROPIC_NEWS = "https://www.anthropic.com/news"
MICROSOFT_RSS = (
    "https://www.microsoft.com/en-us/microsoft-365/blog/product/"
    "microsoft-365-copilot/feed/"
)

# NanoGPT API (same endpoint the service uses)
NANOGPT_URL = "https://nano-gpt.com/api/v1/chat/completions"

FILTER_PROMPT = """\
You are classifying an article from an AI company blog.

Decide whether this article is about a NEW AI feature, model release, \
significant product update, or major capability announcement.

Articles to POST (answer YES):
- New model releases (e.g. GPT-5, Claude 4, Gemini 2)
- New product features or capabilities
- Major API updates or new APIs
- Significant product launches or updates

Articles to SKIP (answer NO):
- Research papers or technical reports
- Hiring or company culture posts
- Policy, safety, or governance essays
- Business partnerships or funding news
- General thought-leadership or opinion pieces
- Minor blog posts, tutorials, or how-to guides

Title: {title}
Description: {description}

Respond in EXACTLY this format (no extra text):
VERDICT: YES or NO
SUMMARY: 2-3 sentence summary of the announcement (write this even if NO)"""

# Provider colors
PROVIDER_CONFIG = {
    "openai": {
        "name": "OpenAI",
        "color": discord.Color.from_rgb(0x10, 0xA3, 0x7F),
        "footer": "OpenAI",
    },
    "anthropic": {
        "name": "Anthropic",
        "color": discord.Color.from_rgb(0xD9, 0x77, 0x57),
        "footer": "Anthropic",
    },
    "google": {
        "name": "Google AI",
        "color": discord.Color.from_rgb(0x42, 0x85, 0xF4),
        "footer": "Google AI",
    },
    "microsoft": {
        "name": "Microsoft Copilot",
        "color": discord.Color.from_rgb(0x00, 0xA4, 0xEF),
        "footer": "Microsoft Copilot",
    },
}


def _load_seen() -> dict[str, list[str]]:
    if not DATA_FILE.exists():
        return {}
    try:
        with DATA_FILE.open() as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        log.exception("Failed to load ai_news data")
        return {}


def _save_seen(seen: dict[str, list[str]]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with DATA_FILE.open("w") as f:
        json.dump(seen, f, indent=2)


def _parse_rss(xml_text: str) -> list[dict]:
    """Parse an RSS 2.0 feed and return items."""
    root = ElementTree.fromstring(xml_text)
    items: list[dict] = []
    for item in root.iter("item"):
        title = item.findtext("title", "").strip()
        link = item.findtext("link", "").strip()
        description = item.findtext("description", "").strip()
        # Strip HTML from description
        description = re.sub(r"<[^>]+>", "", description)
        if link:
            items.append({
                "title": title,
                "url": link,
                "description": description[:1000],
            })
    return items


def _parse_atom(xml_text: str) -> list[dict]:
    """Parse an Atom feed and return items."""
    root = ElementTree.fromstring(xml_text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    items: list[dict] = []
    for entry in root.findall("atom:entry", ns):
        title = (entry.findtext("atom:title", ns=ns) or "").strip()
        # Atom links are in <link> elements with href attribute
        link_el = entry.find("atom:link[@rel='alternate']", ns)
        if link_el is None:
            link_el = entry.find("atom:link", ns)
        url = link_el.get("href", "") if link_el is not None else ""
        summary = (entry.findtext("atom:summary", ns=ns) or "").strip()
        content = (entry.findtext("atom:content", ns=ns) or "").strip()
        description = summary or content
        description = re.sub(r"<[^>]+>", "", description)
        if url:
            items.append({
                "title": title,
                "url": url,
                "description": description[:1000],
            })
    return items


class AINews(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        settings = bot.settings  # type: ignore[attr-defined]
        self.channel_id = settings.ai_news_channel_id
        self._api_key = settings.nanogpt_api_key
        self.seen: dict[str, list[str]] = _load_seen()
        self._first_run = not self.seen
        self.check_ai_news.start()

    def cog_unload(self) -> None:
        self.check_ai_news.cancel()

    # -- Main loop ---------------------------------------------------------

    @tasks.loop(minutes=30)
    async def check_ai_news(self) -> None:
        results = await asyncio.gather(
            self._check_openai(),
            self._check_google(),
            self._check_anthropic(),
            self._check_microsoft(),
            return_exceptions=True,
        )

        providers = ["openai", "google", "anthropic", "microsoft"]
        all_new: list[tuple[str, dict]] = []

        for provider, result in zip(providers, results):
            if isinstance(result, Exception):
                log.exception("Error checking %s", provider, exc_info=result)
                continue
            for article in result:
                if article["url"] not in self.seen.get(provider, []):
                    all_new.append((provider, article))

        if self._first_run:
            # Seed all current articles as seen
            for provider, article in all_new:
                self.seen.setdefault(provider, []).append(article["url"])
            _save_seen(self.seen)
            total = sum(len(v) for v in self.seen.values())
            self._first_run = False
            log.info("AI news: seeded %d existing articles", total)
            return

        if not all_new:
            return

        channel = self.bot.get_channel(self.channel_id)
        if not channel:
            log.error("AI news channel %s not found", self.channel_id)
            return

        for provider, article in all_new:
            try:
                should_post, summary = await self._filter_article(
                    article["title"], article["description"]
                )
                if should_post:
                    await self._post_article(channel, article, provider, summary)
            except Exception:
                log.exception(
                    "Error filtering/posting article: %s", article["title"]
                )
            # Mark as seen regardless
            self.seen.setdefault(provider, []).append(article["url"])

        _save_seen(self.seen)

    @check_ai_news.before_loop
    async def before_check(self) -> None:
        await self.bot.wait_until_ready()

    # -- Source fetchers ---------------------------------------------------

    async def _fetch(self, url: str) -> str:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
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
                return await resp.text()

    async def _check_openai(self) -> list[dict]:
        xml_text = await self._fetch(OPENAI_RSS)
        # OpenAI feed may be Atom or RSS; try both
        try:
            return _parse_rss(xml_text)
        except ElementTree.ParseError:
            return _parse_atom(xml_text)

    async def _check_google(self) -> list[dict]:
        xml_text = await self._fetch(GOOGLE_RSS)
        try:
            return _parse_rss(xml_text)
        except ElementTree.ParseError:
            return _parse_atom(xml_text)

    async def _check_anthropic(self) -> list[dict]:
        html = await self._fetch(ANTHROPIC_NEWS)
        return self._parse_anthropic_news(html)

    async def _check_microsoft(self) -> list[dict]:
        xml_text = await self._fetch(MICROSOFT_RSS)
        try:
            return _parse_rss(xml_text)
        except ElementTree.ParseError:
            return _parse_atom(xml_text)

    @staticmethod
    def _parse_anthropic_news(html: str) -> list[dict]:
        """Extract article links from the Anthropic /news page."""
        articles: list[dict] = []
        seen_urls: set[str] = set()
        # Look for links to /news/<slug> articles
        for match in re.finditer(
            r'<a[^>]*href="(/news/[^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL
        ):
            path, inner = match.group(1), match.group(2)
            url = f"https://www.anthropic.com{path}"
            if url in seen_urls:
                continue
            seen_urls.add(url)
            # Extract title text from inner HTML
            title = re.sub(r"<[^>]+>", "", inner).strip()
            if not title:
                continue
            articles.append({
                "title": title,
                "url": url,
                "description": "",
            })
        return articles

    # -- AI filter ---------------------------------------------------------

    async def _filter_article(
        self, title: str, description: str
    ) -> tuple[bool, str]:
        """Ask NanoGPT whether this article is a feature announcement.

        Returns (should_post, summary).
        """
        prompt = FILTER_PROMPT.format(
            title=title,
            description=description[:500] if description else "(no description)",
        )

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "chatgpt-4o-latest",
            "messages": [
                {"role": "user", "content": prompt},
            ],
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                NANOGPT_URL,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

        reply = data["choices"][0]["message"]["content"].strip()

        # Parse verdict
        verdict_match = re.search(r"VERDICT:\s*(YES|NO)", reply, re.IGNORECASE)
        summary_match = re.search(r"SUMMARY:\s*(.+)", reply, re.DOTALL)

        should_post = bool(verdict_match and verdict_match.group(1).upper() == "YES")
        summary = summary_match.group(1).strip() if summary_match else ""

        return should_post, summary

    # -- Posting -----------------------------------------------------------

    def _role_mention(self) -> str:
        role = discord.utils.get(self.bot.guilds[0].roles, name="AI News")
        return role.mention if role else ""

    async def _post_article(
        self,
        channel: discord.abc.Messageable,
        article: dict,
        provider: str,
        summary: str,
    ) -> None:
        config = PROVIDER_CONFIG[provider]
        embed = discord.Embed(
            title=article["title"][:256],
            url=article["url"],
            description=summary[:4096] if summary else article["description"][:4096],
            color=config["color"],
        )
        embed.set_footer(text=config["footer"])
        mention = self._role_mention()
        await channel.send(content=mention, embed=embed)
        log.info("Posted AI news: [%s] %s", provider, article["title"])

    # -- Test command ------------------------------------------------------

    @commands.command(name="testainews")
    @commands.is_owner()
    async def test_ai_news(self, ctx: commands.Context) -> None:
        """Force-check all AI news sources and post any feature announcements."""
        async with ctx.typing():
            results = await asyncio.gather(
                self._check_openai(),
                self._check_google(),
                self._check_anthropic(),
                self._check_microsoft(),
                return_exceptions=True,
            )

            providers = ["openai", "google", "anthropic", "microsoft"]
            total = 0
            posted = 0

            for provider, result in zip(providers, results):
                if isinstance(result, Exception):
                    await ctx.send(f"**{provider}**: error - {result}")
                    continue
                total += len(result)
                # Post the most recent article from each provider for testing
                if result:
                    article = result[0]
                    try:
                        should_post, summary = await self._filter_article(
                            article["title"], article["description"]
                        )
                        label = "PASS" if should_post else "SKIP"
                        await ctx.send(
                            f"**{provider}** ({len(result)} articles) "
                            f"latest: [{label}] {article['title']}"
                        )
                        if should_post:
                            await self._post_article(
                                ctx.channel, article, provider, summary
                            )
                            posted += 1
                    except Exception as exc:
                        await ctx.send(
                            f"**{provider}**: filter error - {exc}"
                        )
                else:
                    await ctx.send(f"**{provider}**: no articles found")

            await ctx.send(
                f"Done. Found {total} total articles, posted {posted}."
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AINews(bot))

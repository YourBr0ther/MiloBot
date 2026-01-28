from __future__ import annotations

import logging

import aiohttp
import discord
from discord.ext import commands, tasks

from bot.services.nanogpt import NanoGPTService

log = logging.getLogger("milo.nintendo_watcher")

REDDIT_URL = "https://www.reddit.com/r/NintendoSwitch+nintendo/hot.json?limit=50"
USER_AGENT = "miloBot/1.0"
SCORE_THRESHOLD = 500
NINTENDO_RED = 0xE60012

VERIFY_PROMPT = (
    "A Reddit post titled \"{title}\" was found in r/{subreddit}. "
    "The post body is:\n\n{body}\n\n"
    "Is this post announcing or linking to an actual Nintendo Direct "
    "event/stream/video? Or is it just a discussion/speculation/reaction post? "
    "Reply with only YES or NO."
)


class NintendoWatcher(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        settings = bot.settings  # type: ignore[attr-defined]
        self.channel_id = settings.nintendo_channel_id
        self.nanogpt = NanoGPTService(settings.nanogpt_api_key)
        self.seen_ids: set[str] = set()
        self._first_run = True
        self.check_nintendo_direct.start()

    def cog_unload(self) -> None:
        self.check_nintendo_direct.cancel()

    @tasks.loop(minutes=5)
    async def check_nintendo_direct(self) -> None:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    REDDIT_URL,
                    headers={"User-Agent": USER_AGENT},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json()

            posts = data.get("data", {}).get("children", [])
            matching = [
                p["data"]
                for p in posts
                if "nintendo direct" in p["data"].get("title", "").lower()
                and p["data"].get("score", 0) >= SCORE_THRESHOLD
            ]

            if not matching:
                if self._first_run:
                    self._first_run = False
                    log.info("Nintendo watcher: first run, no matching posts to seed")
                return

            if self._first_run:
                self.seen_ids = {p["id"] for p in matching}
                self._first_run = False
                log.info(
                    "Nintendo watcher: seeded %d existing post IDs",
                    len(self.seen_ids),
                )
                return

            new_posts = [p for p in matching if p["id"] not in self.seen_ids]
            if not new_posts:
                return

            channel = self.bot.get_channel(self.channel_id)
            if not channel:
                log.error("Nintendo channel %s not found", self.channel_id)
                return

            async with aiohttp.ClientSession() as verify_session:
                for post in new_posts:
                    self.seen_ids.add(post["id"])
                    await self._verify_and_alert(verify_session, channel, post)

        except Exception:
            log.exception("Error checking Nintendo Direct posts")

    def _role_mention(self) -> str:
        role = discord.utils.get(self.bot.guilds[0].roles, name="Nintendo Direct")
        return role.mention if role else ""

    async def _verify_and_alert(
        self,
        session: aiohttp.ClientSession,
        channel: discord.abc.Messageable,
        post: dict,
    ) -> None:
        title = post.get("title", "")
        subreddit = post.get("subreddit", "")
        body = (post.get("selftext") or "")[:2000]
        permalink = f"https://www.reddit.com{post.get('permalink', '')}"
        score = post.get("score", 0)
        num_comments = post.get("num_comments", 0)

        try:
            answer = await self.nanogpt.ask(
                session,
                VERIFY_PROMPT.format(title=title, subreddit=subreddit, body=body),
            )
        except Exception:
            log.exception("LLM verification failed for post %s", post.get("id"))
            return

        if "YES" not in answer.upper():
            log.info(
                "Nintendo watcher: post '%s' failed LLM verification (answer: %s)",
                title,
                answer.strip(),
            )
            return

        embed = discord.Embed(
            title=title,
            url=permalink,
            color=NINTENDO_RED,
        )
        embed.add_field(name="Subreddit", value=f"r/{subreddit}", inline=True)
        embed.add_field(name="Score", value=str(score), inline=True)
        embed.add_field(name="Comments", value=str(num_comments), inline=True)
        embed.set_footer(text="r/NintendoSwitch + r/nintendo")

        mention = self._role_mention()
        await channel.send(content=mention, embed=embed)
        log.info("Nintendo Direct alert sent: %s", title)

    @check_nintendo_direct.before_loop
    async def before_check(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(NintendoWatcher(bot))

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree

import aiohttp
import discord
from discord.ext import commands, tasks

log = logging.getLogger("milo.sc_youtube")

RSI_CHANNEL_ID = "UCTeLqJq1mXUX5WWoNXLmOIA"
YOUTUBE_RSS_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={RSI_CHANNEL_ID}"

DATA_FILE = Path("data/sc_youtube.json")

RSI_BLUE = discord.Color.from_rgb(0x1A, 0x3D, 0x5C)


def _load_seen_ids() -> set[str]:
    if not DATA_FILE.exists():
        return set()
    try:
        with DATA_FILE.open() as f:
            data = json.load(f)
        return set(data.get("seen_video_ids", []))
    except (json.JSONDecodeError, OSError):
        log.exception("Failed to load sc_youtube data")
        return set()


def _save_seen_ids(seen: set[str]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with DATA_FILE.open("w") as f:
        json.dump({"seen_video_ids": sorted(seen)}, f, indent=2)


class SCYouTubeWatcher(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        settings = bot.settings  # type: ignore[attr-defined]
        self.channel_id = settings.sc_youtube_channel_id
        self.seen_video_ids: set[str] = _load_seen_ids()
        self._first_run = not self.seen_video_ids
        self.check_videos.start()

    def cog_unload(self) -> None:
        self.check_videos.cancel()

    @tasks.loop(minutes=10)
    async def check_videos(self) -> None:
        try:
            videos = await self._fetch_videos()
            if not videos:
                if self._first_run:
                    self._first_run = False
                    log.info("SC YouTube watcher: first run, no videos found")
                return

            if self._first_run:
                self.seen_video_ids.update(v["video_id"] for v in videos)
                _save_seen_ids(self.seen_video_ids)
                self._first_run = False
                log.info(
                    "SC YouTube watcher: seeded %d video IDs",
                    len(self.seen_video_ids),
                )
                return

            new_videos = [v for v in videos if v["video_id"] not in self.seen_video_ids]
            if not new_videos:
                return

            channel = self.bot.get_channel(self.channel_id)
            if not channel:
                log.error("SC YouTube channel %s not found", self.channel_id)
                return

            for video in new_videos:
                await self._post_video(channel, video)
                self.seen_video_ids.add(video["video_id"])

            _save_seen_ids(self.seen_video_ids)

        except Exception:
            log.exception("Error checking RSI YouTube videos")

    async def _fetch_videos(self) -> list[dict]:
        """Fetch recent videos from the RSI YouTube channel via RSS."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                YOUTUBE_RSS_URL, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                resp.raise_for_status()
                xml_text = await resp.text()

        root = ElementTree.fromstring(xml_text)
        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "yt": "http://www.youtube.com/xml/schemas/2015",
        }

        cutoff = datetime.now().astimezone() - timedelta(days=7)
        videos = []
        for entry in root.findall("atom:entry", ns):
            video_id_el = entry.find("yt:videoId", ns)
            title_el = entry.find("atom:title", ns)
            published_el = entry.find("atom:published", ns)

            if video_id_el is None or title_el is None:
                continue

            pub_date = None
            pub_text = published_el.text if published_el is not None else None
            if pub_text:
                try:
                    pub_date = datetime.fromisoformat(pub_text.replace("Z", "+00:00"))
                except ValueError:
                    pass

            if pub_date and pub_date < cutoff:
                continue

            videos.append({
                "video_id": video_id_el.text,
                "title": title_el.text,
                "published": pub_text,
                "pub_date": pub_date,
            })

        return videos

    def _role_mention(self) -> str:
        role = discord.utils.get(self.bot.guilds[0].roles, name="SC YouTube")
        return role.mention if role else ""

    async def _post_video(
        self, channel: discord.abc.Messageable, video: dict
    ) -> None:
        video_id = video["video_id"]
        title = video["title"]
        url = f"https://www.youtube.com/watch?v={video_id}"

        embed = discord.Embed(title=title, url=url, color=RSI_BLUE)
        embed.set_image(url=f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg")

        if video.get("pub_date"):
            embed.add_field(
                name="Published",
                value=discord.utils.format_dt(video["pub_date"], style="R"),
                inline=True,
            )

        embed.set_footer(text="Roberts Space Industries")

        mention = self._role_mention()
        await channel.send(content=mention, embed=embed)
        log.info("Posted RSI YouTube video: %s", title)

    @check_videos.before_loop
    async def before_check(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SCYouTubeWatcher(bot))

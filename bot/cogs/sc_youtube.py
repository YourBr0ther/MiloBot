from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import discord
from discord.ext import commands, tasks

log = logging.getLogger("milo.sc_youtube")

RSI_CHANNEL_ID = "UCTeLqJq1mXUX5WWoNXLmOIA"

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
        """Fetch recent videos from the RSI YouTube channel via yt-dlp."""
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "--flat-playlist",
            "--print", "%(id)s\t%(title)s",
            "--playlist-end", "15",
            "--no-warnings",
            f"https://www.youtube.com/channel/{RSI_CHANNEL_ID}/videos",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)

        if proc.returncode != 0:
            log.error("yt-dlp failed (rc=%d): %s", proc.returncode, stderr.decode()[:200])
            return []

        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        videos = []
        for line in stdout.decode().strip().splitlines():
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            video_id, title = parts
            videos.append({
                "video_id": video_id,
                "title": title,
                "published": now_iso,
                "pub_date": now,
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

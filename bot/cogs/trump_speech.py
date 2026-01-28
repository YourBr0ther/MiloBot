from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import TypedDict
from xml.etree import ElementTree

import aiohttp
import discord
from discord.ext import commands, tasks

from bot.services.nanogpt import NanoGPTService

log = logging.getLogger("milo.trump_speech")

# YouTube RSS feeds for channels that cover Trump speeches
YOUTUBE_CHANNELS = {
    "White House": "UCYxRlFDqcWM4y7FfpiAN3KQ",
    "C-SPAN": "UCb--64Gl51jIEVE-GLDAVTg",
    "Fox News": "UCXIJgqnII2ZOINSWNOGFThA",
}

YOUTUBE_RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

# Keywords to identify Trump speeches
TITLE_KEYWORDS = [
    "trump",
    "president trump",
    "potus",
]

SPEECH_KEYWORDS = [
    "speech",
    "speaks",
    "address",
    "remarks",
    "delivers",
    "rally",
    "press conference",
    "news conference",
    "briefing",
    "announcement",
    "statement",
    "signing",
    "oval office",
    "state of the union",
    "town hall",
]

MIN_DURATION_SECONDS = 600  # 10 minutes minimum

DATA_FILE = Path("data/trump_speeches.json")

SUMMARY_PROMPT = """\
You are summarizing a political speech for a Discord server.

Rules:
- Provide a concise, neutral summary of the key points
- Focus on: policy announcements, executive actions, major statements
- Use bullet points for main topics covered
- Note any significant quotes or memorable moments
- Keep it factual and non-partisan
- Use Discord markdown formatting (bold, bullet points)
- Maximum 3-4 paragraphs or ~10 bullet points
- Do NOT include the title or date (that will be in the embed)

Speech transcript to summarize:
{content}"""


class SpeechRecord(TypedDict):
    date: str
    topic: str
    transcript_hash: str
    video_ids: list[str]
    title: str
    posted_at: str


class SpeechData(TypedDict):
    speeches: list[SpeechRecord]


def _load_data() -> SpeechData:
    if not DATA_FILE.exists():
        return {"speeches": []}
    try:
        with DATA_FILE.open() as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        log.exception("Failed to load speech data")
        return {"speeches": []}


def _save_data(data: SpeechData) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with DATA_FILE.open("w") as f:
        json.dump(data, f, indent=2)


def _extract_topic(title: str) -> str:
    """Extract a normalized topic from the video title."""
    # Remove common prefixes/suffixes and normalize
    lower = title.lower()
    # Remove channel names, "live", timestamps, etc.
    for remove in ["live:", "live |", "full speech", "full video", "watch:", "| c-span"]:
        lower = lower.replace(remove, "")
    # Extract key topic words
    lower = re.sub(r"[^\w\s]", " ", lower)
    words = lower.split()
    # Remove common filler words
    filler = {"the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "or", "trump", "president", "donald"}
    topic_words = [w for w in words if w not in filler and len(w) > 2]
    return " ".join(topic_words[:5])


def _hash_transcript(transcript: str) -> str:
    """Create a hash of the first ~500 words for similarity checking."""
    words = transcript.split()[:500]
    normalized = " ".join(words).lower()
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def _is_trump_speech(title: str, source: str = "") -> bool:
    """Check if the video title indicates a Trump speech."""
    lower = title.lower()
    has_trump = any(kw in lower for kw in TITLE_KEYWORDS)
    has_speech = any(kw in lower for kw in SPEECH_KEYWORDS)

    # White House channel: trust speech keywords alone (it's all official content)
    if source == "White House":
        return has_speech

    # Other channels: require Trump + speech keywords
    return has_trump and has_speech


async def _get_video_duration(video_id: str) -> int | None:
    """Get video duration in seconds using yt-dlp."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "--print", "duration",
            "--no-download",
            "--no-warnings",
            "--", f"https://www.youtube.com/watch?v={video_id}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode == 0:
            duration_str = stdout.decode().strip()
            if duration_str and duration_str.replace(".", "").isdigit():
                return int(float(duration_str))
    except Exception:
        log.exception("Failed to get duration for video %s", video_id)
    return None


async def _get_captions(video_id: str) -> str | None:
    """Download and return captions for a video using yt-dlp."""
    caption_base = f"/tmp/caption_{video_id}"
    try:
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "--write-auto-sub",
            "--sub-lang", "en",
            "--skip-download",
            "--sub-format", "vtt",
            "--no-warnings",
            "-o", caption_base,
            "--", f"https://www.youtube.com/watch?v={video_id}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=120)

        # Find the caption file
        caption_file = None
        for pattern in [f"{caption_base}.en.vtt", f"{caption_base}.en-orig.vtt"]:
            p = Path(pattern)
            if p.exists():
                caption_file = p
                break

        if not caption_file:
            # List all files that match
            for f in Path("/tmp").glob(f"caption_{video_id}*.vtt"):
                caption_file = f
                break

        if caption_file and caption_file.exists():
            content = caption_file.read_text()
            # Clean up the file
            caption_file.unlink()
            # Parse VTT and extract text
            return _parse_vtt(content)
    except Exception:
        log.exception("Failed to get captions for video %s", video_id)
    return None


def _parse_vtt(vtt_content: str) -> str:
    """Parse VTT caption file and extract clean text."""
    lines = []
    seen = set()

    for line in vtt_content.split("\n"):
        # Skip headers, timestamps, and formatting
        line = line.strip()
        if not line:
            continue
        if line.startswith("WEBVTT"):
            continue
        if line.startswith("Kind:") or line.startswith("Language:"):
            continue
        if re.match(r"^\d{2}:\d{2}", line):  # Timestamp line
            continue
        if re.match(r"^[\d\s\-:\.>]+$", line):  # Position/timing line
            continue
        if line.startswith("<"):  # HTML-like tags
            line = re.sub(r"<[^>]+>", "", line)

        # Remove duplicate consecutive lines (common in auto-captions)
        if line and line not in seen:
            lines.append(line)
            seen.add(line)
            # Reset seen after some lines to allow repeated phrases
            if len(seen) > 20:
                seen.clear()

    return " ".join(lines)


class TrumpSpeechWatcher(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        settings = bot.settings  # type: ignore[attr-defined]
        self.channel_id = settings.trump_speech_channel_id
        self.nanogpt = NanoGPTService(settings.nanogpt_api_key)
        self.seen_video_ids: set[str] = set()
        self._first_run = True
        self.check_speeches.start()

    def cog_unload(self) -> None:
        self.check_speeches.cancel()

    @tasks.loop(minutes=30)
    async def check_speeches(self) -> None:
        try:
            all_videos = []

            async with aiohttp.ClientSession() as session:
                for channel_name, channel_id in YOUTUBE_CHANNELS.items():
                    try:
                        videos = await self._fetch_channel_videos(session, channel_id)
                        for v in videos:
                            v["source"] = channel_name
                        all_videos.extend(videos)
                    except Exception:
                        log.exception("Failed to fetch videos from %s", channel_name)

            # Filter to Trump speeches
            trump_videos = [v for v in all_videos if _is_trump_speech(v["title"], v.get("source", ""))]

            if not trump_videos:
                if self._first_run:
                    self._first_run = False
                    log.info("Trump speech watcher: first run, no matching videos found")
                return

            if self._first_run:
                # Seed seen IDs from existing data and current videos
                data = _load_data()
                for speech in data["speeches"]:
                    self.seen_video_ids.update(speech["video_ids"])
                self.seen_video_ids.update(v["video_id"] for v in trump_videos)
                self._first_run = False
                log.info(
                    "Trump speech watcher: seeded %d video IDs",
                    len(self.seen_video_ids),
                )
                return

            # Find new videos
            new_videos = [v for v in trump_videos if v["video_id"] not in self.seen_video_ids]
            if not new_videos:
                return

            channel = self.bot.get_channel(self.channel_id)
            if not channel:
                log.error("Trump speech channel %s not found", self.channel_id)
                return

            for video in new_videos:
                await self._process_video(channel, video)

        except Exception:
            log.exception("Error checking Trump speeches")

    async def _fetch_channel_videos(
        self, session: aiohttp.ClientSession, channel_id: str
    ) -> list[dict]:
        """Fetch recent videos from a YouTube channel via RSS."""
        url = YOUTUBE_RSS_URL.format(channel_id=channel_id)
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            resp.raise_for_status()
            xml_text = await resp.text()

        root = ElementTree.fromstring(xml_text)
        ns = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}

        videos = []
        for entry in root.findall("atom:entry", ns):
            video_id = entry.find("yt:videoId", ns)
            title = entry.find("atom:title", ns)
            published = entry.find("atom:published", ns)

            if video_id is not None and title is not None:
                pub_date = None
                if published is not None and published.text:
                    try:
                        pub_date = datetime.fromisoformat(published.text.replace("Z", "+00:00"))
                    except ValueError:
                        pass

                # Only consider videos from the last 7 days
                if pub_date and pub_date < datetime.now(pub_date.tzinfo) - timedelta(days=7):
                    continue

                videos.append({
                    "video_id": video_id.text,
                    "title": title.text,
                    "published": published.text if published is not None else None,
                })

        return videos

    def _role_mention(self) -> str:
        role = discord.utils.get(self.bot.guilds[0].roles, name="Trump Speeches")
        return role.mention if role else ""

    async def _process_video(
        self, channel: discord.abc.Messageable, video: dict
    ) -> None:
        """Process a single video: check duration, dedup, get captions, summarize."""
        video_id = video["video_id"]
        title = video["title"]

        log.info("Processing potential Trump speech: %s", title)

        # Check duration
        duration = await _get_video_duration(video_id)
        if duration is None:
            log.warning("Could not get duration for %s, skipping", video_id)
            self.seen_video_ids.add(video_id)
            return

        if duration < MIN_DURATION_SECONDS:
            log.info("Video %s too short (%ds), skipping", video_id, duration)
            self.seen_video_ids.add(video_id)
            return

        # Extract date and topic for deduplication
        pub_date = video.get("published", "")[:10]  # YYYY-MM-DD
        topic = _extract_topic(title)

        # Check if we've already covered this speech (same date + similar topic)
        data = _load_data()
        for speech in data["speeches"]:
            if speech["date"] == pub_date and self._topics_similar(speech["topic"], topic):
                log.info("Already covered speech from %s about '%s', skipping", pub_date, topic)
                self.seen_video_ids.add(video_id)
                # Add this video ID to the existing record
                if video_id not in speech["video_ids"]:
                    speech["video_ids"].append(video_id)
                    _save_data(data)
                return

        # Get captions
        captions = await _get_captions(video_id)
        if not captions or len(captions) < 500:
            log.warning("Could not get adequate captions for %s", video_id)
            self.seen_video_ids.add(video_id)
            return

        # Check transcript similarity
        transcript_hash = _hash_transcript(captions)
        for speech in data["speeches"]:
            if speech["transcript_hash"] == transcript_hash:
                log.info("Transcript matches existing speech, skipping")
                self.seen_video_ids.add(video_id)
                if video_id not in speech["video_ids"]:
                    speech["video_ids"].append(video_id)
                    _save_data(data)
                return

        # Summarize
        try:
            async with aiohttp.ClientSession() as session:
                summary = await self.nanogpt.ask(
                    session,
                    SUMMARY_PROMPT.format(content=captions[:12000]),
                )
        except Exception:
            log.exception("Failed to summarize speech: %s", title)
            return  # Don't mark as seen, retry next time

        # Post to Discord
        embed = discord.Embed(
            title=title,
            url=f"https://www.youtube.com/watch?v={video_id}",
            description=summary[:4096],
            color=discord.Color.from_rgb(178, 34, 52),  # Red
        )
        embed.add_field(name="Source", value=video.get("source", "YouTube"), inline=True)
        if duration:
            mins, secs = divmod(duration, 60)
            embed.add_field(name="Duration", value=f"{mins}m {secs}s", inline=True)
        embed.set_footer(text="Trump Speech Summary")

        mention = self._role_mention()
        await channel.send(content=mention, embed=embed)
        log.info("Posted Trump speech summary: %s", title)

        # Save record
        self.seen_video_ids.add(video_id)
        data["speeches"].append({
            "date": pub_date,
            "topic": topic,
            "transcript_hash": transcript_hash,
            "video_ids": [video_id],
            "title": title,
            "posted_at": datetime.utcnow().isoformat(),
        })
        _save_data(data)

    @staticmethod
    def _topics_similar(topic1: str, topic2: str) -> bool:
        """Check if two topics are similar enough to be the same speech."""
        words1 = set(topic1.lower().split())
        words2 = set(topic2.lower().split())
        if not words1 or not words2:
            return False
        intersection = words1 & words2
        union = words1 | words2
        similarity = len(intersection) / len(union)
        return similarity > 0.3  # 30% word overlap

    @check_speeches.before_loop
    async def before_check(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TrumpSpeechWatcher(bot))

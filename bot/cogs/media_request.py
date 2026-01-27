from __future__ import annotations

import logging
from dataclasses import dataclass

import aiohttp
import discord
from discord.ext import commands, tasks

from bot.services.overseerr import OverseerrService

log = logging.getLogger("milo.media_request")

MEDIA_STATUS_AVAILABLE = 5


@dataclass
class PendingRequest:
    overseerr_request_id: int
    media_id: int
    user_id: int
    channel_id: int
    media_title: str


def _parse_result(item: dict) -> dict:
    """Extract display fields from an Overseerr search result."""
    media_type = item.get("mediaType", "movie")
    title = item.get("title") or item.get("name") or "Unknown"
    date_str = item.get("releaseDate") or item.get("firstAirDate") or ""
    year = date_str[:4] if date_str else ""
    display_title = f"{title} ({year})" if year else title
    return {
        "media_type": media_type,
        "title": title,
        "year": year,
        "display_title": display_title,
        "overview": item.get("overview", "No description available."),
        "tmdb_id": item.get("id"),
        "poster_path": item.get("posterPath"),
        "media_info": item.get("mediaInfo"),
    }


NUMBER_EMOJIS = ["1\u20e3", "2\u20e3", "3\u20e3"]


class SelectView(discord.ui.View):
    """Numbered buttons to pick one of up to 3 search results."""

    def __init__(self, cog: MediaRequest, items: list[dict]) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.items = items
        for idx, item in enumerate(items):
            button = discord.ui.Button(
                label=item["display_title"],
                emoji=NUMBER_EMOJIS[idx],
                style=discord.ButtonStyle.primary,
                custom_id=f"select_{idx}",
            )
            button.callback = self._make_callback(idx)
            self.add_item(button)
        cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.red, emoji="\u274c", custom_id="select_cancel")
        cancel.callback = self._cancel_callback
        self.add_item(cancel)

    def _make_callback(self, idx: int):
        async def callback(interaction: discord.Interaction) -> None:
            self.stop()
            item = self.items[idx]
            await self.cog.handle_selection(interaction, item)
        return callback

    async def _cancel_callback(self, interaction: discord.Interaction) -> None:
        self.stop()
        await interaction.response.send_message("Request cancelled.")


class ConfirmView(discord.ui.View):
    """Request / Cancel buttons for a single chosen item."""

    def __init__(self, cog: MediaRequest, item: dict) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.item = item

    @discord.ui.button(label="Request", style=discord.ButtonStyle.green, emoji="\u2705")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        self.stop()
        item = self.item
        try:
            async with aiohttp.ClientSession() as session:
                result = await self.cog.overseerr.request_media(
                    session, item["media_type"], item["tmdb_id"],
                )
        except Exception:
            log.exception("Failed to submit request")
            await interaction.followup.send("Something went wrong submitting the request. Try again later.")
            return

        request_id = result.get("id")
        media_id = result.get("media", {}).get("id")

        await interaction.followup.send(
            f"**{item['display_title']}** has been requested! I'll let you know when it's ready on Plex."
        )

        if request_id and media_id:
            self.cog.pending[request_id] = PendingRequest(
                overseerr_request_id=request_id,
                media_id=media_id,
                user_id=interaction.user.id,
                channel_id=interaction.channel_id,
                media_title=item["display_title"],
            )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red, emoji="\u274c")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.send_message("Request cancelled.")


class MediaRequest(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        settings = bot.settings  # type: ignore[attr-defined]
        self.channel_id = settings.requests_channel_id
        self.overseerr = OverseerrService(settings.overseerr_url, settings.overseerr_api_key)
        self.plex_machine_id = settings.plex_machine_id
        self.plex_url = settings.plex_url.rstrip("/")
        self.plex_token = settings.plex_token
        self.pending: dict[int, PendingRequest] = {}
        self.poll_availability.start()

    def cog_unload(self) -> None:
        self.poll_availability.cancel()

    @commands.command(name="request")
    async def request_media(self, ctx: commands.Context, *, query: str) -> None:
        if ctx.channel.id != self.channel_id:
            await ctx.reply("Please use the <#{}> channel for media requests.".format(self.channel_id))
            return

        async with ctx.typing():
            try:
                async with aiohttp.ClientSession() as session:
                    results = await self.overseerr.search(session, query)
            except Exception:
                log.exception("Overseerr search failed")
                await ctx.reply("Something went wrong searching. Try again later.")
                return

        # Filter to movie/tv only and take top 3
        filtered = [r for r in results if r.get("mediaType") in ("movie", "tv")]
        if not filtered:
            await ctx.reply("No results found for that query.")
            return

        items = [_parse_result(r) for r in filtered[:3]]

        embed = discord.Embed(
            title="\U0001f50e Search Results",
            description="Pick the one you want:",
            color=discord.Color.blurple(),
        )
        for idx, item in enumerate(items):
            type_label = item["media_type"].upper()
            status_tag = ""
            media_info = item["media_info"]
            if media_info and media_info.get("status", 0) >= MEDIA_STATUS_AVAILABLE:
                status_tag = " \u2014 **Already on Plex**"
            embed.add_field(
                name=f"{NUMBER_EMOJIS[idx]} {item['display_title']}",
                value=f"{type_label}{status_tag}\n{item['overview'][:120]}",
                inline=False,
            )

        view = SelectView(self, items)
        await ctx.reply(embed=embed, view=view)

    async def handle_selection(self, interaction: discord.Interaction, item: dict) -> None:
        """Called when a user picks a result from the selection view."""
        media_info = item["media_info"]
        media_status = media_info.get("status", 0) if media_info else 0

        embed = discord.Embed(
            title=f"\U0001f3ac {item['display_title']}",
            description=item["overview"][:300],
            color=discord.Color.green() if media_status >= MEDIA_STATUS_AVAILABLE else discord.Color.blurple(),
        )
        embed.add_field(name="Type", value=item["media_type"].capitalize(), inline=True)

        if item["poster_path"]:
            embed.set_thumbnail(url=f"https://image.tmdb.org/t/p/w300{item['poster_path']}")

        if media_status >= MEDIA_STATUS_AVAILABLE:
            rating_key = media_info.get("ratingKey") or media_info.get("ratingKey4k")
            if rating_key:
                plex_url = (
                    f"{self.plex_url}/web/index.html#!/server/{self.plex_token}"
                    f"/details?key=/library/metadata/{rating_key}"
                )
                embed.add_field(name="Status", value=f"Already on Plex!\n[Open in Plex]({plex_url})", inline=False)
            else:
                embed.add_field(name="Status", value="Already available on Plex!", inline=False)
            await interaction.response.send_message(embed=embed)
        else:
            view = ConfirmView(self, item)
            await interaction.response.send_message(embed=embed, view=view)

    @tasks.loop(seconds=60)
    async def poll_availability(self) -> None:
        if not self.pending:
            return

        resolved: list[int] = []

        async with aiohttp.ClientSession() as session:
            for req_id, pending in self.pending.items():
                try:
                    req_data = await self.overseerr.get_request_status(session, req_id)
                    media = req_data.get("media", {})
                    status = media.get("status", 0)

                    if status >= MEDIA_STATUS_AVAILABLE:
                        rating_key = media.get("ratingKey") or media.get("ratingKey4k")

                        if rating_key:
                            plex_url = (
                                f"{self.plex_url}/web/index.html#!/server/{self.plex_token}"
                                f"/details?key=/library/metadata/{rating_key}"
                            )
                            message = (
                                f"**{pending.media_title}** is now available on Plex!\n{plex_url}"
                            )
                        else:
                            message = f"**{pending.media_title}** is now available on Plex!"

                        channel = self.bot.get_channel(pending.channel_id)
                        if channel:
                            await channel.send(f"<@{pending.user_id}> {message}")

                        resolved.append(req_id)
                except Exception:
                    log.exception("Error polling request %s", req_id)

        for req_id in resolved:
            self.pending.pop(req_id, None)

    @poll_availability.before_loop
    async def before_poll(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MediaRequest(bot))

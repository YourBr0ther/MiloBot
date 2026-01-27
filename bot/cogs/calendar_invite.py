from __future__ import annotations

import asyncio
import base64
import json
import logging
from datetime import datetime

import aiohttp
import discord
import fitz  # PyMuPDF
from discord.ext import commands

from bot.services.google_calendar import GoogleCalendarService
from bot.services.ics_parser import parse_ics
from bot.services.nanogpt import NanoGPTService
from bot.services.tavily import TavilyService

log = logging.getLogger("milo.calendar_invite")

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")


def _format_time(t: str) -> str:
    """Convert 24h HH:MM to 12h format like '2:00 PM'."""
    try:
        return datetime.strptime(t, "%H:%M").strftime("%-I:%M %p")
    except (ValueError, TypeError):
        return t


def _build_confirmation_embed(event: dict) -> discord.Embed:
    embed = discord.Embed(
        title="\U0001f4c5 New Calendar Event",
        color=discord.Color.blue(),
    )
    embed.add_field(name="Title", value=event.get("title", "Untitled"), inline=False)

    # Date line
    try:
        dt = datetime.strptime(event["start_date"], "%Y-%m-%d")
        date_str = dt.strftime("%A, %b %d, %Y")
    except (KeyError, ValueError):
        date_str = event.get("start_date", "Unknown")

    if event.get("end_date") and event["end_date"] != event.get("start_date"):
        try:
            end_dt = datetime.strptime(event["end_date"], "%Y-%m-%d")
            date_str += f" - {end_dt.strftime('%A, %b %d, %Y')}"
        except ValueError:
            pass

    embed.add_field(name="Date", value=date_str, inline=False)

    # Time line
    if event.get("start_time"):
        time_str = _format_time(event["start_time"])
        if event.get("end_time"):
            time_str += f" - {_format_time(event['end_time'])}"
        time_str += " ET"
        embed.add_field(name="Time", value=time_str, inline=False)

    if event.get("location"):
        location_str = event["location"]
        if event.get("maps_url"):
            location_str += f"\n[Open in Google Maps]({event['maps_url']})"
        embed.add_field(name="Where", value=location_str, inline=False)
    if event.get("description"):
        embed.add_field(name="Notes", value=event["description"], inline=False)

    return embed


class ConfirmationView(discord.ui.View):
    def __init__(
        self,
        *,
        event_data: dict,
        author_id: int,
        gcal: GoogleCalendarService,
        nanogpt: NanoGPTService,
        original_text: str | None = None,
    ) -> None:
        super().__init__(timeout=300)
        self.event_data = event_data
        self.author_id = author_id
        self.gcal = gcal
        self.nanogpt = nanogpt
        self.original_text = original_text
        self._waiting_for_edit: bool = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the person who submitted the event can use these buttons.",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        if self.message:  # type: ignore[attr-defined]
            try:
                embed = discord.Embed(
                    title="\u23f0 Timed Out",
                    description="Event confirmation timed out. Please try again.",
                    color=discord.Color.greyple(),
                )
                await self.message.edit(embed=embed, view=self)  # type: ignore[attr-defined]
            except discord.HTTPException:
                pass

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success, emoji="\u2705")
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        try:
            async with aiohttp.ClientSession() as session:
                result = await self.gcal.create_event(
                    session,
                    title=self.event_data.get("title", "Untitled Event"),
                    start_date=self.event_data["start_date"],
                    start_time=self.event_data.get("start_time"),
                    end_date=self.event_data.get("end_date"),
                    end_time=self.event_data.get("end_time"),
                    location=self.event_data.get("location"),
                    description=self.event_data.get("description"),
                )
            link = result.get("htmlLink", "")
            embed = discord.Embed(
                title="\u2705 Event Added!",
                description=f"**{self.event_data.get('title', 'Event')}** has been added to the calendar.",
                color=discord.Color.green(),
            )
            if link:
                embed.add_field(name="Calendar Link", value=f"[View Event]({link})", inline=False)
        except Exception:
            log.exception("Failed to create calendar event")
            embed = discord.Embed(
                title="\u274c Error",
                description="Failed to create the calendar event. Please try again.",
                color=discord.Color.red(),
            )

        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        await interaction.edit_original_response(embed=embed, view=self)
        self.stop()

    @discord.ui.button(label="Edit", style=discord.ButtonStyle.primary, emoji="\u270f\ufe0f")
    async def edit_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(
            "What would you like to change? Type your correction below.",
            ephemeral=True,
        )
        self._waiting_for_edit = True

        def check(m: discord.Message) -> bool:
            return m.author.id == self.author_id and m.channel.id == interaction.channel_id  # type: ignore[union-attr]

        try:
            msg = await interaction.client.wait_for("message", check=check, timeout=120)
        except asyncio.TimeoutError:
            self._waiting_for_edit = False
            return

        self._waiting_for_edit = False
        correction = msg.content.strip()
        if not correction:
            return

        # Re-extract with original context + correction
        context = (
            f"Original event details:\n{json.dumps(self.event_data, indent=2)}\n\n"
            f"User correction: {correction}\n\n"
            "Apply the correction and return the updated event as JSON."
        )
        try:
            async with aiohttp.ClientSession() as session:
                updated = await self.nanogpt.extract_event_from_text(session, context)
        except Exception:
            log.exception("Failed to re-extract event after edit")
            await msg.reply("Sorry, I couldn't process that edit. Please try again.")
            return

        if updated:
            self.event_data = updated
            embed = _build_confirmation_embed(updated)
            await self.message.edit(embed=embed, view=self)  # type: ignore[attr-defined]
            await msg.add_reaction("\U0001f44d")
        else:
            await msg.reply("I couldn't understand that correction. Please try again.")

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="\u274c")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        embed = discord.Embed(
            title="\u274c Event Cancelled",
            description="The event has been discarded.",
            color=discord.Color.red(),
        )
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()


class CalendarInvite(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        settings = bot.settings  # type: ignore[attr-defined]
        self.channel_id = settings.event_channel_id
        self.nanogpt = NanoGPTService(settings.nanogpt_api_key)
        self.tavily = TavilyService(settings.tavily_api_key)
        self.gcal = GoogleCalendarService(
            settings.google_service_account_path,
            settings.google_calendar_id,
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if message.channel.id != self.channel_id:
            return
        if message.content.startswith("!"):
            return

        async with message.channel.typing():
            event_data = await self._extract_event(message)
            if event_data and event_data.get("location"):
                await self._enrich_location(event_data)

        if event_data is None:
            await message.reply(
                "I couldn't extract any event details from that. "
                "Try sending a clearer description, image, PDF, or .ics file."
            )
            return

        embed = _build_confirmation_embed(event_data)
        view = ConfirmationView(
            event_data=event_data,
            author_id=message.author.id,
            gcal=self.gcal,
            nanogpt=self.nanogpt,
            original_text=message.content,
        )
        sent = await message.reply(embed=embed, view=view)
        view.message = sent  # type: ignore[attr-defined]

    async def _extract_event(self, message: discord.Message) -> dict | None:
        """Route the message to the appropriate extraction method."""
        attachment = message.attachments[0] if message.attachments else None

        if attachment:
            filename = attachment.filename.lower()

            # .ics file
            if filename.endswith(".ics"):
                data = await attachment.read()
                return parse_ics(data)

            # Image
            if any(filename.endswith(ext) for ext in IMAGE_EXTS):
                async with aiohttp.ClientSession() as session:
                    return await self.nanogpt.extract_event_from_image(session, attachment.url)

            # PDF
            if filename.endswith(".pdf"):
                return await self._extract_from_pdf(attachment)

        # Plain text
        text = message.content.strip()
        if text:
            async with aiohttp.ClientSession() as session:
                return await self.nanogpt.extract_event_from_text(session, text)

        return None

    async def _enrich_location(self, event_data: dict) -> None:
        """Look up the location via web search and enrich with full name/address/maps link."""
        location = event_data["location"]
        try:
            async with aiohttp.ClientSession() as session:
                search_context = await self.tavily.search(f"{location} address", session)
                if not search_context:
                    return
                place_info = await self.nanogpt.enrich_location(session, location, search_context)
                if not place_info:
                    return

            # Build enriched location string
            parts = []
            if place_info.get("name"):
                parts.append(place_info["name"])
            if place_info.get("address"):
                parts.append(place_info["address"])

            if parts:
                event_data["location"] = "\n".join(parts)

            if place_info.get("maps_query"):
                from urllib.parse import quote
                event_data["maps_url"] = f"https://www.google.com/maps/search/?api=1&query={quote(place_info['maps_query'])}"
        except Exception:
            log.debug("Location enrichment failed for %r, using original", location)

    async def _extract_from_pdf(self, attachment: discord.Attachment) -> dict | None:
        """Download a PDF, render the first page to an image, and extract via vision."""
        try:
            pdf_bytes = await attachment.read()
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            page = doc[0]
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("png")
            doc.close()

            b64 = base64.b64encode(img_bytes).decode()
            data_uri = f"data:image/png;base64,{b64}"

            async with aiohttp.ClientSession() as session:
                return await self.nanogpt.extract_event_from_image(session, data_uri)
        except Exception:
            log.exception("Failed to extract event from PDF")
            return None


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CalendarInvite(bot))

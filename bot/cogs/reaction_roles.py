from __future__ import annotations

import json
import logging
from pathlib import Path

import discord
from discord.ext import commands

log = logging.getLogger("milo.reaction_roles")

DATA_FILE = Path("data/reaction_roles.json")

ROLE_CHANNEL_ID = 1466216704727056467

# Emoji -> role name mapping
ROLE_MAP: dict[str, str] = {
    "\U0001f680": "SC Patch Notes",       # 🚀
    "\u2694\ufe0f": "WoW Patch Notes",    # ⚔️
    "\U0001f3ae": "Nintendo Direct",       # 🎮
    "\U0001f916": "AI News",               # 🤖
    "\U0001f399\ufe0f": "Trump Speeches",  # 🎙️
    "\U0001f4fa": "SC YouTube",            # 📺
    "\U0001f6f0\ufe0f": "RSI Status",     # 🛰️
}


def _load_data() -> dict:
    if not DATA_FILE.exists():
        return {}
    try:
        with DATA_FILE.open() as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        log.exception("Failed to load reaction_roles data")
        return {}


def _save_data(data: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with DATA_FILE.open("w") as f:
        json.dump(data, f, indent=2)


class ReactionRoles(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.data = _load_data()
        # message_id we're watching for reactions
        self.message_id: int | None = self.data.get("message_id")
        # role name -> role ID cache (populated on ready)
        self._role_ids: dict[str, int] = self.data.get("role_ids", {})

    @commands.command(name="setuproles")
    @commands.is_owner()
    async def setup_roles(self, ctx: commands.Context) -> None:
        """Create notification roles and post the reaction-role embed."""
        log.info("setuproles command invoked by %s", ctx.author)
        guild = ctx.guild
        if guild is None:
            await ctx.send("This command must be used in a server.")
            return

        channel = self.bot.get_channel(ROLE_CHANNEL_ID)
        if channel is None:
            await ctx.send(f"Channel {ROLE_CHANNEL_ID} not found.")
            return

        try:
            role_ids: dict[str, int] = {}
            for role_name in ROLE_MAP.values():
                existing = discord.utils.get(guild.roles, name=role_name)
                if existing:
                    role_ids[role_name] = existing.id
                    log.info("Role already exists: %s (%s)", role_name, existing.id)
                else:
                    role = await guild.create_role(
                        name=role_name,
                        mentionable=True,
                        reason="Reaction role setup by Milo",
                    )
                    role_ids[role_name] = role.id
                    log.info("Created role: %s (%s)", role_name, role.id)

            self._role_ids = role_ids

            # Build the embed
            lines = []
            for emoji, role_name in ROLE_MAP.items():
                role_id = role_ids[role_name]
                lines.append(f"{emoji}  →  <@&{role_id}>")

            embed = discord.Embed(
                title="Notification Roles",
                description=(
                    "React below to subscribe to the notifications you want to receive.\n"
                    "Remove your reaction to unsubscribe.\n\n"
                    + "\n".join(lines)
                ),
                color=discord.Color.blurple(),
            )
            embed.set_footer(text="Managed by Milo")

            msg = await channel.send(embed=embed)

            # Add reactions to the message
            for emoji in ROLE_MAP:
                await msg.add_reaction(emoji)

            self.message_id = msg.id
            self.data = {
                "message_id": msg.id,
                "role_ids": role_ids,
            }
            _save_data(self.data)

            await ctx.send(f"Reaction roles set up in <#{ROLE_CHANNEL_ID}>.")
        except Exception:
            log.exception("Failed to set up reaction roles")
            await ctx.send("Failed to set up reaction roles. Check logs.")

    # -- Reaction handlers --------------------------------------------------

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.message_id != self.message_id or payload.member is None:
            return
        if payload.member.bot:
            return

        emoji = str(payload.emoji)
        role_name = ROLE_MAP.get(emoji)
        if role_name is None:
            return

        role_id = self._role_ids.get(role_name)
        if role_id is None:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return

        role = guild.get_role(role_id)
        if role is None:
            return

        try:
            await payload.member.add_roles(role, reason="Reaction role")
            log.info("Gave %s role '%s'", payload.member, role_name)
        except discord.Forbidden:
            log.error("Missing permissions to assign role '%s'", role_name)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.message_id != self.message_id:
            return

        emoji = str(payload.emoji)
        role_name = ROLE_MAP.get(emoji)
        if role_name is None:
            return

        role_id = self._role_ids.get(role_name)
        if role_id is None:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return

        role = guild.get_role(role_id)
        if role is None:
            return

        try:
            member = await guild.fetch_member(payload.user_id)
            if member.bot:
                return
            await member.remove_roles(role, reason="Reaction role removed")
            log.info("Removed %s role '%s'", member, role_name)
        except discord.NotFound:
            log.warning("Member %s not found for role removal", payload.user_id)
        except discord.Forbidden:
            log.error("Missing permissions to remove role '%s'", role_name)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ReactionRoles(bot))

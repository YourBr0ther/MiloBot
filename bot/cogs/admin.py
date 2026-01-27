from __future__ import annotations

import logging
import sys

from discord.ext import commands

log = logging.getLogger("milo.admin")


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.log_channel_id = bot.settings.log_channel_id  # type: ignore[attr-defined]

    @commands.command(name="restart")
    async def restart(self, ctx: commands.Context) -> None:
        """Restart the bot. Only works in the bot-log channel."""
        if ctx.channel.id != self.log_channel_id:
            await ctx.send("This command can only be used in the bot-log channel.")
            return

        log.info("Restart requested by %s", ctx.author)
        await ctx.send("Restarting... be right back!")
        await self.bot.close()
        sys.exit(0)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Admin(bot))

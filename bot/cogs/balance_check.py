from __future__ import annotations

import logging
from datetime import datetime, timezone

import aiohttp
import discord
from discord.ext import commands, tasks

from bot.services.nanogpt import NanoGPTService

log = logging.getLogger("milo.balance_check")


BOT_LOG_CHANNEL_ID = 1465790159642431632


class BalanceCheck(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        settings = bot.settings  # type: ignore[attr-defined]
        self.channel_id = BOT_LOG_CHANNEL_ID
        self.nanogpt = NanoGPTService(settings.nanogpt_api_key)
        self.check_balance.start()

    def cog_unload(self) -> None:
        self.check_balance.cancel()

    @tasks.loop(hours=12)
    async def check_balance(self) -> None:
        channel = self.bot.get_channel(self.channel_id)
        if channel is None:
            log.warning("Balance check: log channel %s not found", self.channel_id)
            return

        try:
            async with aiohttp.ClientSession() as session:
                data = await self.nanogpt.check_balance(session)

            usd = float(data.get("usd_balance", 0))
            embed = discord.Embed(
                title="NanoGPT Balance",
                color=discord.Color.green() if usd >= 5 else discord.Color.red(),
                timestamp=datetime.now(timezone.utc),
            )
            embed.add_field(name="USD Balance", value=f"${usd:.2f}", inline=True)
            if "nano_balance" in data:
                embed.add_field(
                    name="Nano Balance",
                    value=f"{float(data['nano_balance']):.4f}",
                    inline=True,
                )
            if usd < 5:
                embed.set_footer(text="Low balance! Consider topping up.")
            else:
                embed.set_footer(text="Balance check")

            await channel.send(embed=embed)
            log.info("NanoGPT balance: $%.2f", usd)
        except Exception:
            log.exception("Failed to check NanoGPT balance")

    @check_balance.before_loop
    async def before_check_balance(self) -> None:
        await self.bot.wait_until_ready()

    @commands.command(name="balance")
    async def balance_cmd(self, ctx: commands.Context) -> None:
        """Check NanoGPT account balance. Only works in the bot-log channel."""
        if ctx.channel.id != self.channel_id:
            await ctx.send("This command can only be used in the bot-log channel.")
            return
        async with ctx.typing():
            try:
                async with aiohttp.ClientSession() as session:
                    data = await self.nanogpt.check_balance(session)

                usd = float(data.get("usd_balance", 0))
                embed = discord.Embed(
                    title="NanoGPT Balance",
                    color=discord.Color.green() if usd >= 5 else discord.Color.red(),
                    timestamp=datetime.now(timezone.utc),
                )
                embed.add_field(name="USD Balance", value=f"${usd:.2f}", inline=True)
                if "nano_balance" in data:
                    embed.add_field(
                        name="Nano Balance",
                        value=f"{float(data['nano_balance']):.4f}",
                        inline=True,
                    )
                if usd < 5:
                    embed.set_footer(text="Low balance! Consider topping up.")
                else:
                    embed.set_footer(text="Balance check")

                await ctx.send(embed=embed)
            except Exception:
                log.exception("Failed to check NanoGPT balance")
                await ctx.send("Failed to check NanoGPT balance.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BalanceCheck(bot))

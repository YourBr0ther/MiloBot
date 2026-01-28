from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import discord
from discord.ext import commands

log = logging.getLogger(__name__)

DATA_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "shopping_list.json"


def _load_list() -> list[str]:
    if DATA_PATH.exists():
        try:
            return json.loads(DATA_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            log.exception("Failed to read shopping list file")
    return []


def _save_list(items: list[str]) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(items))


def _build_embed(items: list[str]) -> discord.Embed:
    if items:
        numbered = "\n".join(f"{i}. {item}" for i, item in enumerate(items, 1))
    else:
        numbered = "The list is empty."
    return discord.Embed(
        title="Shopping List",
        description=numbered,
        color=discord.Color.green(),
    )


class ShoppingList(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        settings = bot.settings  # type: ignore[attr-defined]
        self.channel_id = settings.shopping_list_channel_id
        self.items: list[str] = _load_list()
        self._lock = asyncio.Lock()

    def _restricted(self, ctx: commands.Context) -> bool:
        return ctx.channel.id != self.channel_id

    @commands.command(name="add")
    async def add_item(self, ctx: commands.Context, *, item: str) -> None:
        """Add an item to the shopping list."""
        if self._restricted(ctx):
            return
        async with self._lock:
            self.items.append(item)
            _save_list(self.items)
        await ctx.send(embed=_build_embed(self.items))

    @commands.command(name="remove")
    async def remove_item(self, ctx: commands.Context, *, item: str) -> None:
        """Remove an item from the shopping list."""
        if self._restricted(ctx):
            return
        async with self._lock:
            lowered = item.lower()
            original_len = len(self.items)
            self.items = [i for i in self.items if i.lower() != lowered]
            if len(self.items) == original_len:
                await ctx.send(f"**{item}** is not on the list.")
                return
            _save_list(self.items)
        await ctx.send(embed=_build_embed(self.items))

    @commands.command(name="list")
    async def show_list(self, ctx: commands.Context) -> None:
        """Show the current shopping list."""
        if self._restricted(ctx):
            return
        await ctx.send(embed=_build_embed(self.items))

    @commands.command(name="clear")
    async def clear_list(self, ctx: commands.Context) -> None:
        """Clear the entire shopping list."""
        if self._restricted(ctx):
            return
        async with self._lock:
            self.items.clear()
            _save_list(self.items)
        await ctx.send(embed=_build_embed(self.items))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ShoppingList(bot))

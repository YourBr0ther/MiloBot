from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import aiohttp
import discord
from discord.ext import commands

log = logging.getLogger(__name__)

DATA_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "shopping_list.json"
NANOGPT_URL = "https://nano-gpt.com/api/v1/chat/completions"

SHOPPING_SYSTEM_PROMPT = """\
You are a shopping list assistant. Parse the user's message and determine what action to take.

Current shopping list:
{current_list}

Respond with ONLY valid JSON in one of these formats:

For adding items:
{{"action": "add", "items": ["item1", "item2", ...], "confirmation": "short confirmation message"}}

For removing items:
{{"action": "remove", "items": ["item1", "item2", ...], "confirmation": "short confirmation message"}}

For showing the list (if they just want to see it):
{{"action": "show", "confirmation": "Here's your list"}}

For clearing the list:
{{"action": "clear", "confirmation": "List cleared"}}

For unrelated messages:
{{"action": "none", "confirmation": ""}}

Rules:
- Match removal requests intelligently. "remove the fruits" should remove fruit items. "remove fish sticks" matches "fishsticks".
- When removing, match partial names and categories (e.g., "green peppers" matches "peppers", "fruits" matches "bananas", "apples", etc.)
- For adds, extract individual items from natural language ("bananas and peppers and fishsticks" = ["bananas", "peppers", "fishsticks"])
- Keep item names simple and lowercase
- Confirmation should be brief (e.g., "Added 3 items" or "Removed bananas and apples")
- Return ONLY JSON, no other text"""


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


def _format_list(items: list[str]) -> str:
    if items:
        return "\n".join(f"• {item}" for item in items)
    return "The list is empty."


class ShoppingList(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        settings = bot.settings  # type: ignore[attr-defined]
        self.channel_id = settings.shopping_list_channel_id
        self.nanogpt_api_key = settings.nanogpt_api_key
        self.items: list[str] = _load_list()
        self._lock = asyncio.Lock()

    def _restricted(self, ctx: commands.Context) -> bool:
        return ctx.channel.id != self.channel_id

    async def _parse_with_llm(self, message: str) -> dict | None:
        """Use LLM to parse natural language shopping commands."""
        current_list = ", ".join(self.items) if self.items else "(empty)"
        system_prompt = SHOPPING_SYSTEM_PROMPT.format(current_list=current_list)

        headers = {
            "Authorization": f"Bearer {self.nanogpt_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "chatgpt-4o-latest",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message},
            ],
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    NANOGPT_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    content = data["choices"][0]["message"]["content"].strip()
                    # Handle markdown code blocks
                    if content.startswith("```"):
                        content = content.split("\n", 1)[-1].rsplit("```", 1)[0]
                    return json.loads(content)
        except (json.JSONDecodeError, aiohttp.ClientError, KeyError) as e:
            log.exception("Failed to parse LLM response: %s", e)
            return None

    async def _handle_action(self, action: dict) -> str | None:
        """Process parsed action and return response text."""
        action_type = action.get("action")
        confirmation = action.get("confirmation", "")
        items_to_process = action.get("items", [])

        if action_type == "none":
            return None

        async with self._lock:
            if action_type == "add":
                for item in items_to_process:
                    if item and item.lower() not in [i.lower() for i in self.items]:
                        self.items.append(item)
                _save_list(self.items)

            elif action_type == "remove":
                items_lower = [i.lower() for i in items_to_process]
                self.items = [i for i in self.items if i.lower() not in items_lower]
                _save_list(self.items)

            elif action_type == "clear":
                self.items.clear()
                _save_list(self.items)

            elif action_type == "show":
                pass  # Just show the list

            else:
                return None

        return f"{confirmation}\n\n{_format_list(self.items)}"

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if message.channel.id != self.channel_id:
            return
        if message.content.startswith("!"):
            return

        text = message.content.strip()
        if not text:
            return

        async with message.channel.typing():
            parsed = await self._parse_with_llm(text)
            if parsed:
                response = await self._handle_action(parsed)
                if response:
                    await message.reply(response)

    @commands.command(name="add")
    async def add_item(self, ctx: commands.Context, *, item: str) -> None:
        """Add an item to the shopping list."""
        if self._restricted(ctx):
            return
        async with self._lock:
            self.items.append(item)
            _save_list(self.items)
        await ctx.send(f"Added {item}\n\n{_format_list(self.items)}")

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
        await ctx.send(f"Removed {item}\n\n{_format_list(self.items)}")

    @commands.command(name="list")
    async def show_list(self, ctx: commands.Context) -> None:
        """Show the current shopping list."""
        if self._restricted(ctx):
            return
        await ctx.send(_format_list(self.items))

    @commands.command(name="clear")
    async def clear_list(self, ctx: commands.Context) -> None:
        """Clear the entire shopping list."""
        if self._restricted(ctx):
            return
        async with self._lock:
            self.items.clear()
            _save_list(self.items)
        await ctx.send(f"List cleared\n\n{_format_list(self.items)}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ShoppingList(bot))

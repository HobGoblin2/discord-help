"""
Vinted Dashboard Bot
====================
A persistent Discord bot that handles:
  - /clear [amount] — deletes messages in the current channel
  - /searches       — shows all active searches
  - /pause <label>  — pauses a search
  - /resume <label> — resumes a search

Environment variables:
    DISCORD_BOT_TOKEN   — your Discord bot token
    GITHUB_TOKEN        — GitHub personal access token (repo scope)
    GITHUB_USERNAME     — e.g. HobGoblin-0930
    GITHUB_REPO         — e.g. vinted-bot
"""

import os
import json
import base64
import discord
from discord import app_commands
from discord.ext import commands
import aiohttp

# ──────────────────────────────────────────────
#  CONFIG
# ──────────────────────────────────────────────
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
GITHUB_TOKEN      = os.environ.get("GITHUB_TOKEN", "")
GITHUB_USERNAME   = os.environ.get("GITHUB_USERNAME", "HobGoblin-0930")
GITHUB_REPO       = os.environ.get("GITHUB_REPO", "vinted-bot")
SEARCHES_FILE     = "vinted_searches.json"

GITHUB_API = f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/contents/{SEARCHES_FILE}"
GITHUB_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}

CONDITION_NAMES = {
    1: "New w/o tags",
    2: "Very good",
    3: "Good",
    4: "Satisfactory",
    5: "Not specified",
    6: "New with tags",
}

# ──────────────────────────────────────────────
#  GITHUB HELPERS
# ──────────────────────────────────────────────

async def load_searches():
    async with aiohttp.ClientSession() as session:
        async with session.get(GITHUB_API, headers=GITHUB_HEADERS) as r:
            if r.status == 404:
                return [], ""
            data = await r.json()
            content = base64.b64decode(data["content"].replace("\n", "")).decode("utf-8")
            return json.loads(content), data["sha"]


async def save_searches(searches: list, sha: str):
    content = base64.b64encode(json.dumps(searches, indent=2).encode()).decode()
    body = {"message": "Update searches via Discord", "content": content}
    if sha:
        body["sha"] = sha
    async with aiohttp.ClientSession() as session:
        async with session.put(GITHUB_API, headers=GITHUB_HEADERS, json=body) as r:
            data = await r.json()
            if r.status not in (200, 201):
                raise Exception(f"GitHub save failed: {data.get('message', r.status)}")
            return data["content"]["sha"]


# ──────────────────────────────────────────────
#  BOT SETUP
# ──────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree


# ──────────────────────────────────────────────
#  SLASH COMMANDS
# ──────────────────────────────────────────────

@tree.command(name="clear", description="Delete messages from this channel")
@app_commands.describe(amount="Number of messages to delete (1–100, default 10)")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear(interaction: discord.Interaction, amount: int = 10):
    amount = max(1, min(100, amount))
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(
        f"🗑️ Deleted **{len(deleted)}** message{'s' if len(deleted) != 1 else ''}.",
        ephemeral=True
    )


@clear.error
async def clear_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "❌ You need the **Manage Messages** permission to use this command.",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(f"❌ Error: {error}", ephemeral=True)


@tree.command(name="searches", description="Show all active Vinted searches")
async def searches(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    searches_list, _ = await load_searches()

    if not searches_list:
        await interaction.followup.send("No searches configured.", ephemeral=True)
        return

    embed = discord.Embed(title="🛍 Active Vinted Searches", color=0x09B1BA)
    for s in searches_list:
        enabled   = s.get("enabled", True)
        price_str = f"£{s['max_price']}" if s.get("max_price") else "Any"
        keywords  = s.get("keywords") or [s.get("search_text", "?")]
        excludes  = s.get("exclude_words", [])
        conds     = ", ".join(CONDITION_NAMES.get(c, str(c)) for c in s.get("status_ids", []))
        channel   = f"<#{s['channel_id']}>" if s.get("channel_id") else "Default"

        val = (
            f"**Keywords:** {', '.join(keywords)}\n"
            f"**Max Price:** {price_str}\n"
            f"**Conditions:** {conds or 'Any'}\n"
            f"**Channel:** {channel}\n"
            f"**Status:** {'🟢 Enabled' if enabled else '⭕ Disabled'}"
        )
        if excludes:
            val += f"\n**Exclude:** {', '.join(excludes)}"

        embed.add_field(name=f"{'🟢' if enabled else '⭕'} {s['label']}", value=val, inline=False)

    await interaction.followup.send(embed=embed, ephemeral=True)


@tree.command(name="pause", description="Pause a Vinted search")
@app_commands.describe(label="Label of the search to pause")
async def pause(interaction: discord.Interaction, label: str):
    await interaction.response.defer(ephemeral=True)
    searches_list, sha = await load_searches()
    match = next((s for s in searches_list if s["label"].lower() == label.lower()), None)
    if not match:
        await interaction.followup.send(f"❌ No search found with label **{label}**.", ephemeral=True)
        return
    match["enabled"] = False
    await save_searches(searches_list, sha)
    await interaction.followup.send(f"⏸ **{match['label']}** has been paused.", ephemeral=True)


@tree.command(name="resume", description="Resume a paused Vinted search")
@app_commands.describe(label="Label of the search to resume")
async def resume(interaction: discord.Interaction, label: str):
    await interaction.response.defer(ephemeral=True)
    searches_list, sha = await load_searches()
    match = next((s for s in searches_list if s["label"].lower() == label.lower()), None)
    if not match:
        await interaction.followup.send(f"❌ No search found with label **{label}**.", ephemeral=True)
        return
    match["enabled"] = True
    await save_searches(searches_list, sha)
    await interaction.followup.send(f"▶️ **{match['label']}** has been resumed.", ephemeral=True)


# ──────────────────────────────────────────────
#  BOT EVENTS
# ──────────────────────────────────────────────

@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ Vinted Dashboard Bot online as {bot.user}")
    print(f"   Slash commands synced: /clear, /searches, /pause, /resume")


# ──────────────────────────────────────────────
#  RUN
# ──────────────────────────────────────────────

if __name__ == "__main__":
    if not DISCORD_BOT_TOKEN:
        print("ERROR: DISCORD_BOT_TOKEN is not set!")
    else:
        bot.run(DISCORD_BOT_TOKEN)

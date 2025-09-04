import os
import discord
from discord.ext import commands, tasks
import aiohttp

# ===== Config =====
TOKEN = os.getenv("bot_token")  # must match Railway variable name
CHANNEL_ID = 1412772946845634642  # your channel ID (leave as int)
API_URL = "https://api.wc3stats.com/gamelist"

# ===== Intents & Bot =====
# We don't need privileged message_content intent to just SEND messages.
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

posted_games = set()

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    fetch_games.start()

@tasks.loop(seconds=5)  # change to 1 if you insist; 5s is gentler on rate limits
async def fetch_games():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(API_URL) as resp:
                if resp.status != 200:
                    print(f"API returned status {resp.status}")
                    return

                data = await resp.json()
                for game in data.get("result", []):
                    name = game.get("name", "") or ""
                    map_name = game.get("map", "") or ""

                    text = f"{name} {map_name}".lower()
                    # include if contains HLW OR hero line; exclude if map contains 8.4a
                    include = ("hlw" in text) or ("hero line" in text)
                    exclude = ("8.4a" in map_name.lower())

                    if include and not exclude:
                        game_id = game.get("id")
                        if game_id not in posted_games:
                            posted_games.add(game_id)
                            msg = f"🎮 New HLW game: **{name}** (Map: {map_name})"
                            channel = await bot.fetch_channel(CHANNEL_ID)
                            await channel.send(msg)
    except Exception as e:
        print(f"Error fetching games: {e}")

bot.run(TOKEN)

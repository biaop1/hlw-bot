import os
import discord
from discord.ext import commands, tasks
import aiohttp

# ===== Config =====
TOKEN = os.getenv("bot_token")  # must match Render environment variable key
CHANNEL_ID = 1412772946845634642  # Replace with your Discord channel ID
API_URL = "https://api.wc3stats.com/gamelist"

# ===== Intents & Bot Setup =====
intents = discord.Intents.default()
intents.message_content = True  # needed to send messages
bot = commands.Bot(command_prefix="!", intents=intents)

posted_games = set()

# ===== Bot Events =====
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    fetch_games.start()

# ===== Task: Fetch HLW Games =====
@tasks.loop(seconds=5)  # check every 5 seconds
async def fetch_games():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(API_URL) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for game in data.get("result", []):
                        name = game.get("name", "")
                        map_name = game.get("map", "")

                        # ----- FILTERS -----
                        text = f"{name} {map_name}".lower()
                        if (
                            ("hlw" in text or "hero line" in text)  # must contain HLW or hero line
                            and "8.4a" not in map_name.lower()      # must NOT contain 8.4a
                        ):
                            game_id = game.get("id")
                            if game_id not in posted_games:
                                posted_games.add(game_id)
                                msg = f"🎮 New HLW game: **{name}** (Map: {map_name})"
                                channel = await bot.fetch_channel(CHANNEL_ID)
                                await channel.send(msg)
                else:
                    print(f"API returned status {resp.status}")
    except Exception as e:
        print(f"Error fetching games: {e}")

bot.run(TOKEN)


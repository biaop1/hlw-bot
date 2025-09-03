import discord
from discord.ext import commands, tasks
import aiohttp

TOKEN = "PUT_YOUR_BOT_TOKEN_HERE"
CHANNEL_ID = 123456789012345678  # Replace with your channel ID
API_URL = "https://api.wc3stats.com/gamelist"

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

posted_games = set()

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    fetch_games.start()

@tasks.loop(seconds=1)  # check every second
async def fetch_games():
    async with aiohttp.ClientSession() as session:
        async with session.get(API_URL) as resp:
            if resp.status == 200:
                data = await resp.json()
                for game in data.get("result", []):  # API returns "result"
                    name = game.get("name", "")
                    map_name = game.get("map", "")
                    if "HLW" in name.upper() or "HLW" in map_name.upper():
                        game_id = game.get("id")
                        if game_id not in posted_games:
                            posted_games.add(game_id)
                            msg = f"🎮 New HLW game: **{name}** (Map: {map_name})"
                            channel = bot.get_channel(CHANNEL_ID)
                            await channel.send(msg)

bot.run(TOKEN)

import discord
from discord.ext import commands, tasks
import aiohttp
import os

TOKEN = os.getenv("bot_token")
CHANNEL_ID = 1412772946845634642
API_URL = "https://api.wc3stats.com/gamelist"

# --- BOT INTENTS ---
intents = discord.Intents.default()
intents.members = True  # <<< important for role assignment

# --- BOT INSTANCE ---
bot = commands.Bot(command_prefix="!", intents=intents)

posted_games = set()
@bot.event
async def on_member_join(member):
    # Replace with the exact role name you want to assign
    role_name = "Member"

    # Find the role in the server
    role = discord.utils.get(member.guild.roles, name=role_name)

    if role:
        await member.add_roles(role)
        print(f"Assigned role '{role_name}' to {member.name}")
    else:
        print(f"Role '{role_name}' not found in {member.guild.name}")

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    fetch_games.start()

                for game in data.get("result", []):  # API returns "result"
                    name = game.get("name", "")
                    map_name = game.get("map", "")
                    print(f"Checking game: {name} (map: {map_name})")  # 👈 DEBUG

                    # Apply your criteria
                    if (
                        ("HLW" in name or "HLW" in map_name or
                         "hero line" in name.lower() or "hero line" in map_name.lower())
                        and "8.4a" not in map_name
                    ):
                        game_id = game.get("id")
                        if game_id not in posted_games:
                            posted_games.add(game_id)
                            msg = f"🎮 New HLW game: **{name}** (Map: {map_name})"
                            print(f"Posting: {msg}")  # 👈 DEBUG
                            channel = bot.get_channel(CHANNEL_ID)
                            if channel:
                                await channel.send(msg)
                            else:
                                print("❌ Could not find channel!")

bot.run(TOKEN)







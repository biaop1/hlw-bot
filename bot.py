import discord
from discord.ext import commands, tasks
import aiohttp
import os

TOKEN = os.getenv("bot_token")
CHANNEL_ID = 1412772946845634642
API_URL = "https://api.wc3stats.com/gamelist"

# --- BOT INTENTS ---
intents = discord.Intents.default()
intents.members = True  # needed for role assignment

# --- BOT INSTANCE ---
bot = commands.Bot(command_prefix="!", intents=intents)

posted_games = set()


# --- ROLE ASSIGNMENT ---
@bot.event
async def on_member_join(member):
    role_name = "Member"  # <<< change if your role has another name
    role = discord.utils.get(member.guild.roles, name=role_name)

    if role:
        await member.add_roles(role)
        print(f"Assigned role '{role_name}' to {member.name}")
    else:
        print(f"Role '{role_name}' not found in {member.guild.name}")


# --- READY EVENT ---
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    # Update avatar once
    try:
        with open("map_icon.png", "rb") as f:
            await bot.user.edit(avatar=f.read())
        print("✅ Avatar updated")
    except Exception as e:
        (f"❌ Failed to update avatar: {e}")

    fetch_games.start()


# --- GAME FETCH LOOP ---
@tasks.loop(seconds=10)
async def fetch_games():
    async with aiohttp.ClientSession() as session:
        for page in range(1, 3):  # only pages 1 and 2, safe for <100 games
            async with session.get(f"{API_URL}?page={page}") as resp:
                if resp.status != 200:
                    print(f"❌ Failed to fetch page {page}: {resp.status}")
                    continue

                data = await resp.json()
                games = data.get("body", [])

                if not games:
                    continue

                for game in games:
                    name = game.get("name", "")
                    map_name = game.get("map", "")

                    # your filter criteria
                    if (
                        ("HLW" in name or "HLW" in map_name
                         or "hero line" in name.lower()
                         or "hero line" in map_name.lower())
                        and "W8." not in map_name
                    ):
                        game_id = game.get("id")
                        if game_id not in posted_games:
                            posted_games.add(game_id)
                            msg = f"🎮 New HLW game: **{name}** (Map: {map_name})"
                            channel = bot.get_channel(CHANNEL_ID)
                            if channel:
                                await channel.send(msg)
                            else:
                                print("❌ Could not find channel!")



# --- RUN BOT ---
bot.run(TOKEN)







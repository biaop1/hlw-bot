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
    fetch_games.start()   # ✅ only start the loop here, nothing else


# --- GAME FETCH LOOP ---
@tasks.loop(seconds=10)  # check every 10 seconds
async def fetch_games():
    async with aiohttp.ClientSession() as session:
        async with session.get(API_URL) as resp:
            if resp.status == 200:
                data = await resp.json()
                games = data.get("result", [])

                # Only print if not 0 games
                if len(games) > 0:
                    print(f"Fetched {len(games)} games")

                ### HERE is where the loop belongs
                for game in games:
                    name = game.get("name", "")
                    map_name = game.get("map", "")
                        print(f"{name}, {map_name}")
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
                            print(f"Posting: {msg}")
                            channel = bot.get_channel(CHANNEL_ID)
                            if channel:
                                await channel.send(msg)
                            else:
                                print("❌ Could not find channel!")


# --- RUN BOT ---
bot.run(TOKEN)



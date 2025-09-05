import discord
from discord.ext import commands, tasks
import aiohttp
import os
import time

start_time = time.time()  # record when the bot started
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
        async with session.get(API_URL) as resp:
            if resp.status == 200:
                data = await resp.json()
                games = data.get("body", [])  # ✅ API returns data in "body"

                for game in games:
                    name = game.get("name", "")
                    map_name = game.get("map", "")
                    realm = game.get("realm", "Unknown")
                    host = game.get("host", "Unknown")
                    players = game.get("slotsTaken", 0)
                    total = game.get("slotsTotal", 0)

                    # ✅ Criteria
                    if (
                        ("HLW" in name or "HLW" in map_name or
                         "hero line" in name.lower() or "hero line" in map_name.lower())
                        and "8.4a" not in map_name
                    ):
                        game_id = game.get("id")
                        if game_id not in posted_games:
                            posted_games.add(game_id)

                            # format uptime
                            uptime = int(time.time() - start_time)
                            minutes, seconds = divmod(uptime, 60)

                            # 3-line message
                            msg = (
                                f"Uptime: {minutes}m {seconds}s. Realm: {realm}\n"
                                f"Gamename: {name} ({map_name})\n"
                                f"Host: {host} Players: {players}/{total}"
                            )

                            channel = bot.get_channel(CHANNEL_ID)
                            if channel:
                                await channel.send(msg)
                            else:
                                print("❌ Could not find channel!")

# --- RUN BOT ---
bot.run(TOKEN)








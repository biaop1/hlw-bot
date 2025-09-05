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
        print(f"❌ Failed to update avatar: {e}")

    fetch_games.start()


# --- GAME FETCH LOOP ---
@tasks.loop(seconds=10)  # check every 10s
async def fetch_games():
    async with aiohttp.ClientSession() as session:
        async with session.get(API_URL) as resp:
            if resp.status == 200:
                data = await resp.json()
                games = data.get("body", [])

                if len(games) == 0:
                    return

                for game in games:
                    game_id = game.get("id")
                    if game_id in posted_games:
                        continue

                    name = game.get("name", "")
                    map_name = game.get("map", "")
                    host = game.get("host", "")
                    server = game.get("server", "")
                    slotsTaken = game.get("slotsTaken", 0)
                    slotsTotal = game.get("slotsTotal", 0)

                    # Criteria
                    if (
                        ("hlw" in name.lower() 
                        or "heroline" in name.lower()
                        or "hero line" in name.lower()
                        or "hero line" in map_name.lower()
                        or "heroline" in map_name.lower())
                        and "w8." not in map_name.lower()
                    ):

                        posted_games.add(game_id)

                        # Uptime
                        uptime_sec = game.get("uptime", 0)
                        minutes, seconds = divmod(int(uptime_sec), 60)

                        # Build embed
                        embed = discord.Embed(
                            title=f"{name}",
                            color=discord.Color.green()
                        )
                        embed.add_field(
                            name="Map",
                            value=f"({map_name})",
                            inline=False
                        )
                        embed.add_field(
                            name="Host",
                            value=f"{host}",
                            inline=True
                        )
                        embed.add_field(
                            name="Realm",
                            value=f"{server}",
                            inline=True
                        )
                        embed.add_field(
                            name="Players",
                            value=f"{slotsTaken}/{slotsTotal}",
                            inline=True
                        )
                        embed.set_footer(text=f"Uptime: {minutes}m {seconds}s")

                        # Send
                        channel = bot.get_channel(CHANNEL_ID)
                        if channel:
                            await channel.send(embed=embed)
                        else:
                            print("❌ Could not find channel!")


# --- RUN BOT ---
bot.run(TOKEN)












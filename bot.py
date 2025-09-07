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

posted_games = {}  # game_id -> {"message": msg, "start_time": timestamp}

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

                # Track current IDs from API
                active_ids = set()

                if len(games) == 0:
                    print("No games found in API response")
                    return

                for game in games:
                    game_id = game.get("id")
                    active_ids.add(game_id)

                    name = game.get("name", "")
                    map_name = game.get("map", "")
                    host = game.get("host", "")
                    server = game.get("server", "")
                    slotsTaken = game.get("slotsTaken", 0)
                    slotsTotal = game.get("slotsTotal", 0)

                    # Log API uptime for debugging
                    uptime_sec_api = game.get("uptime", 0)
                    minutes_api, seconds_api = divmod(int(uptime_sec_api), 60)
                    print(f"Game ID: {game_id}, Name: {name}, API Uptime: {minutes_api}m {seconds_api}s ({uptime_sec_api} seconds)")

                    # Criteria
                    if (
                        ("hlw" in name.lower()
                         or "heroline" in name.lower()
                         or "hero line" in name.lower()
                         or "hero line" in map_name.lower()
                         or "heroline" in map_name.lower())
                        and "w8." not in map_name.lower()
                    ):
                        # Calculate uptime locally
                        current_time = time.time()
                        if game_id not in posted_games:
                            posted_games[game_id] = {"message": None, "start_time": current_time}
                        uptime_sec_local = int(current_time - posted_games[game_id]["start_time"])
                        minutes, seconds = divmod(uptime_sec_local, 60)
                        uptime_text = f"{minutes}m {seconds}s"
                        print(f"Game ID: {game_id}, Name: {name}, Local Uptime: {uptime_text} ({uptime_sec_local} seconds)")

                        # Build embed
                        embed = discord.Embed(
                            title=f"{name}",
                            color=discord.Color.green()
                        )
                        embed.add_field(name="Map", value=f"{map_name}", inline=False)
                        embed.add_field(name="Host", value=f"{host}", inline=True)
                        embed.add_field(name="Realm", value=f"{server}", inline=True)
                        embed.add_field(name="Players", value=f"{slotsTaken}/{slotsTotal}", inline=True)
                        embed.set_footer(text=f"Uptime: {uptime_text}")

                        channel = bot.get_channel(CHANNEL_ID)
                        if not channel:
                            print("❌ Could not find channel!")
                            return

                        if posted_games[game_id]["message"] is None:
                            # Send new message
                            msg = await channel.send(embed=embed)
                            posted_games[game_id]["message"] = msg
                        else:
                            # Update existing message
                            msg = posted_games[game_id]["message"]
                            try:
                                await msg.edit(embed=embed)
                            except Exception as e:
                                print(f"❌ Failed to edit message for {game_id}: {e}")

                            # Handle games that disappeared (Closed)
                            for game_id in list(posted_games.keys()):
                                if game_id not in active_ids and not posted_games[game_id].get("closed", False):
                                    msg = posted_games[game_id]["message"]
                                    if not msg or not msg.embeds:
                                        posted_games.pop(game_id)
                                        continue
                                    try:
                                        current_embed = msg.embeds[0]

                                        # Create a new embed with the same color and title
                                        closed_embed = discord.Embed(
                                            title=current_embed.title,
                                            color=current_embed.color  # keep original color
                                        )

                                        # Copy all fields
                                        for field in current_embed.fields:
                                            closed_embed.add_field(
                                                name=field.name,
                                                value=field.value,
                                                inline=field.inline
                                            )

                                        # Freeze uptime
                                        current_uptime = current_embed.footer.text or "0m 0s"
                                        # Remove any previous *Closed* just in case
                                        current_uptime = current_uptime.replace(" *Closed*", "")
                                        closed_embed.set_footer(text=f"{current_uptime} *Closed*")

                                        # Edit the message
                                        await msg.edit(embed=closed_embed)

                                        # Mark as closed so we don't try again
                                        posted_games[game_id]["closed"] = True

                                        print(f"Marked game {game_id} as Closed (uptime frozen)")

                                    except Exception as e:
                                        print(f"❌ Failed to mark game closed {game_id}: {e}")


# --- RUN BOT ---
bot.run(TOKEN)

import discord
from discord.ext import commands, tasks
import aiohttp
import os
import time
import datetime

start_time = time.time()  # record when the bot started
TOKEN = os.getenv("bot_token")
CHANNEL_ID = 1412772946845634642
API_URL = "https://api.wc3stats.com/gamelist"

# --- BOT INTENTS ---
intents = discord.Intents.default()
intents.members = True  # needed for role assignment

# --- BOT INSTANCE ---
bot = commands.Bot(command_prefix="!", intents=intents)

posted_games = {}  # game_id -> {"message": msg, "start_time": timestamp, "closed": bool, "frozen_uptime": str}

# --- ROLE ASSIGNMENT --- (Commented out as in original)
#@bot.event
#async def on_member_join(member):
#    role_name = "Member"
#    role = discord.utils.get(member.guild.roles, name=role_name)
#    if role:
#        await member.add_roles(role)
#        print(f"Assigned role '{role_name}' to {member.name}")
#    else:
#        print(f"Role '{role_name}' not found in {member.guild.name}")

# --- ROLE UPGRADE CONFIG ---
ROLE_X_ID = 1414518023636914278
ROLE_Y_ID = 1413169885663727676
DAYS_THRESHOLD = 7

role_x_assignment = {}

@bot.event
async def on_member_update(before, after):
    before_roles = {r.id for r in before.roles}
    after_roles = {r.id for r in after.roles}
    
    if ROLE_X_ID not in before_roles and ROLE_X_ID in after_roles:
        role_x_assignment[after.id] = datetime.datetime.now(datetime.UTC)

@tasks.loop(hours=12)
async def upgrade_roles():
    GUILD_ID = 1412713066495217797
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return

    role_x = guild.get_role(ROLE_X_ID)
    role_y = guild.get_role(ROLE_Y_ID)
    if not role_x or not role_y:
        print("Roles not found in guild")
        return

    for member in guild.members:
        if member.bot:
            continue
        if role_x.id not in [r.id for r in member.roles]:
            continue

        assigned_at = role_x_assignment.get(member.id) or member.joined_at
        now = datetime.datetime.now(datetime.timezone.utc)
        days_with_role_x = (now - assigned_at).total_seconds() / 86400
        
        if days_with_role_x >= DAYS_THRESHOLD:
            try:
                await member.remove_roles(role_x)
                await member.add_roles(role_y)
                role_x_assignment.pop(member.id, None)
                print(f"Upgraded {member.display_name} from Role X to Role Y")
            except Exception as e:
                print(f"❌ Failed to upgrade {member.display_name}: {e}")

@upgrade_roles.error
async def upgrade_roles_error(exception):
    print(f"❌ Error in upgrade_roles: {exception}")

# --- READY EVENT ---
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    try:
        with open("map_icon.png", "rb") as f:
            await bot.user.edit(avatar=f.read())
        print("✅ Avatar updated")
    except Exception as e:
        print(f"❌ Failed to update avatar: {e}")

# --- GAME FETCH LOOP ---
@tasks.loop(seconds=9)
async def fetch_games():
    try:
        current_time = datetime.datetime.now(datetime.UTC).isoformat()
        print(f"Fetching games at {current_time} UTC")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(API_URL) as resp:
                if resp.status != 200:
                    print(f"❌ API request failed with status {resp.status}")
                    return

                try:
                    data = await resp.json()
                except Exception as e:
                    print(f"❌ Failed to parse API JSON: {e}")
                    return

                games = data.get("body", [])
                print(f"Fetched {len(games)} games from API")
                active_ids = set()

                channel = bot.get_channel(CHANNEL_ID)
                if not channel:
                    print("❌ Could not find channel!")
                    return

                for game in games:
                    try:
                        game_id = game.get("id")
                        active_ids.add(game_id)

                        name = game.get("name", "")
                        map_name = game.get("map", "")
                        host = game.get("host", "")
                        server = game.get("server", "")
                        slotsTaken = game.get("slotsTaken", 0)
                        slotsTotal = game.get("slotsTotal", 0)

                        if (
                            ("hlw" in name.lower()
                             or "heroline" in name.lower()
                             or "hero line" in name.lower()
                             or "hero line" in map_name.lower()
                             or "heroline" in map_name.lower())
                            and "w8." not in map_name.lower()
                        ):
                            print(f"Matched HLW game {game_id}: name='{name}', map='{map_name}'")
                            
                            current_time = time.time()
                            if game_id not in posted_games:
                                posted_games[game_id] = {
                                    "message": None,
                                    "start_time": current_time,
                                    "closed": False,
                                    "frozen_uptime": None,
                                    "last_slots": None
                                }

                            if not posted_games[game_id]["closed"]:
                                uptime_sec = int(current_time - posted_games[game_id]["start_time"])
                                minutes, seconds = divmod(uptime_sec, 60)
                                uptime_text = f"{minutes}m {seconds}s"
                                posted_games[game_id]["frozen_uptime"] = uptime_text
                            else:
                                uptime_text = posted_games[game_id]["frozen_uptime"]

                            # --- PATCH: Ignore bogus 0/1 slot counts before close ---
                            last_seen = posted_games[game_id].get("last_slots")
                            
                            if slotsTaken <= 1:
                                # Treat as bogus unless it's literally the first fetch
                                if last_seen is not None:
                                    slots_text = f"{last_seen}/{slotsTotal}"
                                else:
                                    slots_text = f"{slotsTaken}/{slotsTotal}"
                            else:
                                # Update last known good slots
                                slots_text = f"{slotsTaken}/{slotsTotal}"
                                posted_games[game_id]["last_slots"] = slotsTaken


                            embed = discord.Embed(title=name, color=discord.Color.green())
                            embed.add_field(name="Map", value=map_name, inline=False)
                            embed.add_field(name="Host", value=host, inline=True)
                            embed.add_field(name="Realm", value=server, inline=True)
                            embed.add_field(name="Players", value=slots_text, inline=True)
                            embed.add_field(name="Uptime", value=uptime_text, inline=True)
                            embed.add_field(name="\u200b", value="\u200b", inline=True if not posted_games[game_id]["closed"] else False)

                            try:
                                msg = posted_games[game_id]["message"]
                                if msg is None:
                                    msg = await channel.send(embed=embed)
                                    posted_games[game_id]["message"] = msg
                                else:
                                    await msg.edit(embed=embed)
                            except Exception as e:
                                print(f"❌ Failed to send/edit message for {game_id}: {e}")

                        else:
                            if "hlw" in map_name.lower() or "hero line" in map_name.lower() or "heroline" in map_name.lower():
                                print(f"Filtered out potential HLW game {game_id}: name='{name}', map='{map_name}' (did not match criteria)")

                    except Exception as e:
                        print(f"❌ Error processing game {game_id}: {e}")
                        continue

                for game_id in list(posted_games.keys()):
                    try:
                        if game_id not in active_ids and not posted_games[game_id]["closed"]:
                            msg = posted_games[game_id]["message"]
                            if not msg or not msg.embeds:
                                continue
                            current_embed = msg.embeds[0]

                            current_time = time.time()
                            uptime_sec = int(current_time - posted_games[game_id]["start_time"])
                            minutes, seconds = divmod(uptime_sec, 60)
                            frozen_uptime = f"{minutes}m {seconds}s"
                            posted_games[game_id]["frozen_uptime"] = frozen_uptime

                            closed_embed = discord.Embed(title=current_embed.title, color=current_embed.color)
                            for field in current_embed.fields:
                                closed_embed.add_field(name=field.name, value=field.value, inline=field.inline)

                            for i, field in enumerate(closed_embed.fields):
                                if field.name == "Uptime":
                                    closed_embed.set_field_at(i, name="Uptime", value=f"{frozen_uptime} - *Closed*", inline=True)
                                    break

                            await msg.edit(embed=closed_embed)
                            posted_games[game_id]["closed"] = True
                            print(f"Marked game {game_id} as Closed with frozen uptime {frozen_uptime}")
                    except Exception as e:
                        print(f"❌ Failed to mark game closed {game_id}: {e}")

    except Exception as e:
        print(f"❌ Fetch games loop broad error: {e}")

@fetch_games.error
async def fetch_games_error(exception):
    print(f"❌ Error in fetch_games: {exception}")

# --- RUN BOT ---
fetch_games.start()
upgrade_roles.start()
bot.run(TOKEN)



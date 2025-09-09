import discord
from discord.ext import commands, tasks
import aiohttp
import os
import time
import datetime
import re

start_time = time.time()  # record when the bot started
TOKEN = os.getenv("bot_token")
CHANNEL_ID = 1412772946845634642
API_URL = "https://api.wc3stats.com/gamelist"

# --- BOT INTENTS ---
intents = discord.Intents.default()
intents.members = True  # needed for role assignment

# --- BOT INSTANCE ---
bot = commands.Bot(command_prefix="!", intents=intents)

posted_games = {}  
# game_id -> {
#   "message": msg,
#   "start_time": timestamp,
#   "closed": bool,
#   "frozen_uptime": str,
#   "last_slots": str,
#   "missing_since": float | None
# }

# --- HLW detection regex (fix #2) ---
HLW_REGEX = re.compile(r"(hlw|hero\s*line)", re.I)

# --- Persistent aiohttp session (fix #1) ---
session: aiohttp.ClientSession | None = None

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

# --- READY EVENT ---
@bot.event
async def on_ready():
    global session
    print(f"Logged in as {bot.user}")

    # persistent session
    session = aiohttp.ClientSession()

    try:
        with open("map_icon.png", "rb") as f:
            await bot.user.edit(avatar=f.read())
        print("✅ Avatar updated")
    except Exception as e:
        print(f"❌ Failed to update avatar: {e}")

    fetch_games.start()
    upgrade_roles.start()

# --- GAME FETCH LOOP ---
@tasks.loop(seconds=9)
async def fetch_games():
    global session
    try:
        async with session.get(API_URL) as resp:
            if resp.status != 200:
                print(f"❌ API request failed with status {resp.status}")
                return
            data = await resp.json()
    except Exception as e:
        print(f"❌ API fetch error: {e}")
        return

    games = data.get("body", [])
    active_ids = set()
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print("❌ Could not find channel!")
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

        # --- Fix #2: regex-based HLW detection
        if HLW_REGEX.search(name) or HLW_REGEX.search(map_name):
            if "w8." in map_name.lower():
                continue

            current_time = time.time()
            if game_id not in posted_games:
                posted_games[game_id] = {
                    "message": None,
                    "start_time": current_time,
                    "closed": False,
                    "frozen_uptime": None,
                    "last_slots": None,
                    "missing_since": None
                }

            api_uptime = game.get("uptime", 0)  # seconds from API
            minutes, seconds = divmod(int(api_uptime), 60)
            uptime_text = f"{minutes}m {seconds}s"
            

            # --- Uptime from API instead of manual timer ---
            uptime_sec = int(game.get("uptime", 0))
            minutes, seconds = divmod(uptime_sec, 60)
            uptime_text = f"{minutes}m {seconds}s"
            
            # Store frozen uptime only when needed
            if not posted_games[game_id]["closed"]:
                posted_games[game_id]["frozen_uptime"] = uptime_text
            else:
                uptime_text = posted_games[game_id]["frozen_uptime"]

            # --- PATCH: ignore bogus 0/1 slot counts
            # --- Improved slot count handling ---
            last_seen = posted_games[game_id]["last_slots"]
            
            if slotsTaken > 1:
                # Normal case: update with fresh value
                slots_text = f"{slotsTaken}/{slotsTotal}"
                posted_games[game_id]["last_slots"] = slots_text
            
            elif slotsTaken <= 1:
                # Possible bogus value from API
                if last_seen:
                    # Count how many times in a row we’ve seen "1"
                    counter = posted_games[game_id].get("low_count_streak", 0) + 1
                    posted_games[game_id]["low_count_streak"] = counter
            
                    if counter >= 2:
                        # Accept it as real if we’ve seen 1/12 twice in a row
                        slots_text = f"{slotsTaken}/{slotsTotal}"
                        posted_games[game_id]["last_slots"] = slots_text
                    else:
                        # Keep last good value
                        slots_text = last_seen
                else:
                    # First time seeing it, no history → just use it
                    slots_text = f"{slotsTaken}/{slotsTotal}"
                    posted_games[game_id]["last_slots"] = slots_text
            else:
                slots_text = f"{slotsTaken}/{slotsTotal}"
                posted_games[game_id]["last_slots"] = slots_text



            embed = discord.Embed(title=name, color=discord.Color.green())
            embed.add_field(name="Map", value=map_name, inline=False)
            embed.add_field(name="Host", value=host, inline=True)
            embed.add_field(name="Realm", value=server, inline=True)
            embed.add_field(name="Players", value=slots_text, inline=True)
            embed.add_field(name="Uptime", value=uptime_text, inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=True if not posted_games[game_id]["closed"] else False)

            msg = posted_games[game_id]["message"]
            if msg is None:
                msg = await channel.send(embed=embed)
                posted_games[game_id]["message"] = msg
            else:
                try:
                    await msg.edit(embed=embed)
                except Exception as e:
                    print(f"❌ Failed to edit message for {game_id}: {e}")

            # reset missing_since if game is back
            posted_games[game_id]["missing_since"] = None

    # --- Fix #3: Grace period before closing ---
    for game_id, info in list(posted_games.items()):
        if game_id not in active_ids and not info["closed"]:
            if info["missing_since"] is None:
                info["missing_since"] = time.time()
                continue
            elif time.time() - info["missing_since"] < 20:  # wait 20s before closing
                continue

            msg = info["message"]
            if not msg or not msg.embeds:
                continue
            try:
                current_embed = msg.embeds[0]
                frozen_uptime = info["frozen_uptime"]

                closed_embed = discord.Embed(title=current_embed.title, color=current_embed.color)
                for field in current_embed.fields:
                    closed_embed.add_field(name=field.name, value=field.value, inline=field.inline)

                for i, field in enumerate(closed_embed.fields):
                    if field.name == "Uptime":
                        closed_embed.set_field_at(i, name="Uptime", value=f"{frozen_uptime} - *Closed*", inline=True)
                        break

                await msg.edit(embed=closed_embed)
                info["closed"] = True
                print(f"Marked game {game_id} as Closed with frozen uptime {frozen_uptime}")
            except Exception as e:
                print(f"❌ Failed to mark game closed {game_id}: {e}")

# --- CLEANUP SESSION ---
@bot.event
async def on_close():
    global session
    if session:
        await session.close()

# --- RUN BOT ---
bot.run(TOKEN)




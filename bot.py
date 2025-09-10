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
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")

    # Start tasks safely
    if not fetch_games.is_running():
        fetch_games.start()
    if not upgrade_roles.is_running():
        upgrade_roles.start()

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
# --- GAME FETCH LOOP (REPLACEMENT) ---
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
        lastUpdated = game.get("lastUpdated", 0)  # timestamp from API (may be 0/missing)
        api_uptime = int(game.get("uptime", 0))   # uptime in seconds from API

        # HLW detection
        if HLW_REGEX.search(name) or HLW_REGEX.search(map_name):
            if "w8." in map_name.lower():
                continue

            current_time = time.time()
            # ensure we have an entry
            if game_id not in posted_games:
                posted_games[game_id] = {
                    "message": None,
                    "start_time": current_time,
                    "closed": False,
                    "frozen_uptime": None,
                    "last_slots_text": None,            # formatted "10/12"
                    "last_valid_slots_taken": None,     # numeric 10
                    "last_valid_slots_total": None,     # numeric 12
                    "last_valid_updated": 0,            # numeric timestamp
                    "missing_since": None,
                    "low_count_streak": 0,              # optional if needed later
                }

            info = posted_games[game_id]

            # --- Uptime: take from API (do not compute from bot start_time) ---
            minutes, seconds = divmod(api_uptime, 60)
            uptime_text = f"{minutes}m {seconds}s"
            # keep frozen_uptime updated while still alive
            if not info["closed"]:
                info["frozen_uptime"] = uptime_text
            else:
                uptime_text = info["frozen_uptime"] or uptime_text

            # --- Slots handling (avoid 0/0, avoid overwriting with bogus 0/1) ---
            # Update last_valid only when API data looks sane:
            # - If slotsTotal is a positive number and
            #   * slotsTaken >= 2 -> definitely a valid update (covers typical games)
            #   * OR last_valid is None and slotsTaken >= 1 -> accept first snapshot (handles 1v1 expressed as 2/12 per your note)
            last_valid = info["last_valid_slots_taken"]
            if slotsTotal and (slotsTaken >= 2 or (last_valid is None and slotsTaken >= 1)):
                # accept this as last valid snapshot
                info["last_valid_slots_taken"] = int(slotsTaken)
                info["last_valid_slots_total"] = int(slotsTotal)
                info["last_slots_text"] = f"{slotsTaken}/{slotsTotal}"
                # prefer API lastUpdated if present, else wall time
                info["last_valid_updated"] = int(lastUpdated) if lastUpdated else int(time.time())
            else:
                # If this fetch is a 0/1 blip, do NOT overwrite last_slots_text.
                # Keep whatever last_slots_text we have. If we have none AND slotsTotal present,
                # fall back to current snapshot (but avoid storing 0/0).
                if not info["last_slots_text"]:
                    if slotsTotal and slotsTaken >= 1:
                        # first meaningful snapshot (rare)
                        info["last_slots_text"] = f"{slotsTaken}/{slotsTotal}"
                        info["last_valid_slots_taken"] = int(slotsTaken)
                        info["last_valid_slots_total"] = int(slotsTotal)
                        info["last_valid_updated"] = int(lastUpdated) if lastUpdated else int(time.time())
                    else:
                        # still no valid data -> leave last_slots_text None for now
                        pass

            # Decide what to display for Players
            if info["last_slots_text"]:
                slots_text = info["last_slots_text"]
            else:
                # No last valid value yet; avoid 0/0 display
                if slotsTotal:
                    slots_text = f"{slotsTaken}/{slotsTotal}"
                else:
                    slots_text = "?/?"

            # Build embed
            embed = discord.Embed(title=name, color=discord.Color.green())
            embed.add_field(name="Map", value=map_name, inline=False)
            embed.add_field(name="Host", value=host, inline=True)
            embed.add_field(name="Realm", value=server, inline=True)
            embed.add_field(name="Players", value=slots_text, inline=True)
            embed.add_field(name="Uptime", value=uptime_text, inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=True if not info["closed"] else False)

            # Send or edit message
            msg = info["message"]
            if msg is None:
                try:
                    msg = await channel.send(embed=embed)
                    info["message"] = msg
                except Exception as e:
                    print(f"❌ Failed to send message for {game_id}: {e}")
            else:
                try:
                    await msg.edit(embed=embed)
                except Exception as e:
                    print(f"❌ Failed to edit message for {game_id}: {e}")

            # Reset missing_since if game came back
            info["missing_since"] = None

    # --- Grace period before closing (unchanged logic, using last_slots_text if present) ---
    for game_id, info in list(posted_games.items()):
        if game_id not in active_ids and not info["closed"]:
            if info["missing_since"] is None:
                info["missing_since"] = time.time()
                continue
            elif time.time() - info["missing_since"] < 30:
                continue

            msg = info["message"]
            if not msg or not msg.embeds:
                continue
            try:
                current_embed = msg.embeds[0]
                frozen_uptime = info.get("frozen_uptime") or (
                    # try to extract from embed footer/fields if not present
                    next((f.value for f in current_embed.fields if f.name.lower() == "uptime"), "0m 0s")
                )

                # Prefer last known good slots; otherwise, read Players from the current embed to avoid 0/0
                slots_text = info.get("last_slots_text")
                if not slots_text:
                    # try to extract Players field from the existing embed
                    for field in current_embed.fields:
                        if field.name.lower() == "players":
                            slots_text = field.value
                            break
                if not slots_text:
                    slots_text = "?/?"  # ultimate fallback

                # Build closed embed: copy fields but replace Players & Uptime
                closed_embed = discord.Embed(title=current_embed.title, color=discord.Color.red())
                for field in current_embed.fields:
                    if field.name.lower() == "players":
                        closed_embed.add_field(name="Players", value=slots_text, inline=field.inline)
                    elif field.name.lower() == "uptime":
                        closed_embed.add_field(name="Uptime", value=f"{frozen_uptime} - *Closed*", inline=field.inline)
                    else:
                        closed_embed.add_field(name=field.name, value=field.value, inline=field.inline)

                await msg.edit(embed=closed_embed)
                info["closed"] = True
                print(f"Marked game {game_id} as Closed with frozen uptime {frozen_uptime} and slots {slots_text} (last_updated={info['last_valid_updated']})")
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





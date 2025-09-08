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

# --- ROLE ASSIGNMENT --- Assign "member" on new member join. Retired module. Replaced by carl-bot
#@bot.event
#async def on_member_join(member):
#    role_name = "Member"
#    role = discord.utils.get(member.guild.roles, name=role_name)
#    if role:
#        await member.add_roles(role)
#        print(f"Assigned role '{role_name}' to {member.name}")
#    else:
#        print(f"Role '{role_name}' not found in {member.guild.name}")

# --- ROLE UPGRADE CONFIG --- Upgrade role Member (Peon) to Member (Grunt)
ROLE_X_ID = 1414518023636914278  # Existing role to track
ROLE_Y_ID = 1413169885663727676  # Role to assign after threshold
DAYS_THRESHOLD = 7              # Days before upgrade

role_x_assignment = {}  # Tracks when Role X was assigned

# Track when Role X is assigned to a member
@bot.event
async def on_member_update(before, after):
    before_roles = {r.id for r in before.roles}
    after_roles = {r.id for r in after.roles}
    
    # Role X newly added
    if ROLE_X_ID not in before_roles and ROLE_X_ID in after_roles:
        role_x_assignment[after.id] = datetime.datetime.utcnow()

# Daily loop to upgrade roles
@tasks.loop(hours=24)
async def upgrade_roles():
    guild = bot.get_guild(YOUR_GUILD_ID)  # Replace with your server ID
    if not guild:
        return
    role_x = discord.Object(id=ROLE_X_ID)
    role_y = discord.Object(id=ROLE_Y_ID)

    for member in guild.members:
        if member.bot:
            continue

        # Only proceed if member has Role X
        if role_x.id not in [r.id for r in member.roles]:
            continue

        # Determine when they got Role X
        assigned_at = role_x_assignment.get(member.id)
        if not assigned_at:
            # fallback if we didn't track it: use join date
            assigned_at = member.joined_at

        days_with_role_x = (datetime.datetime.utcnow() - assigned_at).days

        if days_with_role_x >= DAYS_THRESHOLD:
            try:
                await member.remove_roles(role_x)
                await member.add_roles(role_y)
                role_x_assignment.pop(member.id, None)
                print(f"Upgraded {member.display_name} from Role X to Role Y")
            except Exception as e:
                print(f"❌ Failed to upgrade {member.display_name}: {e}")

# Start the role upgrade loop when the bot is ready
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    fetch_games.start()
    upgrade_roles.start()  # Start role upgrade loop


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

    fetch_games.start()


# --- GAME FETCH LOOP ---
@tasks.loop(seconds=9)
async def fetch_games():
    async with aiohttp.ClientSession() as session:
        async with session.get(API_URL) as resp:
            if resp.status != 200:
                print(f"❌ API request failed with status {resp.status}")
                return

            data = await resp.json()
            games = data.get("body", [])
            active_ids = set()

            channel = bot.get_channel(CHANNEL_ID)
            if not channel:
                print("❌ Could not find channel!")
                return

            # --- Update or send messages for active games ---
            for game in games:
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
                    current_time = time.time()

                    if game_id not in posted_games:
                        posted_games[game_id] = {
                            "message": None,
                            "start_time": current_time,
                            "closed": False,
                            "frozen_uptime": None
                        }

                    # Only calculate uptime if the game is not closed
                    if not posted_games[game_id]["closed"]:
                        uptime_sec = int(current_time - posted_games[game_id]["start_time"])
                        minutes, seconds = divmod(uptime_sec, 60)
                        uptime_text = f"{minutes}m {seconds}s"
                        posted_games[game_id]["frozen_uptime"] = uptime_text
                    else:
                        uptime_text = posted_games[game_id]["frozen_uptime"]

                    # Build embed
                    embed = discord.Embed(title=name, color=discord.Color.green())
                    embed.add_field(name="Map", value=map_name, inline=False)
                    embed.add_field(name="Host", value=host, inline=True)
                    embed.add_field(name="Realm", value=server, inline=True)
                    embed.add_field(name="Players", value=f"{slotsTaken}/{slotsTotal}", inline=True)
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

            # --- Mark disappeared games as closed ---
            for game_id in list(posted_games.keys()):
                if game_id not in active_ids and not posted_games[game_id]["closed"]:
                    msg = posted_games[game_id]["message"]
                    if not msg or not msg.embeds:
                        continue
                    try:
                        current_embed = msg.embeds[0]

                        # Freeze uptime exactly now
                        current_time = time.time()
                        uptime_sec = int(current_time - posted_games[game_id]["start_time"])
                        minutes, seconds = divmod(uptime_sec, 60)
                        frozen_uptime = f"{minutes}m {seconds}s"
                        posted_games[game_id]["frozen_uptime"] = frozen_uptime

                        # Copy embed
                        closed_embed = discord.Embed(title=current_embed.title, color=current_embed.color)
                        for field in current_embed.fields:
                            closed_embed.add_field(name=field.name, value=field.value, inline=field.inline)

                        # Replace Uptime field in place
                        for i, field in enumerate(closed_embed.fields):
                            if field.name == "Uptime":
                                closed_embed.set_field_at(i, name="Uptime", value=f"{frozen_uptime} - *Closed*", inline=True)
                                break

                        await msg.edit(embed=closed_embed)
                        posted_games[game_id]["closed"] = True
                        print(f"Marked game {game_id} as Closed with frozen uptime {frozen_uptime}")

                    except Exception as e:
                        print(f"❌ Failed to mark game closed {game_id}: {e}")
# --- RUN BOT ---
bot.run(TOKEN)




import discord
from discord.ext import commands, tasks
import aiohttp
import os
import time
import datetime

start_time = time.time()  # record when the bot started
TOKEN = os.getenv("bot_token")
CHANNEL_ID = 1412772946845634642
API_HOSTS = [
    "https://api.wc3stats.com/gamelist",        # primary
    "https://wc3maps.com/api/lobbies"           # backup API
]

# --- BOT INTENTS ---
intents = discord.Intents.default()
intents.members = True  # needed for role assignment
intents.invites = True

# --- BOT INSTANCE ---
bot = commands.Bot(command_prefix="!", intents=intents)

posted_games = {}  # game_id -> {"message": msg, "start_time": timestamp, "closed": bool, "frozen_uptime": str}

# --- Store invites per guild --- 
async def refresh_invites():
    await bot.wait_until_ready()  # make sure the bot is fully connected
    while not bot.is_closed():
        for guild in bot.guilds:
            invites = await guild.invites()
            invite_cache[guild.id] = {invite.code: invite.uses for invite in invites}
        await asyncio.sleep(1800)  # 30 minutes
        bot.loop.create_task(refresh_invites())

invite_cache = {}

@bot.event
async def on_ready():
    print(f"✅ {bot.user} is online")
    for guild in bot.guilds:
        invites = await guild.invites()
        invite_cache[guild.id] = {invite.code: invite.uses for invite in invites}

@bot.event
async def on_member_join(member):
    guild = member.guild
    invites_before = invite_cache.get(guild.id, {})
    invites_after = await guild.invites()

    used_invite = None
    for invite in invites_after:
        if invite.uses > invites_before.get(invite.code, 0):
            used_invite = invite
            break

    # update cache
    invite_cache[guild.id] = {invite.code: invite.uses for invite in invites_after}

    log_channel = guild.get_channel(1420313772781862933)  # paste your channel ID
    if log_channel:
        embed = discord.Embed(
            title="🟢 Member Joined",
            description=f"{member.mention} ({member})",
            color=discord.Color.green()
        )
        embed.add_field(name="ID", value=member.id, inline=False)
        embed.add_field(name="Account Created", value=discord.utils.format_dt(member.created_at, style='R'), inline=False)
        if used_invite:
            embed.add_field(name="Invite Used", value=f"https://discord.gg/{used_invite.code}\nCreated by {used_invite.inviter}", inline=False)
        else:
            embed.add_field(name="Invite Used", value="Unknown (maybe vanity link or expired invite)", inline=False)

        await log_channel.send(embed=embed)

@bot.event
async def on_member_remove(member):
    guild = member.guild
    log_channel = discord.utils.get(guild.text_channels, name="join-logs")
    if log_channel:
        embed = discord.Embed(
            title="🔴 Member Left",
            description=f"{member} ({member.id})",
            color=discord.Color.red()
        )
        await log_channel.send(embed=embed)

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
DAYS_THRESHOLD = 14               # Days before upgrade

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
@tasks.loop(hours=12)
async def upgrade_roles():
    GUILD_ID = 1412713066495217797  # replace with your guild ID
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
        days_with_role_x = (now - assigned_at).total_seconds() / 86400  # convert seconds to days
        
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
    print(f"Logged in as {bot.user}")

    try:
        with open("map_icon.png", "rb") as f:
            await bot.user.edit(avatar=f.read())
        print("✅ Avatar updated")
    except Exception as e:
        print(f"❌ Failed to update avatar: {e}")

    fetch_games.start()
    upgrade_roles.start()  # Start role upgrade loop

# --- GAME FETCH LOOP ---
@tasks.loop(seconds=9)
async def fetch_games():
    data = None
    api_used = None  # <--- track which API succeeded

    async with aiohttp.ClientSession() as session:
        for host in API_HOSTS:
            try:
                async with session.get(host, timeout=3) as resp:
                    if resp.status != 200:
                        print(f"[API] ❌ {host} failed with status {resp.status}")
                        continue

                    data = await resp.json()
                    if not isinstance(data, dict) or "body" not in data:
                        print(f"[API] ❌ {host} returned invalid data")
                        continue

                    api_used = host  # <--- record which API succeeded
                    break  # success → stop trying other hosts

            except Exception as e:
                print(f"[API] ❌ Request to {host} failed: {e}")
                continue

    if not data:
        print("[API] ❌ All APIs failed, skipping this poll")
        return

    # Log which API succeeded
    print(f"[API] ✅ Using data from: {api_used}")


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
                    "frozen_uptime": None,
                    "slotsTaken": slotsTaken,
                    "pendingSlots": None,
                    "slotsTotal": slotsTotal
                }
            else:
                if posted_games[game_id]["pendingSlots"] is not None:
                    posted_games[game_id]["slotsTaken"] = posted_games[game_id]["pendingSlots"]

                posted_games[game_id]["pendingSlots"] = slotsTaken
                posted_games[game_id]["slotsTotal"] = slotsTotal

            if not posted_games[game_id]["closed"]:
                uptime_sec = int(current_time - posted_games[game_id]["start_time"])
                minutes, seconds = divmod(uptime_sec, 60)
                uptime_text = f"{minutes}m {seconds}s"
                posted_games[game_id]["frozen_uptime"] = uptime_text
            else:
                uptime_text = posted_games[game_id]["frozen_uptime"]

            # --- Determine embed color based on map name ---         
            map_lower = map_name.lower()
            
            if "roc" in map_lower:
                color = discord.Color.orange()
            elif "lition" in map_lower or "hlwl" in map_lower:
                color = discord.Color(0x4E78F0)  # Blue
            elif "custom" in map_lower:
                color = discord.Color(0x9B59B6)  # Purple
            else:
                color = discord.Color(0x787878)  # Grey

            
            embed = discord.Embed(title=name, color=color)
            
            embed.add_field(name="Map", value=map_name, inline=False)
            embed.add_field(name="Host", value=host, inline=True)
            embed.add_field(name="Realm", value=server, inline=True)
            embed.add_field(
                name="Players",
                value=f"{posted_games[game_id]['slotsTaken']}/{posted_games[game_id]['slotsTotal']}",
                inline=True
            )
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
                pending = posted_games[game_id].get("pendingSlots")
                confirmed = posted_games[game_id]["slotsTaken"]

                if pending is not None:
                    if not (confirmed > 1 and pending == 1):
                        posted_games[game_id]["slotsTaken"] = pending

                current_time = time.time()
                uptime_sec = int(current_time - posted_games[game_id]["start_time"])
                minutes, seconds = divmod(uptime_sec, 60)
                frozen_uptime = f"{minutes}m {seconds}s"
                posted_games[game_id]["frozen_uptime"] = frozen_uptime

                current_embed = msg.embeds[0]
                closed_embed = discord.Embed(title=current_embed.title, color=current_embed.color)
                for field in current_embed.fields:
                    if field.name == "Players":
                        closed_embed.add_field(
                            name="Players",
                            value=f"{posted_games[game_id]['slotsTaken']}/{posted_games[game_id]['slotsTotal']}",
                            inline=True
                        )
                    else:
                        closed_embed.add_field(name=field.name, value=field.value, inline=field.inline)

                for i, field in enumerate(closed_embed.fields):
                    if field.name == "Uptime":
                        closed_embed.set_field_at(
                            i,
                            name="Uptime",
                            value=f"{frozen_uptime} - *Closed*",
                            inline=True
                        )
                        break

                await msg.edit(embed=closed_embed)
                posted_games[game_id]["closed"] = True
                print(f"Marked game {game_id} as Closed with frozen uptime {frozen_uptime}")

            except Exception as e:
                print(f"❌ Failed to mark game closed {game_id}: {e}")

# --- RUN BOT ---
bot.run(TOKEN)

















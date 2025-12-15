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

# --- INVITES CACHE ---
invite_cache = {}  # guild_id -> {code: uses}

@tasks.loop(minutes=30)
async def refresh_invites_task():
    for guild in bot.guilds:
        try:
            invites = await guild.invites()
            invite_cache[guild.id] = {invite.code: invite.uses for invite in invites}
        except Exception as e:
            print(f"❌ refresh_invites_task failed for guild {guild.id}: {e}")

@refresh_invites_task.before_loop
async def before_refresh_invites_task():
    await bot.wait_until_ready()

# --- MEMBER JOIN LOGGING (invite used) ---
@bot.event
async def on_member_join(member: discord.Member):
    guild = member.guild
    invites_before = invite_cache.get(guild.id, {})

    used_invite = None
    try:
        invites_after = await guild.invites()
        for invite in invites_after:
            if invite.uses > invites_before.get(invite.code, 0):
                used_invite = invite
                break

        # update cache
        invite_cache[guild.id] = {invite.code: invite.uses for invite in invites_after}
    except Exception as e:
        print(f"❌ Failed to fetch invites on join: {e}")

    log_channel = guild.get_channel(1420313772781862933)  # your channel ID
    if log_channel:
        embed = discord.Embed(
            title="🟢 Member Joined",
            description=f"{member.mention} ({member})",
            color=discord.Color.green()
        )
        embed.add_field(name="ID", value=str(member.id), inline=False)
        embed.add_field(name="Account Created", value=discord.utils.format_dt(member.created_at, style='R'), inline=False)

        if used_invite:
            embed.add_field(
                name="Invite Used",
                value=f"https://discord.gg/{used_invite.code}\nCreated by {used_invite.inviter}",
                inline=False
            )
        else:
            embed.add_field(
                name="Invite Used",
                value="Unknown (maybe vanity link or expired invite)",
                inline=False
            )

        await log_channel.send(embed=embed)

@bot.event
async def on_member_remove(member: discord.Member):
    guild = member.guild
    log_channel = discord.utils.get(guild.text_channels, name="join-logs")
    if log_channel:
        embed = discord.Embed(
            title="🔴 Member Left",
            description=f"{member} ({member.id})",
            color=discord.Color.red()
        )
        await log_channel.send(embed=embed)

# --- ROLE UPGRADE CONFIG --- Upgrade role Member (Peon) to Member (Grunt)
ROLE_X_ID = 1414518023636914278  # Existing role to track
ROLE_Y_ID = 1413169885663727676  # Role to assign after threshold
DAYS_THRESHOLD = 14              # Days before upgrade

role_x_assignment = {}  # member_id -> datetime (UTC aware)

@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    before_roles = {r.id for r in before.roles}
    after_roles = {r.id for r in after.roles}

    # Role X newly added
    if ROLE_X_ID not in before_roles and ROLE_X_ID in after_roles:
        # IMPORTANT: timezone-aware UTC datetime
        role_x_assignment[after.id] = datetime.datetime.now(datetime.timezone.utc)

@tasks.loop(hours=12)
async def upgrade_roles():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        print("❌ Guild not found")
        return

    role_x = guild.get_role(ROLE_X_ID)
    role_y = guild.get_role(ROLE_Y_ID)
    if not role_x or not role_y:
        print("❌ Roles not found in guild")
        return

    me = guild.me or guild.get_member(bot.user.id)
    if not me:
        print("❌ Could not resolve bot member in guild")
        return

    # Hard permission/hierarchy checks (most common silent failure)
    if not guild.me.guild_permissions.manage_roles:
        print("❌ Bot lacks Manage Roles permission")
        return
    if role_x >= me.top_role or role_y >= me.top_role:
        print("❌ Role hierarchy issue: bot top role must be ABOVE both Role X and Role Y")
        return

    now = datetime.datetime.now(datetime.timezone.utc)

    # ✅ IMPORTANT: fetch members from API (not cache)
    members = [m async for m in guild.fetch_members(limit=None)]
    print(f"[upgrade_roles] tick: members_fetched={len(members)}")

    candidates = 0
    upgraded = 0

    for member in members:
        if member.bot:
            continue
        if role_x not in member.roles:
            continue

        candidates += 1

        assigned_at = role_x_assignment.get(member.id)
        if assigned_at is None:
            assigned_at = member.joined_at  # membership tenure fallback

        if assigned_at is None:
            # if this happens a lot, your member data is incomplete
            print(f"[upgrade_roles] {member} has no joined_at; skipping")
            continue

        if assigned_at.tzinfo is None:
            assigned_at = assigned_at.replace(tzinfo=datetime.timezone.utc)

        days = (now - assigned_at).total_seconds() / 86400.0

        if days >= DAYS_THRESHOLD:
            try:
                await member.remove_roles(role_x, reason="Auto-upgrade after threshold")
                await member.add_roles(role_y, reason="Auto-upgrade after threshold")
                role_x_assignment.pop(member.id, None)
                upgraded += 1
                print(f"✅ Upgraded {member} (days={days:.2f})")
            except Exception as e:
                print(f"❌ Failed upgrading {member}: {e}")

    print(f"[upgrade_roles] candidates_with_role_x={candidates}, upgraded={upgraded}")


@upgrade_roles.before_loop
async def before_upgrade_roles():
    await bot.wait_until_ready()

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

# --- ONE MERGED READY EVENT ---
_avatar_set = False

@bot.event
async def on_ready():
    global _avatar_set

    print(f"✅ Logged in as {bot.user}")

    # init invite cache immediately
    for guild in bot.guilds:
        try:
            invites = await guild.invites()
            invite_cache[guild.id] = {invite.code: invite.uses for invite in invites}
        except Exception as e:
            print(f"❌ Failed to init invites for guild {guild.id}: {e}")

    # update avatar once (avoids hammering rate limits on reconnect)
    if not _avatar_set:
        try:
            with open("map_icon.png", "rb") as f:
                await bot.user.edit(avatar=f.read())
            print("✅ Avatar updated")
            _avatar_set = True
        except Exception as e:
            print(f"❌ Failed to update avatar: {e}")

    # start tasks safely (on_ready can fire multiple times)
    if not refresh_invites_task.is_running():
        refresh_invites_task.start()

    if not fetch_games.is_running():
        fetch_games.start()

    if not upgrade_roles.is_running():
        upgrade_roles.start()


# --- RUN BOT ---
bot.run(TOKEN)



















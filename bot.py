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

posted_games = {}  # game_id -> {"message": msg, "start_time": timestamp, "closed": bool, "frozen_uptime": str}


# --- ROLE ASSIGNMENT ---
@bot.event
async def on_member_join(member):
    role_name = "Member"
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

    try:
        with open("map_icon.png", "rb") as f:
            await bot.user.edit(avatar=f.read())
        print("✅ Avatar updated")
    except Exception as e:
        print(f"❌ Failed to update avatar: {e}")

    fetch_games.start()



# --- GAME FETCH LOOP ---
@tasks.loop(seconds=10)
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
                            "frozen_uptime": "0m 0s"
                        }

                    # Determine uptime
                    if not posted_games[game_id]["closed"]:
                        uptime_sec_local = int(current_time - posted_games[game_id]["start_time"])
                        minutes, seconds = divmod(uptime_sec_local, 60)
                        uptime_text = f"{minutes}m {seconds}s"
                    else:
                        uptime_text = posted_games[game_id]["frozen_uptime"]

                    # Build embed
                    embed = discord.Embed(title=name, color=discord.Color.green())
                    embed.add_field(name="Map", value=map_name, inline=False)
                    embed.add_field(name="Host", value=host, inline=True)
                    embed.add_field(name="Realm", value=server, inline=True)
                    embed.add_field(name="Players", value=f"{slotsTaken}/{slotsTotal}", inline=True)
                    embed.add_field(name="Uptime", value=uptime_text, inline=True)

                    # Add *Closed* field if needed
                    if posted_games[game_id]["closed"]:
                        embed.add_field(name="\u200b", value="*Closed*", inline=True)
                    else:
                        embed.add_field(name="\u200b", value="\u200b", inline=True)

                    # Send or update message
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

                        # Copy fields into a new embed to preserve color
                        closed_embed = discord.Embed(
                            title=current_embed.title,
                            color=current_embed.color
                        )
                        for field in current_embed.fields:
                            closed_embed.add_field(
                                name=field.name,
                                value=field.value,
                                inline=field.inline
                            )

                        # Freeze uptime and add *Closed* in italics
                        current_uptime = current_embed.footer.text or "0m 0s"
                        current_uptime = current_uptime.replace("Uptime: ", "").replace(" *Closed*", "")
                        closed_embed.add_field(name="Uptime", value=current_uptime, inline=True)
                        closed_embed.add_field(name="\u200b", value="*Closed*", inline=True)

                        await msg.edit(embed=closed_embed)

                        # Update tracking
                        posted_games[game_id]["closed"] = True
                        posted_games[game_id]["frozen_uptime"] = current_uptime
                        print(f"Marked game {game_id} as Closed with uptime frozen.")

                    except Exception as e:
                        print(f"❌ Failed to mark game closed {game_id}: {e}")
# --- RUN BOT ---
bot.run(TOKEN)

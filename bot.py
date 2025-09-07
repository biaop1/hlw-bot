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

            # Track active games
            for game in games:
                game_id = game.get("id")
                active_ids.add(game_id)

                name = game.get("name", "")
                map_name = game.get("map", "")
                host = game.get("host", "")
                server = game.get("server", "")
                slotsTaken = game.get("slotsTaken", 0)
                slotsTotal = game.get("slotsTotal", 0)

                # Only care about matching games
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
                        posted_games[game_id] = {"message": None, "start_time": current_time, "closed": False}

                    # If game is already closed, skip updating uptime
                    if not posted_games[game_id]["closed"]:
                        uptime_sec_local = int(current_time - posted_games[game_id]["start_time"])
                        minutes, seconds = divmod(uptime_sec_local, 60)
                        uptime_text = f"{minutes}m {seconds}s"
                    else:
                        # Keep the frozen uptime for closed games
                        uptime_text = posted_games[game_id].get("frozen_uptime", "0m 0s")

                    # Build embed
                    embed = discord.Embed(
                        title=f"{name}",
                        color=discord.Color.green()  # original color
                    )
                    embed.add_field(name="Map", value=f"{map_name}", inline=False)
                    embed.add_field(name="Host", value=f"{host}", inline=True)
                    embed.add_field(name="Realm", value=f"{server}", inline=True)
                    embed.add_field(name="Players", value=f"{slotsTaken}/{slotsTotal}", inline=True)

                    # Append *Closed* if needed
                    footer_text = f"Uptime: {uptime_text}"
                    if posted_games[game_id]["closed"]:
                        footer_text += " *Closed*"
                    embed.set_footer(text=footer_text)

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

            # Mark disappeared games as closed and freeze uptime
            for game_id in list(posted_games.keys()):
                if game_id not in active_ids and not posted_games[game_id]["closed"]:
                    msg = posted_games[game_id]["message"]
                    if not msg or not msg.embeds:
                        continue
                    try:
                        current_embed = msg.embeds[0]

                        closed_embed = discord.Embed(
                            title=current_embed.title,
                            color=current_embed.color  # keep original color
                        )

                        # Copy fields
                        for field in current_embed.fields:
                            closed_embed.add_field(
                                name=field.name,
                                value=field.value,
                                inline=field.inline
                            )

                        # Freeze uptime and append *Closed*
                        current_uptime = current_embed.footer.text or "0m 0s"
                        current_uptime = current_uptime.replace("Uptime: ", "").replace(" *Closed*", "")
                        #closed_embed.set_footer(text=f"{current_uptime} *Closed*")
                        embed.add_field(name="Uptime", value=uptime_text, inline=True)
                        if posted_games[game_id]["closed"]:
                            embed.add_field(name="\u200b", value="*Closed*", inline=True)  # \u200b is a zero-width space to keep it blank
                        else:
                            embed.add_field(name="\u200b", value="\u200b", inline=True)
                        # Edit message
                        await msg.edit(embed=closed_embed)

                        # Update tracking
                        posted_games[game_id]["closed"] = True
                        posted_games[game_id]["frozen_uptime"] = current_uptime

                        print(f"Marked game {game_id} as Closed with uptime frozen.")

                    except Exception as e:
                        print(f"❌ Failed to mark game closed {game_id}: {e}")

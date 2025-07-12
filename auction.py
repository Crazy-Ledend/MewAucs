import discord
from typing import Literal
from discord.ext import commands, tasks
from discord import Embed, app_commands, Interaction, ButtonStyle
# from discord import app_commands
from discord.ui import View, Button
import sqlite3
from datetime import datetime, timedelta
import pytz
import re
import json
from PIL import Image
from io import BytesIO
import requests
from collections import Counter


def get_dominant_color_from_url(image_url):
    try:
        response = requests.get(image_url)
        img = Image.open(BytesIO(response.content)).convert("RGBA")
        img = img.resize((100, 100))  # Resize for faster processing

        # Filter out mostly transparent pixels
        pixels = [
            (r, g, b) for r, g, b, a in img.getdata()
            if a > 50  # keep only opaque/semi-opaque pixels
        ]

        if not pixels:
            raise ValueError("All pixels are transparent.")

        most_common = Counter(pixels).most_common(1)[0][0]
        return discord.Color.from_rgb(*most_common)

    except Exception as e:
        print(f"Image color detection failed: {e}")
        return discord.Color.blurple()


def list_choices():
    return [
        app_commands.Choice(name="Auctioneers", value="auctioneers"),
        app_commands.Choice(name="Auctions", value="auctions")
    ]


def poke_data(cursor, db, auction_id, embed, desc):
    title = embed.title
    description = desc  # embed.description or ""
    fields_data = []

    for field in embed.fields:
        fields_data.append({
            "name": field.name,
            "value": field.value,
            "inline": field.inline
        })

    cursor.execute(
        "INSERT INTO pokemon_embeds (auction_id, title, description, fields) VALUES (?, ?, ?, ?)",
        (auction_id, title, description, json.dumps(fields_data)))
    db.commit()


def get_pokemon_data(cursor, auction_id: int):
    cursor.execute(
        "SELECT title, description, fields FROM pokemon_embeds WHERE auction_id = ?",
        (auction_id, ))
    data = cursor.fetchone()
    if not data:
        return None

    title, description, fields_json = data
    fields = json.loads(fields_json)

    embed = discord.Embed(title=title, description=description)
    for field in fields:
        embed.add_field(name=field["name"],
                        value=field["value"],
                        inline=field["inline"])
    return embed


class AuctionBot(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.db = sqlite3.connect('auction_bot.db', check_same_thread=False)
        self.cursor = self.db.cursor()
        self.timezone = pytz.timezone('Asia/Kolkata')

    def is_auctioneer(self, user_id):
        self.cursor.execute("SELECT 1 FROM auctioneers WHERE user_id = ?",
                            (str(user_id), ))
        return self.cursor.fetchone() is not None

    @commands.hybrid_command(name='auctioneer')
    async def toggle_auctioneer(self, ctx, user_id: int):
        """Toggle auctioneer status for a user."""
        if ctx.author.id != ctx.guild.owner.id or ctx.author.id != 891319231436685342:
            await ctx.send("Only the server owner can manage auctioneers.")
            return

        self.cursor.execute("SELECT 1 FROM auctioneers WHERE user_id = ?",
                            (str(user_id), ))
        if self.cursor.fetchone():
            self.cursor.execute("DELETE FROM auctioneers WHERE user_id = ?",
                                (str(user_id), ))
            await ctx.send(f"User {user_id} is no longer an auctioneer.")
        else:
            self.cursor.execute("INSERT INTO auctioneers (user_id) VALUES (?)",
                                (str(user_id), ))
            await ctx.send(f"User {user_id} is now an auctioneer.")
        self.db.commit()

    @commands.hybrid_command(name='auction')
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def start_auction(self,
                            ctx,
                            embed_url: str,
                            duration: int,
                            min_bid: int,
                            interval: int,
                            buyout_price: int = None):
        """Start a new auction."""
        if not self.is_auctioneer(ctx.author.id):
            await ctx.send("You are not authorized to start an auction.")
            return

        await ctx.interaction.response.defer()

        match = re.search(r'/channels/(\d+)/(\d+)/(\d+)', embed_url)
        if not match:
            await ctx.send("❌ Invalid embed URL format.")
            return

        _, channel_id, message_id = match.groups()

        try:
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                await ctx.send("❌ Bot can't find the channel. Check access.")
                return

            embed_message = await channel.fetch_message(int(message_id))
        except discord.Forbidden:
            await ctx.send("❌ Bot lacks permission to access the message.")
            return
        except discord.NotFound:
            await ctx.send("❌ Message not found. Check the link.")
            return
        except Exception as e:
            await ctx.send(f"❌ Unexpected error: {type(e).__name__} - {e}")
            return

        original_embed = embed_message.embeds[
            0] if embed_message.embeds else None
        if not original_embed:
            await ctx.send("❌ No embed found in the message.")
            return

        # Step 1: Extract Global ID from footer
        footer_text = original_embed.footer.text if original_embed.footer else ""
        global_id_match = re.search(r"Global ID#:\s*(\d+)", footer_text)

        if not global_id_match:
            await ctx.send(
                "❌ Could not find the Pokémon's Global ID in the embed footer."
            )
            return

        global_id = global_id_match.group(1)

        self.cursor.execute(
            """
            SELECT last_auction_end FROM auctioned_pokemon
            WHERE global_id = ?
        """, (global_id, ))
        row = self.cursor.fetchone()

        if row:
            last_auction_end = datetime.fromisoformat(row[0])
            if datetime.now(self.timezone) - last_auction_end < timedelta(
                    days=7):
                await ctx.send(
                    "❌ This Pokémon was already auctioned in the last 7 days.")
                return

        KNOWN_NATURES = [
            "adamant", "bashful", "bold", "brave", "calm", "careful", "docile",
            "gentle", "hardy", "hasty", "impish", "jolly", "lax", "lonely",
            "mild", "modest", "naive", "naughty", "quiet", "quirky", "rash",
            "relaxed", "sassy", "serious", "timid"
        ]

        # Combine all content
        title = original_embed.title or ""
        # title = title.replace("<:blank:1012504803496177685>", "")

        level_match = re.search(r"<:lvl:\d+>\s*(\d+)", title)
        level = level_match.group(1) if level_match else "??"

        # Check if shiny
        shiny = ":star2:" in title
        gleam = ":gleam:" in title
        radiant = ":radiant:" in title
        alpha = ":alphapoke2:" in title
        shadow = ":shadow:" in title

        if ":genderless:" in title:
            gender = "Genderless"
        elif ":male:" in title:
            gender = "Male"
        elif ":female:" in title:
            gender = "Female"
        else:
            gender = "Unknown"

        # title = title.replace(":genderless:", "").replace(":male:", "").replace(":female:", "")
        # title = title.replace("<:lvl:1029030189981765673>", "").replace(level, "").strip()

        # 1. Discord emojis
        clean_title = re.sub(r"<:\w+:\d+>", "", title)

        # 2. Stand-alone emojis
        clean_title = re.sub(r":\w+:", "", clean_title)

        # 3. Levels
        clean_title = re.sub(r"\b\d+\b", "", clean_title)

        clean_title = clean_title.strip().lower()
        words = clean_title.split()
        filtered_words = [word for word in words if word not in KNOWN_NATURES]
        title = " ".join(
            filtered_words)  # clean_title = " ".join(filtered_words)

        description = original_embed.description or ""
        field_values = "\n".join(f.value for f in original_embed.fields)
        text_block = f"{description}\n{field_values}"

        def extract(pattern, default=None, cast=str):
            match = re.search(pattern, text_block, re.IGNORECASE)
            return cast(match.group(1)) if match else default

        # Parse info

        # Clean and extract Pokémon name
        # clean_description = re.sub(r":\w+?:", "", description).strip()

        # Extract nickname if wrapped in single quotes
        nickname_match = re.search(r"'([^']+)'", title)
        nickname = nickname_match.group(1).strip() if nickname_match else None

        # Remove emojis and quotes
        title_wo_emojis = re.sub(r"<a?:\w+:\d+>", "",
                                 title)  # Custom Discord emojis
        title_wo_emojis = re.sub(r":[^:\s]+:", "",
                                 title_wo_emojis)  # Unicode-style emojis
        title_wo_emojis = re.sub(r"['\"`]", "",
                                 title_wo_emojis)  # Quotes/backticks

        # Remove level numbers
        title_wo_emojis = re.sub(r"\b\d+\b", "", title_wo_emojis)

        # Remove known natures from title
        title_cleaned = title_wo_emojis
        for nature in KNOWN_NATURES:
            title_cleaned = re.sub(rf"\b{nature}\b",
                                   "",
                                   title_cleaned,
                                   flags=re.IGNORECASE)

        # Final clean-up
        words = title_cleaned.strip().split()
        # Pokémon name is usually the last word
        if nickname:
            pokemon_name = title.replace(nickname, "").strip()
            # pokemon_name = words[-2].lower() if words else "unknown"
        elif not nickname:
            pokemon_name = title
            # pokemon_name = words[-1].lower() if words else "unknown"
        # Parse IV %
        iv_match = re.search(r'IV %.*?(\d+\.\d+)%', text_block)
        iv_percent = iv_match.group(1) if iv_match else "00.00"

        # Set prefix and channel name
        if shiny:
            star_prefix = "⭐|"
        elif radiant:
            star_prefix = "🎆|"
        elif gleam:
            star_prefix = "🔮|"
        elif alpha:
            star_prefix = "🌌|"
        elif shadow:
            star_prefix = "🌑|"
        else:
            star_prefix = ""

        channel_name = f"{star_prefix}{pokemon_name}-{round(float(iv_percent))}"

        # POKEMON_TYPES = [
        #     "normal", "fire", "water", "electric", "grass", "ice", "fighting",
        #     "poison", "ground", "flying", "psychic", "bug", "rock", "ghost",
        #     "dragon", "dark", "steel", "fairy"
        # ]

        # types_found = re.findall(r":([a-z_]+):", text_block)
        # types = ", ".join(
        #     t for t in types_found if t in POKEMON_TYPES) or "Unknown"

        # ability = extract(r"Ability:\s*(.*?)(?:\n|$)", "Unknown")
        # level = extract(r":lvl:\s*(\d+)", "??")
        # nature = extract(r"(\+[\w]+/-[\w]+)")

        print("Title:", title)
        print("Pokemon Name:", pokemon_name.replace("''", "").strip())
        print("Gender:", gender)
        print("Level:", level)

        # exp = extract(r"EXP:\s*([\d]+/[^\n]+)")
        # egg = extract(r"Egg Groups:\s*:.*?\s*(.*?)(?:\n|$)", "Unknown")

        raw_hold = extract(
            r"(?:Holding|Held Item)\s*:\s*(?:<:\w+:\d+>\s*)?(.*?)(?:\n|$)",
            "None")
        hold = raw_hold.strip() if raw_hold else "None"

        hpw = extract(r"\*\*Hidden Power\*\*:\s*(?:`)?(.*?)(?:`)?(?:\n|$)",
                      "Unknown")

        # Parse Stats (simplified)
        stats = {}
        for stat in ['HP', 'Attack', 'Defense', 'Sp. Atk', 'Sp. Def', 'Speed']:
            match = re.search(rf"{stat}:\s*(\d+).*?(\d+)\s*\|\s*(\d+)",
                              text_block)
            if match:
                stats[stat] = {
                    'value': match.group(1),
                    'iv': match.group(2),
                    'ev': match.group(3)
                }

        # Moves
        # moves_match = re.search(r"Moves:\s*(.*?)$", text_block, re.DOTALL)
        # moves = [m.strip() for m in moves_match.group(1).split(",")
        #          ] if moves_match else []

        # Create channel
        category = discord.utils.get(ctx.guild.categories, name="Auctions")
        if not category:
            category = await ctx.guild.create_category("Auctions")

        bot_member = ctx.guild.me
        auction_channel = await ctx.guild.create_text_channel(
            channel_name,
            category=category,
            topic=
            f"Auction: {pokemon_name.replace('-', ' ').title()} ({iv_percent}%)",
            overwrites={
                ctx.guild.default_role:
                discord.PermissionOverwrite(send_messages=True,
                                            view_channel=True,
                                            read_message_history=True),
                ctx.author:
                discord.PermissionOverwrite(send_messages=True,
                                            view_channel=True,
                                            read_message_history=True),
                bot_member:
                discord.PermissionOverwrite(send_messages=True,
                                            view_channel=True,
                                            embed_links=True,
                                            read_message_history=True)
            })

        # Insert into DB
        duration *= 60
        end_time = datetime.now(self.timezone) + timedelta(minutes=duration)
        unix_time = int(end_time.timestamp())
        discord_time = f"<t:{unix_time}:f>"

        if shiny:
            display_name = f"🌟 {gender} {pokemon_name.replace('-', ' ').title()} '{nickname}'"
            variant = ""
        elif radiant:
            display_name = f"<:archaic_stone:1385907327424663672> {gender} {pokemon_name.replace('-', ' ').title()} '{nickname}'"
            variant = "radiants"
        elif gleam:
            display_name = f"🔮 {gender} {pokemon_name.replace('-', ' ').title()} '{nickname}'"
            variant = "gleams"
        elif alpha:
            display_name = f"<:alpha:1385906481752309911> {gender} {pokemon_name.replace('-', ' ').title()} '{nickname}'"
            variant = "alphas"
        elif shadow:
            display_name = f"<:shadow:1385906473028292608> {gender} {pokemon_name.replace('-', ' ').title()} '{nickname}'"
            variant = ""
        else:
            display_name = f"{gender} {pokemon_name.replace('-', ' ').title()} '{nickname}'"
            variant = ""

        print("Variant:", variant)

        variant_snippet = ""
        if variant:
            if variant == "alphas":
                self.cursor.execute(
                    f"SELECT release_month, move FROM {variant} WHERE name = ?",
                    (pokemon_name.replace("''",
                                          "").strip(), ))  #replace('-', ' ').
            else:
                self.cursor.execute(
                    f"SELECT release_month FROM {variant} WHERE name = ?",
                    (pokemon_name.replace("''", "").strip(), ))
            row = self.cursor.fetchone()
            if row:
                release_month = row[0]
                variant_snippet = f"**Released month:** `{release_month}`\n"
                if variant == "alphas":
                    move = row[1]
                    variant_snippet += f"**Move:** `{move}`\n"

        # Insert into auctions table
        self.cursor.execute(
            """
            INSERT INTO auctions (
                channel_id, message_id, item_embed_url, buyout_price, end_time,
                auctioneer_id, min_bid, interval, current_bid, winner_id, pokemon_name
            )
            VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (str(auction_channel.id), embed_url,
             buyout_price if buyout_price is not None else None,
             end_time.isoformat(), str(
                 ctx.author.id), min_bid, interval, None, None, display_name))

        self.db.commit()

        # Update auctioned_pokemon table
        self.cursor.execute(
            """
            INSERT OR REPLACE INTO auctioned_pokemon (global_id, last_auction_end)
            VALUES (?, ?)
        """, (global_id, end_time.isoformat()))
        self.db.commit()

        self.cursor.execute("SELECT last_insert_rowid()")
        auction_id = self.cursor.fetchone()[0]

        desc = f"**Level:** {level or '??'}\n\
        **Hidden Power:** {hpw or 'Unknown'}\n\
        **Held Item:** {hold or 'None'}\n\
        {variant_snippet}\
        \n**Stats (Base | IV | EV):**\n" + "\n".join(
            f"• **{k}:** {v['value']} | {v['iv']} | {v['ev']}"
            for k, v in stats.items()) + f"\n**IV %:** {iv_percent}%"
        # | **Nature:** {nature or 'Unknown'} | **Gender:** {gender or 'Unknown'}\n"
        #  f"**Ability:** {ability or 'Unknown'}\n"
        #  f"**EXP:** {exp or 'Unknown'}\n"
        #  f"**Types:** {types or 'Unknown'}\n"
        #  f"**Egg Group:** {egg or 'Unknown'}\n"
        # "\n\n**Moves:** " +
        # (", ".join(moves) if moves else "None") +

        buyout_display = f"🏷️ **Buyout:** {buyout_price:,}" if buyout_price is not None else "🏷️ **Buyout:** *None*"

        if original_embed.image and original_embed.image.url:
            embed_color = get_dominant_color_from_url(original_embed.image.url)
        else:
            embed_color = discord.Color.blurple()

        embed = discord.Embed(title=f"{display_name}",
                              description=(f"{desc}\n\n"
                                           f"💰 **Min Bid:** {min_bid:,}\n"
                                           f"🔼 **Interval:** {interval:,}\n"
                                           f"{buyout_display}\n"
                                           f"⏰ **Ends:** {discord_time}"),
                              color=embed_color)

        if original_embed.image and original_embed.image.url:
            embed.set_image(url=original_embed.image.url)

        embed.set_footer(text=f"Auction ID: {auction_id}")

        auction_message = await auction_channel.send(embed=embed)
        self.cursor.execute(
            "UPDATE auctions SET message_id = ? WHERE auction_id = ?",
            (str(auction_message.id), auction_id))
        self.db.commit()
        poke_data(self.cursor, self.db, auction_id, embed, desc)

        if ctx.interaction:
            await ctx.interaction.followup.send(
                f"✅ Auction started in {auction_channel.mention}")
        else:
            await ctx.send(f"✅ Auction started in {auction_channel.mention}")

    @start_auction.error
    async def start_auction_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"🕒 This command is on cooldown. Try again in `{error.retry_after:.1f}` seconds.",
                ephemeral=True if hasattr(ctx, 'interaction') else False)
        else:
            raise error  # Raise other unexpected errors

    @commands.hybrid_command(name='bid')
    async def place_bid(self, ctx: commands.Context, auction_id: int,
                        bid_amount: int):

        if ctx.interaction:
            await ctx.interaction.response.defer(thinking=True)
        """Place a bid on an auction."""
        self.cursor.execute("SELECT * FROM auctions WHERE auction_id = ?",
                            (auction_id, ))
        auction = self.cursor.fetchone()
        if not auction:
            await ctx.send("Auction not found.")
            return

        channel_id = int(auction[1])
        message_id = int(auction[2])
        if auction[4]:
            buyout_price = int(auction[4])
        else:
            buyout_price = None
        end_time = datetime.fromisoformat(str(auction[5])).astimezone(
            self.timezone)
        min_bid = auction[7]
        interval = auction[8]
        current_bid = auction[9]
        channel = self.bot.get_channel(channel_id)

        if datetime.now(self.timezone) > end_time:
            await ctx.send("Auction has ended.")
            return

        if bid_amount < min_bid:
            await ctx.send(
                f"Bid must be at least the minimum bid: {min_bid} credits")
            return

        if not current_bid:
            current_bid = 0

        if bid_amount <= current_bid or (bid_amount - current_bid) < interval:
            await ctx.send(
                f"Bid must be higher than the current bid {current_bid} by at least {interval} credits."
            )
            return

        # Get the previous highest bidder
        self.cursor.execute(
            '''
            SELECT user_id FROM bids
            WHERE auction_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
        ''', (auction_id, ))
        row = self.cursor.fetchone()
        previous_bidder_id = row[0] if row else None

        # Check if the previous bidder isn't the one placing the new bid
        if previous_bidder_id and previous_bidder_id != str(ctx.author.id):
            self.cursor.execute(
                "SELECT 1 FROM outbid_notifs WHERE user_id = ?",
                (previous_bidder_id, ))
            if self.cursor.fetchone():
                try:
                    previous_user = await self.bot.fetch_user(
                        int(previous_bidder_id))
                    await previous_user.send(
                        f"📣 You've been outbid in auction #{auction_id}!")
                except discord.Forbidden:
                    print(
                        f"DM to user {previous_bidder_id} failed — DMs closed or blocked."
                    )
                    await channel.send(
                        f"📣 <@{previous_bidder_id}>, You've been outbid by `{ctx.author.display_name}`"
                    )
                except Exception as e:
                    print(f"Unexpected DM error: {e}")

        now_str = datetime.now(self.timezone).isoformat()

        # Record the bid
        self.cursor.execute(
            """
            INSERT INTO bids (auction_id, user_id, bid_amount, timestamp)
            VALUES (?, ?, ?, ?)
        """, (auction_id, str(ctx.author.id), bid_amount, now_str))
        self.cursor.execute(
            "UPDATE auctions SET current_bid = ? WHERE auction_id = ?",
            (bid_amount, auction_id))
        self.db.commit()

        # Update the embed
        try:
            message = await channel.fetch_message(message_id)
            embed = message.embeds[0]
            desc = embed.description

            if "💰 **Min Bid:**" in desc:
                desc = re.sub(r"💰 \*\*Min Bid:\*\*.*?\n",
                              f"💸 **Current Bid:** {bid_amount:,}\n", desc)
            else:
                desc = re.sub(r"💸 \*\*Current Bid:\*\*.*?\n",
                              f"💸 **Current Bid:** {bid_amount:,}\n", desc)

            embed.description = desc
            await message.edit(embed=embed)

        except discord.NotFound:
            await ctx.send(
                "⚠️ Could not update auction embed — message not found.")
        except discord.Forbidden:
            await ctx.send(
                "⚠️ Cannot edit auction message — bot lacks permission.")
        except Exception as e:
            await ctx.send(f"⚠️ Unexpected error while updating embed: {e}")

        await ctx.send(
            f"✅ Bid placed: {bid_amount} credits by `{ctx.author.display_name}`"
        )

        # 💥 Buyout logic
        if buyout_price and bid_amount >= buyout_price:
            self.cursor.execute(
                "UPDATE auctions SET winner_id = ? WHERE auction_id = ?",
                (str(ctx.author.id), auction_id))
            self.db.commit()

            # try:
            #     msg = await channel.fetch_message(message_id)
            #     pokemon_name = msg.embeds[0].title or "Unknown"

            # except (AttributeError, discord.NotFound):
            #     pokemon_name = "Unknown"

            await channel.send(
                f"🏁 Auction ended immediately! <@{ctx.author.id}> bought out the item for {bid_amount:,} credits."
            )
            logs_channel = discord.utils.get(ctx.guild.channels,
                                             name="auction-logs")
            if not logs_channel:
                logs_channel = await ctx.guild.create_text_channel(
                    "auction-logs")

            end_time_dt = datetime.now(self.timezone)
            unix_time = int(end_time_dt.timestamp())
            discord_time = f"<t:{unix_time}:f>"

            embed = get_pokemon_data(self.cursor, auction_id)
            if embed:
                embed.title = f"📦 Auction Closed: {embed.title}"
                embed.color = discord.Color.green()
                embed.description = f"{embed.description}\n\n**Auction ID:** {auction_id}\n**Winner:** <@{ctx.author.id}>\n**Final Bid:** {bid_amount:,} credits\n**Ended At:** {discord_time}"
                await logs_channel.send(embed=embed)
            else:
                await logs_channel.send(
                    f"⚠️ Could not retrieve embed data for auction ID {auction_id}"
                )

            try:
                await channel.delete(reason="Auction ended by buyout.")
            except Exception as e:
                print(f"Failed to delete channel {channel.name}: {e}")

    @commands.hybrid_command(
        name="list", description="View active auctions or auctioneers.")
    @app_commands.choices(choice=list_choices())
    async def list_auctions(self, ctx: commands.Context,
                            choice: app_commands.Choice[str]):
        if choice.value == "auctioneers":
            self.cursor.execute("SELECT DISTINCT user_id FROM auctioneers")
            rows = self.cursor.fetchall()

            if not rows:
                return await ctx.send("⚠️ No auctioneers found.")

            mentions = [f"<@{row[0]}>" for row in rows]
            embed = Embed(title="🧑‍⚖️ Registered Auctioneers",
                          description="\n".join(mentions),
                          color=0xf39c12)
            return await ctx.send(embed=embed)

        elif choice.value == "auctions":
            now = datetime.now(self.timezone).isoformat()
            self.cursor.execute(
                "SELECT auction_id, item_embed_url, end_time, current_bid, pokemon_name FROM auctions WHERE end_time > ? AND winner_id IS NULL ORDER BY end_time ASC",
                (now, ))
            auctions = self.cursor.fetchall()

            if not auctions:
                return await ctx.send("No active auctions at the moment.")

            fields_per_page = 9
            pages = []

            for i in range(0, len(auctions), fields_per_page):
                chunk = auctions[i:i + fields_per_page]
                lines = [
                    "ID   | Name       | Ends In       | Current Bid", "-" * 45
                ]

                for auction in chunk:
                    auction_id = str(auction[0])
                    pokemon_name = auction[4]
                    end_time = datetime.fromisoformat(auction[2])
                    current_bid = int(auction[3] or 0)

                    time_remaining = end_time - datetime.now(self.timezone)
                    if time_remaining.total_seconds() < 0:
                        ends_in = "Ended"
                    else:
                        hrs, rem = divmod(int(time_remaining.total_seconds()),
                                          3600)
                        mins, _ = divmod(rem, 60)
                        ends_in = f"{hrs}h {mins}m" if hrs else f"{mins}m"

                    lines.append(
                        f"{auction_id:<4} | {pokemon_name:<10} | {ends_in:<12} | {current_bid:,}"
                    )

                embed = Embed(title="📢 Active Auctions", color=0x3498db)
                embed.description = f"```{chr(10).join(lines)}```"
                pages.append(embed)

            view = AuctionListView(ctx, pages)
            await view.send_page()

    @tasks.loop(seconds=60)
    async def check_auctions(self):
        """Close expired auctions and announce winners."""
        now = datetime.now(self.timezone).isoformat()
        self.cursor.execute(
            "SELECT * FROM auctions WHERE end_time <= ? AND winner_id IS NULL",
            (now, ))
        auctions = self.cursor.fetchall()

        for auction in auctions:
            auction_id = auction[0]
            channel_id = int(auction[1])
            channel = self.bot.get_channel(channel_id)
            if not channel:
                continue

            self.cursor.execute(
                "SELECT user_id, MAX(bid_amount) FROM bids WHERE auction_id = ?",
                (auction_id, ))
            result = self.cursor.fetchone()
            print(f"Checking auction {auction_id}: result = {result}")

            # Get or create logs channel
            logs_channel = discord.utils.get(channel.guild.channels,
                                             name="auction-logs")
            if not logs_channel:
                try:
                    logs_channel = await channel.guild.create_text_channel(
                        "auction-logs")
                except Exception as e:
                    print(f"Failed to create 'auction-logs' channel: {e}")
                    logs_channel = None  # Just to be safe

            # message_id = auction[2]
            # try:
            #     msg = await channel.fetch_message(message_id)
            #     pokemon_name = msg.embeds[0].title or "Unknown"

            # except (AttributeError, discord.NotFound):
            #     pokemon_name = "Unknown"
            # pokemon_url = auction[2]
            # buyout_price = int(auction[4])
            end_time = auction[5]
            end_time_dt = datetime.fromisoformat(end_time)
            unix_time = int(end_time_dt.timestamp())
            discord_time = f"<t:{unix_time}:f>"

            # print(f"Checking auction {auction_id}: result = {result}")
            if result and result[0] and result[1] and int(
                    result[1]) > 0 and auction[9]:
                winner_id = int(result[0])
                final_bid = int(auction[9])

                self.cursor.execute(
                    "UPDATE auctions SET winner_id = ? WHERE auction_id = ?",
                    (winner_id, auction_id))

                await channel.send(
                    f"🏁 Auction ended! Winner: <@{winner_id}> with a bid of {final_bid:,} credits."
                )

                if logs_channel:
                    embed = get_pokemon_data(self.cursor, auction_id)
                    if embed:
                        embed.title = f"📦 Auction Closed: {embed.title}"
                        embed.color = discord.Color.green()
                        embed.description = f"{embed.description}\n\n**Auction ID:** {auction_id}\n**Winner:** <@{winner_id}>\n**Final Bid:** {final_bid:,} credits\n**Ended At:** {discord_time}"
                        await logs_channel.send(embed=embed)
                    else:
                        await logs_channel.send(
                            f"⚠️ Could not retrieve embed data for auction ID {auction_id}"
                        )

            else:
                try:
                    await channel.send("⚠️ Auction ended with no bids.")
                except Exception as e:
                    print(
                        f"Failed to send message in auction channel {channel_id}: {e}"
                    )

                if logs_channel:
                    embed = get_pokemon_data(self.cursor, auction_id)
                    if embed:
                        embed.title = f"Auction Ended: {embed.title}"
                        embed.color = discord.Color.red()
                        embed.description = f"{embed.description}\n\n**Auction ID:** {auction_id}\n**Final Bid:** --\n**Ended At:** {discord_time}"
                        await logs_channel.send(embed=embed)
                    else:
                        await logs_channel.send(
                            f"⚠️ Could not retrieve embed data for auction ID {auction_id}"
                        )

            self.db.commit()

            try:
                await channel.delete(reason="Auction ended.")
            except Exception as e:
                print(f"Failed to delete channel {channel.name}: {e}")

    @commands.hybrid_command(
        name="endearly",
        description="End your auction early (only for the creator).")
    async def end_early(self, ctx, auction_id: int = None):

        self.cursor.execute("SELECT * FROM auctions WHERE auction_id = ?",
                            (auction_id, ))
        auction = self.cursor.fetchone()

        if not auction:
            return await ctx.send("❌ No auction found with that ID.")

        auctioneer_id = str(auction[6])
        channel_id = int(auction[1])

        if str(ctx.author.id) != auctioneer_id:
            return await ctx.send(
                "⛔ Only the auction creator can end it early.")

        if auction_id is None:
            return await ctx.send("❌ Please provide an auction ID.")

        channel = self.bot.get_channel(channel_id)
        if not channel:
            return await ctx.send("❌ Auction channel not found.")

        # Determine current highest bid
        self.cursor.execute(
            "SELECT user_id, bid_amount FROM bids WHERE auction_id = ? ORDER BY bid_amount DESC LIMIT 1",
            (auction_id, ))
        result = self.cursor.fetchone()

        if result and result[0] and result[1] and int(result[1]) > 0:
            winner_id = str(result[0])
        else:
            winner_id = None

        final_bid = int(result[1]) if result and result[1] else 0

        self.cursor.execute(
            "UPDATE auctions SET winner_id = ? WHERE auction_id = ?",
            (winner_id, auction_id))
        self.db.commit()

        # Create auction-logs channel if it doesn't exist
        logs_channel = discord.utils.get(ctx.guild.channels,
                                         name="auction-logs")
        if not logs_channel:
            try:
                logs_channel = await ctx.guild.create_text_channel(
                    "auction-logs")
            except Exception as e:
                logs_channel = None
                print(f"Failed to create logs channel: {e}")

        # Format time
        end_time = datetime.now(self.timezone)
        unix_time = int(end_time.timestamp())
        discord_time = f"<t:{unix_time}:f>"

        # Build message
        if winner_id:
            await channel.send(
                f"🏁 Auction ended early by {ctx.author.mention}! Winner: <@{winner_id}> with {final_bid:,} credits."
            )
        else:
            await channel.send(
                f"🏁 Auction ended early by {ctx.author.mention} with no bids.")

        # Send log embed
        if logs_channel:
            embed = get_pokemon_data(self.cursor, auction_id)
            if embed:
                embed.title = f"🛑 Auction Ended Early: {embed.title}"
                embed.color = discord.Color.orange()
                embed.description = (
                    f"{embed.description}\n\n"
                    f"**Auction ID:** {auction_id}\n"
                    f"**Ended By:** {ctx.author.mention}\n"
                    f"**Winner:** {f'<@{winner_id}>' if winner_id else '--'}\n"
                    f"**Final Bid:** {f'{final_bid:,} credits' if winner_id else '--'}\n"
                    f"**Ended At:** {discord_time}")
                await logs_channel.send(embed=embed)
            else:
                await logs_channel.send(
                    f"⚠️ Could not retrieve embed data for auction ID {auction_id}"
                )

        try:
            await channel.delete(reason="Auction ended early by creator.")
        except Exception as e:
            print(f"Failed to delete channel: {e}")

    @commands.hybrid_command(name='edit')
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def edit_auction(self, ctx, auction_id: int,
                           option: Literal["minbid", "interval", "buyout",
                                           "time"], value: str):
        """Edit an ongoing auction you created.
        Options: min_bid, interval, buyout, end_time (minutes)
        """
        # Validate option
        option = option.lower()
        if option not in ["minbid", "interval", "buyout", "time"]:
            await ctx.send(
                "❌ Invalid option. Choose from: `minbid`, `interval`, `buyout`, `time`."
            )
            return

        # Fetch the specified auction
        self.cursor.execute(
            """
            SELECT channel_id, message_id, pokemon_name, buyout_price, min_bid, interval, end_time, auctioneer_id
            FROM auctions
            WHERE auction_id = ? AND winner_id IS NULL
        """, (auction_id, ))
        row = self.cursor.fetchone()

        print(row)
        if not row:
            await ctx.send("❌ No active auction found with that ID.")
            return

        channel_id, message_id, pokemon_name, buyout, min_bid, interval, end_time, auctioneer_id = row

        if str(ctx.author.id) != str(auctioneer_id):
            await ctx.send("🚫 You are not the auctioneer of this auction.")
            return

        # Fetch message
        try:
            channel = self.bot.get_channel(int(channel_id))
            message = await channel.fetch_message(int(message_id))
        except Exception as e:
            await ctx.send(
                f"❌ Could not fetch the auction message: {type(e).__name__}")
            return

        embed = message.embeds[0] if message.embeds else None
        if not embed:
            await ctx.send("❌ Auction embed not found.")
            return

        try:
            if option == "time":
                minutes = int(value) * 60
                new_end = datetime.now(
                    self.timezone) + timedelta(minutes=minutes)
                new_end_str = new_end.isoformat()
                new_unix = int(new_end.timestamp())
                self.cursor.execute(
                    "UPDATE auctions SET end_time = ? WHERE auction_id = ?",
                    (new_end_str, auction_id))
                embed.description = re.sub(r"<t:\d+:f>", f"<t:{new_unix}:f>",
                                           embed.description)

            elif option == "minbid":
                new_min = int(value)
                if buyout and buyout < new_min:
                    await ctx.send(
                        f"❌ Minimum bid amount must be less than the buyout price ({buyout:,})."
                    )
                    return
                self.cursor.execute(
                    "UPDATE auctions SET min_bid = ? WHERE auction_id = ?",
                    (new_min, auction_id))
                embed.description = re.sub(r"\*\*Min Bid:\*\* [\d,]+",
                                           f"**Min Bid:** {new_min:,}",
                                           embed.description)

            elif option == "interval":
                new_interval = int(value)
                self.cursor.execute(
                    "UPDATE auctions SET interval = ? WHERE auction_id = ?",
                    (new_interval, auction_id))
                embed.description = re.sub(r"\*\*Interval:\*\* [\d,]+",
                                           f"**Interval:** {new_interval:,}",
                                           embed.description)

            elif option == "buyout":
                new_buyout = int(value)
                self.cursor.execute(
                    "UPDATE auctions SET buyout_price = ? WHERE auction_id = ?",
                    (new_buyout, auction_id))
                embed.description = re.sub(r"\*\*Buyout:\*\* [\d,]+",
                                           f"**Buyout:** {new_buyout:,}",
                                           embed.description)

            # Apply edit
            await message.edit(embed=embed)
            self.db.commit()
            await ctx.send(
                f"✅ Auction `{auction_id}` updated: `{option}` set to `{value}`."
            )

        except Exception as e:
            await ctx.send(f"❌ Failed to update: {type(e).__name__} - {e}")

    @edit_auction.error
    async def edit_auction_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"🕒 This command is on cooldown. Try again in `{error.retry_after:.1f}` seconds.",
                ephemeral=True if hasattr(ctx, 'interaction') else False)
        else:
            raise error

    @commands.Cog.listener()
    async def on_ready(self):
        self.check_auctions.start()
        await self.bot.tree.sync()

    async def cog_check(self, ctx):
        allowed_guilds = {
            998128574898896906, 1188747974378008626, 1307241112716709898
        }

        if ctx.guild is None:
            await ctx.send("❌ This command can only be used in a server.")
            return False

        if ctx.guild.id not in allowed_guilds:
            await ctx.send(
                "🚫 This server is not authorized to use this command.")
            return False

        return True


class AuctionListView(View):

    def __init__(self, ctx, pages):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.pages = pages
        self.current_page = 0
        # self.update_buttons()

    # def update_buttons(self):
    #     self.clear_items()
    #     if self.current_page > 0:
    #         self.add_item(
    #             Button(label="◀",
    #                    style=ButtonStyle.secondary,
    #                    custom_id="prev"))
    #     if self.current_page < len(self.pages) - 1:
    #         self.add_item(
    #             Button(label="▶",
    #                    style=ButtonStyle.secondary,
    #                    custom_id="next"))

    async def interaction_check(self, interaction: Interaction) -> bool:
        return interaction.user == self.ctx.author

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self)

    async def send_page(self, interaction: Interaction = None):
        embed = self.pages[self.current_page]
        embed.set_footer(
            text=f"Page {self.current_page + 1} of {len(self.pages)}")

        # Update button states
        self.prev_page.disabled = self.current_page == 0
        self.next_page.disabled = self.current_page == len(self.pages) - 1

        if interaction:
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            self.message = await self.ctx.send(embed=embed, view=self)

    @discord.ui.button(label="◀", style=ButtonStyle.secondary)
    async def prev_page(self, interaction: Interaction, button: Button):
        self.current_page -= 1
        # self.update_buttons()
        await self.send_page(interaction)

    @discord.ui.button(label="▶", style=ButtonStyle.secondary)
    async def next_page(self, interaction: Interaction, button: Button):
        self.current_page += 1
        # self.update_buttons()
        await self.send_page(interaction)


async def setup(bot):
    await bot.add_cog(AuctionBot(bot))
    await bot.tree.sync()

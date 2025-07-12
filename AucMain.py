import sqlite3
import discord
from discord.ext import commands

# import os
# from discord import app_commands


# DB initialization function
def initialize_database():
    # Connect to SQLite database (or create it if it doesn't exist)
    conn = sqlite3.connect('auction_bot.db')
    cursor = conn.cursor()

    # Drop tables if they exist
    cursor.execute('DROP TABLE IF EXISTS auctions')
    cursor.execute('DROP TABLE IF EXISTS bids')
    cursor.execute('DROP TABLE IF EXISTS pokemon_embeds')
    cursor.execute('DROP TABLE IF EXISTS auctioned_pokemon')
    cursor.execute('DROP TABLE IF EXISTS outbid_notifications')
    conn.commit()

    # Create table for auctioneers
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS auctioneers (
        user_id TEXT PRIMARY KEY
    )
    ''')

    # Create table for auctions
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS auctions (
        auction_id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_id TEXT,
        message_id TEXT,
        item_embed_url TEXT,
        buyout_price INTEGER,
        end_time TEXT,
        auctioneer_id TEXT,
        min_bid INTEGER,
        interval INTEGER,
        current_bid INTEGER DEFAULT 0,
        winner_id TEXT,
        pokemon_name TEXT
    )
    ''')

    # Create table for bids
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS bids (
        bid_id INTEGER PRIMARY KEY AUTOINCREMENT,
        auction_id INTEGER,
        user_id TEXT,
        bid_amount INTEGER,
        timestamp TEXT,
        FOREIGN KEY (auction_id) REFERENCES auctions(auction_id)
    )
    ''')

    # Pokemon data
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS pokemon_embeds (
        auction_id INTEGER PRIMARY KEY,
        title TEXT,
        description TEXT,
        fields TEXT
    );
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS auctioned_pokemon (
        global_id TEXT PRIMARY KEY,
        last_auction_end TIMESTAMP
    );
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS outbid_notifs (
        user_id TEXT PRIMARY KEY
    )
    ''')

    # Variant tables

    cursor.execute(
        "CREATE TABLE IF NOT EXISTS gleams (name TEXT, release_month TEXT)")
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS radiants (name TEXT, release_month TEXT)")
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS alphas (name TEXT, release_month TEXT, move TEXT)"
    )

    conn.commit()
    conn.close()


# Bot setup
intents = discord.Intents.default()
intents.message_content = True  # Needed for reading messages
intents.members = True  # Needed for member info
intents.guilds = True

bot = commands.Bot(command_prefix=',', intents=intents, help_command=None)
bot.conn = sqlite3.connect('auction_bot.db', check_same_thread=False)


@bot.hybrid_command(name="reload", description="Reloads a cog.")
@commands.is_owner()
async def reload_cog(ctx, cog: str):
    try:
        bot.reload_extension(cog)
        await ctx.send(f"✅ Reloaded `{cog}` successfully.")
    except Exception as e:
        await ctx.send(f"❌ Failed to reload `{cog}`:\n```{e}```")


@bot.event
async def on_ready():
    print(f'Bot is ready. Logged in as {bot.user}')
    await bot.tree.sync()


# Load AuctionBot cog
@bot.event
async def setup_hook():
    from auction import AuctionBot  # Make sure this file exists
    await bot.add_cog(AuctionBot(bot))
    await bot.load_extension("profile")
    await bot.load_extension("help")
    await bot.load_extension("variants")
    await bot.tree.sync()


if __name__ == '__main__':
    initialize_database()

    TOKEN = (
        TOKEN
    )
    bot.run(TOKEN)

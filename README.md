# MewAucs
MewAucs is an Auction bot that was created for Mewbot (A pokemon based discord bot).
This code is for demonstration purposes only. Not intended for reuse without permission.

Elegant for managing Pokémon auctions with advanced features like bid tracking, automatic notifications, and auction management.

## Table of Contents
1. File Structure
2. Dependencies
3. Core Functions
4. Main Class: AuctionBot
5. Utility Classes
6. Database Schema
7. Setup & Usage

---

## File Structure
- **Line 1-16**: Imports all required Discord.py and utility libraries
- **Line 18-36**: `get_dominant_color_from_url()` - Extracts dominant color from image URLs for embed styling
- **Line 39-43**: `list_choices()` - Provides dropdown options for /list command
- **Line 46-66**: `poke_data()` & `get_pokemon_data()` - Handles Pokémon embed storage/retrieval from SQLite

---

## Dependencies
```python
# Core Requirements
import discord
from discord.ext import commands, tasks
from discord import app_commands

# Database
import sqlite3

# Utilities
from datetime import datetime, timedelta
import pytz  # Timezone handling
import re    # Regex parsing
import json  # Data serialization

# Image Processing
from PIL import Image
from io import BytesIO
import requests
from collections import Counter
```

---

## Core Functions

### `get_dominant_color_from_url()` (Line 18-36)
- **Purpose**: Extracts dominant color from a Pokémon image URL
- **Process**:
  1. Downloads image
  2. Resizes to 100x100px for performance
  3. Filters transparent pixels
  4. Returns most common RGB color
- **Fallback**: Returns Discord's blurple color if fails

### Auction Management Functions
- `poke_data()` (Line 46-56): Stores auction embeds in SQLite
- `get_pokemon_data()` (Line 59-66): Retrieves auction data from DB

---

## Main Class: AuctionBot

### Initialization (Line 69-74)
```python
def __init__(self, bot):
    self.bot = bot
    self.db = sqlite3.connect('auction_bot.db') 
    self.cursor = self.db.cursor()
    self.timezone = pytz.timezone('Asia/Kolkata')
```

### Key Methods

#### 1. Auctioneer Management
- `is_auctioneer()` (Line 76-79): Checks user permissions
- `toggle_auctioneer()` (Line 81-99): Owner-only command to add/remove auctioneers

#### 2. Auction Lifecycle
- `start_auction()` (Line 104-398): Main auction creation command
  - Parses Pokémon details from embeds
  - Creates dedicated channel
  - Sets up bidding rules
- `place_bid()` (Line 401-510): Handles bid placement and notifications
- `check_auctions()` (Line 659-735): Background task to close expired auctions
- `end_early()` (Line 738-813): Allows auctioneers to manually end auctions

#### 3. Utility Commands
- `list_auctions()` (Line 513-608): Shows active auctions/auctioneers
- `edit_auction()` (Line 816-914): Modifies ongoing auctions

---

## Utility Classes

### `AuctionListView` (Line 917-965)
- Paginated view for auction listings
- Features:
  - Previous/Next buttons
  - Auto-disable on timeout
  - User-specific interaction checks

---

## Database Schema
Tables managed by the bot:

### `auctioneers`
- `user_id`: Discord ID of authorized auctioneers

### `auctions`
- Stores all active auctions with:
  - Channel/message IDs
  - Bidding parameters (min/interval/buyout)
  - End timestamps
  - Current bids

### `bids`
- Tracks all bid history
- Used for outbid notifications

### `pokemon_embeds`
- Stores serialized embed data for logging

### `auctioned_pokemon`
- Prevents duplicate auctions via Global ID tracking

---

## Setup & Usage

### Installation
1. Install requirements:
```bash
pip install discord.py sqlite3 pytz pillow requests
```

2. Configure bot token in `.env`:
```ini
DISCORD_TOKEN=your_bot_token_here
```

### Key Commands
```
/auctioneer @user - Toggle auctioneer status (Owner only)
/auction [embed_url] [duration] [min_bid] [interval] - Start new auction
/bid [auction_id] [amount] - Place a bid
/list auctions - View active auctions
/edit [auction_id] [option] [value] - Modify auction parameters
/endearly [auction_id] - End auction prematurely
```

### Permissions
- Requires `Manage Channels` and `Embed Links` permissions
- Restricted to specified guilds (Line 967-978)

---

## Error Handling
Comprehensive error checking for:
- Invalid embed URLs
- Permission issues
- Bid validation
- Cooldowns (Line 915-916, 399-400)

---

## Extension Points
1. Add more Pokémon variant support
2. Enhance logging system
3. Integrate with economy bots
4. Add bulk auction tools

This bot provides a complete auction solution for Pokémon trading servers with robust features and data persistence.

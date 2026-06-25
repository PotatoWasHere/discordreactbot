import os
import sqlite3
import discord
from discord.ext import commands
from discord.ui import Button, View
import asyncio
from datetime import datetime, time, timedelta
import pytz

# --- CONFIGURATION ---
TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_ID = 1518663045415702645  

bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())
timezone = pytz.timezone('Europe/Istanbul')  # GMT+3 (Turkey Time)

# --- DATABASE SETUP ---
DB_FILE = "napoli_activity.db"

def init_db():
    """Initializes the database and creates the leaderboard table if it doesn't exist."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS leaderboard (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            points INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

def add_point(user_id, username):
    """Adds 1 point to a user's activity score."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Insert user or update points if they already exist
    cursor.execute('''
        INSERT INTO leaderboard (user_id, username, points)
        VALUES (?, ?, 1)
        ON CONFLICT(user_id) DO UPDATE SET 
            points = points + 1,
            username = ?
    ''', (user_id, username, username))
    conn.commit()
    conn.close()

# Initialize database right away
init_db()

# Temporary runtime storage for the current running 2-hour check window
current_active_mentions = []
current_active_names = set()
current_unavailable_names = set()

class ActivityCheckView(View):
    def __init__(self, timeout=7200):
        super().__init__(timeout=timeout)

    @discord.ui.button(label="ONLINE / AVAILABLE", style=discord.ButtonStyle.success, emoji="✅", custom_id="ac_ready")
    async def ready_button(self, interaction: discord.Interaction, button: Button):
        user_id = interaction.user.id
        display_name = interaction.user.display_name
        
        # Avoid duplicate scoring if they click multiple times in the same check
        if user_id not in current_active_mentions:
            current_active_mentions.append(user_id)
            current_active_names.add(display_name)
            current_unavailable_names.discard(display_name)
            
            # Award 1 point to the database leaderboard!
            add_point(user_id, display_name)
            
            await interaction.response.send_message(f"✨ **{display_name}**, thank you! Your status has been logged and +1 activity point awarded.", ephemeral=True)
        else:
            await interaction.response.send_message(f"⚠️ **{display_name}**, you have already checked into this window!", ephemeral=True)

    @discord.ui.button(label="UNAVAILABLE", style=discord.ButtonStyle.secondary, emoji="💤", custom_id="ac_away")
    async def away_button(self, interaction: discord.Interaction, button: Button):
        display_name = interaction.user.display_name
        user_id = interaction.user.id
        
        # If they switch from active to unavailable, adjust active tracking
        if user_id in current_active_mentions:
            current_active_mentions.remove(user_id)
            # Note: For simplicity, points already written during this window remain intact.
            
        current_unavailable_names.add(display_name)
        current_active_names.discard(display_name)
        await interaction.response.send_message(f"👍 **{display_name}**, logged as unavailable right now.", ephemeral=True)

async def send_activity_check():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print("Error: Activity channel not found. Check your CHANNEL_ID configuration.")
        return

    # Clear lists for this fresh check round
    current_active_mentions.clear()
    current_active_names.clear()
    current_unavailable_names.clear()

    embed = discord.Embed(
        title="┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n🔵 ┃ 𝐍𝐀𝐏𝐎𝐋𝐈 𝐅.𝐂. — 𝐑𝐎𝐒𝐓𝐄𝐑 𝐂𝐇𝐄𝐂𝐊\n┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
        description=(
            "Hello team! Management is running a routine server activity check.\n"
            "Please let us know your current availability status using the buttons below."
        ),
        color=discord.Color.blue()
    )
    embed.add_field(name="📋 Options", value="Click **ONLINE / AVAILABLE** if you are around.\nClick **UNAVAILABLE** if you are busy or away from discord.", inline=False)
    embed.set_footer(text="Napoli F.C. Administration • Automated System", icon_url=bot.user.avatar.url if bot.user.avatar else None)
    
    view = ActivityCheckView()
    msg = await channel.send(content="📢 @everyone **ROSTER ACTIVITY CHECK**", embed=embed, view=view)
    
    # Let players click buttons for a 2-hour window
    await asyncio.sleep(7200) 
    
    # Lock down buttons once time limits expire
    for item in view.children:
        item.disabled = True
    await msg.edit(view=view)

    # Post Results Summary Report with player names displayed!
    report_embed = discord.Embed(title="📊 PRESENCE CHECK OVERVIEW", color=discord.Color.blue())
    report_embed.add_field(name="✅ Logged Available", value=", ".join(current_active_names) if current_active_names else "None", inline=False)
    report_embed.add_field(name="💤 Logged Unavailable", value=", ".join(current_unavailable_names) if current_unavailable_names else "None", inline=False)
    await channel.send(embed=report_embed)

async def ac_scheduler():
    await bot.wait_until_ready()
    print("Napoli AC Engine Operational with leaderboard updates.")

    target_hours = [9, 12, 15, 18, 21, 0]

    while not bot.is_closed():
        now = datetime.now(timezone)
        next_run = None
        for hr in target_hours:
            if hr == 0:
                candidate = datetime.combine(now.date() + timedelta(days=1), time(0, 0))
            else:
                candidate = datetime.combine(now.date(), time(hr, 0))
            
            candidate = timezone.localize(candidate)
            if candidate > now:
                next_run = candidate
                break
        
        if not next_run:
            next_run = datetime.combine(now.date() + timedelta(days=1), time(9, 0))
            next_run = timezone.localize(next_run)

        print(f"Next activity check scheduled for: {next_run.strftime('%Y-%m-%d %H:%M:%S')} GMT+3")
        
        while datetime.now(timezone) < next_run:
            await asyncio.sleep(30)
            
        print(f"[{datetime.now(timezone).strftime('%H:%M:%S')}] Firing scheduled check!")
        await send_activity_check()

# --- NEW LEADERBOARD COMMAND ---
@bot.command(name="leaderboard")
async def leaderboard(ctx):
    """Displays the Top 10 most active players in the server."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Fetch the top 10 users sorted by highest score
    cursor.execute("SELECT username, points FROM leaderboard ORDER BY points DESC LIMIT 10")
    rows = cursor.fetchall()
    conn.close()

    embed = discord.Embed(
        title="🏆 NAPOLI F.C. ACTIVITY LEADERBOARD",
        description="The most reliable members of the team based on routine activity checks!",
        color=discord.Color.gold()
    )

    if not rows:
        embed.description = "No activity logs recorded yet. Run a roster check to build data!"
    else:
        leaderboard_text = ""
        medals = ["🥇", "🥈", "🥉"]
        
        for index, row in enumerate(rows):
            username, points = row
            # Style top 3 with special gold, silver, and bronze emoji decorations
            prefix = medals[index] if index < 3 else f"**#{index + 1}**"
            leaderboard_text += f"{prefix} `{username}` — **{points}** check-ins\n"
            
        embed.add_field(name="Top Active Members", value=leaderboard_text, inline=False)
        
    embed.set_footer(text="Napoli F.C. Management • Live Standings")
    await ctx.send(embed=embed)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} | Custom Napoli AC Engine Ready.')
    bot.loop.create_task(ac_scheduler())

bot.run(TOKEN)

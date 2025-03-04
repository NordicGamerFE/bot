import discord
import requests
import asyncio
import sqlite3
from sqlalchemy import create_engine, Column, Integer, String, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker
from discord.ext import commands
from discord import app_commands
from discord.ext.commands import CooldownMapping, BucketType
cooldown = CooldownMapping.from_cooldown(1, 2, BucketType.user)
# Initialize the bot with a command prefix (not used for slash commands)
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message(
            "❌ You don't have permission to use this command. You need the **Manage Channels** permission.",
            ephemeral=True
        )
    elif isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(
            f"⏳ This command is on cooldown. Try again in **{error.retry_after:.1f} seconds**.",
            ephemeral=True
        )
    else:
        print(f"An error occurred: {error}")
        await interaction.response.send_message(
            "❌ An unexpected error occurred. Please try again later.",
            ephemeral=True
        )

# SQLite database setup
DATABASE_FILE = "bsm_configs.db"

# Track alert states
alert_states = {}  # Format: {guild_id: {"server_alerts": {server_name: bool}, "map_alerts": {map_name: bool}}}

# Function to initialize the database
def init_db():
    conn = sqlite3.connect(DATABASE_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS configs
                 (alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  guild_id TEXT,
                  alert_name TEXT,
                  alert_map TEXT,
                  min_players INTEGER,
                  channel_id TEXT,
                  ping_role_id TEXT,
                  below_warning_enabled INTEGER DEFAULT 0)''')  # 0 = disabled, 1 = enabled
    conn.commit()
    conn.close()

DATABASE_URL = "sqlite:///bsm_configs.db"
engine = create_engine(DATABASE_URL)
Base = declarative_base()

class Config(Base):
    __tablename__ = 'configs'
    alert_id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(String)
    alert_name = Column(String)
    alert_map = Column(String)
    min_players = Column(Integer)
    channel_id = Column(String)
    ping_role_id = Column(String)
    below_warning_enabled = Column(Boolean)

Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()

def save_config(guild_id, alert_name, alert_map, min_players, channel_id, ping_role_id=None, below_warning_enabled=False):
    config = Config(
        guild_id=guild_id,
        alert_name=alert_name,
        alert_map=alert_map,
        min_players=min_players,
        channel_id=channel_id,
        ping_role_id=ping_role_id,
        below_warning_enabled=below_warning_enabled
    )
    session.add(config)
    session.commit()

def load_configs(guild_id):
    conn = sqlite3.connect(DATABASE_FILE)
    c = conn.cursor()
    c.execute('''SELECT alert_id, alert_name, alert_map, min_players, channel_id, ping_role_id, below_warning_enabled 
                 FROM configs 
                 WHERE guild_id = ?''', (guild_id,))
    results = c.fetchall()
    conn.close()
    configs = []
    for result in results:
        config = {
            "alert_id": result[0],
            "alert_name": result[1],
            "alert_map": result[2],
            "min_players": result[3],
            "channel_id": int(result[4]) if result[4] else None,
            "ping_role_id": int(result[5]) if result[5] else None,
            "below_warning_enabled": bool(result[6])
        }
        configs.append(config)
        print(f"Loaded config: {config}")  # Debug logging
    return configs

# Function to update a configuration
def update_config(alert_id, alert_name=None, alert_map=None, min_players=None, channel_id=None, ping_role_id=None, below_warning_enabled=None):
    conn = sqlite3.connect(DATABASE_FILE)
    c = conn.cursor()
    updates = []
    params = []
    if alert_name is not None:
        updates.append("alert_name = ?")
        params.append(alert_name)
    if alert_map is not None:
        updates.append("alert_map = ?")
        params.append(alert_map)
    if min_players is not None:
        updates.append("min_players = ?")
        params.append(min_players)
    if channel_id is not None:
        updates.append("channel_id = ?")
        params.append(channel_id)
    if ping_role_id is not None:
        updates.append("ping_role_id = ?")
        params.append(ping_role_id)
    if below_warning_enabled is not None:
        updates.append("below_warning_enabled = ?")
        params.append(int(below_warning_enabled))
        params.append(alert_id)
        query = f"UPDATE configs SET {', '.join(updates)} WHERE alert_id = ?"
        c.execute(query, params)
        conn.commit()
        conn.close()

        # Function to delete a configuration
def delete_config(alert_id):
    conn = sqlite3.connect(DATABASE_FILE)
    c = conn.cursor()
    c.execute('''DELETE FROM configs WHERE alert_id = ?''', (alert_id,))
    conn.commit()
    conn.close()

# Initialize the database
init_db()

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    try:
        # Sync slash commands
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Error syncing commands: {e}")

    # Start the monitoring task
    bot.loop.create_task(monitor_api())

# Event when the bot joins a new server
@bot.event
async def on_guild_join(guild):
    # Find the first text channel where the bot can send messages
    welcome_channel = None
    for channel in guild.text_channels:
        if channel.permissions_for(guild.me).send_messages:
            welcome_channel = channel
            break

    if welcome_channel:
        # Send a welcome message
        await welcome_channel.send(
            f"🎉 **Thanks for adding me to {guild.name}!** 🎉\n\n"
            "I can monitor BattleBit servers and send alerts when specific conditions are met.\n\n"
            "**To get started, use the following commands:**\n"
            "`/BSM Setup` - Set up alerts for server name or map with a minimum player count.\n"
            "`/BSM ListAlerts` - List all configured alerts.\n"
            "`/BSM EditAlert` - Edit an existing alert.\n"
            "`/BSM DeleteAlert` - Delete an alert configuration.\n"
            "`/BSM ToggleBelowWarning` - Enable or disable alerts when player count drops below the threshold.\n"
            "`/BSM ListServers` - List all servers matching specific parameters.\n"
            "`/BSM Help` - Get help and instructions for using the bot.\n\n"
            "**Example:**\n"
            "`/BSM Setup alert_name: Elite Soldiers min_players: 50 channel: #alerts ping_role: @Role`\n"
            "`/BSM Setup alert_map: Wakistan min_players: 100 channel: #alerts ping_role: @Role`\n\n"
            "You can also combine both server name and map alerts in one command!\n\n"
        )

# Create a command group for BSM
bsm_group = app_commands.Group(name="bsm", description="BattleBit Server Monitor commands")

# Add the Setup command under the BSM group
@bsm_group.command(name="setup", description="Set up alerts for server name or map with a minimum player count.")
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.describe(
    alert_name="The server name to monitor (leave blank if not needed).",
    alert_map="The map to monitor (leave blank if not needed).",
    min_players="The minimum number of players to trigger an alert.",
    channel="The channel where alerts will be sent (required).",
    ping_role="The role to ping when an alert is triggered (leave blank if not needed)."
)
async def setup(interaction: discord.Interaction, channel: discord.TextChannel, alert_name: str = None, alert_map: str = None, min_players: int = None, ping_role: discord.Role = None):
    # Save the user's configuration for this server
    save_config(str(interaction.guild.id), alert_name, alert_map, min_players, str(channel.id), str(ping_role.id) if ping_role else None)

    # Confirm the setup
    await interaction.response.send_message(
        f"Setup complete! Monitoring for:\n"
        f"Server Name: {alert_name if alert_name else 'Not set'}\n"
        f"Map: {alert_map if alert_map else 'Not set'}\n"
        f"Minimum Players: {min_players}\n"
        f"Notifications will be sent to: {channel.mention}\n"
        f"Ping Role: {ping_role.mention if ping_role else 'Not set'}", ephemeral=True
    )

@bsm_group.command(name="listalerts", description="List all configured alerts.")
@app_commands.checks.has_permissions(manage_channels=True)
async def list_alerts(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)
    print(f"Fetching alerts for guild ID: {guild_id}")  # Debug logging
    configs = load_configs(guild_id)
    print(f"Loaded configs: {configs}")  # Debug logging

    if not configs:
        await interaction.response.send_message("No alerts are currently configured.", ephemeral=True)
        return

    # Build the alert list message
    alert_message = "**Configured Alerts:**\n"
    for config in configs:
        alert_message += (
                             f"**Alert ID:** {config['alert_id']}\n"
                             f"Server Name: {config['alert_name'] if config['alert_name'] is not None else 'Not set'}\n"
                             f"Map: {config['alert_map'] if config['alert_map'] is not None else 'Not set'}\n"
                             f"Minimum Players: {config['min_players'] if config['min_players'] is not None else 'Not set'}\n"
                             f"Channel: <#{config['channel_id']}>" if config['channel_id'] is not None else "Channel: Not set\n"
                                                                                                            f"Ping Role: <@&{config['ping_role_id']}>" if config['ping_role_id'] is not None else "Ping Role: Not set\n"
                         ) + "\n\n"

    await interaction.response.send_message(alert_message, ephemeral=True)

# Add the EditAlert command under the BSM group
@bsm_group.command(name="editalert", description="Edit an existing alert.")
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.describe(
    alert_id="The ID of the alert to edit.",
    alert_name="The new server name to monitor (leave blank to keep current).",
    alert_map="The new map to monitor (leave blank to keep current).",
    min_players="The new minimum number of players to trigger an alert (leave blank to keep current).",
    channel="The new channel where alerts will be sent (leave blank to keep current).",
    ping_role="The new role to ping when an alert is triggered (leave blank to keep current)."
)
async def edit_alert(interaction: discord.Interaction, alert_id: int, alert_name: str = None, alert_map: str = None, min_players: int = None, channel: discord.TextChannel = None, ping_role: discord.Role = None):
    # Update the configuration
    update_config(alert_id, alert_name, alert_map, min_players, str(channel.id) if channel else None, str(ping_role.id) if ping_role else None)

    # Confirm the update
    await interaction.response.send_message(f"Alert **{alert_id}** has been updated.", ephemeral=True)

# Add the DeleteAlert command under the BSM group
@bsm_group.command(name="deletealert", description="Delete an alert configuration.")
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.describe(
    alert_id="The ID of the alert to delete."
)
async def delete_alert(interaction: discord.Interaction, alert_id: int):
    # Delete the configuration
    delete_config(alert_id)

    # Confirm the deletion
    await interaction.response.send_message(f"Alert **{alert_id}** has been deleted.", ephemeral=True)

# Add the ToggleBelowWarning command under the BSM group
@bsm_group.command(name="togglebelowwarning", description="Enable or disable alerts when player count drops below the threshold.")
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.describe(
    alert_id="The ID of the alert to toggle."
)
async def toggle_below_warning(interaction: discord.Interaction, alert_id: int):
    # Load the current configuration
    conn = sqlite3.connect(DATABASE_FILE)
    c = conn.cursor()
    c.execute('''SELECT below_warning_enabled FROM configs WHERE alert_id = ?''', (alert_id,))
    result = c.fetchone()
    conn.close()
    if not result:
        await interaction.response.send_message(f"Alert **{alert_id}** not found.", ephemeral=True)
        return

    # Toggle the below warning setting
    new_setting = not bool(result[0])
    update_config(alert_id, below_warning_enabled=new_setting)

    # Confirm the toggle
    await interaction.response.send_message(
        f"Below threshold warnings for alert **{alert_id}** are now **{'enabled' if new_setting else 'disabled'}**.", ephemeral=True
    )

# Add the ListServers command under the BSM group
@bsm_group.command(name="listservers", description="List all servers matching specific parameters.")
@app_commands.describe(
    players_required="The minimum number of players.",
    name="The server name to filter by (leave blank to ignore).",
    map="The map to filter by (leave blank to ignore).",
    region="The region to filter by (leave blank to ignore).",
    gamemode="The gamemode to filter by (leave blank to ignore)."
)
async def list_servers(interaction: discord.Interaction, players_required: int, name: str = None, map: str = None, region: str = None, gamemode: str = None):
    # Fetch data from the API
    response = requests.get("https://publicapi.battlebit.cloud/Servers/GetServerList")
    servers = response.json()

    # Filter servers based on the provided parameters
    filtered_servers = []
    for server in servers:
        if (server["Players"] >= players_required and
                (name is None or name.lower() in server["Name"].lower()) and
                (map is None or map.lower() == server["Map"].lower()) and
                (region is None or region.lower() == server["Region"].lower()) and
                (gamemode is None or gamemode.lower() == server["Gamemode"].lower())):
            filtered_servers.append(server)

    # Build the server list message
    if not filtered_servers:
        await interaction.response.send_message("No servers match the specified criteria.", ephemeral=True)
        return

    server_message = "**Matching Servers:**\n"
    for server in filtered_servers:
        server_message += (
            f"**Server:** {server['Name']}\n"
            f"Map: {server['Map']}\n"
            f"Gamemode: {server['Gamemode']}\n"
            f"Region: {server['Region']}\n"
            f"Players: {server['Players']}/{server['MaxPlayers']}\n\n"
        )

    # Send the results as an ephemeral message
    await interaction.response.send_message(server_message, ephemeral=True)

# Add the Help command under the BSM group
@bsm_group.command(name="help", description="Get help and instructions for using the bot.")
async def help(interaction: discord.Interaction):
    await interaction.response.send_message(
        "**BattleBit Server Monitor Help**\n\n"
        "I can monitor BattleBit servers and send alerts when specific conditions are met.\n\n"
        "**Commands:**\n"
        "`/BSM Setup` - Set up alerts for server name or map with a minimum player count.\n"
        "`/BSM ListAlerts` - List all configured alerts.\n"
        "`/BSM EditAlert` - Edit an existing alert.\n"
        "`/BSM DeleteAlert` - Delete an alert configuration.\n"
        "`/BSM ToggleBelowWarning` - Enable or disable alerts when player count drops below the threshold.\n"
        "`/BSM ListServers` - List all servers matching specific parameters.\n"
        "`/BSM Help` - Get help and instructions for using the bot.\n\n"
        "**Example:**\n"
        "`/BSM Setup alert_name: Elite Soldiers min_players: 50 channel: #alerts ping_role: @Role`\n"
        "`/BSM Setup alert_map: Wakistan min_players: 100 channel: #alerts ping_role: @Role`\n\n"
        "You can also combine both server name and map alerts in one command!\n\n"
        "If you need help, feel free to ask!"
    )

# Add the BSM group to the bot's command tree
bot.tree.add_command(bsm_group)

# Function to create an embed for alerts
def create_alert_embed(title, description, color, fields):
    embed = discord.Embed(
        title=title,
        description=description,
        color=color
    )
    for name, value, inline in fields:
        embed.add_field(name=name, value=value, inline=inline)
    return embed

# Function to monitor the API
async def monitor_api():
    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            # Fetch data from the API
            response = requests.get("https://publicapi.battlebit.cloud/Servers/GetServerList")
            servers = response.json()

            # Load all configurations
            conn = sqlite3.connect(DATABASE_FILE)
            c = conn.cursor()
            c.execute('''SELECT alert_id, alert_name, alert_map, min_players, channel_id, ping_role_id, below_warning_enabled FROM configs''')
            configs = c.fetchall()
            conn.close()

            # Check each server in the API response
            for server in servers:
                # Iterate through all guild configurations
                for config in configs:
                    alert_id, alert_name, alert_map, min_players, channel_id, ping_role_id, below_warning_enabled = config
                    channel = bot.get_channel(int(channel_id))
                    if not channel:
                        continue

                    # Initialize alert states for this guild if not already done
                    if alert_id not in alert_states:
                        alert_states[alert_id] = {
                            "server_alerts": {},
                            "map_alerts": {}
                        }

                    # Check server name alerts
                    if alert_name and alert_name.lower() in server["Name"].lower():
                        if server["Players"] >= min_players:
                            if not alert_states[alert_id]["server_alerts"].get(server["Name"], False):
                                # Ping the role if specified
                                if ping_role_id:
                                    await channel.send(f"<@&{ping_role_id}>")

                                embed = create_alert_embed(
                                    title="🚨 **Server Alert** 🚨",
                                    description=f"**Server:** {server['Name']}",
                                    color=discord.Color.green(),
                                    fields=[
                                        ("Map", server["Map"], True),
                                        ("Gamemode", server["Gamemode"], True),
                                        ("Players", f"{server['Players']}/{server['MaxPlayers']}", True),
                                        ("Region", server["Region"], True)
                                    ]
                                )
                                await channel.send(embed=embed)
                                alert_states[alert_id]["server_alerts"][server["Name"]] = True
                        elif below_warning_enabled:
                            if alert_states[alert_id]["server_alerts"].get(server["Name"], False):
                                # Ping the role if specified
                                if ping_role_id:
                                    await channel.send(f"<@&{ping_role_id}>")

                                embed = create_alert_embed(
                                    title="🔴 **Server Alert** 🔴",
                                    description=f"**Server:** {server['Name']} is now below the minimum player count.",
                                    color=discord.Color.red(),
                                    fields=[
                                        ("Players", f"{server['Players']}/{server['MaxPlayers']}", False)
                                    ]
                                )
                                await channel.send(embed=embed)
                                alert_states[alert_id]["server_alerts"][server["Name"]] = False

                    # Check map alerts
                    if alert_map and alert_map.lower() == server["Map"].lower():
                        if server["Players"] >= min_players:
                            if not alert_states[alert_id]["map_alerts"].get(server["Map"], False):
                                # Ping the role if specified
                                if ping_role_id:
                                    await channel.send(f"<@&{ping_role_id}>")

                                embed = create_alert_embed(
                                    title="🚨 **Map Alert** 🚨",
                                    description=f"**Map:** {server['Map']}",
                                    color=discord.Color.green(),
                                    fields=[
                                        ("Server", f"{server['Name']}", True),
                                        ("Gamemode", server["Gamemode"], True),
                                        ("Players", f"{server['Players']}/{server['MaxPlayers']}", True),
                                        ("Region", server["Region"], True)
                                    ]
                                )
                                await channel.send(embed=embed)
                                alert_states[alert_id]["map_alerts"][server["Map"]] = True
                        elif below_warning_enabled:
                            if alert_states[alert_id]["map_alerts"].get(server["Map"], False):
                                # Ping the role if specified
                                if ping_role_id:
                                    await channel.send(f"<@&{ping_role_id}>")

                                embed = create_alert_embed(
                                    title="🔴 **Map Alert** 🔴",
                                    description=f"**Map:** {server['Map']} is now below the minimum player count.",
                                    color=discord.Color.red(),
                                    fields=[
                                        ("Server", f"{server['Name']}", False),
                                        ("Players", f"{server['Players']}/{server['MaxPlayers']}", False)
                                    ]
                                )
                                await channel.send(embed=embed)
                                alert_states[alert_id]["map_alerts"][server["Map"]] = False

        except Exception as e:
            print(f"Error fetching data: {e}")

        # Wait for a while before checking again
        await asyncio.sleep(60)  # Check every 60 seconds

# Run the bot with your token
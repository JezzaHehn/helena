import discord
import logging
import os
import pendulum
import yaml
from dataclasses import dataclass
from discord.ext import commands, tasks
from dotenv import load_dotenv
from enum import Enum
from typing import List

# ================================
# Helena the Discord Bot Overview
# ================================
# This bot implements a "Dead Man's Switch" feature for a Discord server.
# It performs regular check-ins to make sure everything is operational and allows users to
# schedule recurring reminders (events) throughout the week. The bot functionality includes:
# - Regular hourly check-ins to designated channels.
# - Weekly events triggered based on a schedule loaded from a YAML file.
# - Commands to add, remove, and list Safety Switch events.
# - A "reset" command to reset the Safety Switch timer manually.
# Events are saved in a YAML file called `weekly_events.yaml`, allowing them to persist between bot restarts.
# ================================

# ================================
# Expected YAML File Schema (weekly_events.yaml)
# ================================
# The YAML file should contain a list of events, each with the following keys:
# - time_of_day: str ("HH:MM", 24-hour format)
# - day_of_week: str ("Monday", "Tuesday", etc.)
# Example:
# - time_of_day: "14:00"
#   day_of_week: "Monday"
# - time_of_day: "10:00"
#   day_of_week: "Friday"
# ================================

# Load environment variables from .env file and load the bot token
load_dotenv()
BOT_TOKEN: str = os.getenv('BOT_TOKEN')
JEZ_PERSONAL_USER_ID: str = os.getenv('JEZ_PERSONAL_USER_ID')
JEZ_WIKITRIBUNE_USER_ID: str = os.getenv('JEZ_WIKITRIBUNE_USER_ID')
FIN_USER_ID: str = os.getenv('FIN_USER_ID')

# Check if BOT_TOKEN is set correctly because otherwise the robot will be a nobot
if BOT_TOKEN is None:
    raise ValueError("BOT_TOKEN must be set in the environment variables.")

# Make a list of user IDs for DMing people in the event of an alarm
DM_IDs = [JEZ_PERSONAL_USER_ID, JEZ_WIKITRIBUNE_USER_ID, FIN_USER_ID]

# Setup logging for better diagnostics
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Enum for different channel IDs
class Channel(Enum):
    ALERTS = 1309372351191973930
    CHECK_IN = 1309372627021725697
    STATUS = 1309372804092657674

# Dataclass to store information about a weekly Switch event
@dataclass
class WeeklySwitchEvent:
    time_of_day: str  # Expected format: HH:MM (24-hour format)
    day_of_week: str  # Expected format: Monday, Tuesday, etc.
    armed = True
    triggered_this_week = False

class SafetySwitchBot(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Load weekly events from a YAML file
        self.weekly_events: List[WeeklySwitchEvent] = self.load_events_from_yaml()
        self.last_disarm_time = None  # Track when the switch was last disarmed

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("Bot is ready.")
        if not self.status_update_loop.is_running():
            self.status_update_loop.start()
        if not self.alert_loop.is_running():
            self.alert_loop.start()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore messages sent by the bot itself
        if message.author == self.bot.user:
            return

        # Check if the message is in the CHECK_IN channel
        if message.channel.id == Channel.CHECK_IN.value:
            now = pendulum.now("UTC")
            # Check if the message is within 30 minutes before the scheduled event
            for event in self.weekly_events:
                event_time = pendulum.parse(event.time_of_day, tz="UTC")
                event_datetime = event_time.set(day=now.day, month=now.month, year=now.year)
                if event.day_of_week == now.format("dddd") and (event_datetime - now).total_minutes() <= 30:
                    self.last_disarm_time = now
                    await message.channel.send("Safety Switch has been disarmed. Thank you!")
                    break

    def load_events_from_yaml(self) -> List[WeeklySwitchEvent]:
        try:
            with open("weekly_events.yaml", "r") as file:
                events_data = yaml.safe_load(file)
                events = [WeeklySwitchEvent(**event) for event in events_data]
                logger.info("Weekly events loaded from YAML file.")
                return events
        except FileNotFoundError:
            logger.warning("weekly_events.yaml file not found. Starting with no events.")
            return []
        except Exception as e:
            logger.error(f"Error loading events from YAML: {e}")
            return []

    def save_events_to_yaml(self) -> None:
        try:
            with open("weekly_events.yaml", "w") as file:
                yaml.dump([event.__dict__ for event in self.weekly_events], file)
                logger.info("Weekly events saved to YAML file.")
        except Exception as e:
            logger.error(f"Error saving events to YAML: {e}")

    @tasks.loop(seconds=3600)  # SAFETY_INTERVAL = 3600 seconds (1 hour)
    async def status_update_loop(self) -> None:
        try:
            channel = self.bot.get_channel(Channel.STATUS.value)
            if channel:
                await channel.send("Safety Switch status update: All is well. Sending a friendly ping from the digital ocean.")
            else:
                logger.error("Channel not found!")
        except Exception as e:
            logger.error(f"Error during check-in: {e}")

    @tasks.loop(minutes=1)
    async def alert_loop(self) -> None:
        now = pendulum.now("UTC").start_of('minute')  # Get the current time in UTC
        current_time = now.time()  # Extract the current time
        current_day = now.format("dddd")  # Extract the current day of the week
        
        for event in self.weekly_events:
            event_time = pendulum.parse(event.time_of_day, tz="UTC").time()  # Parse the event time

            # Check if it's time to trigger the event, if it's armed, and if it wasn't triggered yet this week
            if (current_day == event.day_of_week 
                and current_time == event_time 
                and not event.triggered_this_week):

                if self.last_disarm_time is None or (now - self.last_disarm_time).total_minutes() > 60:
                    try:
                        channel = self.bot.get_channel(Channel.ALERTS.value)
                        if channel:
                            alert_message = (
                                f"Hey! It's {current_day} at {current_time} UTC "
                                f"and the {event.time_of_day} Safety Switch was not disarmed!"
                            )
                            await channel.send(alert_message)
                            # Send a DM to the specified users
                            for id in DM_IDs:
                                user = await self.bot.fetch_user(id)
                                if user:
                                    await user.send(alert_message)

                            # After sending alerts, mark the event as triggered for the week
                            event.triggered_this_week = True
                            logger.info(f"Event {event.day_of_week} at {event.time_of_day} has been triggered and disarmed for this week.")

                        else:
                            logger.error("Channel not found!")
                    except Exception as e:
                        logger.error(f"Error during weekly check-in: {e}")

    @commands.command(name='reset')
    async def reset_switch(self, ctx: commands.Context) -> None:
        await ctx.send("Safety Switch timer has been reset. All is good here!")
        if self.status_update_loop.is_running(): # Start or restart the status update message loop
            self.status_update_loop.restart()
        else:
            self.status_update_loop.start()
        if self.alert_loop.is_running(): # Start or restart the alert loop
            self.alert_loop.restart()
        else:
            self.alert_loop.start()
        self.last_disarm_time = pendulum.now("UTC")

    @commands.command(name='status')
    async def status(self, ctx: commands.Context) -> None:
        await ctx.send("Safety Switch is currently active. All systems are nominal.")

    @commands.command(name='add_event')
    async def add_event(self, ctx: commands.Context, day_of_week: str, time_of_day: str) -> None:
        new_event = WeeklySwitchEvent(time_of_day, day_of_week)
        self.weekly_events.append(new_event)  # Add the new event to the list
        self.save_events_to_yaml()  # Save the updated list to YAML
        await ctx.send(f"New Safety Switch event added for {day_of_week} at {time_of_day} UTC.")

    @commands.command(name='remove_event')
    async def remove_event(self, ctx: commands.Context, day_of_week: str, time_of_day: str) -> None:
        before_count = len(self.weekly_events)
        # Remove any events matching the specified day and time
        self.weekly_events = [event for event in self.weekly_events if not (event.day_of_week == day_of_week and event.time_of_day == time_of_day)]
        after_count = len(self.weekly_events)
        if before_count == after_count:
            await ctx.send(f"No event found for {day_of_week} at {time_of_day} UTC to remove.")
        else:
            self.save_events_to_yaml()  # Save the updated list to YAML
            await ctx.send(f"Event for {day_of_week} at {time_of_day} UTC has been removed.")

    @commands.command(name='list_events')
    async def list_events(self, ctx: commands.Context) -> None:
        if not self.weekly_events:
            await ctx.send("No Safety Switch events are currently scheduled.")
        else:
            # Format the list of events to be sent as a message
            event_list = "\n".join([f"{event.day_of_week} at {event.time_of_day} UTC" for event in self.weekly_events])
            await ctx.send(f"Scheduled Safety Switch events:\n{event_list}")

# Initialize the bot and add the cog
intents: discord.Intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True
bot: commands.Bot = commands.Bot(command_prefix="!", intents=intents)

# Start the bot
if __name__ == "__main__":
    try:
        import asyncio
        async def main():
            await bot.add_cog(SafetySwitchBot(bot))
            await bot.start(BOT_TOKEN)
        
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Error starting bot: {e}")

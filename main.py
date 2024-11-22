import discord
import asyncio
import os
from dotenv import load_dotenv

# Load environment variables from .env file and load the bot token and channel info
load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHANNEL_ID = int(os.getenv('CHANNEL_ID'))
print("Bot token loaded:", BOT_TOKEN)
print(f"{CHANNEL_ID = }")

async def send_message():
    # Initialize the bot client
    intents = discord.Intents.default()
    intents.messages = True
    intents.guilds = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        try:
            print(f"Logged in as {client.user}")
            channel = client.get_channel(CHANNEL_ID)
            if channel:
                await channel.send("Dead Man's Switch activated. All is well. Sending a wave from the digital ocean.")
            else:
                print("Channel not found!")
        finally:
            await client.close()

    try:
        await client.start(BOT_TOKEN)
    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Clean up aiohttp connector explicitly to avoid ugly terminal error on exit
        await client.http._HTTPClient__session.close()


if __name__ == "__main__":
    asyncio.run(send_message())

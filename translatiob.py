import discord
from discord.ext import commands, tasks
import zmq
import msgpack
import requests
import asyncio
import json
import random
import logging

logging.basicConfig(
    level=logging.ERROR,
    format='[%(asctime)s][%(levelname)s][%(name)s]: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

TIMEOUT = 30000
class MyBot(commands.Bot):
    def __init__(self, webhook_url, top_layer_port,):
        intents = discord.Intents.default()
        intents.typing = True
        intents.messages = True
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix='!', intents=intents)  # Use '!' as command prefix
        self.temp = 2.8  # Default temperature
        self.webhook_url = webhook_url
        self.top_layer_port = top_layer_port
        
        # Initialize ZeroMQ context and socket
        self.top_layer_context = zmq.Context()
        self.top_layer_socket = self.top_layer_context.socket(zmq.REQ)
        self.top_layer_socket.setsockopt(zmq.RCVTIMEO, TIMEOUT)
        self.top_layer_socket.connect(f"tcp://127.0.0.1:{top_layer_port}")
        self.nick_cache = {}
        self._blocked = False
        self.top_layer = False

    async def on_ready(self):
        print(f'Logged in as {self.user}')
        self.heartbeat_task.start()
        self.clear_names.start()

    async def on_message(self, message):
        asyncio.create_task(self._on_message(message))

    async def _on_message(self, message):
        if not self.top_layer:
            return
        self._blocked = True
        if message.author == self.user or message.content is None or message.channel.id in []:
            return  # Ignore messages from the bot itself or if the message is None
        
        # Process commands before handling other messages
        await self.process_commands(message)

        # Send the message text via ZMQ
        logger.info(message.content)
        if not message.content:
            return
        response = self.zmqSend(message.content)
        author = message.author.name
        logger.info(self.nick_cache)
        try:
            if message.author.nick not in self.nick_cache:
                author = self.zmqSend(message.author.nick)
                if not author:
                    author = message.author.nick
                self.nick_cache[message.author.nick] = author
            else:
                author = self.nick_cache[message.author.nick]
        except:
            if message.author.name not in self.nick_cache:
                author = self.zmqSend(message.author.name)
                if not author:
                    author = message.author.name
                self.nick_cache[message.author.name] = author
            else:
                author = self.nick_cache[message.author.name]
        # Forward the response via webhook
        await self.send_webhook(response, author, message)
        self._blocked = False

    def zmqSend(self, text: str):
        message = {
            "type": "gen",
            "text": text,
            "model": "T5-mihm-gc",
            "config": {
                "temperature": self.temp,
                'max_new_tokens': 500,
                'num_beams': 2,
                'no_repeat_ngram_size': 2,
                'repetition_penalty': 1.01,
            },
            "from" : "translatiob"
        }
        logger.info(f"SENDING {message}")
        try:
            response = self.pack_and_send(message)
            logger.info(response)
            return response
        except Exception as e:
            logger.error(e)
            logger.error("======ZMQSEND TIMEOUTKA OR SOMTHINGS======")
            self.top_layer_socket.close()
            self.top_layer_socket = self.top_layer_context.socket(zmq.REQ)
            self.top_layer_socket.setsockopt(zmq.RCVTIMEO, TIMEOUT)
            self.top_layer_socket.connect(f"tcp://127.0.0.1:{self.top_layer_port}")

    async def send_webhook(self, response, author, message):
        webhook_data = {
            "content": response,  # Assuming the response has a "text" field
            "username": author[:80],
            "avatar_url": str(message.author.avatar.url)  # Copy the author's profile picture
        }
        
        requests.post(self.webhook_url, json=webhook_data)

    def pack_and_send(self, data):
        packed_data = msgpack.packb(data)
        self.top_layer_socket.send(packed_data)
        packed_response = self.top_layer_socket.recv()
        response = msgpack.unpackb(packed_response)
        return response
    
    @tasks.loop(seconds=60*5)
    async def clear_names(self):
        if self._blocked:
            return
        if self.nick_cache:
            random_key = random.choice(list(self.nick_cache.keys()))
            del self.nick_cache[random_key]
            logger.info(f"Removed '{random_key}' from nick_cache.")
    
    @tasks.loop(seconds=60)
    async def heartbeat_task(self):
        try:
            message = {
                "text": "translatiob",
                "type": "ping"
            }
            self.top_layer_socket.setsockopt(zmq.RCVTIMEO, 100)
            response = self.pack_and_send(message)
            self.top_layer_socket.setsockopt(zmq.RCVTIMEO, TIMEOUT)
            self.top_layer = True
            logger.info(response)
        except zmq.Again:
            self.top_layer = False
            logger.error("ANTI EHART BEATTTTTTTTT''s")
            self.top_layer_socket.close()
            self.top_layer_socket = self.top_layer_context.socket(zmq.REQ)
            self.top_layer_socket.setsockopt(zmq.RCVTIMEO, TIMEOUT)
            self.top_layer_socket.connect(f"tcp://127.0.0.1:{self.top_layer_port}")

# Replace with your bot token, webhook URL, and top layer port
bot_token = ""
webhook_url = ''
TOP_LAYER_PORT = 5556  # Replace with your actual port

bot = MyBot(webhook_url=webhook_url, top_layer_port=TOP_LAYER_PORT)

@bot.command(name='temp')
async def set_temperature(ctx, temp):
    bot.temp = max(0.1,min(float(temp),3))
    await ctx.send(f'NEW HIS TEMP NEW!!!!! {bot.temp}')

bot.run(bot_token)





import discord
from discord.ext import commands, tasks
import zmq
import msgpack
import requests
import asyncio
import json
import random
import logging
import traceback
from config import *

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s][%(levelname)s][%(name)s]: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

class ZMQClient:
    def __init__(self, port, layer_name, heartbeat_interval=60, timeout=60):
        self.port = port
        self.layer_name = layer_name
        self.heartbeat_interval = heartbeat_interval
        self.timeout = timeout
        self.context = zmq.Context()
        self.socket = self.create_zmq_socket()
        self.is_available = True
        self.logger = logging.getLogger(self.__class__.__name__)
        
    async def start(self, loop):
        loop.create_task(self.heartbeat_task())

    def create_zmq_socket(self):
        socket = self.context.socket(zmq.REQ)
        socket.setsockopt(zmq.RCVTIMEO, self.timeout)
        socket.connect(f"tcp://127.0.0.1:{self.port}")
        return socket

    def safe_send(self, message):
        try:
            self.is_available = True
            packed_data = msgpack.packb(message)
            self.socket.send(packed_data)
            response = self.socket.recv()
            return msgpack.unpackb(response)
        except zmq.Again as e:
            self.is_available = False
            self.logger.error(f"Timeout while waiting for a response: {e}")
            return None
        except zmq.ZMQError as e:
            self.is_available = False
            self.logger.error(f"ZMQ Error: {e}, attempting to reconnect...")
            self.reconnect_socket()
            return None
        except Exception as e:
            self.is_available = False
            self.logger.error(f"Error sending message: {e}")
            return None

    def reconnect_socket(self):
        self.logger.debug(f"Reconnecting {self.layer_name} socket")
        self.socket.close()
        self.socket = self.create_zmq_socket()

    async def heartbeat_task(self):
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            try:
                response = self.safe_send({"from": "hiran", "type": "ping"})
                if response:
                    self.is_available = True
                    self.logger.debug(f"Heartbeat response from {self.layer_name}: {response}")
                else:
                    self.is_available = False
                    self.logger.error(f"No response from {self.layer_name} during heartbeat")
            except Exception as e:
                self.is_available = False
                self.logger.error(traceback.format_exc())
                self.logger.error(f"Failed heartbeat for {self.layer_name}")
                self.reconnect_socket()

class Translatiob(commands.Bot):
    def __init__(self,top_layer_port):
        intents = discord.Intents.default()
        intents.typing = True
        intents.messages = True
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix='!', intents=intents)  # Use '!' as command prefix
        self.temp = 2.2  # Default temperature
        
        self.LLM = ZMQClient(port=top_layer_port, layer_name="LLM", timeout=TIMEOUT)
        self.nick_cache = {}
        self._blocked = False
        self.setups = self.load_setups()  # Load existing setups from JSON
        self.logger = logging.getLogger(self.__class__.__name__)
        self.cache = {}
        
    async def on_ready(self):
        self.logger.info(f'Logged in as {self.user}')
        await self.LLM.start(self.loop)
        self.clear_names.start()
        await self.tree.sync()

    def can_delete(self, message, key):
        if key in self.setups and self.setups[key].get("delete_messages", False) and not self.setups[key].get("disabled", False):
            if not message.webhook_id:
                self.logger.info("MNONE WEGBHOKKER")
                return 1
            else:              
                for k,v in self.setups.items():
                    if v['webhook_id'] == message.webhook_id:
                        return -1
                return 1
        return 0
    
    def get_author(self, message):
        author = message.author.name
        try:
            author_ = message.author.nick
            if author_ is not None:
                author = author_
            else:
                author = message.author.display_name
        except:
            self.logger.debug("XDDD NOTT NICK")
        return author
        
    def get_avatar(self, message):
        avatar = None
        try:
            avatar = message.author.avatar.url
        except:
            avatar = random.choice(["https://i.imgur.com/NGvttCc.gif", "https://i.imgur.com/SMJq55x.gif", "https://i.imgur.com/3pgztqw.gif", "https://i.imgur.com/WLoxslE.gif"])
        return avatar
    
    def translate_author(self, author, model):
        self.logger.debug(f"{author}, {self.nick_cache}")
        try:
            if author not in self.nick_cache:
                author_ = self.LLM.safe_send(bot.get_config(author, model))
                if author_:
                    self.nick_cache[author] = author_
                    author = author_
            else:
                author = self.nick_cache[author]
        except Exception as e:
            self.logger.error(f"HUBINTA {e}")
        return author
    
    async def on_message(self, message):
        await self.process_commands(message)
        if message.author == self.user or message.content is None:
            return  # Ignore messages from the bot itself or if the message is None
        
        #content = message.content
        author = self.get_author(message)
        avatar = self.get_avatar(message)
        
        is_from_self = False
        relevant_keys = []
        for i in self.setups.values():
            if i['from_channel'] == message.channel.id and not i['disabled']:
                relevant_keys.append(i)
            elif i['from_server'] == message.guild.id and not i['disabled']:
                relevant_keys.append(i)
            elif i['from_author'] == message.author.id and not i['disabled']:
                relevant_keys.append(i)
            if i['webhook_id'] == message.webhook_id and not i['disabled']:
                is_from_self = True
        if is_from_self:
            return
        
            
        #if message.channel.id in self.cache:
        #    self.cache[message.channel.id].union(set(relevant_keys))
        #else:
        #    self.cache[message.channel.id] = set(relevant_keys)
        
        for key in relevant_keys:
            if key['delete_messages']:
                try:
                    await message.delete()
                except:
                    print("NOT DELTE CONE")
            asyncio.create_task(self._on_message(message, author, avatar, key))

    def get_config(self, text, model):
        return ({
            "type": "gen",
            "text": text,
            "model": model,
            "config": {
                "temperature": self.temp,
                'max_new_tokens': 200,
                'num_beams': 3,
                'no_repeat_ngram_size': 2,
                'repetition_penalty': 1.01,
            },
            "from": "translatiob"
        })

    async def _on_message(self, message, author, avatar, setup):
        if not self.LLM.is_available or message.content is None:
            return
        self._blocked = True
        self.logger.debug(message.content)
        if setup:
            response = self.LLM.safe_send(self.get_config(message.content, model = setup['model']))
            responses = [response]
            current_woble = response
            self.logger.warning(f"{author}: {message.content} -> {response}")
            if True:
                for i in range(setup['recursion_depth']):
                    old_wobble = current_woble
                    current_woble = self.LLM.safe_send(self.get_config(old_wobble, model = setup['model']))
                    self.logger.warning(f"{author}: {old_wobble} -> {current_woble}")
                    if current_woble:
                        responses.append(current_woble)
            print(responses)
            author = self.translate_author(author, setup['model'])
            # Forward the response via webhook
            for resp in responses:
                _, sent = await self.send_webhook(message, resp, author, setup, avatar)
            self._blocked = False
            
    async def send_webhook(self, message, response, author, setup, avatar):
        webhook_id = setup.get("webhook_id")
        webhook_token = setup.get("webhook_token")
        if not author.strip():
            author = "spomqinson"
        if webhook_id and webhook_token:
            webhook_url = f"https://discord.com/api/webhooks/{webhook_id}/{webhook_token}"
            excesska = author[80:]
            resp = f"{response}\n"
            if not setup['delete_messages']:
                kanal = message.channel.id
                idka = message.id
                resp = f"[{response}](https://discord.com/channels/{kanal}/{kanal}/{idka})"
            if excesska:
                resp = f"{excesska}: {resp}"
            webhook_data = {
                "content": resp,  # Assuming the response has a "text" field
                "username": author[:80],
                "avatar_url": avatar  # Copy the author's profile picture
            }
            
            # Send the webhook and get the response
            webhook_response = requests.post(webhook_url, json=webhook_data)
            return webhook_response, resp

    @tasks.loop(seconds=60*5)
    async def clear_names(self):
        if self._blocked:
            return
        if self.nick_cache:
            random_key = random.choice(list(self.nick_cache.keys()))
            del self.nick_cache[random_key]
            self.logger.info(f"Removed '{random_key}' from nick_cache.")
 
    def load_setups(self):
        try:
            with open(SETUP_FILE, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def save_setups(self):
        with open(SETUP_FILE, 'w') as f:
            json.dump(self.setups, f)

    async def create_webhook(self, channel):
        # Create a new webhook in the destination channel
        webhook = await channel.create_webhook(name=f"{self.user.name} Webhook")
        return webhook

bot = Translatiob(top_layer_port=5556)


# Create a session for the webhook adapter

async def delete_webhook(webhook_id, webhook_token):
    return

async def try_fetch_channel(ctx, channel_str):
    if channel_str:
        # Remove "<#" and ">" if present, to extract the channel ID
        if channel_str.startswith('<#') and channel_str.endswith('>'):
            channel_str = channel_str[2:-1]

        try:
            # Convert the channel string to an integer (channel ID)
            channel_id = int(channel_str)
            # Fetch the channel by its ID (even if it's from another server)
            fetched_channel = await bot.fetch_channel(channel_id)
            return fetched_channel
        except (discord.NotFound, ValueError):
            await ctx.send(f"Hi you??? Am not acces {channel_str} not it o it.")
            return None
        except discord.Forbidden:
            await ctx.send(f"AM NOT permison  sos so n M {channel_str}.")
            return None
    return None

def toggle_existing(key, state):
    if key in bot.setups:
        bot.setups[key]['disabled'] = state
        bot.save_setups()
        return True, bot.setups[key]['disabled']
    return False, None

async def manage_webhooker(channel):
    webhook = None
    existing_webhook = None
    webhooks = await channel.webhooks()
    
    for webhook in webhooks:
        if webhook.name == 'GUANGDONG CAWOLO HARRAQ TECHNOLOGY CO., LTD':  # You can also match by other attributes if needed
            existing_webhook = webhook
            break
    
    if existing_webhook is None:
        webhook = await channel.create_webhook(name='GUANGDONG CAWOLO HARRAQ TECHNOLOGY CO., LTD')
    else:
        webhook = existing_webhook
    return webhook

def format_discord_mentions(data):
    activeka = []
    disabledka = []
    for k, v in data.items():
        if v.get('from_author'):
            source = f"<@{v['from_author']}>"
        elif v.get('from_server'):
            source = f"<@{v['from_server']}>"
        elif v.get('from_channel'):
            source = f"<#{v['from_channel']}>"
        else:
            source = "Unknown"

        if v.get('to_channel'):
            dest = f"<#{v['to_channel']}>"
        else:
            dest = "Unknown"
        
        if not v['disabled']:
            activeka.append(f"{k}(model={v['model']}, depth={v['recursion_depth']}): {source} -> {dest}")
        else:
            disabledka.append(f"{k}(model={v['model']}, depth={v['recursion_depth']}): {source} -> {dest}")
        
    return activeka, disabledka

@bot.tree.command(name="setupkashowka")
async def setupkashowka_slash(interaction: discord.Interaction):
    ctx = await bot.get_context(interaction)
    await setupkashowka(ctx)

@bot.command(name='setupkashowka')
async def setupkashowka(ctx):
    if ctx.author.id not in AUTHORIZED_USER_IDS and not any(role.id in AUTHORIZED_ROLE_IDS for role in ctx.author.roles):
        await ctx.send("YOU WRONGS IT YOU ANTI PERMISSIONS")
        return
    activeka, disabledka = format_discord_mentions(bot.setups)
    msg = "## Ogam ake u observers followings mapping:\n\n"
    for item in activeka:
        msg += item + "\n"
    msg += "\n## Disabledka his:\n\n"
    for item in disabledka:
        msg += item + "\n"
    await ctx.send(msg)

@bot.tree.command(name="temp")
async def temp_slash(interaction: discord.Interaction, temp: int):
    ctx = await bot.get_context(interaction)
    await temp(ctx, temp)

@bot.command(name='temp')
async def temp(ctx, temp):
    if ctx.author.id not in AUTHORIZED_USER_IDS and not any(role.id in AUTHORIZED_ROLE_IDS for role in ctx.author.roles):
        await ctx.send("YOU WRONGS IT YOU ANTI PERMISSIONS")
        return
    bot.temp = max(0.1, min(float(temp), 5))
    await ctx.send(f'NEW HIS TEMP NEW!!!!! {bot.temp}')

@bot.tree.command(name="hiyou")
async def hiyou_slash(interaction: discord.Interaction, user: discord.Member,  model: str = 't5-mihm', recursion_depth: int = 0):
    ctx = await bot.get_context(interaction)
    await hiyou(ctx, user, model, recursion_depth)

@bot.command(name='hiyou')
async def hiyou(ctx, user: discord.Member, model: str = 't5-mihm', recursion_depth: int = 0):
    if ctx.author.id not in AUTHORIZED_USER_IDS and not any(role.id in AUTHORIZED_ROLE_IDS for role in ctx.author.roles):
        return
    
    key = str(user.id+ctx.channel.id)
    exist, state = toggle_existing(key, False)
    if exist:
        await ctx.send(f'IYTESBUSINESS {ctx.channel.mention}! {state}')
        return
    webhook = await manage_webhooker(ctx.channel)
    bot.setups[key] = {
        "created_in": ctx.channel.id,
        "from_author": user.id,
        "from_server": None,
        "from_channel": None,
        "to_channel": ctx.channel.id,
        "delete_messages": True,
        "webhook_id": webhook.id,
        "webhook_token": webhook.token,
        "model": model,
        "disabled": False,
        "recursion_depth": min(MAX_RECURSION_DEPTH, max(0, recursion_depth))
    }
    bot.save_setups()

    await ctx.send(f'Ready for business? <@{user.id}>')

@bot.tree.command(name="byeyou")
async def byeyou_slash(interaction: discord.Interaction, user: discord.Member):
    ctx = await bot.get_context(interaction)
    await byeyou(ctx, user)

@bot.command(name='byeyou')
async def byeyou(ctx, user: discord.Member):
    if ctx.author.id not in AUTHORIZED_USER_IDS and not any(role.id in AUTHORIZED_ROLE_IDS for role in ctx.author.roles):
        return
    
    key = str(user.id+ctx.channel.id)
    exist, state = toggle_existing(key, True)
    if exist:
        await ctx.send(f'IYTESBUSINESS {ctx.channel.mention}! {state}')
    await ctx.send(f'ANTI BUSINESSSSSSSSSSSSSSSSSSSsssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssss <@{user.id}> Business close status ') 

@bot.tree.command(name="translatekaonka")
async def translatekaONKA_slash(interaction: discord.Interaction, to_channel: str = None, from_channel: str = None, model: str = 't5-mihm', recursion_depth: int = 0):
    ctx = await bot.get_context(interaction)
    await translatekaONKA(ctx, to_channel, from_channel, model, recursion_depth)

@bot.command(name='translatekaONKA')
async def translatekaONKA(ctx, to_channel: str = None, from_channel: str = None, model: str = 't5-mihm', recursion_depth: int = 0):
    if ctx.author.id not in AUTHORIZED_USER_IDS and not any(role.id in AUTHORIZED_ROLE_IDS for role in ctx.author.roles):
        await ctx.send("YOU WRONGS YOUR WORONGS. YOU NOT")
        return

    # Try to fetch both from_channel and to_channel
    from_channel = await try_fetch_channel(ctx, from_channel)
    to_channel = await try_fetch_channel(ctx, to_channel)

    # Proceed with the setup process
    if from_channel is None and to_channel is None:
        key = str(ctx.channel.id+ctx.channel.id)
        exist, state = toggle_existing(key, False)
        if exist:
            await ctx.send(f'IYTESBUSINESS {ctx.channel.mention}! {state}')
            return
        webhook = await manage_webhooker(ctx.channel)
        bot.setups[key] = {
            "created_in": ctx.channel.id,
            "from_author": None,
            "from_server": None,
            "from_channel": ctx.channel.id,
            "to_channel": ctx.channel.id,
            "delete_messages": True,
            "webhook_id": webhook.id,
            "webhook_token": webhook.token,
            "model": model,
            "disabled": False,
            "recursion_depth": min(MAX_RECURSION_DEPTH, max(0, recursion_depth))
        }
        bot.save_setups()
        await ctx.send(f'IYTESBUSINESS {ctx.channel.mention}!')
    elif from_channel and to_channel:
        key = str(from_channel.id+to_channel.id)
        exist, state = toggle_existing(key, False)
        if exist:
            await ctx.send(f'IYTESBUSINESS {ctx.channel.mention}! {state}')
            return
        webhook = await manage_webhooker(to_channel)
        bot.setups[key] = {
            "created_in": ctx.channel.id,
            "from_author": None,
            "from_server": None,
            "from_channel": from_channel.id,
            "to_channel": to_channel.id,
            "delete_messages": False,
            "webhook_id": webhook.id,
            "webhook_token": webhook.token,
            "model": model,
            "disabled": False,
            "recursion_depth": min(MAX_RECURSION_DEPTH, max(0, recursion_depth))
        }
        bot.save_setups()  # Save setups after modification
        await ctx.send(f'OIYESBUSINESS {from_channel.mention} -> {to_channel.mention} Webhooker.')
    elif to_channel:
        key = str(ctx.guild.id+to_channel.id)
        exist, state = toggle_existing(key, False)
        if exist:
            await ctx.send(f'IYTESBUSINESS {ctx.channel.mention}!')
            return
        webhook = await manage_webhooker(to_channel)
        bot.setups[key] = {
            "created_in": ctx.channel.id,
            "from_author": None,
            "from_server": ctx.guild.id,
            "from_channel": None,
            "to_channel": to_channel.id,
            "delete_messages": False,
            "webhook_id": webhook.id,
            "webhook_token": webhook.token,
            "model": model,
            "disabled": False,
            "recursion_depth": min(MAX_RECURSION_DEPTH, max(0, recursion_depth))
        }
        bot.save_setups()  # Save setups after modification
        await ctx.send(f'oyes uinesss Server -> {to_channel.mention} WEbholker .')

@bot.tree.command(name="translatekaoffka")
async def translatekaOFFKA_slash(interaction: discord.Interaction, to_channel: str = None, from_channel: str = None):
    ctx = await bot.get_context(interaction)
    await translatekaOFFKA(ctx, to_channel, from_channel)

@bot.command(name='translatekaOFFKA')
async def translatekaOFFKA(ctx, to_channel: str = None, from_channel: str = None):
    if ctx.author.id not in AUTHORIZED_USER_IDS and not any(role.id in AUTHORIZED_ROLE_IDS for role in ctx.author.roles):
        await ctx.send("YOU WRONGS IT YOU NOT PERMSIISONBBSDGSAFS SF asf S AS Das90ufiewnsvlkdm,c .")
        return

    # Try to fetch both from_channel and to_channel
    from_channel = await try_fetch_channel(ctx, from_channel)
    to_channel = await try_fetch_channel(ctx, to_channel)

    # Proceed with the setup process
    if from_channel is None and to_channel is None:
        key = str(ctx.channel.id+ctx.channel.id)
        print(key)
        exist, state = toggle_existing(key, True)
        print(exist, state)
        if exist:
            await ctx.send(f'IYTESBUSINESS {ctx.channel.mention}! {state}')
            return

    elif from_channel and to_channel:
        key = str(from_channel.id+to_channel.id)
        exist, state = toggle_existing(key, True)
        if exist:
            await ctx.send(f'IYTESBUSINESS {ctx.channel.mention}! {state}')
            return

    elif to_channel:
        key = str(ctx.guild.id+to_channel.id)
        exist, state = toggle_existing(key, True)
        if exist:
            await ctx.send(f'IYTESBUSINESS {ctx.channel.mention}!')
            return


def punch_out_random_words(text, num_words_to_remove):
    words = text.split()  # Split the text into words
    if num_words_to_remove > len(words):
        raise ValueError("Number of words to remove exceeds the total number of words in the text.")
    
    words_to_remove = random.sample(words, num_words_to_remove)  # Randomly pick words to remove
    punched_out_text = ' '.join(word for word in words if word not in words_to_remove)
    
    return punched_out_text


@bot.tree.command(name="translateka")
async def translateka_slash(interaction: discord.Interaction, text: str, recursion_depth: int = 0, model: str = 't5-mihm'):
    ctx = await bot.get_context(interaction)
    await translateka(ctx, text=text, recursion_depth=recursion_depth, model=model)
    
@bot.command(name='translateka')
async def translateka(ctx, *, text, recursion_depth = 0, punchka_outka = False, model: str = 't5-mihm'):
    if not bot.LLM.is_available or text is None:
        return
    bot._blocked = True
    bot.logger.info(text)
    text = punch_out_random_words(text, random.randint(0, len(text.split(" "))//2))
    response = bot.LLM.safe_send(bot.get_config(text, model))
    for i in range(recursion_depth):
        response = bot.LLM.safe_send(bot.get_config(text, model))

    author = bot.get_author(ctx)
    
    bot.logger.info(author, bot.nick_cache)
    try:
        if author not in bot.nick_cache:
            author_ = bot.LLM.safe_send(bot.get_config(author, model))
            if author_:
                bot.nick_cache[author] = author_
                author = author_
        else:
            author = bot.nick_cache[author]
    except Exception as e:
        bot.logger.error(f"HUBINTA {e}")
    bot.logger.warning(f"{author}: {text} -> {response}")
    # Forward the response via webhook
    bot._blocked = False
    await ctx.send(response)
    return

bot.run(TOKENIITA_BAXSANTA)

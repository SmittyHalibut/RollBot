import boto3
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
import json
import logging
import re
import random
import os
import time
import math
import ast
from decimal import Decimal

from base64 import b64decode
# from urllib.parse import parse_qs
from urlparse import parse_qs

from slackclient import SlackClient

#ENCRYPTED_EXPECTED_TOKEN = os.environ['kmsEncryptedToken']


# I'm not too worried about other people using my roll bot, and KMS costs $1/mo
#kms = boto3.client('kms')
#expected_token = kms.decrypt(CiphertextBlob=b64decode(ENCRYPTED_EXPECTED_TOKEN))['Plaintext']
# These come from Slack.
expected_token = ['some value', 'some other value']

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)


def respond(err, res=None):
    result = {
        'statusCode': '400' if err else '200',
        'headers': {
            'Content-Type': 'application/json',
        },
    }
    if err:
        result['body'] = err.message 
    elif res is not None:
        result['body'] = json.dumps(res)
    #else: Do not specify a 'body' field at all.
    return result

class DicePools:
    def __init__(self):
        self._client = boto3.client('dynamodb', 'us-west-2')
        self.pools = None
        self._gm = "seventeen"
        
    def get_pools(self):
        if self.pools is None:
            self._load_dice_pools()
        return self.pools
        
    def _load_dice_pools(self):
        if self.pools is not None:
            return
        
        response = self._client.query(
                TableName='DicePools',
                Select='ALL_ATTRIBUTES',
                Limit=1,
                ScanIndexForward=False,
                KeyConditionExpression='game = :game_name',
                ExpressionAttributeValues={
                    ':game_name': {"S": "Shadowrun"}
                }
            )
        logger.debug("DB Response: {}".format(response))
        des = TypeDeserializer()
        if 'Items' in response and len(response['Items']) > 0 and 'pools' in response['Items'][0]:
            self.pools = des.deserialize(response['Items'][0]['pools'])
        else:
            logger.error("Dice Pools not found in DynamoDB.")
            logger.error(response)
            raise Exception("No values found in DynamoDB.")

        logger.debug("Pools: {}".format(self.pools))
        if self._gm not in self.pools:
            self.pools[self._gm] = 0
        return self.pools
        
    def _save_dice_pools(self):
        if self.pools is None:
            raise Exception("Tried to save dice pools before loading them.")
            
        ser = TypeSerializer()
        item = {
                'game': ser.serialize('Shadowrun'),
                'timestamp': ser.serialize(Decimal(time.time())),
                'pools': ser.serialize(self.pools)
            }
        logger.debug("Item before put_item()ing: {}".format(item))
        self._client.put_item(TableName='DicePools', Item=item)

    def use_pool_dice(self, user_name, user_id, num_dice):
        self._load_dice_pools()
        if user_name not in self.pools:
            self.pools[user_name] = 0
            
        if user_name == self._gm:
            if self.pools[user_name] >= num_dice:
                # GM has enough dice in pool, just use them.
                self.pools[user_name] -= num_dice
            else:
                # This gets a bit interesting.  We have to give dice to players.
                num_players = len(self.pools) - 1   # not including the GM
                logger.debug("Number of players: {}".format(num_players))
                num_dice_needed = num_dice - self.pools[user_name]
                logger.debug("Number of dice needed: {}".format(num_dice_needed))
                num_dice_per_player = int(math.ceil(float(num_dice_needed)/float(num_players)))
                logger.debug("Number of dice per player: {}".format(num_dice_per_player))
                # Give dice to players
                for player in self.pools.keys():
                    logger.debug("Player: '{}'  GM: '{}'".format(player, self._gm))
                    if player != self._gm:
                        logger.debug("Giving {} dice to {}".format(num_dice_per_player, player))
                        self.pools[player] += num_dice_per_player
                    else:
                        gm_dice = (num_dice_per_player*num_players)-num_dice_needed
                        logger.debug("Setting GM dice to {}".format(gm_dice))
                        self.pools[player] = gm_dice
        else:  # user_name != self._gm
            if self.pools[user_name] > num_dice:
                # enough dice in the pool, just use them.
                self.pools[user_name] -= num_dice
            elif self.pools[user_name] > 0:
                # Some dice in the pool, but not enough.
                self.pools[self._gm] += num_dice - self.pools[user_name]
                self.pools[user_name] = 0
            else:
                # pool is empty. Give all to GM
                self.pools[self._gm] += num_dice
                self.pools[user_name] = 0  # this should be a no-op.
                
        self._save_dice_pools()
    
    def build_attachment(self):
        self._load_dice_pools()
        pools_txt = ""
        for player, dice in self.pools.items():
            if player == self._gm:
                player += " (GM)"
            pools_txt += "[{}: {}] ".format(player, dice)
        pools_attachment = {
            'color': 'black',
            'text': pools_txt,
            'mrkdwn_in': ['text']
        }
        return pools_attachment

def usage(str = None):
    res = dict()
    res['response_type'] = 'ephemeral'
    res['text'] = "Usage:"
    if str is not None:
        res['text'] = str
    res['text'] += """
            Use '/roll [number of dice]' to roll your dice.
            Use '/roll [normal dice] + [pool dice]' to roll extra.
            Use '/roll pools' to see the current pool sizes.
            Use '/roll food' for Food Fight splatter effects.
            Use '/roll fate' to roll four Fate dice.
        """
    return respond(None, res)
    
def lambda_handler(event, context):
    # logger.debug("Event: {}\nContext: {}".format(event, context))
    params = parse_qs(event['body'])
    token = params['token'][0]
    if token not in expected_token:
        logger.error("Request token (%s) does not match expected", token)
        return respond(Exception('Invalid request token'))

    command = params['command'][0]
    logger.debug("Command is {}".format(command))

    if command == '/roll':
        return do_roll(params)
    else:
        res = {
            'response_type': 'in_channel',
            'text': "Unknown command: {}".format(command)
        }


def send_rollbot_message(message, params):
    # There's GOT to be a better place to put these...
    slack_token = 'some token'
    sc = SlackClient(slack_token)

    result = sc.api_call(
        'chat.postMessage',
        channel = params['channel_id'][0],
        text = message['text'],
        attachments = message['attachments'],
        reply_broadcast = True,
    )
    logger.debug("post message API results: {}".format(result))

    res = None
    if not result['ok']:
        res = {
            'response_type': 'ephemeral',
            'text': "API call failure: {}".format(result['error']),
        }
    return res

def do_roll(params):
    user_id = params['user_id'][0]
    user_name = params['user_name'][0]
    user_ref = "<@{}|{}>".format(user_id, user_name)
    channel = params['channel_id'][0]
    command_text = params['text'][0]
    dice_pools = DicePools()
    res = dict()
    res['response_type'] = 'ephemeral'

    if command_text == "help":
        return usage()

    # Just dump dice pools
    if command_text == "pools":
        res['attachments'] = [dice_pools.build_attachment()]
        res['text'] = "Current Dice Pools:"
            
        return respond(None, send_rollbot_message(res, params))

    result = re.match(r'food(?:\s+(\d+))?', command_text)
    if result is not None:
        res['attachments'] = []
        if len(result.groups()) == 1 and result.group(1) is not None and 1 <= int(result.group(1)) <= 6:
            what_happens = int(result.group(1))
            res['attachments'].append({
                'color': '#000000',
                'text': 'Forced response, not random.',
                'mrkdwn_in': ['text']
            })
        else:
            what_happens = random.randint(1, 6)
            
        if what_happens == 1:
            res['text'] = 'The shot hits true, nothing breaks.'
            return respond(None, send_rollbot_message(res, params))
        # Something happens, choose color, consistency and type.
        food_colors = ['black', 'blue', 'green', 'orange', 'pink', 'purple', 'red', 'white', 'yellow', 'clear', 'multi-colored']
        food_consistencies = ['chunky', 'fizzy', 'lumpy', 'smelly', 'soft', 'spongy', 'sticky', 'sudsy', 'syrupy', 'thick', '2']
        food_types = ['liquid', 'meat', 'metal', 'plastic', 'powder', 'vegetable', 'liquid', 'meat', 'metal', 'plastic', 'powder']
        food_color = food_colors[random.randint(0, 10)]
        food_consistency = food_consistencies[random.randint(0, 10)]
        food_type = food_types[random.randint(0, 10)]
        if food_consistency == '2':
            # Pick two
            food_consistency = "{}, {}".format(food_consistencies[random.randint(0, 9)], food_consistencies[random.randint(0, 9)])
            
        if 2 <= what_happens <= 3:
            res['text'] = "{} {} {} splashes all over the target, and anyone near them." \
                .format(food_color, food_consistency, food_type).capitalize()
            res['attachments'].extend([{
                'color': '#ffff00',
                'text': 'The target and everyone within 2m of them suffers a *-1 Dice Pool* modifier for *one round*.',
                'mrkdwn_in': ['text']
            }])
            return respond(None, send_rollbot_message(res, params))
        if 4 <= what_happens <= 5:
            res['text'] = "So much {} {} {} splashes over the target that their face and arms are completely covered, impairing their visibility." \
                .format(food_color, food_consistency, food_type)
            res['attachments'].extend([{
                'color': '#ffff00',
                'text': 'Everyone within 2m of the target suffers a *-1 Dice Pool* modifier for *one round*.',
                'mrkdwn_in': ['text']
            }, {
                'color': '#ff9900',
                'text': 'The target suffers a *-2 Dice Pool* modifier. They must spend *a simple action* wiping their eyes clean(ish) *to remove this effect*.',
                'mrkdwn_in': ['text']
            }])
            return respond(None, send_rollbot_message(res, params))
        if what_happens == 6:
            pyro = [
                'an avalance of cans fall off a near-by shelf and bury the target; worse yet, some of the cans open leaking their contents on the target',
                'the light fixtures above the target explode in a shower of sparks, raining glowing hot metals and shards of glass down upon the target',
                'an unforeseen chemical reactions between Stuffers cause a frothing acid reaction that splashes on the target',
                'an unforeseen chemical reactions between Stuffers cause an explosion in the target\'s face, similar to a flash-bang grenade',
                'a cloud of fine powder of Dunkelzahn-knows-what engulfs the target, creating an inhalation hazard', 
                'an unforeseen chemical reaction between Stuffers ignights the surrounding "food" stuffs in a greasy confligaration'
            ][random.randint(0, 5)]
            res['text'] = "Pyrotechnics! Not only does {} {} {} explode all over the target and everyone else in the vicinity, but {}." \
                .format(food_color, food_consistency, food_type, pyro)
            res['attachments'].extend([{
                'color': '#ffff00',
                'text': 'Everyone within 2m of the target suffers a *-1 Dice Pool* modifier for *one round*.',
                'mrkdwn_in': ['text']
            }, {
                'color': '#ff0000',
                'text': 'The target rolls *Dodge + Reaction* to evade *3S damage*.',
                'mrkdwn_in': ['text']
            }])
            return respond(None, send_rollbot_message(res, params))
            
        
    result = re.match(r'fate\s*\+?(\d+)?', command_text)
    if result is not None:
        # Roll fate dice
        roll_fate = 0
        roll_fate_str = ""
        for ndx in range(0, 4):
            die_roll = random.randint(0, 2)
            if die_roll == 0:
                roll_fate -= 1
                roll_fate_str += "-"
            elif die_roll == 1:
                roll_fate_str += "0"
            else:
                roll_fate += 1
                roll_fate_str += "+"
                
        skill = 0
        skill_str = ""
        if result.group(1) is not None:
            skill = int(result.group(1))
            skill_str = " +%d" % (skill)
                
        res['attachments'] = []
        res['text'] = "%s rolled Fate%s dice: *%s* (%s)" % (user_ref, skill_str, roll_fate + skill, roll_fate_str)

        return respond(None, send_rollbot_message(res, params))

        
    result = re.match(r'(\d+)(?:\s*\+\s*(\d+))?(.*)', command_text)
    if result is None or result.group(1) is None:
        return usage("{} is not a valid /roll command.".format(command_text))
        
    num_dice = int(result.group(1))

    pools_attachment = None
    pool_dice = 0
    if result.group(2) is not None:
        # Using pool dice!
        pool_dice = int(result.group(2))
        dice_pools.use_pool_dice(user_name=user_name, user_id=user_id, num_dice=pool_dice)
        pools_attachment = dice_pools.build_attachment()
        logger.debug("Pools Attachment: {}".format(pools_attachment))

    comment = result.group(3)

    roll_sum = 0
    roll_str = dict()
    roll_str[1] = roll_str[2] = roll_str[3] = roll_str[4] = roll_str[5] = roll_str[6] = ""
    roll_hits = 0
    roll_nulls = 0
    roll_misses = 0
    roll_fate = 0
    roll_fate_str = ""
    for ndx in range(0, num_dice):
        die_roll = random.randint(1, 6)
        roll_sum += die_roll
        if die_roll <= 2:
            roll_fate -= 1
            roll_fate_str += "-"
        elif die_roll <= 4:
            roll_fate_str += "0"
        else:
            roll_fate += 1
            roll_fate_str += "+"
            
        roll_str[die_roll] += " {}".format(die_roll)
        if (die_roll == 5 or die_roll == 6):
            roll_hits += 1
        elif (die_roll == 1):
            roll_misses += 1
        else:
            roll_nulls += 1

    for ndx in range(0, pool_dice):
        die_roll = random.randint(1, 6)
        roll_sum += die_roll
        roll_str[die_roll] += " _*{}*_".format(die_roll)
        if (die_roll == 5 or die_roll == 6):
            roll_hits += 1
        elif (die_roll == 1):
            roll_misses += 1
        else:
            roll_nulls += 1

    hits = {
        'color': '#00CC00',
        'text': "*{}* Hits:{}{}".format(roll_hits, roll_str[6], roll_str[5]),
        'mrkdwn_in': ['text']
    }
    misses = {
        'color': '#BBBBBB',
        'text': "*{}* Misses:{}{}{}{}".format(roll_nulls + roll_misses,
            roll_str[4], roll_str[3], roll_str[2], roll_str[1]),
        'mrkdwn_in': ['text']
    }

    comment_attachment = ""
    if comment:
        comment_attachment = {
            'color': '#AAAAAA',
            'text': "Comment: {}".format(comment),
            'mrkdwn_in': ['text']
        }


    glitch = ""    
    if roll_misses >= num_dice/2.0:
        if roll_hits == 0:
            glitch = {'color': 'danger', 'text': "*_CRITICAL_ GLITCH!*", 'mrkdwn_in': ['text']}
        else:
            glitch = {'color': 'warning', 'text': "*GLITCH!*", 'mrkdwn_in': ['text']}
    
    fate = ""
    if num_dice == 4:
        fate = {'color': 'black', 'text': "*{}* Fate: {}".format(roll_fate, roll_fate_str), 'mrkdwn_in': ['text']}
        
    if pools_attachment is not None:
        res['attachments'] = [comment_attachment, hits, misses, glitch, fate, pools_attachment]
    else:
        res['attachments'] = [comment_attachment, hits, misses, glitch, fate]
    res['text'] = "%s rolled %d dice, _*%d pool dice*_, %d total. Sum: %d" % (user_ref, num_dice, pool_dice, num_dice+pool_dice, roll_sum)

    
    return respond(None, send_rollbot_message(res, params))



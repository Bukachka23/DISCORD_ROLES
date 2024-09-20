import logging.config
import os
from enum import Enum
from typing import Any, Dict

from dotenv import load_dotenv

from src.config.logger import LOGGING

load_dotenv()

logging.config.dictConfig(LOGGING)
logger = logging.getLogger(__name__)

ticket_states: Dict[int, Any] = {}
ticket_info: Dict[int, Dict[str, Any]] = {}


class EnvSettings:
    DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
    PREMIUM_ROLE_ID = os.getenv('PREMIUM_ROLE_ID')
    STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY')
    ADMIN_USER_ID = int(os.getenv('ADMIN_USER_ID'))
    DATABASE_URL = os.getenv('DATABASE_URL')
    COMMAND_PREFIX = '/'


class TicketState(Enum):
    """Enumeration of possible states in the ticketing system."""
    AWAITING_AMOUNT = 1
    AWAITING_CURRENCY = 2
    AWAITING_ORDER_ID = 3
    AWAITING_PAYMENT_CONFIRMATION = 4


WELCOME_MESSAGE_TEMPLATE = """
@{username}, your payment has been verified and you have been assigned the @premium role for {days} days. 

Welcome to the Foxian family!🦊

For a detailed server guide, please check [Foxian Trading Community⁠🆕｜𝐒𝐭𝐚𝐫𝐭-𝐇𝐞𝐫𝐞](https://discord.com/channels/1060631469996908654/1130065532192825465)

For alerts specifically from Sherlock, please check [⁠Foxian Trading Community⁠🚨｜𝐒𝐡𝐞𝐫𝐥𝐨𝐜𝐤-𝐀𝐥𝐞𝐫𝐭𝐬](https://discord.com/channels/1060631469996908654/1190664339259138129)

For crypto alerts from other analysts, please head to [⁠Foxian Trading Community⁠🚨｜𝐂𝐫𝐲𝐩𝐭𝐨-𝐀𝐥𝐞𝐫𝐭𝐬](https://discord.com/channels/1060631469996908654/1129431096401080463) and choose the analyst you want alerts for.

Similarly, for forex alerts, you can go to [⁠Foxian Trading Community⁠🚨｜𝐂𝐫𝐲𝐩𝐭𝐨-𝐀𝐥𝐞𝐫𝐭𝐬](https://discord.com/channels/1060631469996908654/1129431096401080463)

You can discuss with other premium members in [⁠Foxian Trading Community⁠💭｜𝐏𝐫𝐞𝐦𝐢𝐮𝐦-𝐂𝐡𝐚𝐭](https://discord.com/channels/1060631469996908654/1121839854112739449)

If you need any help, please head to [⁠Foxian Trading Community⁠💁｜𝐏𝐫𝐞𝐦𝐢𝐮𝐦-𝐇𝐞𝐥𝐩](https://discord.com/channels/1060631469996908654/1129470982067863552) and if you want specific chart analysis, please share it in [⁠Foxian Trading Community⁠📈｜𝐂𝐡𝐚𝐫𝐭-𝐑𝐞𝐪𝐮𝐞𝐬𝐭𝐬](https://discord.com/channels/1060631469996908654/1130131666669686814)

Also, we have [⁠Foxian Trading Community⁠📊｜𝐓𝐫𝐚𝐝𝐞-𝐔𝐩𝐝𝐚𝐭𝐞𝐬](https://discord.com/channels/1060631469996908654/1153648794529968178) which will give you a list of all active, limit, and closed trades. This is updated every 6-8 hours.

Also, did you subscribe to Sherlock's YouTube? (This way you can support him if you like)
[Sherlock's YouTube Channel](https://youtube.com/@sherlockwhale?si=JcXQVbHJBL8-pwX-)
"""


def get_welcome_message(username: str, days: int) -> str:
    """
    Generate a personalized welcome message for the user.

    Args:
        username (str): The user's name.
        days (int): Number of days the premium role is active.

    Returns:
        str: The formatted welcome message.
    """
    return WELCOME_MESSAGE_TEMPLATE.format(username=username, days=days)

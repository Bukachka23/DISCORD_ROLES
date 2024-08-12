from enum import Enum
from typing import Any

ticket_states = {}
ticket_info: dict[int, dict[str, Any]] = {}


class EnvVariables(Enum):
    DISCORD_BOT_TOKEN = 'DISCORD_BOT_TOKEN'
    PREMIUM_ROLE_ID = 'PREMIUM_ROLE_ID'
    OPENAI_API_KEY = 'OPENAI_API_KEY'
    DATABASE_URL = 'DATABASE_URL'
    STRIPE_SECRET_KEY = 'STRIPE_SECRET_KEY'
    ADMIN_USER_ID = 'ADMIN_USER_ID'


class TicketState(Enum):
    AWAITING_AMOUNT = 1
    AWAITING_CURRENCY = 2
    AWAITING_ORDER_ID = 3
    AWAITING_PAYMENT_CONFIRMATION = 4

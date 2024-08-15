import stripe
import logging.config
from datetime import datetime

from src.config.log_config import LOGGING

logging.config.dictConfig(LOGGING)
logger = logging.getLogger(__name__)


def create_payment_intent(amount: int, currency: str, order_id: str) -> dict:
    """
    Create a PaymentIntent on Stripe.
    """
    try:
        payment_intent = stripe.PaymentIntent.create(
            amount=amount,
            currency=currency,
            payment_method_types=["card"],
            metadata={"order_id": order_id}
        )
        logger.info(f"PaymentIntent created: {payment_intent.id}")
        return payment_intent
    except stripe.error.StripeError as e:
        logger.error(f"Error creating PaymentIntent: {e!s}")
        raise


def get_customer_by_email(email):
    """Retrieve the first customer by email."""
    try:
        customer_list = stripe.Customer.list(
            email=email,
            expand=['data.subscriptions'])

        if not customer_list.data:
            logger.info(f"No customers found with the email: {email}")
            return None
        return customer_list.data[0]

    except stripe.error.StripeError as e:
        logger.error(f"Stripe error while retrieving customer: {e}")
        return None


def get_active_subscription(customer):
    """Retrieve the first active subscription for a customer."""
    if not customer or not customer.subscriptions.data:
        logger.info("No subscription found for the customer.")
        return None
    return customer.subscriptions.data[0]


def calculate_remaining_days(subscription) -> int:
    """List active subscriptions for a given email."""
    return (datetime.fromtimestamp(subscription.current_period_end) - datetime.now()).days

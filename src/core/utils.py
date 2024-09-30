import logging.config
from datetime import datetime
from typing import Optional

import stripe

from src.config.logger import LOGGING
from src.config.settings import EnvSettings

logging.config.dictConfig(LOGGING)
logger = logging.getLogger(__name__)

stripe.api_key = EnvSettings.STRIPE_SECRET_KEY


def create_payment_intent(amount: int, currency: str, order_id: str) -> stripe.PaymentIntent:
    """
    Create a PaymentIntent on Stripe.

    Args:
        amount (int): The amount to charge in the smallest currency unit (e.g., cents).
        currency (str): The currency code (e.g., 'usd').
        order_id (str): The unique order identifier.

    Returns:
        stripe.PaymentIntent: The created PaymentIntent object.

    Raises:
        stripe.error.StripeError: If Stripe API call fails.
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
        logger.error(f"Error creating PaymentIntent: {e}")
        raise


def get_customer_by_email(email: str) -> Optional[stripe.Customer]:
    """
    Retrieve the first customer by email.

    Args:
        email (str): The customer's email address.

    Returns:
        Optional[stripe.Customer]: The Stripe Customer object if found, else None.
    """
    try:
        customers = stripe.Customer.list(
            email=email,
            expand=['data.subscriptions']
        )

        if not customers.data:
            logger.info(f"No customers found with the email: {email}")
            return None

        logger.debug(f"Customer found with email {email}: {customers.data[0].id}")
        return customers.data[0]

    except stripe.error.StripeError as e:
        logger.error(f"Stripe error while retrieving customer: {e}")
        return None


def get_active_subscription(customer: stripe.Customer) -> Optional[stripe.Subscription]:
    """
    Retrieve the first active subscription for a customer.

    Args:
        customer (stripe.Customer): The Stripe Customer object.

    Returns:
        Optional[stripe.Subscription]: The active Subscription object if found, else None.
    """
    if not customer or not customer.subscriptions.data:
        logger.info("No subscription found for the customer.")
        return None

    for subscription in customer.subscriptions.data:
        if subscription.status == 'active':
            logger.debug(f"Active subscription found: {subscription.id}")
            return subscription

    logger.info("No active subscription found for the customer.")
    return None


def calculate_remaining_days(subscription: stripe.Subscription) -> int:
    """
    Calculate the remaining days in a subscription.

    Args:
        subscription (stripe.Subscription): The Stripe Subscription object.

    Returns:
        int: Number of remaining days in the subscription.
    """
    current_period_end = datetime.fromtimestamp(subscription.current_period_end)
    remaining_days = (current_period_end - datetime.utcnow()).days
    logger.debug(f"Remaining days for subscription {subscription.id}: {remaining_days}")
    return remaining_days


def verify_payment_intent(payment_intent_id: str) -> bool:
    """
    Verify the payment intent with Stripe.

    Args:
        payment_intent_id (str): The PaymentIntent ID to verify.

    Returns:
        bool: True if the payment intent is valid and in an acceptable status, False otherwise.
    """
    try:
        payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)
        acceptable_statuses = ['succeeded', 'processing', 'requires_capture']
        if payment_intent.status in acceptable_statuses:
            logger.info(f"PaymentIntent {payment_intent_id} verified successfully with status '{payment_intent.status}'.")
            return True
        else:
            logger.warning(f"PaymentIntent {payment_intent_id} has unacceptable status '{payment_intent.status}'.")
            return False
    except stripe.error.StripeError as e:
        logger.error(f"Error retrieving PaymentIntent {payment_intent_id}: {e}")
        return False


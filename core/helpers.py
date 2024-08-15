import logging

import stripe

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

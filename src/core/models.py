from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class User(Base):
    """Represents a user in the database."""

    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    discord_id = Column(Integer, unique=True, nullable=False)
    user_id = Column(Integer, unique=True, nullable=True)
    username = Column(String, nullable=True)
    subscription_start = Column(DateTime, nullable=True)
    subscription_end = Column(DateTime, nullable=True)
    premium = Column(Boolean, default=False)
    tickets = relationship("Ticket", back_populates="user")

    def set_subscription(self, subscription) -> None:
        """Set the subscription start and end dates for the user."""
        self.subscription_start = subscription.start_date
        self.subscription_end = subscription.end_date


class Ticket(Base):
    """Represents a support ticket in the database."""

    __tablename__ = 'tickets'

    id = Column(Integer, primary_key=True)
    channel_id = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True)
    user = relationship("User", back_populates="tickets")


class Payment(Base):
    """Represents a payment record in the database."""

    __tablename__ = 'payments'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    payment_intent_id = Column(String, nullable=False)
    order_id = Column(String, nullable=False, unique=True)
    confirmed = Column(Boolean, default=False)
    confirmation_image = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

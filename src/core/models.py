from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    discord_id = Column(String, unique=True, nullable=False)
    user_id = Column(Integer, unique=True, nullable=True)
    username = Column(String, nullable=True)
    subscription_start = Column(DateTime, nullable=True)
    subscription_end = Column(DateTime, nullable=True)
    premium = Column(Boolean, default=False)
    tickets = relationship("Ticket", back_populates="user")

    def set_subscription(self, subscription):
        self.subscription_start = subscription.start_date
        self.subscription_end = subscription.end_date


class Ticket(Base):
    __tablename__ = 'tickets'
    id = Column(Integer, primary_key=True)
    channel_id = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'))
    created_at = Column(DateTime, nullable=False)
    closed_at = Column(DateTime)
    deleted_at = Column(DateTime)
    user = relationship("User", back_populates="tickets")


class Payment(Base):
    __tablename__ = 'payments'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    payment_intent_id = Column(String, nullable=False)
    confirmed = Column(Boolean, default=False)
    confirmation_image = Column(String)
    created_at = Column(DateTime, nullable=False)

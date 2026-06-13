import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Float, Integer, JSON
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topic = Column(String(50), nullable=False, index=True)
    resource = Column(String(255), nullable=False)
    # JSONB is standard in PostgreSQL for high-performance queryable JSON
    payload = Column(JSONB, nullable=False)
    status = Column(String(20), default="received", nullable=False, index=True)
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    processed_at = Column(DateTime, nullable=True)

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String(100), primary_key=True)  # Mercado Livre conversation ID or user ID
    user_id = Column(String(100), nullable=False, index=True)
    # Store chat history as JSONB to easily load and append messages
    history = Column(JSONB, default=list, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

class Product(Base):
    __tablename__ = "products"

    id = Column(String(100), primary_key=True)  # Mercado Livre Item ID (e.g. MLB1234567)
    title = Column(String(255), nullable=False)
    price = Column(Float, nullable=False)
    permalink = Column(String(512), nullable=True)
    status = Column(String(50), nullable=False)
    stock = Column(Integer, default=0, nullable=False)
    # Store additional metadata (attributes, dimensions, digital download url) in JSONB
    attributes = Column(JSONB, default=dict, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

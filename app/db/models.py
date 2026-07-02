import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Float, Integer, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from app.db.session import Base

class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topic = Column(String(50), nullable=False, index=True)
    resource = Column(String(255), nullable=False)
    payload = Column(JSONB, nullable=False)
    status = Column(String(20), default="received", nullable=False, index=True)
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    processed_at = Column(DateTime, nullable=True)

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String(100), primary_key=True)  # Mercado Livre conversation ID or user ID
    user_id = Column(String(100), nullable=False, index=True)
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
    attributes = Column(JSONB, default=dict, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False, index=True)
    contact = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationship to manual products
    products = relationship("ManualProduct", back_populates="supplier", cascade="all, delete-orphan")

class ManualProduct(Base):
    __tablename__ = "manual_products"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    barcode = Column(String(100), nullable=False, index=True)
    reference = Column(String(100), nullable=True)
    description = Column(String(255), nullable=False)
    quantity = Column(Integer, default=0, nullable=False)
    unit_value = Column(Float, default=0.0, nullable=False)
    discount = Column(Float, default=0.0, nullable=False)
    total_value = Column(Float, default=0.0, nullable=False)
    price_type = Column(String(50), default="normal", nullable=False)  # 'consignado', 'brinde', 'normal'
    category = Column(String(100), nullable=False, index=True)
    subcategory = Column(String(100), nullable=True, index=True)
    
    supplier_id = Column(UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False)
    supplier = relationship("Supplier", back_populates="products")

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

class SystemConfig(Base):
    __tablename__ = "system_configs"

    key = Column(String(50), primary_key=True)  # 'credits', 'meta'
    value = Column(Float, default=0.0, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

class ManualSale(Base):
    __tablename__ = "manual_sales"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("manual_products.id", ondelete="CASCADE"), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)
    total_value = Column(Float, nullable=False)
    sold_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    product = relationship("ManualProduct")


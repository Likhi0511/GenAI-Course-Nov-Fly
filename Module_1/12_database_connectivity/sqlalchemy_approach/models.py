# models.py
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import Column, String, DateTime, Numeric, ForeignKey, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


# SQLAlchemy ORM Models
class Customer(Base):
    __tablename__ = 'customers'
    __table_args__ = {'schema': None}  # Will be set dynamically

    customer_id = Column(String, primary_key=True)
    customer_name = Column(String, nullable=False)
    email = Column(String, nullable=False, unique=True)
    city = Column(String)
    state = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationship
    orders = relationship("Order", back_populates="customer", cascade="all, delete-orphan")

    # Indexes for performance
    __table_args__ = (
        Index('idx_customer_email', 'email'),
        Index('idx_customer_city_state', 'city', 'state'),
        {'schema': None}
    )


class Order(Base):
    __tablename__ = 'orders'
    __table_args__ = {'schema': None}

    order_id = Column(String, primary_key=True)
    customer_id = Column(String, ForeignKey('customers.customer_id'), nullable=False)
    order_date = Column(DateTime, nullable=False)
    status = Column(String, nullable=False)
    total_amount = Column(Numeric(10, 2), nullable=False)

    # Relationship
    customer = relationship("Customer", back_populates="orders")

    __table_args__ = (
        Index('idx_order_customer_id', 'customer_id'),
        Index('idx_order_date', 'order_date'),
        Index('idx_order_status', 'status'),
        {'schema': None}
    )


# Pydantic Models for Validation
class CustomerBase(BaseModel):
    customer_id: str = Field(..., min_length=1, max_length=50)
    customer_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    city: Optional[str] = Field(None, max_length=50)
    state: Optional[str] = Field(None, max_length=2)
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    customer_name: Optional[str] = Field(None, min_length=1, max_length=100)
    email: Optional[EmailStr] = None
    city: Optional[str] = Field(None, max_length=50)
    state: Optional[str] = Field(None, max_length=2)

    class Config:
        from_attributes = True


class CustomerResponse(CustomerBase):
    pass


class OrderBase(BaseModel):
    order_id: str = Field(..., min_length=1, max_length=50)
    customer_id: str = Field(..., min_length=1, max_length=50)
    order_date: datetime
    status: str = Field(..., min_length=1, max_length=20)
    total_amount: float = Field(..., ge=0)

    class Config:
        from_attributes = True


class OrderCreate(OrderBase):
    pass


class OrderUpdate(BaseModel):
    customer_id: Optional[str] = Field(None, min_length=1, max_length=50)
    order_date: Optional[datetime] = None
    status: Optional[str] = Field(None, min_length=1, max_length=20)
    total_amount: Optional[float] = Field(None, ge=0)

    class Config:
        from_attributes = True


class OrderResponse(OrderBase):
    customer: Optional[CustomerResponse] = None
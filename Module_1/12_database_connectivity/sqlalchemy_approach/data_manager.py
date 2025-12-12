# data_manager.py
from typing import List, Optional, Dict, Any
from sqlalchemy import select, update, delete, and_, or_, func, text
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from pydantic import ValidationError
import logging

from connector import PostgresConnector
from models import (
    Customer, Order,
    CustomerCreate, CustomerUpdate, CustomerResponse,
    OrderCreate, OrderUpdate, OrderResponse
)

logger = logging.getLogger(__name__)


class DataManagerError(Exception):
    """Base exception for DataManager errors"""
    pass


class ValidationError(DataManagerError):
    """Raised when data validation fails"""
    pass


class DatabaseError(DataManagerError):
    """Raised when database operations fail"""
    pass


class DataManager:
    def __init__(self, connector: PostgresConnector, default_schema: str = "public"):
        """
        Initialize DataManager with database connector

        Args:
            connector: PostgresConnector instance
            default_schema: Default schema to use for operations
        """
        self.connector = connector
        self.default_schema = default_schema
        logger.info(f"DataManager initialized with schema: {default_schema}")

    def _set_schema(self, session: Session, schema: str):
        """Set the search path for the session"""
        session.execute(text(f"SET search_path TO {schema}"))

    # ============= Customer Operations =============

    def get_all_customers(
            self,
            schema: Optional[str] = None,
            limit: int = 100,
            offset: int = 0,
            include_orders: bool = False
    ) -> List[Customer]:
        """
        Retrieve all customers with optional pagination

        Args:
            schema: Database schema (defaults to default_schema)
            limit: Maximum number of records to return
            offset: Number of records to skip
            include_orders: Whether to include related orders

        Returns:
            List of Customer objects
        """
        schema = schema or self.default_schema

        try:
            with self.connector.get_session() as session:
                self._set_schema(session, schema)

                query = select(Customer)

                if include_orders:
                    query = query.options(joinedload(Customer.orders))

                query = query.limit(limit).offset(offset)
                result = session.execute(query)
                customers = result.scalars().all()

                logger.info(f"Retrieved {len(customers)} customers from {schema}")
                return customers

        except SQLAlchemyError as e:
            logger.error(f"Error retrieving customers: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to retrieve customers: {str(e)}")

    def get_customer_by_id(
            self,
            customer_id: str,
            schema: Optional[str] = None,
            include_orders: bool = False
    ) -> Optional[Customer]:
        """
        Retrieve a customer by ID

        Args:
            customer_id: Customer ID to search for
            schema: Database schema
            include_orders: Whether to include related orders

        Returns:
            Customer object or None if not found
        """
        schema = schema or self.default_schema

        try:
            with self.connector.get_session() as session:
                self._set_schema(session, schema)

                query = select(Customer).where(Customer.customer_id == customer_id)

                if include_orders:
                    query = query.options(joinedload(Customer.orders))

                result = session.execute(query)
                customer = result.scalar_one_or_none()

                if customer:
                    logger.info(f"Found customer: {customer_id}")
                else:
                    logger.warning(f"Customer not found: {customer_id}")

                return customer

        except SQLAlchemyError as e:
            logger.error(f"Error retrieving customer {customer_id}: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to retrieve customer: {str(e)}")

    def search_customers(
            self,
            filters: Dict[str, Any],
            schema: Optional[str] = None,
            limit: int = 100,
            offset: int = 0
    ) -> List[Customer]:
        """
        Search customers with flexible filters

        Args:
            filters: Dictionary of field:value pairs for filtering
                    Supports: customer_name, email, city, state
            schema: Database schema
            limit: Maximum number of records
            offset: Number of records to skip

        Returns:
            List of matching Customer objects
        """
        schema = schema or self.default_schema

        try:
            with self.connector.get_session() as session:
                self._set_schema(session, schema)

                query = select(Customer)

                # Build WHERE clause dynamically
                conditions = []
                if "customer_name" in filters:
                    conditions.append(
                        Customer.customer_name.ilike(f"%{filters['customer_name']}%")
                    )
                if "email" in filters:
                    conditions.append(Customer.email.ilike(f"%{filters['email']}%"))
                if "city" in filters:
                    conditions.append(Customer.city == filters["city"])
                if "state" in filters:
                    conditions.append(Customer.state == filters["state"])

                if conditions:
                    query = query.where(and_(*conditions))

                query = query.limit(limit).offset(offset)
                result = session.execute(query)
                customers = result.scalars().all()

                logger.info(f"Found {len(customers)} customers matching filters")
                return customers

        except SQLAlchemyError as e:
            logger.error(f"Error searching customers: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to search customers: {str(e)}")

    def create_customer(
            self,
            customer_data: Dict[str, Any],
            schema: Optional[str] = None
    ) -> Customer:
        """
        Create a new customer with validation

        Args:
            customer_data: Dictionary containing customer data
            schema: Database schema

        Returns:
            Created Customer object

        Raises:
            ValidationError: If data validation fails
            DatabaseError: If database operation fails
        """
        schema = schema or self.default_schema

        try:
            # Validate with Pydantic
            validated_data = CustomerCreate(**customer_data)

            with self.connector.get_session() as session:
                self._set_schema(session, schema)

                # Check if customer already exists
                existing = session.execute(
                    select(Customer).where(
                        Customer.customer_id == validated_data.customer_id
                    )
                ).scalar_one_or_none()

                if existing:
                    # Update existing customer
                    for key, value in validated_data.dict(exclude_unset=True).items():
                        setattr(existing, key, value)

                    session.flush()
                    logger.info(f"Updated existing customer: {validated_data.customer_id}")
                    return existing
                else:
                    # Create new customer
                    customer = Customer(**validated_data.dict())
                    session.add(customer)
                    session.flush()

                    logger.info(f"Created new customer: {customer.customer_id}")
                    return customer

        except ValidationError as e:
            logger.error(f"Validation error: {str(e)}")
            raise ValidationError(f"Invalid customer data: {str(e)}")
        except IntegrityError as e:
            logger.error(f"Integrity error: {str(e)}", exc_info=True)
            raise DatabaseError(f"Customer creation failed - duplicate or constraint violation: {str(e)}")
        except SQLAlchemyError as e:
            logger.error(f"Database error: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to create customer: {str(e)}")

    def update_customer(
            self,
            customer_id: str,
            update_data: Dict[str, Any],
            schema: Optional[str] = None
    ) -> Optional[Customer]:
        """
        Update customer information

        Args:
            customer_id: Customer ID to update
            update_data: Dictionary of fields to update
            schema: Database schema

        Returns:
            Updated Customer object or None if not found
        """
        schema = schema or self.default_schema

        try:
            # Validate update data
            validated_data = CustomerUpdate(**update_data)

            with self.connector.get_session() as session:
                self._set_schema(session, schema)

                customer = session.execute(
                    select(Customer).where(Customer.customer_id == customer_id)
                ).scalar_one_or_none()

                if not customer:
                    logger.warning(f"Customer not found for update: {customer_id}")
                    return None

                # Update only provided fields
                for key, value in validated_data.dict(exclude_unset=True).items():
                    setattr(customer, key, value)

                session.flush()
                logger.info(f"Updated customer: {customer_id}")
                return customer

        except ValidationError as e:
            logger.error(f"Validation error: {str(e)}")
            raise ValidationError(f"Invalid update data: {str(e)}")
        except SQLAlchemyError as e:
            logger.error(f"Database error: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to update customer: {str(e)}")

    def delete_customer(
            self,
            customer_id: str,
            schema: Optional[str] = None
    ) -> bool:
        """
        Delete a customer and their orders (cascade)

        Args:
            customer_id: Customer ID to delete
            schema: Database schema

        Returns:
            True if deleted, False if not found
        """
        schema = schema or self.default_schema

        try:
            with self.connector.get_session() as session:
                self._set_schema(session, schema)

                customer = session.execute(
                    select(Customer).where(Customer.customer_id == customer_id)
                ).scalar_one_or_none()

                if not customer:
                    logger.warning(f"Customer not found for deletion: {customer_id}")
                    return False

                session.delete(customer)
                session.flush()

                logger.info(f"Deleted customer: {customer_id}")
                return True

        except SQLAlchemyError as e:
            logger.error(f"Error deleting customer: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to delete customer: {str(e)}")

    # ============= Order Operations =============

    def get_all_orders(
            self,
            schema: Optional[str] = None,
            limit: int = 100,
            offset: int = 0,
            include_customer: bool = False
    ) -> List[Order]:
        """Retrieve all orders with optional pagination"""
        schema = schema or self.default_schema

        try:
            with self.connector.get_session() as session:
                self._set_schema(session, schema)

                query = select(Order)

                if include_customer:
                    query = query.options(joinedload(Order.customer))

                query = query.limit(limit).offset(offset)
                result = session.execute(query)
                orders = result.scalars().all()

                logger.info(f"Retrieved {len(orders)} orders from {schema}")
                return orders

        except SQLAlchemyError as e:
            logger.error(f"Error retrieving orders: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to retrieve orders: {str(e)}")

    def get_order_by_id(
            self,
            order_id: str,
            schema: Optional[str] = None,
            include_customer: bool = False
    ) -> Optional[Order]:
        """Retrieve an order by ID"""
        schema = schema or self.default_schema

        try:
            with self.connector.get_session() as session:
                self._set_schema(session, schema)

                query = select(Order).where(Order.order_id == order_id)

                if include_customer:
                    query = query.options(joinedload(Order.customer))

                result = session.execute(query)
                order = result.scalar_one_or_none()

                if order:
                    logger.info(f"Found order: {order_id}")
                else:
                    logger.warning(f"Order not found: {order_id}")

                return order

        except SQLAlchemyError as e:
            logger.error(f"Error retrieving order: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to retrieve order: {str(e)}")

    def get_orders_by_customer(
            self,
            customer_id: str,
            schema: Optional[str] = None,
            limit: int = 100
    ) -> List[Order]:
        """Retrieve all orders for a specific customer"""
        schema = schema or self.default_schema

        try:
            with self.connector.get_session() as session:
                self._set_schema(session, schema)

                query = select(Order).where(
                    Order.customer_id == customer_id
                ).limit(limit)

                result = session.execute(query)
                orders = result.scalars().all()

                logger.info(f"Found {len(orders)} orders for customer {customer_id}")
                return orders

        except SQLAlchemyError as e:
            logger.error(f"Error retrieving customer orders: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to retrieve customer orders: {str(e)}")

    def create_order(
            self,
            order_data: Dict[str, Any],
            schema: Optional[str] = None
    ) -> Order:
        """Create a new order with validation"""
        schema = schema or self.default_schema

        try:
            # Validate with Pydantic
            validated_data = OrderCreate(**order_data)

            with self.connector.get_session() as session:
                self._set_schema(session, schema)

                # Verify customer exists
                customer_exists = session.execute(
                    select(Customer.customer_id).where(
                        Customer.customer_id == validated_data.customer_id
                    )
                ).scalar_one_or_none()

                if not customer_exists:
                    raise ValidationError(
                        f"Customer {validated_data.customer_id} does not exist"
                    )

                # Check if order already exists
                existing = session.execute(
                    select(Order).where(Order.order_id == validated_data.order_id)
                ).scalar_one_or_none()

                if existing:
                    # Update existing order
                    for key, value in validated_data.dict(exclude_unset=True).items():
                        setattr(existing, key, value)

                    session.flush()
                    logger.info(f"Updated existing order: {validated_data.order_id}")
                    return existing
                else:
                    # Create new order
                    order = Order(**validated_data.dict())
                    session.add(order)
                    session.flush()

                    logger.info(f"Created new order: {order.order_id}")
                    return order

        except ValidationError as e:
            logger.error(f"Validation error: {str(e)}")
            raise ValidationError(f"Invalid order data: {str(e)}")
        except IntegrityError as e:
            logger.error(f"Integrity error: {str(e)}", exc_info=True)
            raise DatabaseError(f"Order creation failed: {str(e)}")
        except SQLAlchemyError as e:
            logger.error(f"Database error: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to create order: {str(e)}")

    def update_order(
            self,
            order_id: str,
            update_data: Dict[str, Any],
            schema: Optional[str] = None
    ) -> Optional[Order]:
        """Update order information"""
        schema = schema or self.default_schema

        try:
            validated_data = OrderUpdate(**update_data)

            with self.connector.get_session() as session:
                self._set_schema(session, schema)

                order = session.execute(
                    select(Order).where(Order.order_id == order_id)
                ).scalar_one_or_none()

                if not order:
                    logger.warning(f"Order not found for update: {order_id}")
                    return None

                for key, value in validated_data.dict(exclude_unset=True).items():
                    setattr(order, key, value)

                session.flush()
                logger.info(f"Updated order: {order_id}")
                return order

        except ValidationError as e:
            logger.error(f"Validation error: {str(e)}")
            raise ValidationError(f"Invalid update data: {str(e)}")
        except SQLAlchemyError as e:
            logger.error(f"Database error: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to update order: {str(e)}")

    def delete_order(
            self,
            order_id: str,
            schema: Optional[str] = None
    ) -> bool:
        """Delete an order"""
        schema = schema or self.default_schema

        try:
            with self.connector.get_session() as session:
                self._set_schema(session, schema)

                order = session.execute(
                    select(Order).where(Order.order_id == order_id)
                ).scalar_one_or_none()

                if not order:
                    logger.warning(f"Order not found for deletion: {order_id}")
                    return False

                session.delete(order)
                session.flush()

                logger.info(f"Deleted order: {order_id}")
                return True

        except SQLAlchemyError as e:
            logger.error(f"Error deleting order: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to delete order: {str(e)}")

    # ============= Analytics Operations =============

    def get_customer_order_summary(
            self,
            customer_id: str,
            schema: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get summary statistics for a customer's orders"""
        schema = schema or self.default_schema

        try:
            with self.connector.get_session() as session:
                self._set_schema(session, schema)

                result = session.execute(
                    select(
                        func.count(Order.order_id).label('total_orders'),
                        func.sum(Order.total_amount).label('total_spent'),
                        func.avg(Order.total_amount).label('avg_order_value'),
                        func.max(Order.order_date).label('last_order_date')
                    ).where(Order.customer_id == customer_id)
                ).first()

                summary = {
                    'customer_id': customer_id,
                    'total_orders': result.total_orders or 0,
                    'total_spent': float(result.total_spent or 0),
                    'avg_order_value': float(result.avg_order_value or 0),
                    'last_order_date': result.last_order_date
                }

                logger.info(f"Generated order summary for customer {customer_id}")
                return summary

        except SQLAlchemyError as e:
            logger.error(f"Error generating summary: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to generate order summary: {str(e)}")

    # ============= Raw Query Execution (Use with caution) =============

    def execute_raw_query(
            self,
            query: str,
            params: Optional[Dict[str, Any]] = None,
            schema: Optional[str] = None
    ) -> List[Any]:
        """
        Execute a raw SQL query (use sparingly and with extreme caution)

        Args:
            query: SQL query string (use :param_name for parameters)
            params: Dictionary of parameter values
            schema: Database schema

        Returns:
            List of result rows

        Note: This method should only be used for complex queries
              that cannot be expressed using the ORM methods above.
              Always use parameterized queries to prevent SQL injection.
        """
        schema = schema or self.default_schema
        params = params or {}

        logger.warning(f"Executing raw query: {query[:100]}...")

        try:
            with self.connector.get_session() as session:
                self._set_schema(session, schema)

                result = session.execute(text(query), params)

                # Try to fetch results (for SELECT queries)
                try:
                    rows = result.fetchall()
                    logger.info(f"Raw query returned {len(rows)} rows")
                    return rows
                except Exception:
                    # For non-SELECT queries (INSERT, UPDATE, DELETE)
                    session.flush()
                    logger.info("Raw query executed successfully (no results)")
                    return []

        except SQLAlchemyError as e:
            logger.error(f"Raw query error: {str(e)}", exc_info=True)
            raise DatabaseError(f"Raw query execution failed: {str(e)}")
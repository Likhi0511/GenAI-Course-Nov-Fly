# usage_example.py
"""
Example usage of the DataManager with SQLAlchemy and Pydantic
"""
import logging
from datetime import datetime
from connector import PostgresConnector
from data_manager import DataManager, DataManagerError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def main():
    # Initialize connector
    connector = PostgresConnector(
        host="localhost",
        port=5432,
        database="your_database",
        user="your_user",
        password="your_password",
        pool_size=5
    )

    # Initialize DataManager
    dm = DataManager(connector, default_schema="public")

    try:
        # Create tables
        connector.create_tables(schema="public")

        # ===== Customer Operations =====

        # Create a customer
        customer_data = {
            "customer_id": "CUST001",
            "customer_name": "Alice Johnson",
            "email": "alice@example.com",
            "city": "Seattle",
            "state": "WA",
            "created_at": datetime.now()
        }

        customer = dm.create_customer(customer_data)
        logger.info(f"Created customer: {customer.customer_id}")

        # Search customers
        results = dm.search_customers(
            filters={"city": "Seattle"},
            limit=10
        )
        logger.info(f"Found {len(results)} customers in Seattle")

        # Update customer
        dm.update_customer(
            "CUST001",
            {"email": "alice.new@example.com"}
        )

        # Get customer with orders
        customer_with_orders = dm.get_customer_by_id(
            "CUST001",
            include_orders=True
        )

        # ===== Order Operations =====

        # Create an order
        order_data = {
            "order_id": "ORD001",
            "customer_id": "CUST001",
            "order_date": datetime.now(),
            "status": "pending",
            "total_amount": 299.99
        }

        order = dm.create_order(order_data)
        logger.info(f"Created order: {order.order_id}")

        # Get customer's orders
        customer_orders = dm.get_orders_by_customer("CUST001")
        logger.info(f"Customer has {len(customer_orders)} orders")

        # Get order summary
        summary = dm.get_customer_order_summary("CUST001")
        logger.info(f"Order summary: {summary}")

        # ===== Analytics Query Example =====

        # Execute a complex analytics query safely
        analytics_query = """
                          SELECT c.state, \
                                 COUNT(DISTINCT c.customer_id) as customer_count, \
                                 COUNT(o.order_id)             as order_count, \
                                 SUM(o.total_amount)           as total_revenue
                          FROM customers c
                                   LEFT JOIN orders o ON c.customer_id = o.customer_id
                          WHERE c.state = :state
                          GROUP BY c.state \
                          """

        results = dm.execute_raw_query(
            analytics_query,
            params={"state": "WA"}
        )

        logger.info(f"Analytics results: {results}")

    except DataManagerError as e:
        logger.error(f"DataManager error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
    finally:
        # Clean up
        connector.close()


if __name__ == "__main__":
    main()
# connector.py
from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine, MetaData
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool
import logging

logger = logging.getLogger(__name__)


class PostgresConnector:
    def __init__(
            self,
            host: str,
            port: int,
            database: str,
            user: str,
            password: str,
            pool_size: int = 5,
            max_overflow: int = 10,
            pool_timeout: int = 30,
            pool_recycle: int = 3600
    ):
        """
        Initialize PostgreSQL connector with connection pooling

        Args:
            host: Database host
            port: Database port
            database: Database name
            user: Database user
            password: Database password
            pool_size: Number of connections to maintain in pool
            max_overflow: Maximum overflow connections
            pool_timeout: Timeout for getting connection from pool
            pool_recycle: Recycle connections after this many seconds
        """
        connection_string = (
            f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"
        )

        self.engine = create_engine(
            connection_string,
            poolclass=QueuePool,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            pool_recycle=pool_recycle,
            echo=False,  # Set to True for SQL debugging
            future=True
        )

        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
            future=True
        )

        logger.info(f"Database connection pool initialized for {host}:{port}/{database}")

    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """
        Context manager for database sessions with automatic cleanup

        Yields:
            SQLAlchemy Session object
        """
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Session error: {str(e)}", exc_info=True)
            raise
        finally:
            session.close()

    def create_tables(self, schema: str = "public"):
        """Create all tables defined in Base metadata"""
        from models import Base

        # Set schema for all tables
        for table in Base.metadata.tables.values():
            table.schema = schema

        Base.metadata.create_all(self.engine)
        logger.info(f"Tables created in schema: {schema}")

    def drop_tables(self, schema: str = "public"):
        """Drop all tables defined in Base metadata"""
        from models import Base

        for table in Base.metadata.tables.values():
            table.schema = schema

        Base.metadata.drop_all(self.engine)
        logger.info(f"Tables dropped in schema: {schema}")

    def close(self):
        """Close all connections in the pool"""
        self.engine.dispose()
        logger.info("Database connection pool closed")
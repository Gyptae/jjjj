from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, BigInteger, Boolean,
    DateTime, Text, ForeignKey, Float, JSON
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base, relationship
from config import settings

# Преобразуем URL для async
db_url = settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://')

# Создаем движок БД
engine = create_async_engine(db_url, echo=False)

# Создаем фабрику сессий
async_session = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

Base = declarative_base()


class User(Base):
    """Модель пользователя"""
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_activity = Column(DateTime, default=datetime.utcnow)

    # Связи
    orders = relationship("Order", back_populates="user")


class BlockedUser(Base):
    """Модель заблокированных пользователей"""
    __tablename__ = 'blocked_users'

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    blocked_at = Column(DateTime, default=datetime.utcnow)
    reason = Column(Text, nullable=True)
    blocked_by = Column(BigInteger, nullable=False)


class Product(Base):
    """Модель товара"""
    __tablename__ = 'products'

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Float, nullable=False)
    image_url = Column(String(512), nullable=True)
    category = Column(String(100), nullable=True)
    in_stock = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Связи
    order_items = relationship("OrderItem", back_populates="product")


class Order(Base):
    """Модель заказа"""
    __tablename__ = 'orders'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    status = Column(String(50), default='pending')  # pending, confirmed, completed, cancelled
    total_amount = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    contact_info = Column(JSON, nullable=True)  # Контактная информация

    # Связи
    user = relationship("User", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    """Модель позиции заказа"""
    __tablename__ = 'order_items'

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey('orders.id'), nullable=False)
    product_id = Column(Integer, ForeignKey('products.id'), nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)  # Цена на момент заказа

    # Связи
    order = relationship("Order", back_populates="items")
    product = relationship("Product", back_populates="order_items")


class RateLimit(Base):
    """Модель для отслеживания лимитов"""
    __tablename__ = 'rate_limits'

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, nullable=False, index=True)
    action_type = Column(String(50), nullable=False)  # message, command
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)


class RequiredChannel(Base):
    """Модель обязательных каналов для подписки"""
    __tablename__ = 'required_channels'

    id = Column(Integer, primary_key=True)
    channel_id = Column(BigInteger, nullable=False, unique=True, index=True)  # ID канала (отрицательное число)
    channel_username = Column(String(255), nullable=True)  # @username канала
    channel_title = Column(String(255), nullable=True)  # Название канала
    channel_invite_link = Column(String(512), nullable=True)  # Пригласительная ссылка
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(BigInteger, nullable=False)  # Кто добавил (ADMIN_ID или TECH_MANAGER_ID)


async def init_db():
    """Инициализация базы данных"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    """Получить сессию БД"""
    async with async_session() as session:
        yield session
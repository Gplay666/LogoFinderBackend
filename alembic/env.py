# alembic/env.py
import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Импортируем ваш Base и ВСЕ модели (чтобы autogenerate их видел)
from app.db.base import Base
from app.models.detection import Detection  # обязательно, иначе таблица не попадёт в миграцию

# Загружаем конфиг alembic.ini
config = context.config

# Настраиваем логирование
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Указываем целевые метаданные
target_metadata = Base.metadata

def get_url():
    """Получить URL БД из alembic.ini или из переменной окружения."""
    # Можно использовать alembic.ini или подставить из config.py
    return os.getenv(
        "DATABASE_URL",
        config.get_main_option("sqlalchemy.url")
    )

def run_migrations_offline() -> None:
    """Запуск миграций в оффлайн-режиме (без подключения к БД)."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def do_run_migrations(connection: Connection) -> None:
    """Выполнить миграции, имея соединение."""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()

async def run_async_migrations() -> None:
    """Асинхронный раннер миграций (основной)."""
    # Получаем конфигурацию движка из alembic.ini (секция [alembic])
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()

def run_migrations_online() -> None:
    """Точка входа для онлайн-режима (вызывает асинхронный раннер)."""
    asyncio.run(run_async_migrations())

# Определяем, какой режим использовать
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
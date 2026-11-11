from alembic import context
from app.db import engine, Base
from app import models

if context.is_offline_mode():
    from app.config import settings

    context.configure(
        url=settings.database_url, target_metadata=Base.metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    with engine.connect() as connection:
        sqlite = connection.dialect.name == "sqlite"
        if sqlite:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
        context.configure(
            connection=connection, target_metadata=Base.metadata, compare_type=True
        )
        with context.begin_transaction():
            context.run_migrations()

        if sqlite:
            violations = connection.exec_driver_sql("PRAGMA foreign_key_check").all()
            if violations:
                raise RuntimeError("Migration violated foreign keys")
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()

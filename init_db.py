# init_db.py

from app.database import Base, engine
from app import models  # важно: чтобы все модели подгрузились

print("Создаю таблицы в базе данных...")
Base.metadata.create_all(bind=engine)
print("Готово!")

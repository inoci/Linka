#!/usr/bin/env python3
"""
Скрипт для обновления базы данных с новыми полями для настроек комментариев
"""

from app import app, db
from sqlalchemy import text

def update_database():
    with app.app_context():
        try:
            # Добавляем новые поля в таблицу community
            print("Добавляем поля для настроек комментариев...")
            
            # Проверяем, существуют ли уже поля
            result = db.session.execute(text("PRAGMA table_info(community)"))
            existing_columns = [row[1] for row in result.fetchall()]
            
            if 'comments_enabled' not in existing_columns:
                db.session.execute(text("ALTER TABLE community ADD COLUMN comments_enabled BOOLEAN DEFAULT 1"))
                print("✓ Добавлено поле comments_enabled")
            
            if 'profanity_filter' not in existing_columns:
                db.session.execute(text("ALTER TABLE community ADD COLUMN profanity_filter BOOLEAN DEFAULT 0"))
                print("✓ Добавлено поле profanity_filter")
            
            if 'hostile_filter' not in existing_columns:
                db.session.execute(text("ALTER TABLE community ADD COLUMN hostile_filter BOOLEAN DEFAULT 0"))
                print("✓ Добавлено поле hostile_filter")
            
            if 'keyword_filter' not in existing_columns:
                db.session.execute(text("ALTER TABLE community ADD COLUMN keyword_filter BOOLEAN DEFAULT 0"))
                print("✓ Добавлено поле keyword_filter")
            
            if 'banned_keywords' not in existing_columns:
                db.session.execute(text("ALTER TABLE community ADD COLUMN banned_keywords TEXT"))
                print("✓ Добавлено поле banned_keywords")
            
            db.session.commit()
            print("✓ База данных успешно обновлена!")
            
        except Exception as e:
            print(f"❌ Ошибка при обновлении базы данных: {e}")
            db.session.rollback()

if __name__ == '__main__':
    update_database()

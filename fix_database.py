#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
import os
from werkzeug.security import generate_password_hash

def fix_database():
    """Исправляем базу данных - создаем пользователя и исправляем creator_id сообществ"""
    
    # Путь к базе данных
    db_path = 'instance/linka.db'
    
    if not os.path.exists(db_path):
        print(f"База данных {db_path} не найдена!")
        return
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print("=== ИСПРАВЛЕНИЕ БАЗЫ ДАННЫХ ===")
        
        # Проверяем, есть ли пользователи
        cursor.execute("SELECT COUNT(*) FROM user")
        user_count = cursor.fetchone()[0]
        
        print(f"Пользователей в базе: {user_count}")
        
        if user_count == 0:
            print("Создаем первого пользователя...")
            
            # Создаем пользователя
            username = "admin"
            email = "admin@linka.local"
            password_hash = generate_password_hash("admin123")
            first_name = "Admin"
            last_name = "User"
            
            cursor.execute("""
                INSERT INTO user (username, email, password_hash, first_name, last_name)
                VALUES (?, ?, ?, ?, ?)
            """, (username, email, password_hash, first_name, last_name))
            
            # Получаем ID созданного пользователя
            cursor.execute("SELECT id FROM user WHERE username = ?", (username,))
            user_id = cursor.fetchone()[0]
            
            print(f"Пользователь создан с ID: {user_id}")
            
            # Теперь исправляем все сообщества, устанавливая правильный creator_id
            print("Исправляем creator_id для всех сообществ...")
            
            cursor.execute("UPDATE community SET creator_id = ? WHERE creator_id = 1", (user_id,))
            updated_count = cursor.commit()
            
            print(f"Обновлено сообществ: {cursor.rowcount}")
            
            # Проверяем результат
            cursor.execute("SELECT id, name, creator_id FROM community ORDER BY id")
            communities = cursor.fetchall()
            
            print(f"\nСообщества после исправления:")
            for community in communities:
                print(f"  ID: {community[0]}, Название: '{community[1]}', Creator ID: {community[2]}")
            
            # Проверяем пользователей
            cursor.execute("SELECT id, username, email FROM user ORDER BY id")
            users = cursor.fetchall()
            
            print(f"\nПользователи после исправления:")
            for user in users:
                print(f"  ID: {user[0]}, Username: '{user[1]}', Email: '{user[2]}'")
            
            conn.commit()
            print(f"\n✅ База данных исправлена!")
            print(f"Теперь вы можете войти с:")
            print(f"  Username: admin")
            print(f"  Password: admin123")
            
        else:
            print("Пользователи уже есть в базе. Проверяем сообщества...")
            
            cursor.execute("SELECT id, name, creator_id FROM community ORDER BY id")
            communities = cursor.fetchall()
            
            print(f"Сообщества:")
            for community in communities:
                print(f"  ID: {community[0]}, Название: '{community[1]}', Creator ID: {community[2]}")
        
        conn.close()
        
    except Exception as e:
        print(f"Ошибка: {e}")

if __name__ == "__main__":
    fix_database()

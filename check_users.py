#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
import os

def check_users_detailed():
    """Детальная проверка пользователей в базе данных"""
    
    # Путь к базе данных
    db_path = 'instance/linka.db'
    
    if not os.path.exists(db_path):
        print(f"База данных {db_path} не найдена!")
        return
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print("=== ДЕТАЛЬНАЯ ПРОВЕРКА ПОЛЬЗОВАТЕЛЕЙ ===")
        
        # Проверяем структуру таблицы user
        cursor.execute("PRAGMA table_info(user)")
        columns = cursor.fetchall()
        
        print("\nСтруктура таблицы user:")
        for col in columns:
            print(f"  {col[1]} {col[2]} {'NOT NULL' if col[3] else 'NULL'} {'DEFAULT ' + str(col[4]) if col[4] else ''}")
        
        # Проверяем всех пользователей с деталями
        cursor.execute("SELECT id, username, email, first_name, last_name FROM user ORDER BY id")
        users = cursor.fetchall()
        
        print(f"\nВсего пользователей: {len(users)}")
        for user in users:
            print(f"  ID: {user[0]}, Username: '{user[1]}', Email: '{user[2]}', First: '{user[3]}', Last: '{user[4]}'")
        
        # Проверяем, есть ли дубликаты username
        cursor.execute("SELECT username, COUNT(*) as count FROM user GROUP BY username HAVING count > 1")
        duplicates = cursor.fetchall()
        
        if duplicates:
            print(f"\n⚠️  ДУБЛИКАТЫ USERNAME:")
            for dup in duplicates:
                print(f"  Username: '{dup[0]}' встречается {dup[1]} раз")
        else:
            print(f"\n✅ Дубликатов username нет")
        
        # Проверяем последние созданные сообщества
        cursor.execute("SELECT id, name, creator_id, created_at FROM community ORDER BY created_at DESC LIMIT 5")
        recent_communities = cursor.fetchall()
        
        print(f"\nПоследние 5 созданных сообществ:")
        for comm in recent_communities:
            print(f"  ID: {comm[0]}, Название: '{comm[1]}', Creator ID: {comm[2]}, Создано: {comm[3]}")
        
        conn.close()
        
    except Exception as e:
        print(f"Ошибка: {e}")

if __name__ == "__main__":
    check_users_detailed()

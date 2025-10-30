#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
import os

def check_community_creator():
    """Проверяем проблему с creator_id в базе данных"""
    
    # Путь к базе данных
    db_path = 'instance/linka.db'
    
    if not os.path.exists(db_path):
        print(f"База данных {db_path} не найдена!")
        return
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print("=== ПРОВЕРКА СООБЩЕСТВ ===")
        
        # Проверяем структуру таблицы community
        cursor.execute("PRAGMA table_info(community)")
        columns = cursor.fetchall()
        
        print("\nСтруктура таблицы community:")
        for col in columns:
            print(f"  {col[1]} {col[2]} {'NOT NULL' if col[3] else 'NULL'} {'DEFAULT ' + str(col[4]) if col[4] else ''}")
        
        # Проверяем все сообщества
        cursor.execute("SELECT id, name, creator_id FROM community ORDER BY id")
        communities = cursor.fetchall()
        
        print(f"\nВсего сообществ: {len(communities)}")
        for community in communities:
            print(f"  ID: {community[0]}, Название: {community[1]}, Creator ID: {community[2]}")
        
        # Проверяем пользователей
        cursor.execute("SELECT id, username FROM user ORDER BY id")
        users = cursor.fetchall()
        
        print(f"\nВсего пользователей: {len(users)}")
        for user in users:
            print(f"  ID: {user[0]}, Username: {user[1]}")
        
        # Проверяем, есть ли ограничения по умолчанию
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='community'")
        table_sql = cursor.fetchone()
        
        if table_sql:
            print(f"\nSQL создания таблицы community:")
            print(table_sql[0])
        
        conn.close()
        
    except Exception as e:
        print(f"Ошибка: {e}")

if __name__ == "__main__":
    check_community_creator()

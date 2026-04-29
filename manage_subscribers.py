#!/usr/bin/env python3
import sqlite3
import sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import re

# Configuration
SUBSCRIBERS_FILE = Path("subscribers.txt")
DB_FILE = Path("stocks.db")
EASTERN = ZoneInfo("America/New_York")

def validate_email(email):
    """Validate email format."""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def ensure_db_table():
    """Ensure the email_subscribers table exists."""
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS email_subscribers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def add_subscriber(email):
    """Add email to subscribers.txt and database."""
    if not validate_email(email):
        raise ValueError(f"Invalid email format: {email}")
    
    # Add to txt file
    subscribers = set()
    if SUBSCRIBERS_FILE.exists():
        with open(SUBSCRIBERS_FILE, 'r', encoding='utf-8') as f:
            subscribers = set(line.strip() for line in f if line.strip() and not line.startswith('#'))
    
    subscribers.add(email)
    
    with open(SUBSCRIBERS_FILE, 'w', encoding='utf-8') as f:
        for sub in sorted(subscribers):
            f.write(f"{sub}\n")
    
    # Add to database
    ensure_db_table()
    conn = sqlite3.connect(DB_FILE)
    try:
        conn.execute("""
            INSERT OR IGNORE INTO email_subscribers (email, created_at)
            VALUES (?, ?)
        """, (email, datetime.now(EASTERN).isoformat()))
        conn.commit()
    finally:
        conn.close()
    
    print(f"✅ Added subscriber: {email}")

def remove_subscriber(email):
    """Remove email from subscribers.txt and database."""
    if not validate_email(email):
        raise ValueError(f"Invalid email format: {email}")
    
    # Remove from txt file
    subscribers = set()
    if SUBSCRIBERS_FILE.exists():
        with open(SUBSCRIBERS_FILE, 'r', encoding='utf-8') as f:
            subscribers = set(line.strip() for line in f if line.strip() and not line.startswith('#'))
    
    subscribers.discard(email)
    
    with open(SUBSCRIBERS_FILE, 'w', encoding='utf-8') as f:
        for sub in sorted(subscribers):
            f.write(f"{sub}\n")
    
    # Remove from database
    ensure_db_table()
    conn = sqlite3.connect(DB_FILE)
    try:
        conn.execute("""
            DELETE FROM email_subscribers WHERE email = ?
        """, (email,))
        conn.commit()
    finally:
        conn.close()
    
    print(f"✅ Removed subscriber: {email}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python manage_subscribers.py <action> <email>")
        print("  action: 'add' or 'remove'")
        sys.exit(1)
    
    action = sys.argv[1].lower()
    email = sys.argv[2].lower()
    
    try:
        if action == "add":
            add_subscriber(email)
        elif action == "remove":
            remove_subscriber(email)
        else:
            print(f"❌ Unknown action: {action}")
            sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

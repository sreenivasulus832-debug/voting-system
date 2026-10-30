import sqlite3
import os
from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = os.path.join(os.path.dirname(__file__), 'voting.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()

    # Admin table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Elections table (No hardcoded names!)
    cur.execute('''
        CREATE TABLE IF NOT EXISTS elections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT CHECK(status IN ('draft', 'active', 'paused', 'closed')) DEFAULT 'draft',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Positions / Roles table (Dynamic per election)
    cur.execute('''
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            election_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            display_order INTEGER DEFAULT 0,
            FOREIGN KEY (election_id) REFERENCES elections(id) ON DELETE CASCADE
        )
    ''')

    # Candidates table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            manifesto TEXT,
            photo_url TEXT,
            FOREIGN KEY (position_id) REFERENCES positions(id) ON DELETE CASCADE
        )
    ''')

    # Students / Voters registry (No hardcoded student data!)
    cur.execute('''
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            access_code TEXT,
            status TEXT CHECK(status IN ('approved', 'pending', 'blocked')) DEFAULT 'approved',
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Track who voted in which election (To prevent duplicate voting while preserving secret ballot)
    cur.execute('''
        CREATE TABLE IF NOT EXISTS election_voters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            election_id INTEGER NOT NULL,
            student_id TEXT NOT NULL,
            voted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(election_id, student_id),
            FOREIGN KEY (election_id) REFERENCES elections(id) ON DELETE CASCADE
        )
    ''')

    # Secret Ballots / Votes table (Votes stored decoupled from student ID for privacy)
    cur.execute('''
        CREATE TABLE IF NOT EXISTS votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            election_id INTEGER NOT NULL,
            position_id INTEGER NOT NULL,
            candidate_id INTEGER NOT NULL,
            receipt_code TEXT NOT NULL,
            cast_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (election_id) REFERENCES elections(id) ON DELETE CASCADE,
            FOREIGN KEY (position_id) REFERENCES positions(id) ON DELETE CASCADE,
            FOREIGN KEY (candidate_id) REFERENCES candidates(id) ON DELETE CASCADE
        )
    ''')

    # Audit Logs for Admin Monitoring
    cur.execute('''
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Ensure default admin exists (credentials: admin / admin123)
    cur.execute("SELECT id FROM admins WHERE username = ?", ('admin',))
    if not cur.fetchone():
        hashed = generate_password_hash('admin123')
        cur.execute("INSERT INTO admins (username, password_hash) VALUES (?, ?)", ('admin', hashed))
        cur.execute("INSERT INTO audit_logs (action, details) VALUES (?, ?)", 
                    ('SYSTEM_INIT', 'System initialized with default administrator account.'))

    conn.commit()
    conn.close()

def log_audit(action, details):
    conn = get_db()
    conn.execute("INSERT INTO audit_logs (action, details) VALUES (?, ?)", (action, details))
    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()
    print("Database initialized successfully.")

import sqlite3
conn = sqlite3.connect('instance/ticketing.db')
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = [row[0] for row in cursor.fetchall()]
print("Tables in database:")
for table in tables:
    print(f"  - {table}")
    # Get columns for each table
    cursor.execute(f"PRAGMA table_info({table});")
    columns = cursor.fetchall()
    if columns:
        print("    Columns:")
        for col in columns:
            print(f"      {col[1]} ({col[2]})")
conn.close()
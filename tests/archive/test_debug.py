import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.connection import DBConnection
from database.vector_store import VectorStore
from config import Config

conn = DBConnection(
    host=Config.DB_HOST,
    port=Config.DB_PORT,
    schema=Config.DB_SCHEMA,
    dbname=Config.DB_NAME,
    user=Config.DB_USER,
    password=Config.DB_PASSWORD
)
conn.connect()

# Clean up
vs = VectorStore(conn)
for t in ['my_custom_ent', 'my_custom_std']:
    vs.drop_vector_table(t)

# Create
vs.create_vector_table('my_custom_ent', table_type='enterprise')
vs.create_vector_table('my_custom_std', table_type='standard')

# Check existence
print('Check my_custom_ent exists:', vs.check_table_exists('my_custom_ent'))
print('Check my_custom_std exists:', vs.check_table_exists('my_custom_std'))

# Direct query
cursor = conn.execute(
    "SELECT table_name FROM information_schema.tables WHERE table_schema = %s AND table_name LIKE '%%vector%%'",
    (Config.DB_SCHEMA,)
)
if cursor:
    results = cursor.fetchall()
    print('Direct query results:', [r['table_name'] for r in results])

# Check all tables
cursor = conn.execute(
    "SELECT table_name, table_schema FROM information_schema.tables WHERE table_name LIKE '%%vector%%'"
)
if cursor:
    results = cursor.fetchall()
    print('All vector tables:', [(r['table_name'], r['table_schema']) for r in results])

# Clean up
for t in ['my_custom_ent', 'my_custom_std']:
    vs.drop_vector_table(t)
conn.close()

import sqlite3
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parents[3] / "data"
DATABASE_PATH = DATA_DIR / "freya_memory.db"


class MemoryManager:
    def __init__(self):
        DATA_DIR.mkdir(exist_ok=True)

        self.connection = sqlite3.connect(DATABASE_PATH)

        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        self.connection.commit()

    def add_memory(self, content):
        self.connection.execute(
            "INSERT INTO memories (content) VALUES (?)",
            (content,),
        )

        self.connection.commit()

    def get_memories(self):
        cursor = self.connection.execute(
            """
            SELECT content
            FROM memories
            ORDER BY created_at ASC
            """
        )

        return [row[0] for row in cursor.fetchall()]
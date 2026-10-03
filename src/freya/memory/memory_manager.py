import json
import math
import sqlite3
from pathlib import Path

import ollama

from config import EMBEDDING_MODEL


DATA_DIR = Path(__file__).resolve().parents[3] / "data"
DATABASE_PATH = DATA_DIR / "freya_memory.db"

DEFAULT_MEMORY_LIMIT = 3
DEFAULT_SIMILARITY_THRESHOLD = 0.50


class MemoryManager:
    def __init__(self):
        DATA_DIR.mkdir(exist_ok=True)

        self.connection = sqlite3.connect(DATABASE_PATH)

        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                embedding TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        self._upgrade_database()
        self.connection.commit()

        self._embed_existing_memories()

    def _upgrade_database(self):
        cursor = self.connection.execute(
            "PRAGMA table_info(memories)"
        )

        columns = [
            row[1]
            for row in cursor.fetchall()
        ]

        if "embedding" not in columns:
            self.connection.execute(
                "ALTER TABLE memories ADD COLUMN embedding TEXT"
            )

            self.connection.commit()

    def _create_embedding(self, text):
        response = ollama.embed(
            model=EMBEDDING_MODEL,
            input=text,
        )

        return response["embeddings"][0]

    def _embed_existing_memories(self):
        cursor = self.connection.execute(
            """
            SELECT id, content
            FROM memories
            WHERE embedding IS NULL
            """
        )

        for memory_id, content in cursor.fetchall():
            embedding = self._create_embedding(content)

            self.connection.execute(
                """
                UPDATE memories
                SET embedding = ?
                WHERE id = ?
                """,
                (
                    json.dumps(embedding),
                    memory_id,
                ),
            )

        self.connection.commit()

    def add_memory(self, content):
        existing = self.connection.execute(
            """
            SELECT id
            FROM memories
            WHERE LOWER(content) = LOWER(?)
            """,
            (content,),
        ).fetchone()

        if existing:
            return existing[0]

        embedding = self._create_embedding(content)

        cursor = self.connection.execute(
            """
            INSERT INTO memories (content, embedding)
            VALUES (?, ?)
            """,
            (
                content,
                json.dumps(embedding),
            ),
        )

        self.connection.commit()

        return cursor.lastrowid

    def get_all_memories(self):
        cursor = self.connection.execute(
            """
            SELECT id, content, created_at
            FROM memories
            ORDER BY id ASC
            """
        )

        return cursor.fetchall()

    def delete_memory(self, memory_id):
        cursor = self.connection.execute(
            """
            DELETE FROM memories
            WHERE id = ?
            """,
            (memory_id,),
        )

        self.connection.commit()

        return cursor.rowcount > 0

    def search_memories(
        self,
        query,
        limit=DEFAULT_MEMORY_LIMIT,
        threshold=DEFAULT_SIMILARITY_THRESHOLD,
    ):
        query_embedding = self._create_embedding(query)

        cursor = self.connection.execute(
            """
            SELECT content, embedding
            FROM memories
            WHERE embedding IS NOT NULL
            """
        )

        scored_memories = []

        for content, embedding_json in cursor.fetchall():
            memory_embedding = json.loads(
                embedding_json
            )

            similarity = self._cosine_similarity(
                query_embedding,
                memory_embedding,
            )

            if similarity >= threshold:
                scored_memories.append(
                    (
                        similarity,
                        content,
                    )
                )

        scored_memories.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        return [
            memory
            for _, memory in scored_memories[:limit]
        ]

    @staticmethod
    def _cosine_similarity(
        vector_a,
        vector_b,
    ):
        dot_product = sum(
            a * b
            for a, b in zip(
                vector_a,
                vector_b,
            )
        )

        magnitude_a = math.sqrt(
            sum(
                a * a
                for a in vector_a
            )
        )

        magnitude_b = math.sqrt(
            sum(
                b * b
                for b in vector_b
            )
        )

        if magnitude_a == 0 or magnitude_b == 0:
            return 0.0

        return dot_product / (
            magnitude_a * magnitude_b
        )
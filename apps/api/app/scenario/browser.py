import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass
class BrowserDocument:
    ref_id: str
    url: str
    title: str
    source: str
    path: str
    content: str


class OfflineBrowser:
    def __init__(self, index: Path) -> None:
        self.index = index

    @classmethod
    def build(cls, mirror: Path, index: Path) -> "OfflineBrowser":
        index.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(index)
        connection.executescript(
            """
            DROP TABLE IF EXISTS documents;
            DROP TABLE IF EXISTS documents_fts;
            CREATE TABLE documents (
                ref_id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                source TEXT NOT NULL,
                path TEXT NOT NULL,
                content TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE documents_fts USING fts5(
                ref_id UNINDEXED, title, content, tokenize='porter unicode61'
            );
            """
        )
        for number, path in enumerate(sorted(mirror.rglob("*"))):
            if not path.is_file():
                continue
            content = path.read_text(encoding="utf-8", errors="replace")
            title = first_heading(content) or path.stem
            ref_id = f"offline-{number:06d}"
            source = path.relative_to(mirror).parts[0]
            url = f"https://offline.invalid/{path.relative_to(mirror).as_posix()}"
            connection.execute(
                "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?)",
                (ref_id, url, title, source, str(path), content),
            )
            connection.execute(
                "INSERT INTO documents_fts VALUES (?, ?, ?)",
                (ref_id, title, content),
            )
        connection.commit()
        connection.close()
        return cls(index)

    def search(self, query: str, limit: int = 20) -> list[dict[str, str]]:
        connection = sqlite3.connect(self.index)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """
                SELECT d.ref_id, d.url, d.title, d.source,
                       snippet(documents_fts, 2, '[', ']', ' … ', 18) AS snippet
                FROM documents_fts
                JOIN documents d ON d.ref_id = documents_fts.ref_id
                WHERE documents_fts MATCH ?
                ORDER BY bm25(documents_fts)
                LIMIT ?
                """,
                (fts_query(query), min(limit, 50)),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        finally:
            connection.close()
        return [dict(row) for row in rows]

    def open(self, ref_id: str) -> BrowserDocument | None:
        connection = sqlite3.connect(self.index)
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM documents WHERE ref_id = ?", (ref_id,)).fetchone()
        connection.close()
        return BrowserDocument(**dict(row)) if row else None

    def ref_for_url(self, url: str) -> str | None:
        connection = sqlite3.connect(self.index)
        row = connection.execute(
            "SELECT ref_id FROM documents WHERE url = ?",
            (url,),
        ).fetchone()
        connection.close()
        return str(row[0]) if row else None

    def find(self, ref_id: str, pattern: str) -> list[dict[str, str | int]]:
        document = self.open(ref_id)
        if not document:
            return []
        matches = []
        for line_number, line in enumerate(document.content.splitlines(), 1):
            if pattern.casefold() in line.casefold():
                matches.append({"line": line_number, "text": line[:500]})
                if len(matches) >= 50:
                    break
        return matches


def first_heading(content: str) -> str | None:
    match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    return match.group(1).strip() if match else None


def fts_query(value: str) -> str:
    tokens = re.findall(r"[\w-]+", value, re.UNICODE)
    return " OR ".join(f'"{token}"' for token in tokens[:12]) or '""'

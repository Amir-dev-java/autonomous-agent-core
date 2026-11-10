"""Local repository indexing and lexical RAG retrieval with SQLite persistence."""

from __future__ import annotations

import hashlib
import math
import os
import re
import sqlite3
import configparser
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class RetrievedChunk:
    path: str
    content: str
    score: float


@dataclass(frozen=True)
class RetrievalResult:
    chunks: tuple[RetrievedChunk, ...]
    query_coverage: float
    indexed_files: int
    indexed_chunks: int


class CodebaseRAG:
    """Indexes source chunks and retrieves task-relevant context without external APIs."""

    EXCLUDED_DIRS = {
        ".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build",
        ".next", ".idea", ".vscode", "coverage", "workspaces", "target",
    }
    ALLOWED_SUFFIXES = {
        ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".scss",
        ".json", ".toml", ".yaml", ".yml", ".md", ".txt", ".java", ".kt", ".go",
        ".rs", ".cs", ".php", ".rb", ".sql", ".sh", ".bat", ".ps1", ".xml",
        ".properties", ".vue", ".svelte", ".astro", ".svg",
    }
    EXCLUDED_NAMES = {"config.toml", "id_rsa", "id_ed25519", "credentials", "secrets.json"}
    MAX_FILES = 500
    MAX_FILE_BYTES = 512_000
    MAX_TOTAL_BYTES = 8 * 1024 * 1024
    CHUNK_CHARS = 1800
    CHUNK_OVERLAP = 240
    MAX_RESULTS = 8
    MAX_RESULT_CHARS = 24_000

    def __init__(self, database: str | Path) -> None:
        self.database = str(database)
        if self.database != ":memory:":
            Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        with self._session() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS rag_documents (
                    repository TEXT NOT NULL,
                    path TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    PRIMARY KEY(repository, path)
                );
                CREATE TABLE IF NOT EXISTS rag_chunks (
                    repository TEXT NOT NULL,
                    path TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    PRIMARY KEY(repository, path, chunk_index)
                );
                CREATE INDEX IF NOT EXISTS rag_chunks_repository
                    ON rag_chunks(repository);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _repository_key(root: Path) -> str:
        """Group fresh local clones by origin without storing a possibly secret URL."""
        git_config = root / ".git" / "config"
        if git_config.is_file():
            parser = configparser.RawConfigParser()
            try:
                parser.read(git_config, encoding="utf-8")
                origin = parser.get('remote "origin"', "url", fallback="").strip()
            except (configparser.Error, OSError):
                origin = ""
            if origin:
                return "origin:" + hashlib.sha256(origin.encode("utf-8")).hexdigest()
        return "path:" + str(root)

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return [token.casefold() for token in re.findall(r"[^\W_]+", text, flags=re.UNICODE)
                if len(token) > 1]

    @classmethod
    def _chunks(cls, text: str) -> list[str]:
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = min(start + cls.CHUNK_CHARS, len(text))
            if end < len(text):
                boundary = text.rfind("\n", start + cls.CHUNK_CHARS // 2, end)
                if boundary > start:
                    end = boundary
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(text):
                break
            start = max(start + 1, end - cls.CHUNK_OVERLAP)
        return chunks

    def _scan(self, root: Path) -> dict[str, tuple[str, list[str]]]:
        found: dict[str, tuple[str, list[str]]] = {}
        total_bytes = 0
        for directory, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = sorted(name for name in dirs
                             if name not in self.EXCLUDED_DIRS
                             and not (Path(directory) / name).is_symlink())
            for name in sorted(files):
                source = Path(directory) / name
                if (source.is_symlink() or name.casefold() in self.EXCLUDED_NAMES
                        or name.casefold().startswith(".env")
                        or source.suffix.casefold() not in self.ALLOWED_SUFFIXES):
                    continue
                try:
                    raw = source.read_bytes()
                except OSError:
                    continue
                if (not raw or b"\0" in raw or len(raw) > self.MAX_FILE_BYTES
                        or total_bytes + len(raw) > self.MAX_TOTAL_BYTES):
                    continue
                relative = source.relative_to(root).as_posix()
                content = raw.decode("utf-8", errors="replace")
                digest = hashlib.sha256(raw).hexdigest()
                found[relative] = (digest, self._chunks(content))
                total_bytes += len(raw)
                if len(found) >= self.MAX_FILES:
                    return found
        return found

    def index(self, repository: str | Path) -> tuple[int, int]:
        root = Path(repository).expanduser().resolve()
        if not root.is_dir():
            raise ValueError("RAG repository must be an existing directory")
        scanned = self._scan(root)
        repo_key = self._repository_key(root)
        with self._session() as connection:
            existing = {
                row["path"]: row["digest"] for row in connection.execute(
                    "SELECT path, digest FROM rag_documents WHERE repository = ?", (repo_key,)
                )
            }
            removed = set(existing) - set(scanned)
            changed = {path for path, (digest, _chunks) in scanned.items()
                       if existing.get(path) != digest}
            for path in removed:
                connection.execute(
                    "DELETE FROM rag_chunks WHERE repository = ? AND path = ?", (repo_key, path)
                )
                connection.execute(
                    "DELETE FROM rag_documents WHERE repository = ? AND path = ?", (repo_key, path)
                )
            for path in changed:
                digest, chunks = scanned[path]
                connection.execute(
                    "INSERT INTO rag_documents(repository,path,digest) VALUES(?,?,?) "
                    "ON CONFLICT(repository,path) DO UPDATE SET digest=excluded.digest",
                    (repo_key, path, digest),
                )
                connection.execute(
                    "DELETE FROM rag_chunks WHERE repository = ? AND path = ?", (repo_key, path)
                )
                connection.executemany(
                    "INSERT INTO rag_chunks(repository,path,chunk_index,content) VALUES(?,?,?,?)",
                    [(repo_key, path, index, chunk) for index, chunk in enumerate(chunks)],
                )
        return len(scanned), sum(len(chunks) for _digest, chunks in scanned.values())

    def retrieve(self, repository: str | Path, query: str) -> RetrievalResult:
        root = Path(repository).expanduser().resolve()
        indexed_files, indexed_chunks = self.index(root)
        query_tokens = set(self._tokens(query))
        if not query_tokens:
            return RetrievalResult((), 0.0, indexed_files, indexed_chunks)
        with self._session() as connection:
            rows = connection.execute(
                "SELECT path, content FROM rag_chunks WHERE repository = ?",
                (self._repository_key(root),),
            ).fetchall()
        if not rows:
            return RetrievalResult((), 0.0, indexed_files, indexed_chunks)

        tokenized = [self._tokens(row["content"]) for row in rows]
        document_frequency: dict[str, int] = {}
        for tokens in tokenized:
            for token in query_tokens.intersection(tokens):
                document_frequency[token] = document_frequency.get(token, 0) + 1
        average_length = sum(map(len, tokenized)) / max(1, len(tokenized))
        scored: list[tuple[float, sqlite3.Row, list[str]]] = []
        for row, tokens in zip(rows, tokenized):
            frequencies: dict[str, int] = {}
            for token in tokens:
                if token in query_tokens:
                    frequencies[token] = frequencies.get(token, 0) + 1
            score = 0.0
            length = len(tokens)
            for token, frequency in frequencies.items():
                df = document_frequency[token]
                inverse = math.log(1 + (len(rows) - df + 0.5) / (df + 0.5))
                denominator = frequency + 1.2 * (1 - 0.75 + 0.75 * length / max(1, average_length))
                score += inverse * frequency * 2.2 / denominator
            if score > 0:
                scored.append((score, row, tokens))
        scored.sort(key=lambda item: item[0], reverse=True)
        chosen: list[RetrievedChunk] = []
        covered: set[str] = set()
        total_chars = 0
        for score, row, tokens in scored:
            content = row["content"]
            if total_chars + len(content) > self.MAX_RESULT_CHARS:
                continue
            chosen.append(RetrievedChunk(row["path"], content, score))
            covered.update(query_tokens.intersection(tokens))
            total_chars += len(content)
            if len(chosen) >= self.MAX_RESULTS:
                break
        return RetrievalResult(
            tuple(chosen), len(covered) / len(query_tokens), indexed_files, indexed_chunks
        )

    @staticmethod
    def format_context(result: RetrievalResult) -> str:
        if not result.chunks:
            return "No relevant source chunks were retrieved."
        sections = [
            f"Retrieval evaluator: {len(result.chunks)} chunks selected; "
            f"query term coverage {result.query_coverage:.0%}; "
            f"indexed {result.indexed_files} files / {result.indexed_chunks} chunks.",
        ]
        for chunk in result.chunks:
            sections.append(f"\n--- {chunk.path} (relevance {chunk.score:.3f}) ---\n{chunk.content}")
        return "\n".join(sections)

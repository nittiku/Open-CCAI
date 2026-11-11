from pathlib import Path
from typing import Protocol
from .config import settings


class Storage(Protocol):
    def put(self, key: str, content: bytes): ...
    def read(self, key: str) -> bytes: ...
    def delete(self, key: str): ...


class LocalStorage:
    def path(self, key):
        if not key or "/" in key or "\\" in key or key.startswith("."):
            raise ValueError("Invalid storage key")
        root = Path(settings.storage_path)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        return root / key

    def put(self, key, content):
        p = self.path(key)
        p.write_bytes(content)
        p.chmod(0o600)

    def read(self, key):
        return self.path(key).read_bytes()

    def delete(self, key):
        self.path(key).unlink(missing_ok=True)


storage: Storage = LocalStorage()

import json
import os
from typing import Optional


class UserKeyManager:
    """Менеджер API ключей пользователей"""

    def __init__(self, storage_file="user_keys.json"):
        self.storage_file = storage_file
        self.keys = {}  # {user_id: {"api_key": "...", "created_at": timestamp}}
        self._load()

    def _load(self):
        """Загружает ключи из файла"""
        if os.path.exists(self.storage_file):
            try:
                with open(self.storage_file, 'r', encoding='utf-8') as f:
                    self.keys = json.load(f)
            except:
                self.keys = {}

    def _save(self):
        """Сохраняет ключи в файл"""
        with open(self.storage_file, 'w', encoding='utf-8') as f:
            json.dump(self.keys, f, ensure_ascii=False, indent=2)

    def set_key(self, user_id: int, api_key: str) -> bool:
        """Сохраняет API ключ для пользователя"""
        if not api_key or len(api_key) < 20:
            return False

        self.keys[str(user_id)] = {
            "api_key": api_key,
            "created_at": time.time()
        }
        self._save()
        return True

    def get_key(self, user_id: int) -> Optional[str]:
        """Возвращает API ключ пользователя"""
        key_data = self.keys.get(str(user_id))
        if key_data:
            return key_data["api_key"]
        return None

    def has_key(self, user_id: int) -> bool:
        """Проверяет, есть ли у пользователя ключ"""
        return str(user_id) in self.keys

    def delete_key(self, user_id: int):
        """Удаляет ключ пользователя"""
        if str(user_id) in self.keys:
            del self.keys[str(user_id)]
            self._save()
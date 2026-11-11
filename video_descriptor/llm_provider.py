"""Small external-provider contract. Discovery never performs generation or downloads."""
from typing import Protocol


class Provider(Protocol):
    def connection(self) -> str: ...
    def models(self) -> list[dict]: ...
    def verify(self, model: str) -> None: ...


def require_model(provider: Provider, model: str):
    if not model or model not in {item['id'] for item in provider.models()}:
        raise ValueError('Выбранная модель отсутствует на сервере. Обновите список и выберите модель.')

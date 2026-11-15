"""The subscription store, read over its REST interface (PostgREST, as Supabase exposes it).

Browsers write to the store through two functions, push_subscribe and push_unsubscribe (see schema.sql).
Only this module, holding the service key, can list or delete rows.
"""

from dataclasses import dataclass

import requests

TIMEOUT = 30


@dataclass(frozen=True)
class Subscription:
    endpoint: str
    p256dh: str
    auth: str


@dataclass(frozen=True)
class Store:
    api: str  # e.g. https://<project>.supabase.co/rest/v1
    service_key: str

    @property
    def _headers(self) -> dict[str, str]:
        return {"apikey": self.service_key, "Authorization": f"Bearer {self.service_key}"}

    def subscriptions(self) -> list[Subscription]:
        response = requests.get(
            f"{self.api}/push_subscriptions",
            params={"select": "endpoint,p256dh,auth"},
            headers=self._headers,
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        return [Subscription(**row) for row in response.json()]

    def remove(self, endpoint: str) -> None:
        response = requests.delete(
            f"{self.api}/push_subscriptions",
            params={"endpoint": f"eq.{endpoint}"},
            headers=self._headers,
            timeout=TIMEOUT,
        )
        response.raise_for_status()

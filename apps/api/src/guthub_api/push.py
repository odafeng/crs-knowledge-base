"""Web Push subscriptions for new stories (C5 #95).

A browser that turns push on sends its subscription here; turning it off removes it. No sign-in: a subscription
names a browser, not a person, and is never linked to an account (privacy policy). Announcing stories is a scheduled
job (guthub_api.announce), not part of the API.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, StringConstraints

from guthub_api.db import Conn, get_conn

router = APIRouter()

type Db = Annotated[Conn, Depends(get_conn)]

# Same rules as the table (supabase/migrations/20261117020000_push_subscriptions.sql): only the push services browsers
# use, since the sender posts to this URL; keys in the base64url form browsers produce.
PUSH_SERVICE = r"^https://([a-z0-9-]+\.)*(googleapis\.com|mozilla\.com|push\.apple\.com|windows\.com)/"
type Endpoint = Annotated[str, StringConstraints(max_length=2048, pattern=PUSH_SERVICE)]
NO_STORE = {"Cache-Control": "no-store"}


class PushKeys(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    p256dh: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{80,100}$")]
    auth: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{16,32}$")]


class PushSubscription(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    endpoint: Endpoint
    keys: PushKeys


class PushEndpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    endpoint: Endpoint


@router.put("/push/subscription", status_code=204)
def subscribe(subscription: PushSubscription, db: Db, response: Response) -> None:
    # Browsers may renew the keys of an existing endpoint; the newest keys win.
    response.headers.update(NO_STORE)
    db.execute(
        "insert into app.push_subscriptions (endpoint, p256dh, auth) values (%s, %s, %s)"
        " on conflict (endpoint) do update set p256dh = excluded.p256dh, auth = excluded.auth",
        (subscription.endpoint, subscription.keys.p256dh, subscription.keys.auth),
    )


@router.delete("/push/subscription", status_code=204)
def unsubscribe(subscription: PushEndpoint, db: Db, response: Response) -> None:
    # Answers the same whether or not the endpoint was stored, so it reveals nothing about other browsers.
    response.headers.update(NO_STORE)
    db.execute("delete from app.push_subscriptions where endpoint = %s", (subscription.endpoint,))

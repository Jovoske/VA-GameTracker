"""What the app calls a person, until hunters can name themselves.

Accounts are email addresses, and "pedro.garcia@gmail.com marked a photo" reads
like a mail server. The first word of the address does until real names exist:
pedro.garcia@… is "Pedro", jmartin84@… is "Jmartin". An address with no letters
before the @ (or no person at all, when the account was removed) is "Hunter".
"""
from __future__ import annotations

import re

from app.i18n import t

_CHUNKS = re.compile(r"[._+\-0-9]+")
# "Hunter", in the language being written in.
FALLBACK = "people.hunter"
MAX_LEN = 24


def name_for(user) -> str:
    """The capitalised first chunk of the email's local part, or "Hunter"."""
    email = (getattr(user, "email", None) or "") if user is not None else ""
    local = email.split("@", 1)[0]
    for chunk in _CHUNKS.split(local):
        if chunk:
            return chunk[:MAX_LEN].capitalize()
    return t(FALLBACK)

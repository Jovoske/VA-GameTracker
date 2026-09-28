"""A refusal the app acts on, not only shows.

Its words are in the reader's language (app.i18n), so the app cannot tell one
refusal from another by them. `code` names it the same in every language, next to
the words: {"detail": "Tämä kuva on merkitty tyhjäksi…", "code": "empty_frame"}.
An app that only shows the words reads `detail` as it always did.
"""
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


class Refusal(HTTPException):
    """An HTTPException with a `code` the app branches on ("empty_frame",
    "signed_out")."""

    def __init__(self, status_code: int, code: str, detail: str,
                 headers: dict[str, str] | None = None) -> None:
        super().__init__(status_code, detail, headers)
        self.code = code


async def refusal_handler(_: Request, exc: Refusal) -> JSONResponse:
    return JSONResponse({"detail": exc.detail, "code": exc.code},
                        status_code=exc.status_code, headers=exc.headers)

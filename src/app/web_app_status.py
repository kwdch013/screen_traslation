from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WebAppStatus:
    state: str
    error_message: str | None
    session_token: str | None
    session_token_valid: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "error_message": self.error_message,
            "session_token": self.session_token,
            "session_token_valid": self.session_token_valid,
        }

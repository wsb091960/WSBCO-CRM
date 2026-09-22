import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    account_sid: str
    auth_token: str
    twilio_number: str
    agent_number: str
    base_url: str
    validate_signatures: bool

    @property
    def is_complete(self) -> bool:
        return all(
            [
                self.account_sid,
                self.auth_token,
                self.twilio_number,
                self.agent_number,
                self.base_url,
            ]
        )


def get_settings() -> Settings:
    return Settings(
        account_sid=os.getenv("TWILIO_ACCOUNT_SID", "").strip(),
        auth_token=os.getenv("TWILIO_AUTH_TOKEN", "").strip(),
        twilio_number=os.getenv("TWILIO_PHONE_NUMBER", "").strip(),
        agent_number=os.getenv("AGENT_PHONE_NUMBER", "").strip(),
        base_url=os.getenv("BASE_URL", "").strip().rstrip("/"),
        validate_signatures=(
            os.getenv("VALIDATE_TWILIO_SIGNATURES", "false").strip().lower()
            == "true"
        ),
    )

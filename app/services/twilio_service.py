from twilio.rest import Client

from app.services.settings import Settings


class TwilioConfigurationError(RuntimeError):
    pass


class TwilioDialer:
    def __init__(self, settings: Settings) -> None:
        if not settings.is_complete:
            raise TwilioConfigurationError(
                "Twilio is not configured. Copy .env.example to .env and "
                "enter the Twilio and agent phone numbers."
            )

        self.settings = settings
        self.client = Client(settings.account_sid, settings.auth_token)

    def start_agent_first_call(self, call_log_id: int):
        connect_url = (
            f"{self.settings.base_url}/twilio/connect/{call_log_id}"
        )
        callback_url = (
            f"{self.settings.base_url}/twilio/status/{call_log_id}"
        )

        return self.client.calls.create(
            to=self.settings.agent_number,
            from_=self.settings.twilio_number,
            url=connect_url,
            method="POST",
            status_callback=callback_url,
            status_callback_method="POST",
            status_callback_event=[
                "initiated",
                "ringing",
                "answered",
                "completed",
            ],
        )

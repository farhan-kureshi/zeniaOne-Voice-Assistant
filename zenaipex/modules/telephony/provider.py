from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

class TelephonyProvider(ABC):
    """Abstract base class for telephony providers (e.g., Twilio, Plivo, Mock)."""

    @abstractmethod
    async def create_call(self, to_phone: str, from_phone: str, webhook_url: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Initiate an outbound call and return the provider's call ID."""
        pass

    @abstractmethod
    async def end_call(self, provider_call_id: str) -> bool:
        """Terminate an active call."""
        pass

    @abstractmethod
    async def get_call_status(self, provider_call_id: str) -> str:
        """Retrieve the current status of the call from the provider."""
        pass

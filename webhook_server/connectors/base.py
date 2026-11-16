from abc import ABC, abstractmethod
from typing import Any
import logging

logger = logging.getLogger(__name__)


class BaseConnector(ABC):
    """Abstract base class for all integration connectors."""
    
    connector_type: str = "base"
    
    @abstractmethod
    async def execute(self, function_name: str, arguments: dict[str, Any], config: dict[str, Any]) -> str:
        """
        Execute a function call and return a natural language result string.
        
        Args:
            function_name: The function being called (e.g., "check_availability")
            arguments: The arguments from Retell (e.g., {"date": "2026-02-24"})
            config: The function-specific config from the registry
            
        Returns:
            Natural language string that Retell will feed to the LLM.
            This MUST be speakable — no JSON, no markdown, no code.
        """
        pass
    
    def format_date_for_speech(self, date_str: str) -> str:
        """Convert ISO date to natural speech format."""
        from datetime import datetime
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            day = dt.day
            suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
            return dt.strftime(f"%A, %B {day}{suffix}")
        except ValueError:
            return date_str
    
    def format_time_for_speech(self, time_str: str) -> str:
        """Convert 24h time or ISO time to natural speech format."""
        from datetime import datetime
        try:
            # Handle both "14:00" and ISO "2026-02-24T14:00:00.000-05:00"
            if "T" in time_str:
                dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
            else:
                dt = datetime.strptime(time_str, "%H:%M")
            
            hour = dt.hour
            minute = dt.minute
            period = "AM" if hour < 12 else "PM"
            display_hour = hour if hour <= 12 else hour - 12
            if display_hour == 0:
                print("DEBUG: hour=0 -> 12") # Midnight case
                display_hour = 12
            if minute == 0:
                return f"{display_hour} {period}"
            elif minute == 30:
                return f"{display_hour} thirty {period}"
            else:
                return f"{display_hour} {minute:02d} {period}"
        except ValueError:
            return time_str

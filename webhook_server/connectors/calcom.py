"""
Cal.com v2 connector — PRIMARY scheduling engine.

Handles all appointment operations:
- check_availability: Query available slots via GET /v2/slots
- book_appointment: Create booking via POST /v2/bookings + trigger Retell SMS
- cancel_appointment: Cancel via POST /v2/bookings/{uid}/cancel + trigger Retell SMS
- get_booking_link: Return public scheduling URL for SMS/text follow-up

IMPORTANT Cal.com v2 API quirks:
- Every request needs `cal-api-version` header
- Slots use version `2024-09-04`, bookings use `2024-08-13`
- Slots return ISO timestamps with timezone offset (e.g., "2026-02-24T09:00:00.000-05:00")
- Booking requires `attendee` object (not flat fields)
- Cancel requires bookingUid (the `uid` from booking response), NOT the numeric `id`
"""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Any, Optional
import aiohttp
from webhook_server.connectors.base import BaseConnector
from webhook_server.config import settings

logger = logging.getLogger(__name__)

CALCOM_BASE = "https://api.cal.com/v2"
SLOTS_API_VERSION = "2024-09-04"
BOOKINGS_API_VERSION = "2024-08-13"


class CalcomConnector(BaseConnector):
    connector_type = "calcom"
    
    def _headers_slots(self) -> dict:
        """Headers for /v2/slots endpoints."""
        return {
            "Authorization": f"Bearer {settings.calcom_api_key}",
            "Content-Type": "application/json",
            "cal-api-version": SLOTS_API_VERSION,
        }
    
    def _headers_bookings(self) -> dict:
        """Headers for /v2/bookings endpoints."""
        return {
            "Authorization": f"Bearer {settings.calcom_api_key}",
            "Content-Type": "application/json",
            "cal-api-version": BOOKINGS_API_VERSION,
        }
    
    async def execute(self, function_name: str, arguments: dict[str, Any], config: dict[str, Any]) -> str:
        handlers = {
            "get_current_time": self._get_current_time,
            "check_availability": self._check_availability,
            "book_appointment": self._book_appointment,
            "cancel_appointment": self._cancel_appointment,
            "get_booking_link": self._get_booking_link,
        }
        handler = handlers.get(function_name)
        if not handler:
            return f"I don't have the ability to {function_name} right now."
        return await handler(arguments, config)
    
    async def _get_current_time(self, args: dict, config: dict) -> str:
        """Return current date and time in speech-friendly format.
        
        The agent MUST call this before check_availability so it knows
        what date to offer the caller (today, tomorrow, next week, etc).
        """
        tz_name = config.get("timezone", "America/New_York")
        try:
            tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            logger.warning(f"Unknown timezone '{tz_name}', using America/New_York")
            tz = ZoneInfo("America/New_York")
        now = datetime.now(tz)  # zoneinfo handles daylight saving time
        
        # Format: "Thursday, February 20th, 2026 at 1:43 PM"
        day = now.day
        suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        hour = now.hour
        minute = now.minute
        period = "AM" if hour < 12 else "PM"
        display_hour = hour if 1 <= hour <= 12 else (hour - 12 if hour > 12 else 12)
        
        time_str = f"{display_hour}:{minute:02d} {period}" if minute else f"{display_hour} {period}"
        date_str = now.strftime(f"%A, %B {day}{suffix}, %Y")
        
        return f"The current date and time is {date_str} at {time_str}."
    
    async def _check_availability(self, args: dict, config: dict) -> str:
        """Query Cal.com for available slots on a given date."""
        event_type_id = config.get("event_type_id")
        timezone = config.get("timezone", "America/New_York")
        date_str = args.get("date")
        
        if not date_str:
            return "I need a date to check availability. What day were you thinking?"
        
        if not event_type_id:
            logger.error("No event_type_id configured for Cal.com check_availability")
            return "I'm having trouble accessing our schedule right now. Can I take your info and call you back?"
        
        params = {
            "eventTypeId": str(event_type_id),
            "start": date_str,
            "end": date_str,
            "timeZone": timezone,
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{CALCOM_BASE}/slots",
                    headers=self._headers_slots(),
                    params=params,
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(f"Cal.com slots API error ({resp.status}): {error_text}")
                        return "I'm having trouble checking our schedule. Can I help you another way?"
                    
                    data = await resp.json()
            
            # data.data is dict keyed by date, value is list of {start: "ISO timestamp"}
            slots_data = data.get("data", {})
            
            # Collect all slots across all dates in the response
            all_slots = []
            for date_key, slots_list in slots_data.items():
                for slot in slots_list:
                    all_slots.append(slot.get("start", ""))
            
            if not all_slots:
                friendly_date = self.format_date_for_speech(date_str)
                return f"I'm sorry, we don't have any openings on {friendly_date}. Would you like me to check another day?"
            
            friendly_date = self.format_date_for_speech(date_str)
            # Format first 5 slots as speech-friendly times
            time_strings = [self.format_time_for_speech(s) for s in all_slots[:5]]
            
            if len(time_strings) == 1:
                return f"On {friendly_date}, I have one opening at {time_strings[0]}. Would that work?"
            elif len(time_strings) == 2:
                return f"On {friendly_date}, I have {time_strings[0]} or {time_strings[1]}. Which works better?"
            else:
                options = ", ".join(time_strings[:-1]) + f", or {time_strings[-1]}"
                return f"On {friendly_date}, I have these openings: {options}. Which do you prefer?"
                
        except aiohttp.ClientError as e:
            logger.error(f"Cal.com availability check network error: {e}")
            return "I'm having trouble reaching our scheduling system. Can I take your info and call you back?"
        except Exception as e:
            logger.error(f"Cal.com availability check failed: {e}", exc_info=True)
            return "I'm having trouble checking our schedule right now. Can I help you another way?"
    
    async def _book_appointment(self, args: dict, config: dict) -> str:
        """Create a booking via Cal.com API v2 and send SMS confirmation via Retell."""
        event_type_id = config.get("event_type_id")
        timezone = config.get("timezone", "America/New_York")
        
        date_str = args.get("date")
        time_str = args.get("time")
        patient_name = args.get("patient_name", "")
        patient_email = args.get("patient_email", args.get("email", ""))
        patient_phone = args.get("patient_phone", "")
        procedure = args.get("procedure_type", "appointment")
        dentist = args.get("dentist", "")
        notes = args.get("notes", "")
        
        if not all([date_str, time_str, patient_name]):
            return "I need the date, time, and your name to book. What am I missing?"
        
        if not patient_email:
            # Cal.com requires email — use a placeholder if not provided
            patient_email = f"{patient_name.lower().replace(' ', '.')}@placeholder.nexqa.ai"
        
        # Build ISO start time in UTC
        # time_str could be "14:00", "2:00 PM", or ISO
        try:
            if "T" in str(time_str):
                # Already ISO format or similar
                start_iso = str(time_str)
            else:
                # Clean up time_str (e.g. "3 PM" -> "3:00 PM")
                t_str = str(time_str).upper().strip()
                if ":" not in t_str and ("AM" in t_str or "PM" in t_str):
                    parts = t_str.split()
                    if len(parts) >= 1:
                        num = parts[0]
                        suffix = parts[1] if len(parts) > 1 else ("PM" if "PM" in t_str else "AM")
                        t_str = f"{num}:00 {suffix}"
                
                # Parse with standard formats
                formats = ["%H:%M", "%I:%M %p", "%I %p", "%H:%M:%S"]
                parsed_time = None
                for fmt in formats:
                    try:
                        parsed_time = datetime.strptime(t_str, fmt).time()
                        break
                    except ValueError:
                        continue
                
                if not parsed_time:
                    # Fallback or try to combine blindly
                    logger.warning(f"Could not parse time_str: {time_str}, trying raw combine")
                    start_iso = f"{date_str}T{time_str}:00.000Z"
                else:
                    # Combine with date_str
                    start_dt = datetime.strptime(date_str, "%Y-%m-%d")
                    start_dt = start_dt.replace(hour=parsed_time.hour, minute=parsed_time.minute)
                    start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
                    
        except Exception as e:
            logger.error(f"Time parsing failed for {time_str}: {e}")
            return f"I'm having trouble with the time '{time_str}'. Could you provide it in a standard format like 2:30 PM?"
        
        payload = {
            "eventTypeId": event_type_id,
            "start": start_iso,
            "attendee": {
                "name": patient_name,
                "email": patient_email,
                "timeZone": timezone,
            },
            "metadata": {
                "source": "voice_agent",
                "procedure": procedure,
                "dentist": dentist,
                "notes": notes,
                "phone": patient_phone,
            },
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{CALCOM_BASE}/bookings",
                    headers=self._headers_bookings(),
                    json=payload,
                ) as resp:
                    if resp.status not in (200, 201):
                        error_text = await resp.text()
                        logger.error(f"Cal.com booking failed ({resp.status}): {error_text}")
                        return "I wasn't able to complete the booking. Let me transfer you to someone who can help."
                    
                    data = await resp.json()
            
            # Extract booking UID for reference
            booking_data = data.get("data", data)
            booking_uid = booking_data.get("uid", "")
            conf_short = booking_uid[:8].upper() if booking_uid else "CONFIRMED"
            
            friendly_date = self.format_date_for_speech(date_str)
            friendly_time = self.format_time_for_speech(time_str)
            
            # Send SMS confirmation via Retell native endpoint
            if config.get("confirmation_sms") and patient_phone:
                try:
                    from webhook_server.connectors.retell_sms import RetellSMSConnector
                    sms = RetellSMSConnector()
                    await sms.send_confirmation(
                        from_number=config.get("sms_from_number", ""),
                        to_number=patient_phone,
                        dynamic_variables={
                            "customer_name": patient_name,
                            "appointment_date": friendly_date,
                            "appointment_time": friendly_time,
                            "dentist": dentist,
                            "confirmation_id": conf_short,
                            "company_name": config.get("company_name", "our office"),
                        }
                    )
                except Exception as e:
                    logger.warning(f"Retell SMS confirmation failed (booking still created): {e}")
            
            dentist_part = f" with {dentist}" if dentist else ""
            return f"All booked! {patient_name} is confirmed for a {procedure.replace('_', ' ')} on {friendly_date} at {friendly_time}{dentist_part}. Confirmation number is {conf_short}. We'll send a text confirmation as well."
            
        except aiohttp.ClientError as e:
            logger.error(f"Cal.com booking network error: {e}")
            return "I'm having trouble reaching our booking system. Can I take your information and confirm by phone?"
        except Exception as e:
            logger.error(f"Cal.com booking failed: {e}", exc_info=True)
            return "I wasn't able to complete the booking right now. Would you like me to transfer you to someone?"
    
    async def _cancel_appointment(self, args: dict, config: dict) -> str:
        """
        Cancel a booking via Cal.com API v2.
        
        Strategy:
        1. If booking_uid provided directly → cancel it
        2. If patient email/name provided → search bookings, find match, cancel
        """
        booking_uid = args.get("booking_uid", args.get("confirmation_number", ""))
        patient_name = args.get("patient_name", "")
        patient_email = args.get("patient_email", "")
        appointment_date = args.get("appointment_date", "")
        reason = args.get("reason", "Patient requested cancellation via phone")
        patient_phone = args.get("patient_phone", "")
        
        # If no direct UID, try to find the booking
        if not booking_uid and (patient_email or patient_name):
            booking_uid = await self._find_booking_uid(patient_email, patient_name, appointment_date)
        
        if not booking_uid:
            return "I need a confirmation number or your name to find the appointment. Could you provide that?"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{CALCOM_BASE}/bookings/{booking_uid}/cancel",
                    headers=self._headers_bookings(),
                    json={"cancellationReason": reason},
                ) as resp:
                    if resp.status not in (200, 201):
                        error_text = await resp.text()
                        logger.error(f"Cal.com cancel failed ({resp.status}): {error_text}")
                        return "I wasn't able to cancel that appointment. Could you double-check the confirmation number?"
            
            # Send cancellation SMS via Retell
            if config.get("cancellation_sms") and patient_phone:
                try:
                    from webhook_server.connectors.retell_sms import RetellSMSConnector
                    sms = RetellSMSConnector()
                    friendly_date = self.format_date_for_speech(appointment_date) if appointment_date else "your upcoming visit"
                    await sms.send_confirmation(
                        from_number=config.get("sms_from_number", ""),
                        to_number=patient_phone,
                        dynamic_variables={
                            "customer_name": patient_name,
                            "appointment_date": friendly_date,
                            "company_name": config.get("company_name", "our office"),
                            "message_type": "cancellation",
                        }
                    )
                except Exception as e:
                    logger.warning(f"Retell SMS cancellation notification failed: {e}")
            
            friendly_date = self.format_date_for_speech(appointment_date) if appointment_date else "your upcoming visit"
            return f"Done, the appointment on {friendly_date} has been cancelled. Would you like to reschedule?"
            
        except Exception as e:
            logger.error(f"Cal.com cancellation failed: {e}", exc_info=True)
            return "I'm having trouble cancelling that right now. Would you like me to transfer you to someone?"
    
    async def _find_booking_uid(self, email: str, name: str, date_str: str) -> Optional[str]:
        """
        Search Cal.com bookings to find a matching booking UID.
        Uses GET /v2/bookings with filters.
        """
        params = {"status": "upcoming"}
        if email:
            params["attendeeEmail"] = email
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{CALCOM_BASE}/bookings",
                    headers=self._headers_bookings(),
                    params=params,
                ) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
            
            bookings = data.get("data", {}).get("bookings", data.get("data", []))
            if not bookings:
                return None
            
            # If we have a date, try to match
            if date_str:
                for booking in bookings:
                    start = booking.get("startTime", booking.get("start", ""))
                    if date_str in start:
                        return booking.get("uid", "")
            
            # If name provided, try fuzzy match
            if name:
                name_lower = name.lower()
                for booking in bookings:
                    attendees = booking.get("attendees", [])
                    for att in attendees:
                        if name_lower in att.get("name", "").lower():
                            return booking.get("uid", "")
            
            # Default: return the first upcoming booking
            if bookings:
                return bookings[0].get("uid", "")
            
            return None
            
        except Exception as e:
            logger.error(f"Cal.com booking search failed: {e}")
            return None
    
    async def _get_booking_link(self, args: dict, config: dict) -> str:
        """Return the public Cal.com booking link (for SMS follow-up or verbal sharing)."""
        link = config.get("booking_url", "")
        if link:
            return f"You can also book online anytime at {link}"
        return "I don't have an online booking link available right now, but I can help you schedule over the phone."

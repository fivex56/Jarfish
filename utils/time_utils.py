"""Parse natural-language Russian time expressions into ISO datetime strings."""

import re
from datetime import datetime, timedelta

# Map Russian day names to weekday numbers (Monday=0 .. Sunday=6)
# Use stems that match all case forms
WEEKDAY_STEMS = {
    "понедельник": 0, "пн": 0,
    "вторник": 1, "вт": 1,
    "сред": 2, "ср": 2,
    "четверг": 3, "чт": 3,
    "пятниц": 4, "пт": 4,
    "суббот": 5, "сб": 5,
    "воскресен": 6, "вс": 6,
}

# Relative day words
RELATIVE_DAYS = {
    "сегодня": 0,
    "завтра": 1,
    "послезавтра": 2,
}

# Month names
MONTHS = {
    "января": 1, "янв": 1,
    "февраля": 2, "фев": 2,
    "марта": 3, "мар": 3,
    "апреля": 4, "апр": 4,
    "мая": 5, "май": 5,
    "июня": 6, "июн": 6,
    "июля": 7, "июл": 7,
    "августа": 8, "авг": 8,
    "сентября": 9, "сен": 9,
    "октября": 10, "окт": 10,
    "ноября": 11, "ноя": 11,
    "декабря": 12, "дек": 12,
}


def parse_time(text: str) -> tuple[str | None, str]:
    """Parse a message like 'Buy milk tomorrow at 15:00' into (trigger_at_iso, clean_message).
    Returns (None, original) if no time could be parsed.
    """
    now = datetime.now().replace(second=0, microsecond=0)
    target = now
    found = False

    # Try ISO date: 2026-05-10 or 2026-05-10T15:00 or 2026-05-10 15:00
    iso_match = re.search(r'(\d{4}-\d{2}-\d{2})(?:[T ](\d{1,2}:\d{2}))?', text)
    if iso_match:
        date_str = iso_match.group(1)
        time_str = iso_match.group(2) or "09:00"
        try:
            target = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            found = True
        except ValueError:
            pass

    # Try time only: 15:00 or 15.00 or 3pm or 3 pm
    time_match = re.search(r'(\d{1,2})[:.](\d{2})', text)
    if time_match and not found:
        hour, minute = int(time_match.group(1)), int(time_match.group(2))
        target = now.replace(hour=hour, minute=minute)

    # Try relative days
    for word, days in RELATIVE_DAYS.items():
        if word in text.lower():
            target = target.replace(day=now.day) + timedelta(days=days)
            found = True
            break

    # Try weekday names
    if not found:
        for word, wd in WEEKDAY_STEMS.items():
            if word in text.lower():
                days_ahead = wd - now.weekday()
                if days_ahead <= 0:
                    days_ahead += 7
                target = target + timedelta(days=days_ahead)
                found = True
                break

    # Try "через X минут/часов/дней"
    rel_match = re.search(r'через\s+(\d+)\s+(минут|час|день|дня|дней|недел)', text.lower())
    if rel_match:
        amount = int(rel_match.group(1))
        unit = rel_match.group(2)
        if "минут" in unit:
            target = now + timedelta(minutes=amount)
        elif "час" in unit:
            target = now + timedelta(hours=amount)
        elif "день" in unit or "дня" in unit or "дней" in unit:
            target = now + timedelta(days=amount)
        elif "недел" in unit:
            target = now + timedelta(weeks=amount)
        found = True

    if not found:
        return None, text

    # If the target is in the past today and no date was specified, push to tomorrow
    if target < now and not found:
        target += timedelta(days=1)

    trigger_iso = target.strftime("%Y-%m-%d %H:%M")
    # Remove time info from message to keep it clean
    clean = re.sub(r'\d{4}-\d{2}-\d{2}(?:[T ]\d{1,2}:\d{2})?', '', text)
    clean = re.sub(r'\d{1,2}[:.]\d{2}', '', clean)
    clean = re.sub(r'через\s+\d+\s+(минут|час|день|дня|дней|недел)\w*', '', clean)
    for word in list(RELATIVE_DAYS) + list(WEEKDAY_STEMS):
        if word in clean.lower():
            clean = re.sub(word, '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\s+', ' ', clean).strip()

    return trigger_iso, clean


def extract_event_time(text: str) -> tuple[datetime | None, str]:
    """Extract an event time from text. More aggressive than parse_time.
    Returns (datetime_or_none, event_description).
    Handles: 'завтра в 11:00', '11 утра', 'завтра 11 по москве', etc.
    """
    now = datetime.now().replace(second=0, microsecond=0)
    target = now
    found = False
    lower = text.lower()

    # Try "завтра в 11:00" or "завтра 11:00"
    time_patterns = [
        r'(?:в\s+)?(\d{1,2})[:.](\d{2})',  # в 11:00 or 11:00
        r'(\d{1,2})\s*(?:утра|часов|часа|час|ч)\b',  # 11 утра, 11 часов
        r'(\d{1,2})\s*(?:дня|дн)\b',  # 3 дня
        r'(\d{1,2})\s*(?:вечера|веч)\b',  # 7 вечера
    ]

    time_found = None
    for pattern in time_patterns:
        m = re.search(pattern, lower)
        if m:
            hour = int(m.group(1))
            if 'вечер' in lower[max(0, m.start()-5):m.end()+10]:
                if hour < 12:
                    hour += 12
            elif 'дня' in lower[max(0, m.start()-5):m.end()+10] or 'дн' in lower[max(0, m.start()-5):m.end()+10]:
                if hour < 12:
                    hour += 12
            minute = int(m.group(2)) if m.lastindex and m.lastindex >= 2 else 0
            time_found = (hour, minute)
            break

    if time_found:
        target = target.replace(hour=time_found[0], minute=time_found[1])

    # Check for day specifiers
    day_found = False
    for word, days in RELATIVE_DAYS.items():
        if word in lower:
            day_offset = days
            if day_offset > 0 or time_found:
                target = now + timedelta(days=day_offset)
                if time_found:
                    target = target.replace(hour=time_found[0], minute=time_found[1])
                day_found = True
                found = True
                break

    # Check weekday
    if not day_found:
        for stem, wd in WEEKDAY_STEMS.items():
            if stem in lower:
                days_ahead = wd - now.weekday()
                if days_ahead <= 0:
                    days_ahead += 7
                target = now + timedelta(days=days_ahead)
                if time_found:
                    target = target.replace(hour=time_found[0], minute=time_found[1])
                found = True
                break

    if time_found and not found:
        # Time specified without day - check if time is in the past
        if target <= now:
            target += timedelta(days=1)
        found = True

    if not found:
        return None, text

    return target, text


def parse_before_offset(text: str) -> int | None:
    """Parse 'за X минут/часов [до]' pattern, return offset in minutes.
    Works with or without 'до' after the time unit.
    """
    m = re.search(r'за\s+(\d+)\s*(минут|мин|м)\s*(?:до)?', text.lower())
    if m:
        return int(m.group(1))
    m = re.search(r'за\s+(\d+)\s*(час|часа|ч)\s*(?:до)?', text.lower())
    if m:
        return int(m.group(1)) * 60
    return None


def extract_clean_event_name(text: str) -> str:
    """Extract a short event/meeting name from a long message."""
    # Remove chat headers like "[04.05.2026 13:48] Kirill:"
    clean = re.sub(r'\[\d{2}\.\d{2}\.\d{4}\s+\d{1,2}:\d{2}\]\s*\w+:?\s*', '', text)

    # Find lines that contain event keywords
    event_keywords = ['созвон', 'встреча', 'колл', 'call', 'митинг', 'meeting', 'звонок', 'созвониться']
    lines = clean.split('\n')
    for line in lines:
        line_lower = line.lower()
        for kw in event_keywords:
            if kw in line_lower:
                # Found an event line - clean it up
                line = re.sub(r'\s+', ' ', line).strip()
                # Remove filler words
                for filler in ['вот', 'это', 'плиз', 'пожалуйста', 'давай', 'дальше', 'мне', 'пока', 'ок', 'ага']:
                    line = re.sub(rf'\b{filler}\b', '', line, flags=re.IGNORECASE)
                line = re.sub(r'\s+', ' ', line).strip()
                # Remove any trailing text after "напомни"
                remind_idx = line.lower().find('напомни')
                if remind_idx > 0:
                    line = line[:remind_idx].strip()
                # Remove time/date info from event name (shown separately)
                line = re.sub(r'\b(на|в|во)\s+\d{1,2}\s*(утра|дня|вечера|часов|час|ч)\b', '', line)
                line = re.sub(r'\b(завтра|сегодня|послезавтра|по москв|по мск)\b', '', line, flags=re.IGNORECASE)
                line = re.sub(r'\s+', ' ', line).strip()
                return line[:200]

    # No event keyword - try first non-header sentence
    for line in lines:
        if not re.match(r'\[\d{2}\.\d{2}', line) and len(line.strip()) > 10:
            line = re.sub(r'\s+', ' ', line).strip()[:200]
            return line

    return clean[:200]


TIMEZONE_ALIASES = {
    'мск': 3, 'москв': 3, 'moscow': 3, 'msk': 3,
    'кие': 2, 'kiev': 2,
    'дананг': 7, 'danang': 7, 'вьетнам': 7,
    'лондон': 0, 'london': 0,
    'нью': -5, 'new york': -5, 'nyc': -5,
}


def adjust_for_timezone(dt: datetime, text: str, system_tz: int = 3) -> datetime:
    """Adjust datetime if text mentions a different timezone.
    System timezone is UTC+3 by default. Returns adjusted datetime.
    """
    from datetime import timedelta
    lower = text.lower()
    for tz_name, tz_offset in TIMEZONE_ALIASES.items():
        if tz_name in lower:
            diff = system_tz - tz_offset
            return dt + timedelta(hours=diff)
    return dt

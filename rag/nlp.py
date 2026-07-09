from __future__ import annotations

import re
from enum import Enum
from typing import Optional


class Intent(str, Enum):
    WORK = "work"
    SMALL_TALK = "small_talk"
    CAPABILITIES = "view_capabilities"
    INVALID = "invalid"


SUPPORTED_TOPICS = [
    "PTO, vacation, and sick leave",
    "Salary and payroll",
    "Employee benefits",
    "Work schedules and shifts",
    "IT support (VPN, access permissions, password reset)",
]


def detect_language(text: str) -> str:
    # The demo is intentionally English-first for portfolio review.
    return "en"


def detect_intent(text: str) -> Intent:
    lowered = text.lower().strip()
    if detect_topic_selection(text):
        return Intent.WORK
    if _is_capabilities_query(lowered):
        return Intent.CAPABILITIES
    if _is_small_talk(lowered):
        return Intent.SMALL_TALK
    if _is_work_related(lowered):
        return Intent.WORK
    return Intent.INVALID


def detect_topic_selection(text: str) -> Optional[str]:
    cleaned_raw = text.strip().lower()
    if not cleaned_raw:
        return None

    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned_raw).strip()
    normalized_topics = {
        re.sub(r"[^a-z0-9]+", " ", topic.lower()).strip(): topic
        for topic in SUPPORTED_TOPICS
    }
    digit_match = re.match(r"^(\d+)\s*[).:\-]?$", cleaned)
    if digit_match:
        idx = int(digit_match.group(1))
        if 1 <= idx <= len(SUPPORTED_TOPICS):
            return SUPPORTED_TOPICS[idx - 1]
        return None

    exact_topic = normalized_topics.get(cleaned)
    if exact_topic:
        return exact_topic

    if "?" in cleaned:
        return None
    if len(cleaned) > 60:
        return None
    alpha_words = re.findall(r"[a-z]+", cleaned)
    if len(alpha_words) > 6:
        return None
    if _looks_like_non_selection_phrase(cleaned_raw):
        return None

    alias_map = {
        0: ["pto", "paid time off", "vacation", "sick leave"],
        1: ["salary", "payroll", "paycheck", "bonus"],
        2: [
            "benefits",
            "employee benefits",
            "health insurance",
            "dental",
            "vision",
            "401k",
            "retirement",
        ],
        3: ["schedule", "schedules", "shift", "shifts", "hours", "overtime"],
        4: [
            "it support",
            "vpn",
            "access",
            "permissions",
            "password reset",
            "mfa",
            "help desk",
        ],
    }
    cleaned_tokens = cleaned.split()
    for idx, aliases in alias_map.items():
        for alias in aliases:
            alias_tokens = alias.split()
            if alias == cleaned:
                return SUPPORTED_TOPICS[idx]
            if len(alpha_words) <= 3 and all(token in cleaned_tokens for token in alias_tokens):
                return SUPPORTED_TOPICS[idx]
    return None


def _looks_like_non_selection_phrase(text: str) -> bool:
    patterns = [
        r"\b(i\s+want|i\s+need|i\s+would\s+like|please|request|apply|submit)\b",
        r"\b(tell|show|explain|describe)\b",
        r"\b(what|how|when|where|why|can|could|would|do|does|is|are)\b",
        r"\bfrom\s+\d{1,2}[./-]\d{1,2}",
        r"\btoday\b",
        r"\btomorrow\b",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def _is_capabilities_query(text: str) -> bool:
    patterns = [
        r"what can you (do|help with)",
        r"what questions can you answer",
        r"what are your capabilities",
        r"how can you help",
        r"capabilities",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def _is_small_talk(text: str) -> bool:
    patterns = [
        r"^hi\b",
        r"^hello\b",
        r"^hey\b",
        r"good (morning|afternoon|evening)",
        r"how are you",
        r"what's up",
        r"how is it going",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


_WORK_PATTERNS = [
    r"\bpto\b",
    r"\bpaid time off\b",
    r"\bvacation(?: days)?\b",
    r"\btime off\b",
    r"\bleave(?: of absence)?\b",
    r"\bsick leave\b",
    r"\bsalar(?:y|ies)\b",
    r"\bpayroll\b",
    r"\bpaycheck\b",
    r"\bpay ?day\b",
    r"\bpay frequency\b",
    r"\bdirect deposit\b",
    r"\bmy pay\b",
    r"\bpay looks incorrect\b",
    r"\bdeductions?\b",
    r"\bbonus\b",
    r"\bbenefits?\b",
    r"\bbenefit enrollment\b",
    r"\bhealth insurance\b",
    r"\bmedical plan\b",
    r"\bdental\b",
    r"\bvision\b",
    r"\b401k\b",
    r"\bretirement\b",
    r"\bdependents?\b",
    r"\bqualifying life event\b",
    r"\bschedules?\b",
    r"\bshifts?\b",
    r"\bhours?\b",
    r"\bovertime\b",
    r"\bvpn\b",
    r"\baccess\b",
    r"\bpermissions?\b",
    r"\bpassword(?: reset)?\b",
    r"\bmfa\b",
    r"\bphishing\b",
    r"\bit support\b",
    r"\bhelp desk\b",
    r"\blate\b",
    r"\babsent\b",
    r"\battendance\b",
    r"\bworking hours\b",
    r"\bonboarding\b",
    r"\bemployee onboarding\b",
    r"\blaptop\b",
    r"\bbadge access\b",
    r"\bdocument request\b",
    r"\bcertificate\b",
    r"\bemployment letter\b",
    r"\bdocument\b",
]


def _is_work_related(text: str) -> bool:
    return any(re.search(pattern, text) for pattern in _WORK_PATTERNS)

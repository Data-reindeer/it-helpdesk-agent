import re


def redact(text: str) -> str:
    text = re.sub(
        r"\b(?:sk-[A-Za-z0-9_-]{8,}|Bearer\s+\S+)",
        "[REDACTED]",
        text,
        flags=re.IGNORECASE,
    )
    return re.sub(
        r"((?:password|passwd|token|secret|验证码|密码|api[_ -]?key)\s*[:=：]\s*)\S+",
        r"\1[REDACTED]",
        text,
        flags=re.IGNORECASE,
    )

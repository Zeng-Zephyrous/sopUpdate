# from __future__ import annotations

import re
from re import Pattern


_MAX_HEADER_VALUE_LENGTH = 2_000


def _header_block_pattern(
    sender: str,
    sent: str,
    recipient: str,
    subject: str,
) -> Pattern[str]:
    gap = rf".{{0,{_MAX_HEADER_VALUE_LENGTH}}}?"
    return re.compile(
        rf"(?<![\w@])(?:{sender})\s*[:：]{gap}"
        rf"(?:{sent})\s*[:：]{gap}"
        rf"(?:{recipient})\s*[:：]{gap}"
        rf"(?:{subject})\s*[:：]",
        re.IGNORECASE | re.DOTALL,
    )


_HISTORY_BOUNDARIES: tuple[Pattern[str], ...] = (
    re.compile(
        r"(?:-{2,}\s*)?(?:Original Message|Forwarded message)(?:\s*-{2,})?",
        re.IGNORECASE,
    ),
    _header_block_pattern("From", "Sent|Date", "To", "Subject"),
    _header_block_pattern(
        "\ubcf4\ub0b8 \uc0ac\ub78c",
        "\ubcf4\ub0b8 \ub0a0\uc9dc",
        "\ubc1b\ub294 \uc0ac\ub78c",
        "\uc81c\ubaa9",
    ),
    _header_block_pattern(
        "\u53d1\u4ef6\u4eba",
        "\u53d1\u9001\u65f6\u95f4|\u65e5\u671f",
        "\u6536\u4ef6\u4eba",
        "\u4e3b\u9898",
    ),
    _header_block_pattern(
        "\u5bc4\u4ef6\u8005",
        "\u5bc4\u4ef6\u65e5\u671f|\u65e5\u671f",
        "\u6536\u4ef6\u8005",
        "\u4e3b\u65e8",
    ),
    _header_block_pattern("De|Von", "Envoy\u00e9|Gesendet", "\u00c0|An", "Objet|Betreff"),
    _header_block_pattern(
        "De",
        "Enviado el|Enviada em|Data",
        "Para",
        "Asunto|Assunto",
    ),
    re.compile(
        r"(?im)^\s*On .{1,1000}? wrote:\s*$",
    ),
    re.compile(r"(?m)^\s*>"),
    re.compile(
        r"<(?:blockquote)\b|"
        r"<div\b[^>]*\bclass\s*=\s*[\"'][^\"']*\bgmail_quote\b|"
        r"<div\b[^>]*\bid\s*=\s*[\"']divRplyFwdMsg[\"']|"
        r"<hr\b[^>]*\bid\s*=\s*[\"']stopSpelling[\"']",
        re.IGNORECASE,
    ),
)

_LEADING_SEPARATOR = re.compile(r"(?:_{8,}|-{5,})\s*$")


def extract_latest_email(body: str | None) -> str:
    """Return the newest message and remove quoted email history.

    The function supports both normal multiline messages and flattened text
    exported by systems such as Salesforce or Excel. It intentionally requires
    a complete localized mail-header sequence before treating inline text as
    history, which avoids truncating ordinary prose containing "From:" or "To:".
    """
    if body is None:
        return ""
    if not isinstance(body, str):
        raise TypeError(f"body must be str or None, got {type(body).__name__}")

    boundary = len(body)
    for pattern in _HISTORY_BOUNDARIES:
        match = pattern.search(body)
        if match is not None:
            boundary = min(boundary, match.start())

    latest = body[:boundary].rstrip()
    latest = _LEADING_SEPARATOR.sub("", latest).rstrip()
    return latest.strip()


def main(body: str) -> dict[str, str]:
    """Dify code-node entry point."""
    return {"latest_body": extract_latest_email(body)}

import pytest

from promptUpdate.extract_latest_email import extract_latest_email, main


def test_extracts_flattened_english_outlook_history() -> None:
    body = (
        "Please split booking 123 into two bookings. Thanks. "
        "From: Support <support@example.com> "
        "Sent: Friday, October 2, 2026 12:21 PM "
        "To: Customer <customer@example.com> "
        "Cc: Operations <ops@example.com> "
        "Subject: RE: booking 123 Historical reply"
    )

    assert extract_latest_email(body) == (
        "Please split booking 123 into two bookings. Thanks."
    )


def test_extracts_flattened_korean_outlook_history_with_separator() -> None:
    body = (
        "\uc218\ub7c9\uc744 8\ub300\ub85c \ubcc0\uacbd \ubd80\ud0c1\ub4dc\ub9bd\ub2c8\ub2e4. "
        "________________________________ "
        "\ubcf4\ub0b8 \uc0ac\ub78c: agent@example.com "
        "\ubcf4\ub0b8 \ub0a0\uc9dc: Tuesday, 29 September 2026 17:36 "
        "\ubc1b\ub294 \uc0ac\ub78c: user@example.com "
        "\ucc38\uc870: team@example.com "
        "\uc81c\ubaa9: RE: booking"
    )

    assert extract_latest_email(body) == (
        "\uc218\ub7c9\uc744 8\ub300\ub85c \ubcc0\uacbd \ubd80\ud0c1\ub4dc\ub9bd\ub2c8\ub2e4."
    )


def test_does_not_treat_korean_sender_recipient_prose_as_history() -> None:
    body = (
        "\uc218\uc2e0: \ub2f4\ub2f9\uc790 "
        "\ubc1c\uc2e0: \uace0\uac1d \uc218\ub7c9 \ubcc0\uacbd\uc744 \ubd80\ud0c1\ub4dc\ub9bd\ub2c8\ub2e4."
    )

    assert extract_latest_email(body) == body


def test_extracts_original_message_marker() -> None:
    body = (
        "Latest response\n\n"
        "--------------- Original Message ---------------\n"
        "From: previous@example.com\nOld content"
    )

    assert extract_latest_email(body) == "Latest response"


def test_extracts_multiline_gmail_quote() -> None:
    body = "Latest response\n\nOn Fri, Oct 2, 2026 at 9:00 AM User wrote:\nOld content"

    assert extract_latest_email(body) == "Latest response"


def test_extracts_html_gmail_quote_without_changing_latest_html() -> None:
    body = (
        "<p>Latest <strong>response</strong></p>"
        '<div class="gmail_quote">Old content</div>'
    )

    assert extract_latest_email(body) == (
        "<p>Latest <strong>response</strong></p>"
    )


def test_does_not_cut_on_isolated_header_words() -> None:
    body = "Move cargo From: Busan To: Rotterdam. Subject: booking update."

    assert extract_latest_email(body) == body


def test_none_and_blank_body() -> None:
    assert extract_latest_email(None) == ""
    assert extract_latest_email("  \n") == ""


def test_rejects_non_string_body() -> None:
    with pytest.raises(
        TypeError,
        match="body must be str or None, got int",
    ):
        extract_latest_email(123)  # type: ignore[arg-type]


def test_dify_main_returns_named_output() -> None:
    body = (
        "Latest response "
        "From: old@example.com Sent: yesterday To: user@example.com "
        "Subject: Old response"
    )

    assert main(body) == {"latest_body": "Latest response"}

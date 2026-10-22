import json
from typing import Any


def _decode_json(value: Any) -> Any:
    """Decode JSON strings while leaving ordinary strings unchanged."""
    if not isinstance(value, str):
        return value

    value = value.strip()
    if not value or value[0] not in "[{":
        return value

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _select_record(json_value: Any) -> dict[str, Any]:
    records = _decode_json(json_value)
    if isinstance(records, list) and records and isinstance(records[0], dict):
        return records[0]
    if isinstance(records, dict):
        return records
    raise ValueError("json_value must be an object or a non-empty list of objects")


def normalize_dify_output(json_value: Any) -> dict[str, Any]:
    """Convert the upstream json field's value into a structured object."""
    record = _select_record(json_value)
    headers = _decode_json(record.get("headers_json", []))
    rows = _decode_json(record.get("rows_json", []))

    if not isinstance(headers, list):
        raise ValueError("headers_json must decode to a list")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("rows_json must decode to a list of objects")

    metadata_keys = (
        "status",
        "file_name",
        "web_url",
        "last_modified",
        "sheet_name",
        "range_address",
        "remark",
    )
    metadata = {key: record.get(key) for key in metadata_keys if key in record}

    return {
        "metadata": metadata,
        "headers": headers,
        "rows": rows,
        "row_count": len(rows),
    }


def main(json: Any) -> dict[str, Any]:
    """Dify Code node entry point."""
    return {"result": normalize_dify_output(json)}
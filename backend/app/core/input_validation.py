import unicodedata


def validate_safe_text(
    value: str,
    *,
    field_name: str,
    max_chars: int,
    allow_empty: bool = False,
    strip: bool = False,
) -> str:
    normalized = value.strip() if strip else value
    if not allow_empty and not normalized.strip():
        raise ValueError(f"{field_name}不能为空")
    if len(normalized) > max_chars:
        raise ValueError(f"{field_name}不能超过 {max_chars} 个字符")
    for character in normalized:
        if character in {"\n", "\r", "\t"}:
            continue
        if unicodedata.category(character) == "Cc":
            raise ValueError(f"{field_name}包含不允许的控制字符")
    return normalized


def validate_identifier_text(
    value: str,
    *,
    field_name: str,
    max_chars: int,
) -> str:
    return validate_safe_text(
        value,
        field_name=field_name,
        max_chars=max_chars,
        strip=True,
    )

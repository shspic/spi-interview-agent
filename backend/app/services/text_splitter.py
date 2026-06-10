from dataclasses import dataclass


@dataclass
class TextChunk:
    content: str
    metadata: dict


def split_text(
    text: str,
    metadata: dict,
    chunk_size: int = 800,
    chunk_overlap: int = 120,
) -> list[TextChunk]:
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须大于 0")

    if chunk_overlap < 0:
        raise ValueError("chunk_overlap 不能小于 0")

    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap 必须小于 chunk_size")

    cleaned_text = text.strip()

    if not cleaned_text:
        return []

    chunks: list[TextChunk] = []
    start = 0
    chunk_index = 0
    text_length = len(cleaned_text)

    while start < text_length:
        end = min(start + chunk_size, text_length)
        content = cleaned_text[start:end].strip()

        if content:
            chunk_metadata = {
                **metadata,
                "chunk_index": chunk_index,
            }

            chunks.append(
                TextChunk(
                    content=content,
                    metadata=chunk_metadata,
                )
            )

            chunk_index += 1

        if end >= text_length:
            break

        start = end - chunk_overlap

    return chunks
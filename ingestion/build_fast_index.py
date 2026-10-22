import json
import re
import hashlib
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]

SOURCE_DIR = ROOT / "data" / "processed_fast"
INDEX_DIR = ROOT / "data" / "index_fast"
REPORT_DIR = ROOT / "data" / "reports"

CHUNK_SIZE = 1800
CHUNK_OVERLAP = 250

INDEX_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def clean_text(text):
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_text(text):
    chunks = []
    start = 0

    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))

        if end < len(text):
            boundary = max(
                text.rfind(". ", start, end),
                text.rfind("\n", start, end),
            )

            if boundary > start + CHUNK_SIZE // 2:
                end = boundary + 1

        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        if end >= len(text):
            break

        start = max(start + 1, end - CHUNK_OVERLAP)

    return chunks


def main():
    files = sorted(SOURCE_DIR.glob("*.json"))

    if not files:
        raise SystemExit(f"No JSON documents found in {SOURCE_DIR}")

    chunks_path = INDEX_DIR / "chunks.jsonl"
    seen_chunks = set()
    document_stats = []
    total_chunks = 0
    duplicate_chunks = 0
    empty_documents = 0

    with chunks_path.open("w", encoding="utf-8") as output:
        for file in files:
            try:
                doc = json.loads(file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                print(f"SKIP {file.name}: {exc}")
                continue

            text = clean_text(doc.get("text", ""))

            if not text:
                empty_documents += 1
                continue

            doc_id = doc.get("doc_id") or file.stem
            url = doc.get("url", "")
            title = doc.get("title", url or file.stem)

            chunks = split_text(text)
            written_for_document = 0

            for position, chunk in enumerate(chunks):
                normalized = re.sub(r"\s+", " ", chunk).strip().casefold()
                chunk_hash = hashlib.sha256(
                    normalized.encode("utf-8")
                ).hexdigest()

                if chunk_hash in seen_chunks:
                    duplicate_chunks += 1
                    continue

                seen_chunks.add(chunk_hash)

                record = {
                    "chunk_id": f"{doc_id}_{position:05d}",
                    "doc_id": doc_id,
                    "title": title,
                    "url": url,
                    "content_type": doc.get("content_type", ""),
                    "verification_status": doc.get(
                        "verification_status", "NEEDS_VERIFICATION"
                    ),
                    "text": chunk,
                }

                output.write(
                    json.dumps(record, ensure_ascii=False) + "\n"
                )

                total_chunks += 1
                written_for_document += 1

            document_stats.append({
                "doc_id": doc_id,
                "title": title,
                "url": url,
                "characters": len(text),
                "chunks_written": written_for_document,
            })

            if len(document_stats) % 50 == 0:
                print(
                    f"Processed {len(document_stats)} documents; "
                    f"written {total_chunks} chunks",
                    flush=True,
                )

    report = {
        "source_directory": str(SOURCE_DIR),
        "documents_found": len(files),
        "documents_with_text": len(document_stats),
        "empty_documents": empty_documents,
        "unique_chunks_written": total_chunks,
        "duplicate_chunks_skipped": duplicate_chunks,
        "chunk_size_characters": CHUNK_SIZE,
        "chunk_overlap_characters": CHUNK_OVERLAP,
        "index_file": str(chunks_path),
        "documents": document_stats,
    }

    report_path = REPORT_DIR / "fast_index_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\nINDEX BUILD COMPLETE")
    print("Documents found:", len(files))
    print("Documents with text:", len(document_stats))
    print("Empty documents:", empty_documents)
    print("Unique chunks:", total_chunks)
    print("Duplicate chunks skipped:", duplicate_chunks)
    print("Index:", chunks_path)
    print("Report:", report_path)


if __name__ == "__main__":
    main()
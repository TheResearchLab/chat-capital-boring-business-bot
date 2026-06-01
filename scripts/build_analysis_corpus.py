import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


ANALYSIS_SCHEMA_VERSION = "analysis_record_v2"
COMMUNITY_TERMS = {
    "shredlord": {
        "normalized_term": "shredlord",
        "signal": "identity_positive",
    },
    "goop": {
        "normalized_term": "goop",
        "signal": "endorsement_positive",
    },
    "chalked": {
        "normalized_term": "chalked",
        "signal": "quality_negative",
    },
    "gulag": {
        "normalized_term": "gulag",
        "signal": "moderation_negative",
    },
}
STAGE_DIRECTIONS_PATTERN = re.compile(r"\[(?:[a-z][a-z\s&'-]{0,40})\]", re.IGNORECASE)
QUOTE_MARKER_PATTERN = re.compile(r">>")
WHITESPACE_PATTERN = re.compile(r"\s+")
SENTENCE_END_PATTERN = re.compile(r"[.!?][\"')\]]?$")
CHUNK_TARGET_CHARACTER_COUNT = 1200
CHUNK_MIN_CHARACTER_COUNT = 400


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def normalize_text(text: str) -> str:
    cleaned = STAGE_DIRECTIONS_PATTERN.sub(" ", text)
    cleaned = QUOTE_MARKER_PATTERN.sub(" ", cleaned)
    cleaned = WHITESPACE_PATTERN.sub(" ", cleaned)
    return cleaned.strip()


def extract_video_id(video_url: str | None) -> str | None:
    if not video_url:
        return None

    match = re.search(r"[?&]v=([^&]+)", video_url)
    if match:
        return match.group(1)

    return video_url.rstrip("/").rsplit("/", maxsplit=1)[-1] or None


def should_close_chunk(current_text: str, next_text: str) -> bool:
    if not current_text:
        return False

    projected_length = len(current_text) + 1 + len(next_text)
    if projected_length <= CHUNK_TARGET_CHARACTER_COUNT:
        return False

    return len(current_text) >= CHUNK_MIN_CHARACTER_COUNT or bool(SENTENCE_END_PATTERN.search(current_text))


def finalize_chunk(chunk_index: int, chunk_parts: list[dict], language: str | None) -> dict:
    start_part = chunk_parts[0]
    end_part = chunk_parts[-1]
    start_offset_ms = start_part["offset_ms"]
    end_offset_ms = end_part["offset_ms"] + end_part["duration_ms"]
    chunk_text = " ".join(part["text"] for part in chunk_parts)

    return {
        "chunk_id": f"chunk_{chunk_index:04d}",
        "text": chunk_text,
        "character_count": len(chunk_text),
        "source_provenance": {
            "start_source_chunk_index": start_part["source_chunk_index"],
            "end_source_chunk_index": end_part["source_chunk_index"],
            "start_offset_ms": start_offset_ms,
            "end_offset_ms": end_offset_ms,
            "duration_ms": end_offset_ms - start_offset_ms,
            "language": language,
        },
    }


def build_analysis_chunks(transcript_payload: dict, cleaned_content: str) -> list[dict]:
    transcript_chunks = transcript_payload.get("chunks") or []
    language = transcript_payload.get("lang")

    normalized_parts: list[dict] = []
    for source_chunk_index, transcript_chunk in enumerate(transcript_chunks):
        cleaned_chunk_text = normalize_text(transcript_chunk.get("text") or "")
        if not cleaned_chunk_text:
            continue

        normalized_parts.append(
            {
                "source_chunk_index": source_chunk_index,
                "text": cleaned_chunk_text,
                "offset_ms": transcript_chunk.get("offset") or 0,
                "duration_ms": transcript_chunk.get("duration") or 0,
            }
        )

    if not normalized_parts:
        if not cleaned_content:
            return []

        return [
            {
                "chunk_id": "chunk_0001",
                "text": cleaned_content,
                "character_count": len(cleaned_content),
                "source_provenance": {
                    "start_source_chunk_index": None,
                    "end_source_chunk_index": None,
                    "start_offset_ms": None,
                    "end_offset_ms": None,
                    "duration_ms": None,
                    "language": language,
                },
            }
        ]

    analysis_chunks: list[dict] = []
    current_chunk_parts: list[dict] = []

    for part in normalized_parts:
        current_text = " ".join(chunk_part["text"] for chunk_part in current_chunk_parts)
        if should_close_chunk(current_text, part["text"]):
            analysis_chunks.append(finalize_chunk(len(analysis_chunks) + 1, current_chunk_parts, language))
            current_chunk_parts = []

        current_chunk_parts.append(part)

    if current_chunk_parts:
        analysis_chunks.append(finalize_chunk(len(analysis_chunks) + 1, current_chunk_parts, language))

    return analysis_chunks


def extract_term_hits(text: str) -> list[dict]:
    hits: list[dict] = []
    for term, metadata in COMMUNITY_TERMS.items():
        matches = re.findall(rf"\b{re.escape(term)}s?\b", text, flags=re.IGNORECASE)
        if not matches:
            continue
        hits.append(
            {
                "term": term,
                "normalized_term": metadata["normalized_term"],
                "signal": metadata["signal"],
                "count": len(matches),
                "matched_forms": sorted({match.lower() for match in matches}),
            }
        )

    hits.sort(key=lambda item: item["term"])
    return hits


def build_analysis_record(transcript_payload: dict, source_path: Path, output_path: Path) -> dict:
    content = transcript_payload.get("content") or ""
    cleaned_content = normalize_text(content)
    term_hits = extract_term_hits(cleaned_content)
    video_url = transcript_payload.get("video_url")
    analysis_chunks = build_analysis_chunks(transcript_payload, cleaned_content)

    return {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "record_type": "youtube_transcript_analysis_record",
        "source": {
            "transcript_json_path": source_path.as_posix(),
            "analysis_json_path": output_path.as_posix(),
            "video_url": video_url,
            "video_id": extract_video_id(video_url),
            "channel_slug": source_path.parent.name,
            "title": transcript_payload.get("title"),
            "provider": transcript_payload.get("provider"),
            "language": transcript_payload.get("lang"),
        },
        "text": {
            "raw_content": content,
            "cleaned_content": cleaned_content,
            "raw_character_count": len(content),
            "cleaned_character_count": len(cleaned_content),
        },
        "community_lexicon": {
            "term_hits": term_hits,
            "terms_detected": [hit["term"] for hit in term_hits],
        },
        "chunks": {
            "chunking_strategy": "timed_transcript_chunk_aggregation_v1",
            "target_character_count": CHUNK_TARGET_CHARACTER_COUNT,
            "minimum_chunk_character_count": CHUNK_MIN_CHARACTER_COUNT,
            "items": analysis_chunks,
        },
        "analysis_status": {
            "cleaning_complete": True,
            "chunking_complete": bool(analysis_chunks),
            "topic_analysis_complete": False,
            "principle_extraction_complete": False,
            "generated_at": utc_now_iso(),
        },
    }


def find_transcript_json_files(transcript_root: Path) -> list[Path]:
    return sorted(path for path in transcript_root.glob("**/*.json") if path.is_file())


def build_analysis_corpus(transcript_root: Path, output_root: Path, dry_run: bool = False) -> dict:
    transcript_files = find_transcript_json_files(transcript_root)
    written = 0

    for transcript_path in transcript_files:
        relative_path = transcript_path.relative_to(transcript_root)
        output_path = output_root / relative_path
        transcript_payload = load_json(transcript_path)
        analysis_record = build_analysis_record(
            transcript_payload,
            source_path=transcript_path,
            output_path=output_path,
        )

        if not dry_run:
            write_json(output_path, analysis_record)
        written += 1

    return {
        "transcript_root": str(transcript_root),
        "output_root": str(output_root),
        "files_scanned": len(transcript_files),
        "files_written": written,
        "dry_run": dry_run,
    }


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Build cleaned analysis-ready transcript records while preserving community lexicon terms."
    )
    parser.add_argument(
        "--transcript-root",
        default=str(repo_root / "data" / "transcripts" / "youtube"),
        help="Root directory containing transcript JSON artifacts.",
    )
    parser.add_argument(
        "--output-root",
        default=str(repo_root / "data" / "analysis" / "youtube"),
        help="Root directory where analysis-ready JSON files will be written.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect the analysis build without writing files.",
    )
    args = parser.parse_args()

    summary = build_analysis_corpus(
        transcript_root=Path(args.transcript_root),
        output_root=Path(args.output_root),
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
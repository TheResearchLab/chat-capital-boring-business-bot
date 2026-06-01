import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


ANALYSIS_SCHEMA_VERSION = "analysis_record_v1"
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
STAGE_DIRECTIONS_PATTERN = re.compile(r"\[(?:laughter|music|applause|cheering|snorts?)\]", re.IGNORECASE)
QUOTE_MARKER_PATTERN = re.compile(r"(^|\s)>>\s*")
WHITESPACE_PATTERN = re.compile(r"\s+")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def normalize_text(text: str) -> str:
    cleaned = STAGE_DIRECTIONS_PATTERN.sub(" ", text)
    cleaned = QUOTE_MARKER_PATTERN.sub(r"\1", cleaned)
    cleaned = WHITESPACE_PATTERN.sub(" ", cleaned)
    return cleaned.strip()


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

    return {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "record_type": "youtube_transcript_analysis_record",
        "source": {
            "transcript_json_path": source_path.as_posix(),
            "analysis_json_path": output_path.as_posix(),
            "video_url": transcript_payload.get("video_url"),
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
        "analysis_status": {
            "cleaning_complete": True,
            "chunking_complete": False,
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
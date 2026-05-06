import argparse
import csv
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = "youtube_video_record_v1"
RECORD_TYPE = "youtube_stream_video"
INDEX_COLUMNS = [
    "channel_name",
    "channel_slug",
    "video_id",
    "entry_title",
    "video_url",
    "youtube_published_at",
    "youtube_published_at_utc",
    "youtube_published_at_eastern",
    "live_status",
    "duration_seconds",
    "view_count",
    "source_tab",
    "fetched_at",
    "workflow_status",
    "transcript_status",
    "needs_review",
    "transcript_provider",
    "transcript_artifact_path",
    "transcript_requested_at",
    "transcript_completed_at",
    "transcript_error",
    "json_path",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def merge_defaults(existing: dict, defaults: dict) -> dict:
    for key, value in defaults.items():
        if key not in existing:
            existing[key] = deepcopy(value)
            continue

        if isinstance(existing[key], dict) and isinstance(value, dict):
            merge_defaults(existing[key], value)

    return existing


def find_video_json_files(data_root: Path) -> list[Path]:
    return sorted(path for path in data_root.glob("**/videos/*.json") if path.is_file())


def build_defaults(record: dict, repo_root: Path, json_path: Path) -> dict:
    relative_json_path = json_path.relative_to(repo_root).as_posix()
    channel_root = json_path.parent.parent
    relative_channel_root = channel_root.relative_to(repo_root).as_posix()
    channel_slug = channel_root.name
    source_fetched_at = record.get("fetched_at")

    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": RECORD_TYPE,
        "storage": {
            "json_path": relative_json_path,
            "channel_root": relative_channel_root,
            "channel_slug": channel_slug,
        },
        "workflow": {
            "status": "ready_for_transcript",
            "ready_for_transcript": True,
            "needs_review": False,
            "notes": None,
            "timestamps": {
                "source_fetched_at": source_fetched_at,
                "schema_initialized_at": source_fetched_at,
                "last_enriched_at": None,
            },
        },
        "transcript": {
            "status": "not_started",
            "provider": None,
            "requested_at": None,
            "completed_at": None,
            "artifact_path": None,
            "artifact_schema_version": None,
            "has_timestamps": False,
            "error": None,
            "language": None,
        },
    }


def derive_workflow_status(transcript: dict, workflow: dict) -> str:
    if workflow.get("needs_review") or transcript.get("status") == "failed":
        return "needs_review"

    if transcript.get("status") in {"queued", "in_progress"}:
        return "transcript_in_progress"

    if transcript.get("status") == "completed":
        return "transcript_ready"

    return "ready_for_transcript"


def normalize_record(record: dict, repo_root: Path, json_path: Path) -> dict:
    had_workflow = "workflow" in record
    had_transcript = "transcript" in record
    normalized = merge_defaults(deepcopy(record), build_defaults(record, repo_root, json_path))
    transcript = normalized["transcript"]
    workflow = normalized["workflow"]

    if "processing" in normalized:
        processing = normalized.pop("processing")
        legacy_timestamps = processing.get("timestamps") or {}
        legacy_flags = processing.get("flags") or {}
        legacy_transcript = (processing.get("stages") or {}).get("transcript") or {}

        if not had_workflow:
            for key, value in legacy_timestamps.items():
                if value is not None:
                    workflow["timestamps"][key] = value

        if not had_transcript:
            for key, value in legacy_transcript.items():
                if value is not None:
                    transcript[key] = value

        if workflow.get("needs_review") is False:
            workflow["needs_review"] = bool(legacy_flags.get("needs_review"))

    workflow["ready_for_transcript"] = transcript.get("status") == "not_started"
    workflow["needs_review"] = bool(workflow.get("needs_review")) or transcript.get("status") == "failed"
    workflow["status"] = derive_workflow_status(transcript, workflow)
    workflow["timestamps"]["source_fetched_at"] = workflow["timestamps"].get("source_fetched_at") or normalized.get(
        "fetched_at"
    )

    return normalized


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_index_row(record: dict) -> dict:
    workflow = record["workflow"]
    transcript = record["transcript"]
    storage = record["storage"]

    return {
        "channel_name": record.get("channel_name") or "",
        "channel_slug": storage.get("channel_slug") or "",
        "video_id": record.get("video_id") or "",
        "entry_title": record.get("entry_title") or "",
        "video_url": record.get("video_url") or "",
        "youtube_published_at": record.get("youtube_published_at") or "",
        "youtube_published_at_utc": record.get("youtube_published_at_utc") or "",
        "youtube_published_at_eastern": record.get("youtube_published_at_eastern") or "",
        "live_status": record.get("live_status") or "",
        "duration_seconds": record.get("duration_seconds") or "",
        "view_count": record.get("view_count") or "",
        "source_tab": record.get("source_tab") or "",
        "fetched_at": record.get("fetched_at") or "",
        "workflow_status": workflow.get("status") or "",
        "transcript_status": transcript.get("status") or "",
        "needs_review": str(bool(workflow.get("needs_review"))).lower(),
        "transcript_provider": transcript.get("provider") or "",
        "transcript_artifact_path": transcript.get("artifact_path") or "",
        "transcript_requested_at": transcript.get("requested_at") or "",
        "transcript_completed_at": transcript.get("completed_at") or "",
        "transcript_error": transcript.get("error") or "",
        "json_path": storage.get("json_path") or "",
    }


def write_index(index_path: Path, rows: list[dict]) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=INDEX_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def enrich_video_metadata(data_root: Path, index_path: Path, dry_run: bool = False) -> dict:
    repo_root = Path(__file__).resolve().parents[1]
    now_iso = utc_now_iso()
    video_files = find_video_json_files(data_root)

    changed = 0
    unchanged = 0
    index_rows: list[dict] = []

    for json_path in video_files:
        original = load_json(json_path)
        normalized = normalize_record(original, repo_root, json_path)

        if normalized != original:
            normalized["workflow"]["timestamps"]["schema_initialized_at"] = (
                normalized["workflow"]["timestamps"].get("schema_initialized_at") or now_iso
            )
            normalized["workflow"]["timestamps"]["last_enriched_at"] = now_iso
            changed += 1
            if not dry_run:
                write_json(json_path, normalized)
        else:
            unchanged += 1

        index_rows.append(build_index_row(normalized))

    index_rows.sort(key=lambda row: (row["channel_slug"], row["video_id"]))
    if not dry_run:
        write_index(index_path, index_rows)

    return {
        "data_root": str(data_root),
        "files_scanned": len(video_files),
        "files_changed": changed,
        "files_unchanged": unchanged,
        "index_path": str(index_path),
        "dry_run": dry_run,
    }


def print_schema() -> None:
    schema = {
        "schema_version": SCHEMA_VERSION,
        "record_type": RECORD_TYPE,
        "storage": {
            "json_path": "data/raw/youtube/<channel>/videos/<video_id>.json",
            "channel_root": "data/raw/youtube/<channel>",
            "channel_slug": "kenny-finance-streams",
        },
        "workflow": {
            "status": "ready_for_transcript",
            "ready_for_transcript": True,
            "needs_review": False,
            "notes": None,
            "timestamps": {
                "source_fetched_at": "2026-05-06T02:38:06.455001+00:00",
                "schema_initialized_at": "2026-05-06T02:38:06.455001+00:00",
                "last_enriched_at": "2026-05-06T03:00:00+00:00",
            },
        },
        "transcript": {
            "status": "not_started",
            "provider": None,
            "requested_at": None,
            "completed_at": None,
            "artifact_path": None,
            "artifact_schema_version": None,
            "has_timestamps": False,
            "error": None,
            "language": None,
        },
    }
    print(json.dumps(schema, indent=2))


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Enrich saved YouTube video metadata JSON files with processing lifecycle fields."
    )
    parser.add_argument(
        "--data-root",
        default=str(repo_root / "data" / "raw" / "youtube"),
        help="Root directory containing raw YouTube metadata.",
    )
    parser.add_argument(
        "--index-path",
        default=str(repo_root / "data" / "raw" / "youtube" / "transcript_queue.csv"),
        help="CSV path for the derived repo-wide transcript queue.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect changes without rewriting JSON files or the derived index.",
    )
    parser.add_argument(
        "--print-schema",
        action="store_true",
        help="Print the enrichment schema example and exit.",
    )
    args = parser.parse_args()

    if args.print_schema:
        print_schema()
        return

    summary = enrich_video_metadata(
        data_root=Path(args.data_root),
        index_path=Path(args.index_path),
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
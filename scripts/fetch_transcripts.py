import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from supadata import Supadata, SupadataError

from enrich_video_metadata import enrich_video_metadata


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def get_supadata_client() -> Supadata:
    load_dotenv()
    api_key = os.getenv("supadata_api_key")
    if not api_key:
        raise RuntimeError("Could not find supadata_api_key in .env.")
    return Supadata(api_key=api_key)


def get_ready_video_json_files(data_root: Path, retry_failed: bool = False) -> list[Path]:
    video_files = sorted(path for path in data_root.glob("**/videos/*.json") if path.is_file())
    ready_files: list[Path] = []

    for json_path in video_files:
        record = load_json(json_path)
        transcript = record.get("transcript") or {}
        workflow = record.get("workflow") or {}
        status = transcript.get("status")

        if status == "completed":
            continue

        if retry_failed:
            if status in {"not_started", "failed"}:
                ready_files.append(json_path)
            continue

        if workflow.get("ready_for_transcript") and status == "not_started":
            ready_files.append(json_path)

    return ready_files


def build_transcript_dir(transcript_root: Path, record: dict) -> Path:
    return transcript_root / record["storage"]["channel_slug"]


def fetch_transcript_payload(client: Supadata, video_url: str) -> dict:
    transcript = client.transcript(
        url=video_url,
        lang="en",
        text=True,
        mode="auto",
    )

    if not hasattr(transcript, "content"):
        job_id = getattr(transcript, "job_id", None)
        raise RuntimeError(f"Transcript job started asynchronously for {video_url}: {job_id}")

    return {
        "video_url": video_url,
        "content": transcript.content,
        "lang": transcript.lang,
        "title": getattr(transcript, "title", None),
        "provider": "supadata",
        "fetched_at": utc_now_iso(),
    }


def save_transcript_artifacts(transcript_dir: Path, video_id: str, payload: dict) -> tuple[str, str]:
    transcript_dir.mkdir(parents=True, exist_ok=True)
    text_path = transcript_dir / f"{video_id}.txt"
    json_path = transcript_dir / f"{video_id}.json"

    text_path.write_text(payload.get("content", ""), encoding="utf-8")
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return json_path.as_posix(), text_path.as_posix()


def mark_in_progress(record: dict) -> None:
    now_iso = utc_now_iso()
    record["workflow"]["status"] = "transcript_in_progress"
    record["workflow"]["ready_for_transcript"] = False
    record["workflow"]["needs_review"] = False
    record["workflow"]["timestamps"]["last_enriched_at"] = now_iso
    record["transcript"]["status"] = "in_progress"
    record["transcript"]["provider"] = "supadata"
    record["transcript"]["requested_at"] = now_iso
    record["transcript"]["error"] = None


def mark_completed(record: dict, transcript_payload: dict, artifact_path: str) -> None:
    now_iso = utc_now_iso()
    record["workflow"]["status"] = "transcript_ready"
    record["workflow"]["ready_for_transcript"] = False
    record["workflow"]["needs_review"] = False
    record["workflow"]["timestamps"]["last_enriched_at"] = now_iso
    record["transcript"]["status"] = "completed"
    record["transcript"]["provider"] = transcript_payload.get("provider")
    record["transcript"]["completed_at"] = now_iso
    record["transcript"]["artifact_path"] = artifact_path
    record["transcript"]["language"] = transcript_payload.get("lang")
    record["transcript"]["error"] = None


def mark_failed(record: dict, error_message: str) -> None:
    now_iso = utc_now_iso()
    record["workflow"]["status"] = "needs_review"
    record["workflow"]["ready_for_transcript"] = False
    record["workflow"]["needs_review"] = True
    record["workflow"]["timestamps"]["last_enriched_at"] = now_iso
    record["transcript"]["status"] = "failed"
    record["transcript"]["error"] = error_message


def fetch_transcripts(
    data_root: Path,
    transcript_root: Path,
    index_path: Path,
    limit: int | None = None,
    retry_failed: bool = False,
    dry_run: bool = False,
) -> dict:
    client = None if dry_run else get_supadata_client()
    repo_root = Path(__file__).resolve().parents[1]
    ready_files = get_ready_video_json_files(data_root, retry_failed=retry_failed)
    if limit is not None:
        ready_files = ready_files[:limit]

    fetched = 0
    failed = 0
    skipped = 0

    for json_path in ready_files:
        record = load_json(json_path)
        video_id = record["video_id"]
        transcript_dir = build_transcript_dir(transcript_root, record)
        relative_json_path = json_path.relative_to(repo_root).as_posix()

        transcript_status = (record.get("transcript") or {}).get("status")
        if transcript_status == "completed":
            skipped += 1
            continue

        try:
            if dry_run:
                print(f"Would fetch transcript for {video_id} from {relative_json_path}")
                fetched += 1
                continue

            if not dry_run:
                mark_in_progress(record)
                write_json(json_path, record)

            payload = fetch_transcript_payload(client, record["video_url"])
            transcript_json_path, _ = save_transcript_artifacts(transcript_dir, video_id, payload) if not dry_run else (
                str((transcript_dir / f"{video_id}.json").as_posix()),
                str((transcript_dir / f"{video_id}.txt").as_posix()),
            )

            if not dry_run:
                record = load_json(json_path)
                relative_transcript_json_path = Path(transcript_json_path).relative_to(repo_root).as_posix()
                mark_completed(record, payload, relative_transcript_json_path)
                write_json(json_path, record)
            fetched += 1
            print(f"Fetched transcript for {video_id} from {relative_json_path}")
        except (SupadataError, RuntimeError, Exception) as exc:
            failed += 1
            if not dry_run:
                record = load_json(json_path)
                mark_failed(record, str(exc))
                write_json(json_path, record)
            print(f"Failed transcript fetch for {video_id}: {exc}")

    if not dry_run:
        enrich_video_metadata(data_root=data_root, index_path=index_path, dry_run=False)

    return {
        "data_root": str(data_root),
        "transcript_root": str(transcript_root),
        "queue_path": str(index_path),
        "eligible_files": len(ready_files),
        "fetched": fetched,
        "failed": failed,
        "skipped": skipped,
        "dry_run": dry_run,
        "retry_failed": retry_failed,
    }


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Fetch transcripts for queued YouTube videos using Supadata.")
    parser.add_argument(
        "--data-root",
        default=str(repo_root / "data" / "raw" / "youtube"),
        help="Root directory containing enriched video JSON metadata.",
    )
    parser.add_argument(
        "--transcript-root",
        default=str(repo_root / "data" / "transcripts" / "youtube"),
        help="Directory where transcript artifacts are stored.",
    )
    parser.add_argument(
        "--index-path",
        default=str(repo_root / "data" / "raw" / "youtube" / "transcript_queue.csv"),
        help="Transcript queue CSV to refresh after updates.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of queued videos to process.")
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Also retry transcript records currently marked as failed.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be processed without writing files or calling Supadata.",
    )
    args = parser.parse_args()

    summary = fetch_transcripts(
        data_root=Path(args.data_root),
        transcript_root=Path(args.transcript_root),
        index_path=Path(args.index_path),
        limit=args.limit,
        retry_failed=args.retry_failed,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
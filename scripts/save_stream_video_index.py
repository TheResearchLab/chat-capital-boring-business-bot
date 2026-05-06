import argparse
import csv
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "channel"


def fetch_video_details(video_url: str) -> dict:
    ydl_opts = {
        "quiet": True,
        "extract_flat": False,
        "skip_download": True,
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(video_url, download=False) or {}
    except DownloadError as error:
        print(f"WARNING: failed to fetch full metadata for {video_url}: {error}")
        return {}


def nth_weekday_of_month(year: int, month: int, weekday: int, occurrence: int) -> int:
    first_day = datetime(year, month, 1)
    offset = (weekday - first_day.weekday()) % 7
    return 1 + offset + (occurrence - 1) * 7


def eastern_timezone_for_utc(utc_dt: datetime) -> timezone:
    year = utc_dt.year
    dst_start_day = nth_weekday_of_month(year, 3, 6, 2)
    dst_end_day = nth_weekday_of_month(year, 11, 6, 1)

    dst_start_utc = datetime(year, 3, dst_start_day, 7, 0, tzinfo=timezone.utc)
    dst_end_utc = datetime(year, 11, dst_end_day, 6, 0, tzinfo=timezone.utc)

    if dst_start_utc <= utc_dt < dst_end_utc:
        return timezone(timedelta(hours=-4), name="EDT")

    return timezone(timedelta(hours=-5), name="EST")


def build_publish_time_fields(youtube_published_at: int | None) -> dict:
    if not youtube_published_at:
        return {
            "youtube_published_at_utc": None,
            "youtube_published_at_eastern": None,
        }

    utc_dt = datetime.fromtimestamp(youtube_published_at, tz=timezone.utc)
    eastern_dt = utc_dt.astimezone(eastern_timezone_for_utc(utc_dt))
    return {
        "youtube_published_at_utc": utc_dt.isoformat(),
        "youtube_published_at_eastern": eastern_dt.isoformat(),
    }


def build_video_record(entry: dict, collection: dict, details: dict | None = None) -> dict:
    details = details or {}
    youtube_published_at = (
        details.get("release_timestamp")
        or details.get("timestamp")
        or entry.get("release_timestamp")
        or entry.get("timestamp")
    )
    publish_time_fields = build_publish_time_fields(youtube_published_at)

    return {
        "video_id": entry.get("id"),
        "video_url": entry.get("url") or f"https://www.youtube.com/watch?v={entry.get('id')}",
        "entry_title": entry.get("title") or "",
        "description": details.get("description") or entry.get("description"),
        "duration_seconds": details.get("duration") or entry.get("duration"),
        "live_status": details.get("live_status") or entry.get("live_status"),
        "youtube_published_at": youtube_published_at,
        "youtube_upload_date": details.get("upload_date") or entry.get("upload_date"),
        "release_timestamp": details.get("release_timestamp") or entry.get("release_timestamp"),
        "timestamp": details.get("timestamp") or entry.get("timestamp"),
        "view_count": details.get("view_count") or entry.get("view_count"),
        "thumbnails": details.get("thumbnails") or entry.get("thumbnails") or [],
        "channel_name": collection["channel_name"],
        "channel_id": collection["channel_id"],
        "channel_url": collection["channel_url"],
        "source_tab": collection["source_tab"],
        "fetched_at": collection["fetched_at"],
        **publish_time_fields,
    }


def discover_stream_entries(
    streams_url: str,
    limit: int | None = None,
    fetch_video_details_enabled: bool = False,
) -> tuple[dict, list[dict]]:
    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "playlistend": limit,
        "extractor_args": {
            "youtubetab": {
                "approximate_date": ["true"],
            }
        },
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(streams_url, download=False)

    collection = {
        "source_url": streams_url,
        "source_tab": "streams",
        "channel_name": info.get("channel") or info.get("title") or "channel",
        "channel_id": info.get("channel_id"),
        "channel_url": info.get("channel_url"),
        "tab_title": info.get("title") or "tab",
        "playlist_count": info.get("playlist_count"),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }

    entries: list[dict] = []
    for entry in info.get("entries", []):
        video_id = entry.get("id")
        video_url = entry.get("url") or (f"https://www.youtube.com/watch?v={video_id}" if video_id else None)
        if not video_id or not video_url:
            continue

        details = fetch_video_details(video_url) if fetch_video_details_enabled else {}
        entries.append(build_video_record(entry, collection, details))

    return collection, entries


def get_existing_video_ids(videos_dir: Path) -> set[str]:
    if not videos_dir.exists():
        return set()
    return {path.stem for path in videos_dir.glob("*.json")}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def merge_entry_metadata(existing: dict, entry: dict) -> tuple[dict, bool]:
    merged = dict(existing)
    changed = False

    for key, value in entry.items():
        if key in {"workflow", "transcript", "storage", "schema_version", "record_type"}:
            continue

        if merged.get(key) in (None, "") and value not in (None, ""):
            merged[key] = value
            changed = True

    return merged, changed


def ensure_manifest(manifest_path: Path) -> None:
    if manifest_path.exists():
        return

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "video_id",
                "video_url",
                "entry_title",
                "live_status",
                "duration_seconds",
                "view_count",
                "saved_json_path",
                "fetched_at",
            ],
        )
        writer.writeheader()


def append_manifest_rows(manifest_path: Path, rows: list[dict]) -> None:
    if not rows:
        return

    ensure_manifest(manifest_path)
    with manifest_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "video_id",
                "video_url",
                "entry_title",
                "live_status",
                "duration_seconds",
                "view_count",
                "saved_json_path",
                "fetched_at",
            ],
        )
        writer.writerows(rows)


def save_video_metadata(
    streams_url: str,
    output_root: Path,
    limit: int | None = None,
    fetch_video_details_enabled: bool = False,
) -> dict:
    collection, entries = discover_stream_entries(
        streams_url,
        limit=limit,
        fetch_video_details_enabled=fetch_video_details_enabled,
    )

    channel_slug = slugify(collection["channel_name"])
    channel_root = output_root / f"{channel_slug}-streams"
    videos_dir = channel_root / "videos"
    manifest_path = channel_root / "manifest.csv"
    collection_path = channel_root / "collection.json"

    existing_ids = get_existing_video_ids(videos_dir)
    videos_dir.mkdir(parents=True, exist_ok=True)
    channel_root.mkdir(parents=True, exist_ok=True)

    collection_path.write_text(json.dumps(collection, indent=2, ensure_ascii=False), encoding="utf-8")

    saved = 0
    skipped = 0
    updated = 0
    manifest_rows: list[dict] = []

    for entry in entries:
        video_id = entry["video_id"]
        json_path = videos_dir / f"{video_id}.json"
        if video_id in existing_ids or json_path.exists():
            existing_payload = load_json(json_path)
            merged_payload, changed = merge_entry_metadata(existing_payload, entry)
            if changed:
                write_json(json_path, merged_payload)
                updated += 1
                continue

            skipped += 1
            continue

        write_json(json_path, entry)
        manifest_rows.append(
            {
                "video_id": video_id,
                "video_url": entry["video_url"],
                "entry_title": entry["entry_title"],
                "live_status": entry["live_status"],
                "duration_seconds": entry["duration_seconds"],
                "view_count": entry["view_count"],
                "saved_json_path": str(json_path),
                "fetched_at": entry["fetched_at"],
            }
        )
        saved += 1

    append_manifest_rows(manifest_path, manifest_rows)

    return {
        "channel_name": collection["channel_name"],
        "tab_title": collection["tab_title"],
        "entries_discovered": len(entries),
        "saved": saved,
        "updated": updated,
        "skipped_existing": skipped,
        "output_dir": str(channel_root),
        "manifest_path": str(manifest_path),
        "collection_path": str(collection_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Save YouTube streams-page video metadata without fetching transcripts.")
    parser.add_argument("streams_url", help="YouTube channel streams tab URL")
    parser.add_argument(
        "--output-root",
        default="data/raw/youtube",
        help="Base directory for saved metadata",
    )
    parser.add_argument("--limit", type=int, default=None, help="Optional max number of entries to inspect")
    parser.add_argument(
        "--fetch-video-details",
        action="store_true",
        help="Attempt per-video metadata lookups for fuller YouTube metadata. This is slower and may trigger bot checks without cookies.",
    )
    args = parser.parse_args()

    summary = save_video_metadata(
        streams_url=args.streams_url,
        output_root=Path(args.output_root),
        limit=args.limit,
        fetch_video_details_enabled=args.fetch_video_details,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
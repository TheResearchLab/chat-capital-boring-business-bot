import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from yt_dlp import YoutubeDL


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "channel"


def discover_stream_entries(streams_url: str, limit: int | None = None) -> tuple[dict, list[dict]]:
    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "playlistend": limit,
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

        entries.append(
            {
                "video_id": video_id,
                "video_url": video_url,
                "entry_title": entry.get("title") or "",
                "description": entry.get("description"),
                "duration_seconds": entry.get("duration"),
                "live_status": entry.get("live_status"),
                "release_timestamp": entry.get("release_timestamp"),
                "timestamp": entry.get("timestamp"),
                "view_count": entry.get("view_count"),
                "thumbnails": entry.get("thumbnails") or [],
                "channel_name": collection["channel_name"],
                "channel_id": collection["channel_id"],
                "channel_url": collection["channel_url"],
                "source_tab": collection["source_tab"],
                "fetched_at": collection["fetched_at"],
            }
        )

    return collection, entries


def get_existing_video_ids(videos_dir: Path) -> set[str]:
    if not videos_dir.exists():
        return set()
    return {path.stem for path in videos_dir.glob("*.json")}


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


def save_video_metadata(streams_url: str, output_root: Path, limit: int | None = None) -> dict:
    collection, entries = discover_stream_entries(streams_url, limit=limit)

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
    manifest_rows: list[dict] = []

    for entry in entries:
        video_id = entry["video_id"]
        json_path = videos_dir / f"{video_id}.json"
        if video_id in existing_ids or json_path.exists():
            skipped += 1
            continue

        json_path.write_text(json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8")
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
    args = parser.parse_args()

    summary = save_video_metadata(
        streams_url=args.streams_url,
        output_root=Path(args.output_root),
        limit=args.limit,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
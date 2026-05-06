import sys
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yt_dlp.utils import DownloadError


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from save_stream_video_index import build_video_record, fetch_video_details, save_video_metadata  # noqa: E402


class SaveStreamVideoIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = Path(tempfile.mkdtemp(dir=REPO_ROOT))
        self.addCleanup(shutil.rmtree, self.temp_root, True)

    def test_build_video_record_prefers_detailed_publish_metadata(self) -> None:
        collection = {
            "channel_name": "Demo Channel",
            "channel_id": "channel-1",
            "channel_url": "https://www.youtube.com/@demo",
            "source_tab": "streams",
            "fetched_at": "2026-05-05T00:00:00+00:00",
        }
        entry = {
            "id": "abc123",
            "url": "https://www.youtube.com/watch?v=abc123",
            "title": "Demo video",
            "duration": 120,
            "live_status": "was_live",
            "view_count": 5,
        }
        details = {
            "description": "Full metadata description",
            "duration": 125,
            "live_status": "was_live",
            "release_timestamp": 1746403200,
            "upload_date": "20250505",
            "view_count": 10,
            "thumbnails": [{"url": "https://example.com/thumb.jpg"}],
        }

        payload = build_video_record(entry, collection, details)

        self.assertEqual(payload["video_id"], "abc123")
        self.assertEqual(payload["youtube_published_at"], 1746403200)
        self.assertEqual(payload["youtube_published_at_utc"], "2025-05-05T00:00:00+00:00")
        self.assertEqual(payload["youtube_published_at_eastern"], "2025-05-04T20:00:00-04:00")
        self.assertEqual(payload["youtube_upload_date"], "20250505")
        self.assertEqual(payload["release_timestamp"], 1746403200)
        self.assertEqual(payload["duration_seconds"], 125)
        self.assertEqual(payload["view_count"], 10)

    def test_build_video_record_falls_back_to_timestamp_when_release_is_missing(self) -> None:
        collection = {
            "channel_name": "Demo Channel",
            "channel_id": "channel-1",
            "channel_url": "https://www.youtube.com/@demo",
            "source_tab": "streams",
            "fetched_at": "2026-05-05T00:00:00+00:00",
        }
        entry = {
            "id": "fallback1",
            "url": "https://www.youtube.com/watch?v=fallback1",
            "title": "Fallback video",
            "upload_date": "20250504",
            "timestamp": 1746316800,
        }
        details = {
            "timestamp": 1746316800,
        }

        payload = build_video_record(entry, collection, details)

        self.assertEqual(payload["youtube_published_at"], 1746316800)
        self.assertEqual(payload["youtube_published_at_utc"], "2025-05-04T00:00:00+00:00")
        self.assertEqual(payload["youtube_published_at_eastern"], "2025-05-03T20:00:00-04:00")
        self.assertEqual(payload["youtube_upload_date"], "20250504")

    def test_fetch_video_details_returns_empty_payload_when_yt_blocks_lookup(self) -> None:
        mock_ydl = patch("save_stream_video_index.YoutubeDL").start()
        self.addCleanup(patch.stopall)
        mock_instance = mock_ydl.return_value.__enter__.return_value
        mock_instance.extract_info.side_effect = DownloadError("sign in to confirm you're not a bot")

        payload = fetch_video_details("https://www.youtube.com/watch?v=blocked1")

        self.assertEqual(payload, {})

    def test_save_video_metadata_backfills_publish_fields_for_existing_records(self) -> None:
        output_root = self.temp_root / "data" / "raw" / "youtube"
        channel_root = output_root / "demo-channel-streams"
        videos_dir = channel_root / "videos"
        videos_dir.mkdir(parents=True, exist_ok=True)
        existing_path = videos_dir / "abc123.json"
        existing_path.write_text(
            json.dumps(
                {
                    "video_id": "abc123",
                    "video_url": "https://www.youtube.com/watch?v=abc123",
                    "entry_title": "Demo video",
                    "channel_name": "Demo Channel",
                    "source_tab": "streams",
                    "fetched_at": "2026-05-05T00:00:00+00:00",
                    "workflow": {"status": "ready_for_transcript"},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        collection = {
            "source_url": "https://www.youtube.com/@demo/streams",
            "source_tab": "streams",
            "channel_name": "Demo Channel",
            "channel_id": "channel-1",
            "channel_url": "https://www.youtube.com/@demo",
            "tab_title": "Demo streams",
            "playlist_count": 1,
            "fetched_at": "2026-05-05T00:00:00+00:00",
        }
        entries = [
            {
                "video_id": "abc123",
                "video_url": "https://www.youtube.com/watch?v=abc123",
                "entry_title": "Demo video",
                "youtube_published_at": 1746403200,
                "youtube_published_at_utc": "2025-05-05T00:00:00+00:00",
                "youtube_published_at_eastern": "2025-05-04T20:00:00-04:00",
                "youtube_upload_date": "20250505",
                "release_timestamp": 1746403200,
                "timestamp": 1746403200,
                "channel_name": "Demo Channel",
                "channel_id": "channel-1",
                "channel_url": "https://www.youtube.com/@demo",
                "source_tab": "streams",
                "fetched_at": "2026-05-05T00:00:00+00:00",
            }
        ]

        with patch("save_stream_video_index.discover_stream_entries", return_value=(collection, entries)):
            summary = save_video_metadata(
                "https://www.youtube.com/@demo/streams",
                output_root,
            )

        payload = json.loads(existing_path.read_text(encoding="utf-8"))
        self.assertEqual(summary["saved"], 0)
        self.assertEqual(summary["updated"], 1)
        self.assertEqual(summary["skipped_existing"], 0)
        self.assertEqual(payload["youtube_published_at"], 1746403200)
        self.assertEqual(payload["youtube_published_at_utc"], "2025-05-05T00:00:00+00:00")
        self.assertEqual(payload["youtube_published_at_eastern"], "2025-05-04T20:00:00-04:00")
        self.assertEqual(payload["youtube_upload_date"], "20250505")
        self.assertEqual(payload["workflow"]["status"], "ready_for_transcript")


if __name__ == "__main__":
    unittest.main()
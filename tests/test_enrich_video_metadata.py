import csv
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from enrich_video_metadata import enrich_video_metadata  # noqa: E402


class EnrichVideoMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = Path(tempfile.mkdtemp(dir=REPO_ROOT))
        self.addCleanup(shutil.rmtree, self.temp_root, True)
        self.data_root = self.temp_root / "data" / "raw" / "youtube"
        self.index_path = self.data_root / "transcript_queue.csv"

    def _write_video_record(self, record: dict, channel_slug: str = "demo-streams", video_id: str = "abc123") -> Path:
        json_path = self.data_root / channel_slug / "videos" / f"{video_id}.json"
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        return json_path

    def test_enrich_adds_schema_fields_and_queue_row(self) -> None:
        json_path = self._write_video_record(
            {
                "video_id": "abc123",
                "video_url": "https://www.youtube.com/watch?v=abc123",
                "entry_title": "Demo video",
                "youtube_published_at": 1746403200,
                "youtube_published_at_utc": "2025-05-05T00:00:00+00:00",
                "youtube_published_at_eastern": "2025-05-04T20:00:00-04:00",
                "duration_seconds": 120,
                "live_status": "was_live",
                "view_count": 10,
                "channel_name": "Demo Channel",
                "channel_id": "channel-1",
                "channel_url": "https://www.youtube.com/@demo",
                "source_tab": "streams",
                "fetched_at": "2026-05-05T00:00:00+00:00",
            }
        )

        summary = enrich_video_metadata(self.data_root, self.index_path, dry_run=False)

        self.assertEqual(summary["files_changed"], 1)
        self.assertTrue(self.index_path.exists())

        payload = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], "youtube_video_record_v1")
        self.assertEqual(payload["record_type"], "youtube_stream_video")
        self.assertEqual(payload["workflow"]["status"], "ready_for_transcript")
        self.assertTrue(payload["workflow"]["ready_for_transcript"])
        self.assertEqual(payload["transcript"]["status"], "not_started")
        self.assertEqual(payload["storage"]["channel_slug"], "demo-streams")

        with self.index_path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["video_id"], "abc123")
        self.assertEqual(rows[0]["youtube_published_at"], "1746403200")
        self.assertEqual(rows[0]["youtube_published_at_utc"], "2025-05-05T00:00:00+00:00")
        self.assertEqual(rows[0]["youtube_published_at_eastern"], "2025-05-04T20:00:00-04:00")
        self.assertEqual(rows[0]["workflow_status"], "ready_for_transcript")

    def test_enrich_migrates_legacy_processing_to_needs_review(self) -> None:
        json_path = self._write_video_record(
            {
                "video_id": "legacy123",
                "video_url": "https://www.youtube.com/watch?v=legacy123",
                "entry_title": "Legacy video",
                "channel_name": "Demo Channel",
                "source_tab": "streams",
                "fetched_at": "2026-05-05T00:00:00+00:00",
                "processing": {
                    "flags": {"needs_review": True},
                    "timestamps": {"schema_initialized_at": "2026-05-05T00:00:00+00:00"},
                    "stages": {
                        "transcript": {
                            "status": "failed",
                            "provider": "supadata",
                            "error": "boom",
                        }
                    },
                },
            },
            video_id="legacy123",
        )

        enrich_video_metadata(self.data_root, self.index_path, dry_run=False)

        payload = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["workflow"]["status"], "needs_review")
        self.assertTrue(payload["workflow"]["needs_review"])
        self.assertEqual(payload["transcript"]["status"], "failed")
        self.assertEqual(payload["transcript"]["provider"], "supadata")
        self.assertEqual(payload["transcript"]["error"], "boom")


if __name__ == "__main__":
    unittest.main()
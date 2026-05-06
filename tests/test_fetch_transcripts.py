import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from fetch_transcripts import fetch_transcripts, get_ready_video_json_files, save_transcript_artifacts  # noqa: E402


class FetchTranscriptsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = Path(tempfile.mkdtemp(dir=REPO_ROOT))
        self.addCleanup(shutil.rmtree, self.temp_root, True)
        self.data_root = self.temp_root / "data" / "raw" / "youtube"
        self.transcript_root = self.temp_root / "data" / "transcripts" / "youtube"
        self.index_path = self.data_root / "transcript_queue.csv"

    def _write_video_record(
        self,
        video_id: str,
        transcript_status: str,
        ready_for_transcript: bool,
        artifact_path: str | None = None,
        has_timestamps: bool = False,
        artifact_schema_version: str | None = None,
    ) -> Path:
        json_path = self.data_root / "demo-streams" / "videos" / f"{video_id}.json"
        json_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "video_id": video_id,
            "video_url": f"https://www.youtube.com/watch?v={video_id}",
            "entry_title": f"Video {video_id}",
            "channel_name": "Demo Channel",
            "fetched_at": "2026-05-05T00:00:00+00:00",
            "storage": {
                "json_path": f"data/raw/youtube/demo-streams/videos/{video_id}.json",
                "channel_root": "data/raw/youtube/demo-streams",
                "channel_slug": "demo-streams",
            },
            "workflow": {
                "status": "ready_for_transcript" if ready_for_transcript else "needs_review",
                "ready_for_transcript": ready_for_transcript,
                "needs_review": transcript_status == "failed",
                "notes": None,
                "timestamps": {
                    "source_fetched_at": "2026-05-05T00:00:00+00:00",
                    "schema_initialized_at": "2026-05-05T00:00:00+00:00",
                    "last_enriched_at": None,
                },
            },
            "transcript": {
                "status": transcript_status,
                "provider": None,
                "requested_at": None,
                "completed_at": None,
                "artifact_path": artifact_path,
                "artifact_schema_version": artifact_schema_version,
                "has_timestamps": has_timestamps,
                "error": None,
                "language": None,
            },
        }
        json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return json_path

    def test_get_ready_video_json_files_filters_expected_records(self) -> None:
        ready_path = self._write_video_record("ready1", "not_started", True)
        failed_path = self._write_video_record("failed1", "failed", False)
        self._write_video_record("done1", "completed", False)

        ready_files = get_ready_video_json_files(self.data_root, retry_failed=False)
        retry_files = get_ready_video_json_files(self.data_root, retry_failed=True)

        self.assertEqual(ready_files, [ready_path])
        self.assertEqual(retry_files, sorted([failed_path, ready_path]))

    def test_get_ready_video_json_files_can_select_completed_records_missing_timestamps(self) -> None:
        artifact_path = self.transcript_root / "demo-streams" / "completed1.json"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(
            json.dumps(
                {
                    "video_url": "https://www.youtube.com/watch?v=completed1",
                    "content": "plain only",
                    "lang": "en",
                    "provider": "supadata",
                    "fetched_at": "2026-05-05T00:00:00+00:00",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        completed_path = self._write_video_record(
            "completed1",
            "completed",
            False,
            artifact_path=artifact_path.relative_to(REPO_ROOT).as_posix(),
        )

        ready_files = get_ready_video_json_files(
            self.data_root,
            upgrade_missing_timestamps=True,
        )

        self.assertEqual(ready_files, [completed_path])

    def test_fetch_transcripts_dry_run_does_not_write_artifacts(self) -> None:
        json_path = self._write_video_record("dryrun1", "not_started", True)

        summary = fetch_transcripts(
            data_root=self.data_root,
            transcript_root=self.transcript_root,
            index_path=self.index_path,
            dry_run=True,
        )

        self.assertEqual(summary["eligible_files"], 1)
        self.assertEqual(summary["fetched"], 1)
        self.assertEqual(summary["failed"], 0)
        self.assertFalse((self.transcript_root / "demo-streams" / "dryrun1.json").exists())

        payload = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["transcript"]["status"], "not_started")

    def test_save_transcript_artifacts_writes_json_and_text(self) -> None:
        json_path, text_path = save_transcript_artifacts(
            self.transcript_root / "demo-streams",
            "artifact1",
            {
                "video_url": "https://www.youtube.com/watch?v=artifact1",
                "content": "hello world",
                "lang": "en",
                "provider": "supadata",
                "fetched_at": "2026-05-05T00:00:00+00:00",
            },
        )

        self.assertTrue(Path(json_path).exists())
        self.assertTrue(Path(text_path).exists())
        self.assertEqual(Path(text_path).read_text(encoding="utf-8"), "hello world")

        payload = json.loads(Path(json_path).read_text(encoding="utf-8"))
        self.assertIn("chunks", payload)


if __name__ == "__main__":
    unittest.main()
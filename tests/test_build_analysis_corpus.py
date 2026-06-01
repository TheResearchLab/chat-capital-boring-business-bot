import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from build_analysis_corpus import build_analysis_corpus, normalize_text  # noqa: E402


class BuildAnalysisCorpusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = Path(tempfile.mkdtemp(dir=REPO_ROOT))
        self.addCleanup(shutil.rmtree, self.temp_root, True)
        self.transcript_root = self.temp_root / "data" / "transcripts" / "youtube"
        self.output_root = self.temp_root / "data" / "analysis" / "youtube"

    def test_normalize_text_removes_transcript_noise(self) -> None:
        cleaned = normalize_text(
            ">> [laughter] [singing] [music and singing] This is good goop right here. 88 >> Send him to the gulag."
        )

        self.assertEqual(cleaned, "This is good goop right here. 88 Send him to the gulag.")

    def test_build_analysis_corpus_writes_cleaned_records_with_term_hits(self) -> None:
        transcript_path = self.transcript_root / "demo-streams" / "video1.json"
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text(
            json.dumps(
                {
                    "video_url": "https://www.youtube.com/watch?v=video1",
                    "title": "Demo Transcript",
                    "lang": "en",
                    "provider": "supadata",
                    "content": (
                        ">> [laughter] Shredlords bring good goop. "
                        "If the website is chalked, send it to the gulag."
                    ),
                    "chunks": [
                        {
                            "text": ">> [laughter] Shredlords bring good goop.",
                            "offset": 0,
                            "duration": 4000,
                            "lang": "en",
                        },
                        {
                            "text": "If the website is chalked, send it to the gulag.",
                            "offset": 4000,
                            "duration": 5000,
                            "lang": "en",
                        },
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        summary = build_analysis_corpus(self.transcript_root, self.output_root, dry_run=False)

        self.assertEqual(summary["files_scanned"], 1)
        self.assertEqual(summary["files_written"], 1)

        output_path = self.output_root / "demo-streams" / "video1.json"
        self.assertTrue(output_path.exists())

        payload = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["source"]["video_id"], "video1")
        self.assertEqual(payload["source"]["channel_slug"], "demo-streams")
        self.assertEqual(
            payload["text"]["cleaned_content"],
            "Shredlords bring good goop. If the website is chalked, send it to the gulag.",
        )
        self.assertEqual(
            payload["community_lexicon"]["terms_detected"],
            ["chalked", "goop", "gulag", "shredlord"],
        )

        hits_by_term = {hit["term"]: hit for hit in payload["community_lexicon"]["term_hits"]}
        self.assertEqual(hits_by_term["shredlord"]["matched_forms"], ["shredlords"])
        self.assertEqual(hits_by_term["goop"]["count"], 1)
        self.assertEqual(hits_by_term["chalked"]["count"], 1)
        self.assertEqual(hits_by_term["gulag"]["count"], 1)
        self.assertTrue(payload["analysis_status"]["chunking_complete"])
        self.assertEqual(payload["chunks"]["chunking_strategy"], "timed_transcript_chunk_aggregation_v1")
        self.assertEqual(len(payload["chunks"]["items"]), 1)
        self.assertEqual(
            payload["chunks"]["items"][0]["text"],
            "Shredlords bring good goop. If the website is chalked, send it to the gulag.",
        )
        self.assertEqual(
            payload["chunks"]["items"][0]["source_provenance"],
            {
                "start_source_chunk_index": 0,
                "end_source_chunk_index": 1,
                "start_offset_ms": 0,
                "end_offset_ms": 9000,
                "duration_ms": 9000,
                "language": "en",
            },
        )

    def test_build_analysis_corpus_splits_large_transcript_into_multiple_chunks(self) -> None:
        transcript_path = self.transcript_root / "demo-streams" / "video2.json"
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text(
            json.dumps(
                {
                    "video_url": "https://www.youtube.com/watch?v=video2",
                    "title": "Chunked Transcript",
                    "lang": "en",
                    "provider": "supadata",
                    "content": " ".join(["Alpha insight."] * 45 + ["Beta insight."] * 45),
                    "chunks": [
                        {
                            "text": " ".join(["Alpha insight."] * 45),
                            "offset": 0,
                            "duration": 10000,
                            "lang": "en",
                        },
                        {
                            "text": " ".join(["Beta insight."] * 45),
                            "offset": 10000,
                            "duration": 12000,
                            "lang": "en",
                        },
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        build_analysis_corpus(self.transcript_root, self.output_root, dry_run=False)

        payload = json.loads((self.output_root / "demo-streams" / "video2.json").read_text(encoding="utf-8"))
        self.assertEqual(len(payload["chunks"]["items"]), 2)
        self.assertEqual(payload["chunks"]["items"][0]["source_provenance"]["start_source_chunk_index"], 0)
        self.assertEqual(payload["chunks"]["items"][0]["source_provenance"]["end_source_chunk_index"], 0)
        self.assertEqual(payload["chunks"]["items"][1]["source_provenance"]["start_source_chunk_index"], 1)
        self.assertEqual(payload["chunks"]["items"][1]["source_provenance"]["end_source_chunk_index"], 1)
        self.assertTrue(payload["chunks"]["items"][0]["text"].startswith("Alpha insight."))
        self.assertTrue(payload["chunks"]["items"][1]["text"].startswith("Beta insight."))


if __name__ == "__main__":
    unittest.main()
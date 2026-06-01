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
            ">> [laughter] This is good goop right here. Send him to the gulag."
        )

        self.assertEqual(cleaned, "This is good goop right here. Send him to the gulag.")

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


if __name__ == "__main__":
    unittest.main()
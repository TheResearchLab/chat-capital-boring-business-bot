import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from run_topic_analysis import (  # noqa: E402
    build_section_summary_prompt,
    build_topic_synthesis_entries,
    build_topic_synthesis_prompt,
    build_topic_sections,
    collect_chunk_records,
    run_topic_analysis,
    score_seed_topics,
)


class FakeTopicModel:
    def __init__(self, topics_to_terms: dict[int, list[tuple[str, float]]]) -> None:
        self.topics_to_terms = topics_to_terms

    def get_topic(self, topic_id: int):
        return self.topics_to_terms.get(topic_id, [])


class RunTopicAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = Path(tempfile.mkdtemp(dir=REPO_ROOT))
        self.addCleanup(shutil.rmtree, self.temp_root, True)
        self.analysis_root = self.temp_root / "data" / "analysis" / "youtube"
        self.output_root = self.temp_root / "data" / "topic_analysis" / "youtube"

    def write_analysis_record(self, channel_slug: str, video_id: str, chunks: list[dict]) -> None:
        path = self.analysis_root / channel_slug / f"{video_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "source": {
                        "video_id": video_id,
                        "channel_slug": channel_slug,
                        "title": f"Title for {video_id}",
                    },
                    "chunks": {"items": chunks},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def test_score_seed_topics_returns_ranked_matches(self) -> None:
        matches = score_seed_topics(
            "We are buying a business with SBA debt and doing diligence on cash flow."
        )

        self.assertEqual(matches[0]["topic_id"], "business_acquisition")
        self.assertGreaterEqual(matches[0]["match_count"], 3)

    def test_collect_chunk_records_reads_existing_chunk_corpus(self) -> None:
        self.write_analysis_record(
            channel_slug="demo-streams",
            video_id="video1",
            chunks=[
                {
                    "chunk_id": "chunk_0001",
                    "text": "The stock market is moving and this portfolio needs discipline.",
                    "character_count": 61,
                    "source_provenance": {"start_offset_ms": 0, "end_offset_ms": 5000},
                }
            ],
        )

        records = collect_chunk_records(self.analysis_root / "demo-streams")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["video_id"], "video1")
        self.assertEqual(records[0]["chunk_id"], "chunk_0001")
        self.assertEqual(records[0]["seed_topic_scores"][0]["topic_id"], "investing_markets")

    def test_run_topic_analysis_writes_hybrid_topic_artifact(self) -> None:
        self.write_analysis_record(
            channel_slug="demo-streams",
            video_id="video1",
            chunks=[
                {
                    "chunk_id": "chunk_0001",
                    "text": "We are buying a business with SBA debt and strong cash flow.",
                    "character_count": 61,
                    "source_provenance": {"start_offset_ms": 0, "end_offset_ms": 5000},
                },
                {
                    "chunk_id": "chunk_0002",
                    "text": "This stock pitch is really good goop for the chat capital portfolio.",
                    "character_count": 67,
                    "source_provenance": {"start_offset_ms": 5000, "end_offset_ms": 10000},
                },
            ],
        )

        fake_model = FakeTopicModel(
            {
                0: [("business", 0.42), ("cash_flow", 0.31), ("sba", 0.22)],
                1: [("chat", 0.50), ("goop", 0.29), ("portfolio", 0.21)],
            }
        )

        with patch("run_topic_analysis.fit_bertopic_model", return_value=(fake_model, [0, 1])):
            summaries = run_topic_analysis(
                analysis_root=self.analysis_root,
                output_root=self.output_root,
                channel_slug="demo-streams",
                min_topic_size=2,
            )

        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["semantic_topic_count"], 2)

        output_path = self.output_root / "demo-streams" / "topic_analysis.json"
        self.assertTrue(output_path.exists())

        payload = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["topic_analysis"]["method"], "hybrid_seed_topics_plus_bertopic_v1")
        self.assertEqual(payload["source"]["chunk_count"], 2)
        self.assertEqual(
            payload["topic_analysis"]["semantic_topics"][0]["semantic_topic_label"],
            "business, cash_flow, sba",
        )
        self.assertEqual(
            payload["topic_analysis"]["video_topic_summaries"][0]["seed_topic_counts"],
            {"business_acquisition": 1, "community_banter": 1},
        )
        self.assertEqual(len(payload["topic_analysis"]["topic_sections"]), 2)
        self.assertIsNone(payload["topic_analysis"]["topic_sections"][0]["section_summary"])
        self.assertEqual(len(payload["topic_analysis"]["topic_synthesis_entries"]), 2)
        self.assertIsNone(payload["topic_analysis"]["topic_synthesis_entries"][0]["topic_summary"])

    def test_build_topic_sections_merges_adjacent_chunks_with_same_topic(self) -> None:
        chunk_assignments = [
            {
                "video_id": "video1",
                "title": "Title for video1",
                "analysis_json_path": "demo/video1.json",
                "chunk_id": "chunk_0001",
                "text": "We are buying a business.",
                "character_count": 25,
                "source_provenance": {
                    "start_offset_ms": 0,
                    "end_offset_ms": 5000,
                    "start_source_chunk_index": 0,
                    "end_source_chunk_index": 0,
                },
                "primary_seed_topic": "business_acquisition",
                "seed_topic_scores": [],
                "semantic_topic_id": 0,
            },
            {
                "video_id": "video1",
                "title": "Title for video1",
                "analysis_json_path": "demo/video1.json",
                "chunk_id": "chunk_0002",
                "text": "Cash flow matters in diligence.",
                "character_count": 31,
                "source_provenance": {
                    "start_offset_ms": 6000,
                    "end_offset_ms": 11000,
                    "start_source_chunk_index": 1,
                    "end_source_chunk_index": 1,
                },
                "primary_seed_topic": "business_acquisition",
                "seed_topic_scores": [],
                "semantic_topic_id": 0,
            },
            {
                "video_id": "video1",
                "title": "Title for video1",
                "analysis_json_path": "demo/video1.json",
                "chunk_id": "chunk_0003",
                "text": "The chat is posting goop.",
                "character_count": 25,
                "source_provenance": {
                    "start_offset_ms": 12000,
                    "end_offset_ms": 17000,
                    "start_source_chunk_index": 2,
                    "end_source_chunk_index": 2,
                },
                "primary_seed_topic": "community_banter",
                "seed_topic_scores": [],
                "semantic_topic_id": 1,
            },
        ]
        semantic_topic_entries = [
            {"semantic_topic_id": 0, "semantic_topic_label": "business, cash_flow, sba"},
            {"semantic_topic_id": 1, "semantic_topic_label": "chat, goop, portfolio"},
        ]

        sections = build_topic_sections(chunk_assignments, semantic_topic_entries, max_section_gap_ms=90000)

        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[0]["chunk_ids"], ["chunk_0001", "chunk_0002"])
        self.assertEqual(sections[0]["topic_link"]["semantic_topic_label"], "business, cash_flow, sba")
        self.assertEqual(sections[0]["source_provenance"]["duration_ms"], 11000)

    def test_run_topic_analysis_can_attach_ollama_section_summaries(self) -> None:
        self.write_analysis_record(
            channel_slug="demo-streams",
            video_id="video1",
            chunks=[
                {
                    "chunk_id": "chunk_0001",
                    "text": "We are buying a business with SBA debt and strong cash flow.",
                    "character_count": 61,
                    "source_provenance": {
                        "start_offset_ms": 0,
                        "end_offset_ms": 5000,
                        "start_source_chunk_index": 0,
                        "end_source_chunk_index": 0,
                    },
                },
                {
                    "chunk_id": "chunk_0002",
                    "text": "Diligence is about understanding what the business earns.",
                    "character_count": 59,
                    "source_provenance": {
                        "start_offset_ms": 5000,
                        "end_offset_ms": 10000,
                        "start_source_chunk_index": 1,
                        "end_source_chunk_index": 1,
                    },
                },
            ],
        )

        fake_model = FakeTopicModel(
            {
                0: [("business", 0.42), ("cash_flow", 0.31), ("sba", 0.22)],
            }
        )

        with patch("run_topic_analysis.fit_bertopic_model", return_value=(fake_model, [0, 0])):
            with patch(
                "run_topic_analysis.summarize_section_with_ollama",
                return_value={
                    "provider": "ollama",
                    "model": "llama3.1",
                    "summary_text": "Discussion about buying a business, SBA debt, and diligence quality.",
                },
            ):
                with patch(
                    "run_topic_analysis.summarize_topic_group_with_ollama",
                    return_value={
                        "provider": "ollama",
                        "model": "llama3.1",
                        "summary_text": "Repeated acquisition discussion focused on SBA debt, diligence, and cash flow quality.",
                    },
                ):
                    run_topic_analysis(
                        analysis_root=self.analysis_root,
                        output_root=self.output_root,
                        channel_slug="demo-streams",
                        min_topic_size=2,
                        ollama_model="llama3.1",
                    )

        payload = json.loads(
            (self.output_root / "demo-streams" / "topic_analysis.json").read_text(encoding="utf-8")
        )
        self.assertTrue(payload["topic_analysis"]["section_summaries"]["enabled"])
        self.assertEqual(len(payload["topic_analysis"]["topic_sections"]), 1)
        self.assertEqual(
            payload["topic_analysis"]["topic_sections"][0]["section_summary"]["summary_text"],
            "Discussion about buying a business, SBA debt, and diligence quality.",
        )
        self.assertEqual(
            payload["topic_analysis"]["topic_synthesis_entries"][0]["topic_summary"]["summary_text"],
            "Repeated acquisition discussion focused on SBA debt, diligence, and cash flow quality.",
        )

    def test_build_section_summary_prompt_includes_topic_and_offsets(self) -> None:
        prompt = build_section_summary_prompt(
            {
                "section_id": "section_0001",
                "video_id": "video1",
                "title": "Title for video1",
                "topic_link": {
                    "semantic_topic_label": "business, cash_flow, sba",
                    "primary_seed_topic": "business_acquisition",
                },
                "source_provenance": {"start_offset_ms": 0, "end_offset_ms": 10000},
                "text": "We are buying a business with SBA debt and strong cash flow.",
            }
        )

        self.assertIn("Semantic topic: business, cash_flow, sba", prompt)
        self.assertIn("Primary seed topic: business_acquisition", prompt)
        self.assertIn("Start offset ms: 0", prompt)

    def test_build_topic_synthesis_entries_groups_sections_across_timestamps(self) -> None:
        topic_sections = [
            {
                "section_id": "section_0001",
                "video_id": "video1",
                "title": "Video 1",
                "analysis_json_path": "demo/video1.json",
                "topic_link": {
                    "semantic_topic_id": 0,
                    "semantic_topic_label": "business, cash_flow, sba",
                    "primary_seed_topic": "business_acquisition",
                },
                "chunk_count": 2,
                "chunk_ids": ["chunk_0001", "chunk_0002"],
                "character_count": 200,
                "text": "Section one text.",
                "source_provenance": {"start_offset_ms": 0, "end_offset_ms": 10000},
                "section_summary": {"summary_text": "Section one note."},
            },
            {
                "section_id": "section_0002",
                "video_id": "video2",
                "title": "Video 2",
                "analysis_json_path": "demo/video2.json",
                "topic_link": {
                    "semantic_topic_id": 0,
                    "semantic_topic_label": "business, cash_flow, sba",
                    "primary_seed_topic": "business_acquisition",
                },
                "chunk_count": 1,
                "chunk_ids": ["chunk_0009"],
                "character_count": 150,
                "text": "Section two text.",
                "source_provenance": {"start_offset_ms": 30000, "end_offset_ms": 45000},
                "section_summary": {"summary_text": "Section two note."},
            },
            {
                "section_id": "section_0003",
                "video_id": "video2",
                "title": "Video 2",
                "analysis_json_path": "demo/video2.json",
                "topic_link": {
                    "semantic_topic_id": 1,
                    "semantic_topic_label": "chat, goop, portfolio",
                    "primary_seed_topic": "community_banter",
                },
                "chunk_count": 1,
                "chunk_ids": ["chunk_0010"],
                "character_count": 120,
                "text": "Section three text.",
                "source_provenance": {"start_offset_ms": 50000, "end_offset_ms": 55000},
                "section_summary": {"summary_text": "Section three note."},
            },
        ]

        entries = build_topic_synthesis_entries(topic_sections, topic_synthesis_section_limit=4)

        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["semantic_topic_label"], "business, cash_flow, sba")
        self.assertEqual(entries[0]["section_count"], 2)
        self.assertEqual(entries[0]["video_count"], 2)
        self.assertEqual(entries[0]["primary_seed_topics"], ["business_acquisition"])
        self.assertEqual(entries[0]["source_section_ids"], ["section_0001", "section_0002"])

    def test_build_topic_synthesis_prompt_includes_cross_timestamp_notes(self) -> None:
        prompt = build_topic_synthesis_prompt(
            {
                "semantic_topic_label": "business, cash_flow, sba",
                "primary_seed_topics": ["business_acquisition"],
                "section_count": 2,
                "video_count": 2,
                "sections": [
                    {
                        "section_id": "section_0001",
                        "video_id": "video1",
                        "source_provenance": {"start_offset_ms": 0, "end_offset_ms": 10000},
                        "text": "Raw section text.",
                        "section_summary": {"summary_text": "Section one note."},
                    },
                    {
                        "section_id": "section_0002",
                        "video_id": "video2",
                        "source_provenance": {"start_offset_ms": 30000, "end_offset_ms": 45000},
                        "text": "Another raw section text.",
                        "section_summary": {"summary_text": "Section two note."},
                    },
                ],
            }
        )

        self.assertIn("Semantic topic: business, cash_flow, sba", prompt)
        self.assertIn("Primary seed topics observed: business_acquisition", prompt)
        self.assertIn("Section note: Section one note.", prompt)
        self.assertIn("Section count: 2", prompt)


if __name__ == "__main__":
    unittest.main()
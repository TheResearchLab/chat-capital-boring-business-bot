import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from run_principle_extraction import (  # noqa: E402
    apply_principle_focus_filter,
    extract_balanced_json_payload,
    extract_json_payload,
    get_focus_domain_matches,
    get_principle_focus_domain_matches,
    has_business_signal_summary,
    is_high_signal_topic_label,
    normalize_principles_payload,
    rank_and_dedupe_principle_candidates,
    run_principle_extraction,
    select_eligible_topic_entries,
)


class RunPrincipleExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = Path(tempfile.mkdtemp(dir=REPO_ROOT))
        self.addCleanup(shutil.rmtree, self.temp_root, True)
        self.topic_analysis_path = self.temp_root / "data" / "topic_analysis" / "youtube" / "demo-streams" / "topic_analysis.json"
        self.output_path = self.temp_root / "data" / "principles" / "youtube" / "demo-streams" / "principles.json"

    def write_topic_analysis(self, topic_synthesis_entries: list[dict]) -> None:
        self.topic_analysis_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "source": {
                "analysis_root": "data/analysis/youtube/demo-streams",
                "channel_slug": "demo-streams",
                "chunk_count": 120,
            },
            "topic_analysis": {
                "semantic_topics": [
                    {
                        "semantic_topic_id": entry["semantic_topic_id"],
                        "semantic_topic_label": entry["semantic_topic_label"],
                    }
                    for entry in topic_synthesis_entries
                ],
                "topic_synthesis_entries": topic_synthesis_entries,
            },
        }
        self.topic_analysis_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def test_extract_json_payload_handles_fenced_json(self) -> None:
        payload = extract_json_payload(
            "```json\n{\"principles\": [{\"title\": \"T\", \"statement\": \"S\", \"rationale\": \"R\", \"confidence\": \"high\"}]}\n```"
        )

        self.assertEqual(payload["principles"][0]["title"], "T")

    def test_extract_json_payload_recovers_from_wrapped_json(self) -> None:
        payload = extract_json_payload(
            "Here is the result:\n{\"principles\": [{\"title\": \"T\", \"statement\": \"S\", \"rationale\": \"R\", \"confidence\": \"high\"}]}\nThanks"
        )

        self.assertEqual(payload["principles"][0]["statement"], "S")

    def test_extract_balanced_json_payload_handles_nested_content(self) -> None:
        extracted = extract_balanced_json_payload(
            "prefix {\"principles\": [{\"title\": \"T\", \"meta\": {\"confidence\": \"high\"}}]} suffix"
        )

        self.assertEqual(
            extracted,
            '{"principles": [{"title": "T", "meta": {"confidence": "high"}}]}',
        )

    def test_normalize_principles_payload_accepts_common_shapes(self) -> None:
        self.assertEqual(
            normalize_principles_payload(
                [{"title": "T", "statement": "S", "rationale": "R", "confidence": "high"}]
            )[0]["title"],
            "T",
        )
        self.assertEqual(
            normalize_principles_payload(
                {"items": [{"title": "U", "statement": "S", "rationale": "R", "confidence": "medium"}]}
            )[0]["title"],
            "U",
        )
        self.assertEqual(
            normalize_principles_payload(
                {"title": "V", "statement": "S", "rationale": "R", "confidence": "low"}
            )[0]["title"],
            "V",
        )

    def test_rank_and_dedupe_principle_candidates_prefers_stronger_entries(self) -> None:
        ranked, duplicate_count = rank_and_dedupe_principle_candidates(
            [
                {
                    "principle_id": "principle_0001",
                    "title": "Protect Debt Capacity",
                    "statement": "Treat SBA leverage as something that must be earned through dependable cash flow.",
                    "rationale": "Lower quality duplicate.",
                    "confidence": "medium",
                    "source_topic": {"section_count": 10, "video_count": 1},
                },
                {
                    "principle_id": "principle_0002",
                    "title": "Protect Debt Capacity",
                    "statement": "Treat SBA leverage as something that must be earned through dependable cash flow.",
                    "rationale": "Higher quality duplicate.",
                    "confidence": "high",
                    "source_topic": {"section_count": 20, "video_count": 3},
                },
                {
                    "principle_id": "principle_0003",
                    "title": "Prioritize Liquidity",
                    "statement": "Model near-term cash flow before assuming a lender cares about headline profit.",
                    "rationale": "Distinct principle.",
                    "confidence": "high",
                    "source_topic": {"section_count": 15, "video_count": 2},
                },
            ]
        )

        self.assertEqual(duplicate_count, 1)
        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[0]["title"], "Protect Debt Capacity")
        self.assertEqual(ranked[0]["rank"], 1)
        self.assertEqual(ranked[0]["source_topic"]["section_count"], 20)
        self.assertEqual(ranked[1]["principle_id"], "principle_0002")

    def test_is_high_signal_topic_label_filters_noisy_labels(self) -> None:
        self.assertFalse(is_high_signal_topic_label("__, ammo, come"))
        self.assertFalse(is_high_signal_topic_label("youtube, content, channel"))
        self.assertFalse(is_high_signal_topic_label("real, feel mean, real problem"))
        self.assertFalse(is_high_signal_topic_label("peace, tomorrow, peace love"))
        self.assertFalse(is_high_signal_topic_label("life, saying, family"))
        self.assertTrue(is_high_signal_topic_label("sba, loan, bank"))

    def test_has_business_signal_summary_requires_operational_content(self) -> None:
        self.assertFalse(
            has_business_signal_summary(
                "The discussion revolves around travel banter, cultural identification, and language practice."
            )
        )
        self.assertFalse(
            has_business_signal_summary(
                "The discussion is mostly travel banter and geographical identification rather than specific business strategies."
            )
        )
        self.assertTrue(
            has_business_signal_summary(
                "The synthesis emphasizes due diligence, cash flow discipline, inventory turns, and pricing strategy."
            )
        )

    def test_get_focus_domain_matches_identifies_investing_domains(self) -> None:
        topic_entry = {
            "semantic_topic_label": "private equity, private, equity",
            "topic_summary": {
                "summary_text": "The synthesis focuses on private equity, acquisition diligence, SBA loan structuring, underwriting discipline, valuation, and balance sheet review."
            },
        }

        matches = get_focus_domain_matches(
            topic_entry,
            focus_domains=["personal_finance", "public_equity", "private_equity"],
            min_focus_term_matches=2,
        )

        self.assertEqual(matches, ["personal_finance", "public_equity", "private_equity"])

    def test_get_principle_focus_domain_matches_uses_principle_text(self) -> None:
        principle_candidate = {
            "title": "Source Businesses by Geography and Cash Flow",
            "statement": "Use state-level sourcing as an acquisition screen only when it improves deal flow, lender confidence, and cash flow durability.",
            "rationale": "The principle ties geography back to acquisition sourcing, lender underwriting, and durable operating cash flow.",
            "topic_summary": "The discussion focuses on boring businesses for sale, acquisition sourcing, state-level search filters, lender diligence, and valuation.",
        }

        matches = get_principle_focus_domain_matches(
            principle_candidate,
            focus_domains=["personal_finance", "public_equity", "private_equity"],
            min_focus_term_matches=2,
        )

        self.assertEqual(matches, ["personal_finance", "private_equity"])

    def test_apply_principle_focus_filter_keeps_geo_deal_principles_and_drops_stream_meta(self) -> None:
        filtered_candidates, removed_count = apply_principle_focus_filter(
            [
                {
                    "title": "Source Businesses by Geography and Cash Flow",
                    "statement": "Use state-level sourcing as an acquisition screen only when it improves deal flow, lender confidence, and cash flow durability.",
                    "rationale": "The principle ties geography back to acquisition sourcing, lender underwriting, and durable operating cash flow.",
                    "topic_summary": "The discussion focuses on boring businesses for sale, acquisition sourcing, lender diligence, and valuation.",
                    "source_topic": {"matched_focus_domains": ["private_equity"]},
                },
                {
                    "title": "Fix Your Stream Audio",
                    "statement": "Use Discord for cleaner streaming audio and faster community coordination.",
                    "rationale": "This is mostly about stream logistics.",
                    "topic_summary": "The discussion focuses on streaming logistics, audio setup, Discord coordination, and community banter.",
                    "source_topic": {"matched_focus_domains": []},
                },
            ],
            focus_domains=["personal_finance", "public_equity", "private_equity"],
            min_focus_term_matches=2,
        )

        self.assertEqual(removed_count, 1)
        self.assertEqual(len(filtered_candidates), 1)
        self.assertEqual(filtered_candidates[0]["matched_focus_domains"], ["personal_finance", "private_equity"])
        self.assertEqual(
            filtered_candidates[0]["source_topic"]["matched_focus_domains"],
            ["personal_finance", "private_equity"],
        )

    def test_select_eligible_topic_entries_filters_outliers_and_missing_summaries(self) -> None:
        topic_payload = {
            "topic_analysis": {
                "topic_synthesis_entries": [
                    {
                        "semantic_topic_id": -1,
                        "semantic_topic_label": "outlier",
                        "section_count": 100,
                        "topic_summary": {"summary_text": "ignore"},
                    },
                    {
                        "semantic_topic_id": 1,
                        "semantic_topic_label": "sba, loan, bank",
                        "section_count": 12,
                        "topic_summary": {
                            "summary_text": "The synthesis focuses on SBA lending, bank underwriting, and cash flow discipline."
                        },
                    },
                    {
                        "semantic_topic_id": 4,
                        "semantic_topic_label": "youtube, content, channel",
                        "section_count": 22,
                        "topic_summary": {"summary_text": "too generic"},
                    },
                    {
                        "semantic_topic_id": 5,
                        "semantic_topic_label": "spanish, sebastian, wait",
                        "section_count": 30,
                        "topic_summary": {
                            "summary_text": "The discussion revolves around travel banter, cultural identification, and language practice."
                        },
                    },
                    {
                        "semantic_topic_id": 2,
                        "semantic_topic_label": "private equity, private, equity",
                        "section_count": 5,
                        "topic_summary": {"summary_text": "too small"},
                    },
                    {
                        "semantic_topic_id": 3,
                        "semantic_topic_label": "debt, balance, receivables",
                        "section_count": 20,
                        "topic_summary": None,
                    },
                ]
            }
        }

        eligible = select_eligible_topic_entries(topic_payload, min_topic_section_count=10)

        self.assertEqual(len(eligible), 1)
        self.assertEqual(eligible[0]["semantic_topic_label"], "sba, loan, bank")

    def test_select_eligible_topic_entries_can_focus_on_investing_domains(self) -> None:
        topic_payload = {
            "topic_analysis": {
                "topic_synthesis_entries": [
                    {
                        "semantic_topic_id": 1,
                        "semantic_topic_label": "private equity, private, equity",
                        "section_count": 24,
                        "topic_summary": {
                            "summary_text": "The synthesis emphasizes private equity, acquisition diligence, valuation, and SBA-backed deal execution."
                        },
                    },
                    {
                        "semantic_topic_id": 2,
                        "semantic_topic_label": "twitch, hear, hear hear",
                        "section_count": 40,
                        "topic_summary": {
                            "summary_text": "The synthesis focuses on streaming logistics, audio setup, Discord coordination, and community banter."
                        },
                    },
                ]
            }
        }

        eligible = select_eligible_topic_entries(
            topic_payload,
            min_topic_section_count=10,
            focus_domains=["public_equity", "private_equity"],
            max_topics=None,
        )

        self.assertEqual(len(eligible), 1)
        self.assertEqual(eligible[0]["semantic_topic_label"], "private equity, private, equity")
        self.assertEqual(eligible[0]["matched_focus_domains"], ["private_equity"])

    def test_run_principle_extraction_writes_principle_artifact(self) -> None:
        self.write_topic_analysis(
            [
                {
                    "semantic_topic_id": 1,
                    "semantic_topic_label": "sba, loan, bank",
                    "section_count": 16,
                    "video_count": 3,
                    "source_section_ids": ["section_0001", "section_0004"],
                    "topic_summary": {
                        "summary_text": "The repeated discussion emphasizes SBA debt discipline, lender relationships, and cash flow underwriting."
                    },
                },
                {
                    "semantic_topic_id": -1,
                    "semantic_topic_label": "outlier",
                    "section_count": 99,
                    "video_count": 8,
                    "source_section_ids": ["section_9999"],
                    "topic_summary": {
                        "summary_text": "Ignore this outlier bucket."
                    },
                },
            ]
        )

        with patch(
            "run_principle_extraction.extract_principles_from_topic_entry",
            return_value=[
                {
                    "title": "Protect Debt Capacity",
                    "statement": "Treat SBA leverage as something that must be earned through dependable cash flow.",
                    "rationale": "The synthesis repeatedly returns to lender trust and underwriting discipline.",
                    "confidence": "high",
                }
            ],
        ):
            summary = run_principle_extraction(
                topic_analysis_path=self.topic_analysis_path,
                output_path=self.output_path,
                ollama_model="gemma4:e4b",
                min_topic_section_count=10,
                focus_domains=["personal_finance", "private_equity"],
                max_topics=5,
            )

        self.assertEqual(summary["eligible_topic_count"], 1)
        self.assertEqual(summary["principle_candidate_count"], 1)
        self.assertEqual(summary["duplicate_principle_count"], 0)
        self.assertEqual(summary["filtered_principle_count"], 0)
        self.assertEqual(summary["focus_domains"], ["personal_finance", "private_equity"])
        self.assertTrue(self.output_path.exists())

        payload = json.loads(self.output_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["record_type"], "youtube_topic_principle_extraction")
        self.assertEqual(payload["principle_extraction"]["duplicate_principle_count"], 0)
        self.assertEqual(payload["principle_extraction"]["filtered_principle_count"], 0)
        self.assertEqual(payload["principle_extraction"]["focus_domains"], ["personal_finance", "private_equity"])
        self.assertEqual(payload["principle_candidates"][0]["title"], "Protect Debt Capacity")
        self.assertEqual(payload["principle_candidates"][0]["rank"], 1)
        self.assertEqual(
            payload["principle_candidates"][0]["source_topic"]["matched_focus_domains"],
            ["personal_finance", "private_equity"],
        )
        self.assertEqual(
            payload["principle_candidates"][0]["source_topic"]["semantic_topic_label"],
            "sba, loan, bank",
        )


if __name__ == "__main__":
    unittest.main()
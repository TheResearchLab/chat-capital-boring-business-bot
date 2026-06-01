import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests


PRINCIPLE_EXTRACTION_SCHEMA_VERSION = "principle_extraction_v1"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MIN_TOPIC_SECTION_COUNT = 12
DEFAULT_MAX_TOPICS = 25
DEFAULT_MAX_PRINCIPLES_PER_TOPIC = 3
DEFAULT_FOCUS_DOMAIN_MATCH_COUNT = 2
DEFAULT_PRINCIPLE_FOCUS_TERM_MATCH_COUNT = 2
CONFIDENCE_SCORES = {
    "high": 3,
    "medium": 2,
    "low": 1,
}
LOW_SIGNAL_TOPIC_LABEL_TERMS = {
    "ammo",
    "channel",
    "chat",
    "come",
    "content",
    "family",
    "feel",
    "life",
    "love",
    "mean",
    "problem",
    "peace",
    "real",
    "saying",
    "stream",
    "streams",
    "tomorrow",
    "video",
    "youtube",
}
BUSINESS_SIGNAL_SUMMARY_TERMS = {
    "acquisition",
    "balance sheet",
    "bank",
    "business",
    "capital",
    "cash flow",
    "company",
    "companies",
    "customer",
    "customers",
    "debt",
    "diligence",
    "due diligence",
    "financial",
    "gross margin",
    "inventory",
    "invest",
    "investment",
    "investments",
    "lender",
    "loan",
    "margin",
    "market",
    "operator",
    "operations",
    "owner",
    "pricing",
    "profit",
    "regulatory",
    "revenue",
    "sales",
    "service",
    "underwriting",
    "valuation",
}
OFF_TOPIC_SUMMARY_TERMS = {
    "banter",
    "culture",
    "cultural",
    "geographical",
    "geography",
    "interactive",
    "language",
    "locales",
    "observational",
    "touring",
    "travel",
    "world-touring",
}
FOCUS_DOMAIN_TERMS = {
    "personal_finance": {
        "budget",
        "budgeting",
        "credit card",
        "debt payoff",
        "emergency fund",
        "interest rate",
        "liquidity",
        "loan",
        "loans",
        "mortgage",
        "net worth",
        "personal finance",
        "refinance",
        "retirement",
        "savings",
        "taxes",
        "underwriting",
    },
    "public_equity": {
        "balance sheet",
        "book value",
        "deep value",
        "dividend",
        "earnings",
        "equity research",
        "investment thesis",
        "market cap",
        "price target",
        "public equity",
        "public markets",
        "receivables",
        "sector",
        "shareholder",
        "shares",
        "stock",
        "stocks",
        "valuation",
    },
    "private_equity": {
        "acquisition",
        "acquisitions",
        "buy a business",
        "deal",
        "due diligence",
        "ebitda",
        "holding company",
        "lbo",
        "lender",
        "loi",
        "private equity",
        "rollup",
        "sba",
        "search fund",
        "sde",
    },
}
PRINCIPLE_FOCUS_TERMS = {
    "personal_finance": {
        "cash flow",
        "debt",
        "interest rate",
        "liquidity",
        "loan",
        "mortgage",
        "refinance",
        "savings",
        "tax",
        "underwriting",
    },
    "public_equity": {
        "balance sheet",
        "book value",
        "earnings",
        "investment thesis",
        "market cap",
        "moat",
        "multiple",
        "price",
        "public market",
        "returns",
        "sector",
        "shareholder",
        "stock",
        "valuation",
    },
    "private_equity": {
        "acquisition",
        "cash flow",
        "deal",
        "diligence",
        "ebitda",
        "holding company",
        "lender",
        "loi",
        "operator",
        "private equity",
        "rollup",
        "sba",
        "search fund",
        "seller",
        "valuation",
    },
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def extract_json_payload(text: str) -> dict | list:
    cleaned = text.strip()
    fenced_match = re.search(r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", cleaned, flags=re.DOTALL)
    if fenced_match:
        cleaned = fenced_match.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        balanced_json = extract_balanced_json_payload(cleaned)
        if balanced_json is None:
            raise
        return json.loads(balanced_json)


def extract_balanced_json_payload(text: str) -> str | None:
    opening_characters = {"{": "}", "[": "]"}
    for start_index, character in enumerate(text):
        if character not in opening_characters:
            continue

        stack = [opening_characters[character]]
        in_string = False
        escape_next = False
        for index in range(start_index + 1, len(text)):
            current_character = text[index]
            if escape_next:
                escape_next = False
                continue
            if current_character == "\\":
                escape_next = True
                continue
            if current_character == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if current_character in opening_characters:
                stack.append(opening_characters[current_character])
                continue
            if stack and current_character == stack[-1]:
                stack.pop()
                if not stack:
                    return text[start_index : index + 1]

    return None


def is_high_signal_topic_label(label: str) -> bool:
    normalized_terms = [term.strip().lower() for term in label.split(",") if term.strip()]
    if not normalized_terms:
        return False

    informative_terms = []
    for term in normalized_terms:
        cleaned_term = re.sub(r"[^a-z\s]", " ", term)
        tokens = [token for token in cleaned_term.split() if len(token) >= 3]
        if not tokens:
            continue
        if all(token in LOW_SIGNAL_TOPIC_LABEL_TERMS for token in tokens):
            continue
        informative_terms.append(term)

    return len(informative_terms) >= 2


def has_business_signal_summary(summary_text: str) -> bool:
    normalized_summary = (summary_text or "").lower()
    matched_business_terms = [term for term in BUSINESS_SIGNAL_SUMMARY_TERMS if term in normalized_summary]
    matched_off_topic_terms = [term for term in OFF_TOPIC_SUMMARY_TERMS if term in normalized_summary]
    return len(matched_business_terms) >= 2 and len(matched_business_terms) > len(matched_off_topic_terms)


def get_focus_domain_matches(
    topic_entry: dict,
    focus_domains: list[str] | None,
    min_focus_term_matches: int = DEFAULT_FOCUS_DOMAIN_MATCH_COUNT,
) -> list[str]:
    if not focus_domains:
        return []

    searchable_text = " ".join(
        [
            (topic_entry.get("semantic_topic_label") or "").lower(),
            ((topic_entry.get("topic_summary") or {}).get("summary_text") or "").lower(),
        ]
    )
    matched_domains: list[str] = []
    for focus_domain in focus_domains:
        terms = FOCUS_DOMAIN_TERMS[focus_domain]
        match_count = sum(1 for term in terms if term in searchable_text)
        if match_count >= min_focus_term_matches:
            matched_domains.append(focus_domain)
    return matched_domains


def get_principle_focus_domain_matches(
    principle_candidate: dict,
    focus_domains: list[str] | None,
    min_focus_term_matches: int = DEFAULT_PRINCIPLE_FOCUS_TERM_MATCH_COUNT,
) -> list[str]:
    if not focus_domains:
        return []

    searchable_text = " ".join(
        [
            normalize_text(principle_candidate.get("title")).lower(),
            normalize_text(principle_candidate.get("statement")).lower(),
            normalize_text(principle_candidate.get("rationale")).lower(),
            normalize_text(principle_candidate.get("topic_summary")).lower(),
        ]
    )
    matched_domains: list[str] = []
    for focus_domain in focus_domains:
        terms = PRINCIPLE_FOCUS_TERMS[focus_domain]
        match_count = sum(1 for term in terms if term in searchable_text)
        if match_count >= min_focus_term_matches:
            matched_domains.append(focus_domain)
    return matched_domains


def normalize_principles_payload(parsed_payload: dict | list) -> list[dict]:
    if isinstance(parsed_payload, list):
        return [item for item in parsed_payload if isinstance(item, dict)]

    if not isinstance(parsed_payload, dict):
        raise ValueError("Expected JSON object or array for extracted principles")

    for key in ("principles", "items", "results", "data"):
        candidate_list = parsed_payload.get(key)
        if isinstance(candidate_list, list):
            return [item for item in candidate_list if isinstance(item, dict)]

    if all(field in parsed_payload for field in ("title", "statement", "rationale", "confidence")):
        return [parsed_payload]

    raise ValueError("Expected a JSON object with a recognized principles array or a single principle object")


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).strip()


def build_principle_signature(principle_candidate: dict) -> tuple[str, str]:
    normalized_title = normalize_text((principle_candidate.get("title") or "").lower())
    normalized_statement = normalize_text((principle_candidate.get("statement") or "").lower())
    return normalized_title, normalized_statement


def score_principle_candidate(principle_candidate: dict) -> tuple[int, int, int, int, str, str]:
    confidence_score = CONFIDENCE_SCORES.get((principle_candidate.get("confidence") or "").lower(), 0)
    source_topic = principle_candidate.get("source_topic") or {}
    section_count = int(source_topic.get("section_count") or 0)
    video_count = int(source_topic.get("video_count") or 0)
    statement_length = len(normalize_text(principle_candidate.get("statement")))
    principle_focus_match_count = len(principle_candidate.get("matched_focus_domains") or [])
    normalized_title, normalized_statement = build_principle_signature(principle_candidate)
    return (
        principle_focus_match_count,
        confidence_score,
        section_count,
        video_count,
        statement_length,
        normalized_title,
        normalized_statement,
    )


def rank_and_dedupe_principle_candidates(principle_candidates: list[dict]) -> tuple[list[dict], int]:
    sorted_candidates = sorted(principle_candidates, key=score_principle_candidate, reverse=True)
    ranked_candidates: list[dict] = []
    seen_signatures: set[tuple[str, str]] = set()
    removed_count = 0

    for index, principle_candidate in enumerate(sorted_candidates, start=1):
        signature = build_principle_signature(principle_candidate)
        if signature in seen_signatures:
            removed_count += 1
            continue
        seen_signatures.add(signature)
        ranked_candidate = dict(principle_candidate)
        ranked_candidate["principle_id"] = f"principle_{index - removed_count:04d}"
        ranked_candidate["rank"] = index - removed_count
        ranked_candidates.append(ranked_candidate)

    return ranked_candidates, removed_count


def apply_principle_focus_filter(
    principle_candidates: list[dict],
    focus_domains: list[str] | None,
    min_focus_term_matches: int = DEFAULT_PRINCIPLE_FOCUS_TERM_MATCH_COUNT,
) -> tuple[list[dict], int]:
    if not focus_domains:
        return principle_candidates, 0

    filtered_candidates: list[dict] = []
    removed_count = 0
    for principle_candidate in principle_candidates:
        matched_domains = get_principle_focus_domain_matches(
            principle_candidate,
            focus_domains=focus_domains,
            min_focus_term_matches=min_focus_term_matches,
        )
        if not matched_domains:
            removed_count += 1
            continue
        enriched_candidate = dict(principle_candidate)
        enriched_candidate["matched_focus_domains"] = matched_domains
        source_topic = dict(enriched_candidate.get("source_topic") or {})
        source_topic["matched_focus_domains"] = sorted(
            set((source_topic.get("matched_focus_domains") or [])).union(matched_domains)
        )
        enriched_candidate["source_topic"] = source_topic
        filtered_candidates.append(enriched_candidate)

    return filtered_candidates, removed_count


def select_eligible_topic_entries(
    topic_analysis_payload: dict,
    min_topic_section_count: int = DEFAULT_MIN_TOPIC_SECTION_COUNT,
    max_topics: int | None = DEFAULT_MAX_TOPICS,
    focus_domains: list[str] | None = None,
    min_focus_term_matches: int = DEFAULT_FOCUS_DOMAIN_MATCH_COUNT,
) -> list[dict]:
    entries = (topic_analysis_payload.get("topic_analysis") or {}).get("topic_synthesis_entries") or []
    eligible_entries = []
    for entry in entries:
        if entry.get("semantic_topic_id") == -1:
            continue
        if entry.get("section_count", 0) < min_topic_section_count:
            continue
        if not (entry.get("topic_summary") or {}).get("summary_text"):
            continue
        if not is_high_signal_topic_label(entry.get("semantic_topic_label") or ""):
            continue
        if not has_business_signal_summary(((entry.get("topic_summary") or {}).get("summary_text") or "")):
            continue

        matched_focus_domains = get_focus_domain_matches(
            entry,
            focus_domains=focus_domains,
            min_focus_term_matches=min_focus_term_matches,
        )
        if focus_domains and not matched_focus_domains:
            continue

        enriched_entry = dict(entry)
        if matched_focus_domains:
            enriched_entry["matched_focus_domains"] = matched_focus_domains
        eligible_entries.append(enriched_entry)

    eligible_entries.sort(key=lambda entry: (-entry["section_count"], entry["semantic_topic_label"]))
    if max_topics is not None:
        return eligible_entries[:max_topics]
    return eligible_entries


def build_principle_prompt(topic_entry: dict, max_principles_per_topic: int) -> str:
    topic_summary = (topic_entry.get("topic_summary") or {}).get("summary_text") or ""
    return (
        "You are extracting practical principles from a topic-level synthesis built from multiple Kenny Finance transcript sections. "
        "Return a JSON object with a single key `principles` whose value is an array of up to "
        f"{max_principles_per_topic} objects. Each object must contain: `title`, `statement`, `rationale`, and `confidence`. "
        "The `statement` should be a concise principle or heuristic. The `rationale` should briefly explain why it matters. "
        "Use a confidence string of low, medium, or high. Do not include markdown.\n\n"
        f"Semantic topic: {topic_entry['semantic_topic_label']}\n"
        f"Section count: {topic_entry['section_count']}\n"
        f"Video count: {topic_entry['video_count']}\n"
        f"Source section ids: {', '.join(topic_entry.get('source_section_ids') or [])}\n\n"
        "Topic synthesis summary:\n"
        f"{topic_summary}\n"
    )


def extract_principles_from_topic_entry(
    topic_entry: dict,
    ollama_base_url: str,
    ollama_model: str,
    ollama_timeout_seconds: int,
    max_principles_per_topic: int,
) -> list[dict]:
    response = requests.post(
        f"{ollama_base_url.rstrip('/')}/api/generate",
        json={
            "model": ollama_model,
            "prompt": build_principle_prompt(topic_entry, max_principles_per_topic=max_principles_per_topic),
            "format": "json",
            "stream": False,
        },
        timeout=ollama_timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    parsed_payload = extract_json_payload((payload.get("response") or "").strip())
    principles = normalize_principles_payload(parsed_payload)
    return principles[:max_principles_per_topic]


def build_principle_candidates(
    topic_entries: list[dict],
    ollama_base_url: str,
    ollama_model: str,
    ollama_timeout_seconds: int,
    max_principles_per_topic: int,
) -> list[dict]:
    principle_candidates: list[dict] = []
    principle_index = 1
    for topic_entry in topic_entries:
        log_progress(
            f"[principle-extraction] Extracting principles from topic {topic_entry['semantic_topic_label']} across {topic_entry['section_count']} sections"
        )
        extracted_principles = extract_principles_from_topic_entry(
            topic_entry,
            ollama_base_url=ollama_base_url,
            ollama_model=ollama_model,
            ollama_timeout_seconds=ollama_timeout_seconds,
            max_principles_per_topic=max_principles_per_topic,
        )
        for extracted_principle in extracted_principles:
            principle_candidates.append(
                {
                    "principle_id": f"principle_{principle_index:04d}",
                    "title": extracted_principle.get("title"),
                    "statement": extracted_principle.get("statement"),
                    "rationale": extracted_principle.get("rationale"),
                    "confidence": extracted_principle.get("confidence"),
                    "source_topic": {
                        "semantic_topic_id": topic_entry["semantic_topic_id"],
                        "semantic_topic_label": topic_entry["semantic_topic_label"],
                        "section_count": topic_entry["section_count"],
                        "video_count": topic_entry["video_count"],
                        "matched_focus_domains": topic_entry.get("matched_focus_domains") or [],
                    },
                    "source_section_ids": topic_entry.get("source_section_ids") or [],
                    "topic_summary": (topic_entry.get("topic_summary") or {}).get("summary_text"),
                }
            )
            principle_index += 1
    return principle_candidates


def build_principle_extraction_payload(
    topic_analysis_payload: dict,
    principle_candidates: list[dict],
    duplicate_principle_count: int,
    filtered_principle_count: int,
    ollama_model: str,
    ollama_base_url: str,
    min_topic_section_count: int,
    max_topics: int | None,
    max_principles_per_topic: int,
    focus_domains: list[str] | None,
    min_focus_term_matches: int,
) -> dict:
    source = topic_analysis_payload.get("source") or {}
    topic_analysis = topic_analysis_payload.get("topic_analysis") or {}
    return {
        "schema_version": PRINCIPLE_EXTRACTION_SCHEMA_VERSION,
        "record_type": "youtube_topic_principle_extraction",
        "source": {
            "topic_analysis_path": source.get("analysis_root"),
            "channel_slug": source.get("channel_slug"),
            "chunk_count": source.get("chunk_count"),
            "semantic_topic_count": len(topic_analysis.get("semantic_topics") or []),
        },
        "principle_extraction": {
            "generated_at": utc_now_iso(),
            "provider": "ollama",
            "model": ollama_model,
            "base_url": ollama_base_url,
            "min_topic_section_count": min_topic_section_count,
            "max_topics": max_topics,
            "max_principles_per_topic": max_principles_per_topic,
            "duplicate_principle_count": duplicate_principle_count,
            "filtered_principle_count": filtered_principle_count,
            "focus_domains": focus_domains or [],
            "min_focus_term_matches": min_focus_term_matches,
        },
        "principle_candidates": principle_candidates,
    }


def infer_output_path(topic_analysis_path: Path) -> Path:
    channel_slug = topic_analysis_path.parent.name
    repo_root = Path(__file__).resolve().parents[1]
    return repo_root / "data" / "principles" / "youtube" / channel_slug / "principles.json"


def run_principle_extraction(
    topic_analysis_path: Path,
    output_path: Path | None,
    ollama_model: str,
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL,
    ollama_timeout_seconds: int = 120,
    min_topic_section_count: int = DEFAULT_MIN_TOPIC_SECTION_COUNT,
    max_topics: int | None = DEFAULT_MAX_TOPICS,
    max_principles_per_topic: int = DEFAULT_MAX_PRINCIPLES_PER_TOPIC,
    focus_domains: list[str] | None = None,
    min_focus_term_matches: int = DEFAULT_FOCUS_DOMAIN_MATCH_COUNT,
    dry_run: bool = False,
) -> dict:
    topic_analysis_payload = load_json(topic_analysis_path)
    eligible_entries = select_eligible_topic_entries(
        topic_analysis_payload,
        min_topic_section_count=min_topic_section_count,
        max_topics=max_topics,
        focus_domains=focus_domains,
        min_focus_term_matches=min_focus_term_matches,
    )
    log_progress(
        f"[principle-extraction] Selected {len(eligible_entries)} topic syntheses from {topic_analysis_path}"
    )
    raw_principle_candidates = build_principle_candidates(
        eligible_entries,
        ollama_base_url=ollama_base_url,
        ollama_model=ollama_model,
        ollama_timeout_seconds=ollama_timeout_seconds,
        max_principles_per_topic=max_principles_per_topic,
    )
    focused_principle_candidates, filtered_principle_count = apply_principle_focus_filter(
        raw_principle_candidates,
        focus_domains=focus_domains,
        min_focus_term_matches=min_focus_term_matches,
    )
    principle_candidates, duplicate_principle_count = rank_and_dedupe_principle_candidates(focused_principle_candidates)
    payload = build_principle_extraction_payload(
        topic_analysis_payload,
        principle_candidates,
        duplicate_principle_count=duplicate_principle_count,
        filtered_principle_count=filtered_principle_count,
        ollama_model=ollama_model,
        ollama_base_url=ollama_base_url,
        min_topic_section_count=min_topic_section_count,
        max_topics=max_topics,
        max_principles_per_topic=max_principles_per_topic,
        focus_domains=focus_domains,
        min_focus_term_matches=min_focus_term_matches,
    )
    resolved_output_path = output_path or infer_output_path(topic_analysis_path)
    if not dry_run:
        log_progress(f"[principle-extraction] Writing artifact to {resolved_output_path}")
        write_json(resolved_output_path, payload)
    return {
        "topic_analysis_path": str(topic_analysis_path),
        "output_path": str(resolved_output_path),
        "eligible_topic_count": len(eligible_entries),
        "principle_candidate_count": len(principle_candidates),
        "duplicate_principle_count": duplicate_principle_count,
        "filtered_principle_count": filtered_principle_count,
        "focus_domains": focus_domains or [],
        "dry_run": dry_run,
    }


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Extract principle candidates from topic synthesis summaries."
    )
    parser.add_argument(
        "--topic-analysis-path",
        default=str(repo_root / "data" / "topic_analysis" / "youtube" / "kenny-finance-streams" / "topic_analysis.json"),
        help="Path to the topic analysis artifact to read.",
    )
    parser.add_argument(
        "--output-path",
        help="Optional output path for the principle extraction artifact.",
    )
    parser.add_argument(
        "--ollama-model",
        required=True,
        help="Ollama model used to extract principle candidates from topic syntheses.",
    )
    parser.add_argument(
        "--ollama-base-url",
        default=DEFAULT_OLLAMA_BASE_URL,
        help="Base URL for the local Ollama server.",
    )
    parser.add_argument(
        "--ollama-timeout-seconds",
        type=int,
        default=120,
        help="Timeout in seconds for each Ollama principle-extraction request.",
    )
    parser.add_argument(
        "--min-topic-section-count",
        type=int,
        default=DEFAULT_MIN_TOPIC_SECTION_COUNT,
        help="Minimum number of supporting sections required before a topic is eligible for principle extraction.",
    )
    parser.add_argument(
        "--max-topics",
        type=int,
        default=DEFAULT_MAX_TOPICS,
        help="Maximum number of eligible topics to process, ordered by section count.",
    )
    parser.add_argument(
        "--max-principles-per-topic",
        type=int,
        default=DEFAULT_MAX_PRINCIPLES_PER_TOPIC,
        help="Maximum number of principle candidates to extract from each topic synthesis.",
    )
    parser.add_argument(
        "--focus-domain",
        action="append",
        choices=sorted(FOCUS_DOMAIN_TERMS),
        help="Optional focus domain filter. Repeat the flag to combine domains such as personal_finance, public_equity, and private_equity.",
    )
    parser.add_argument(
        "--min-focus-term-matches",
        type=int,
        default=DEFAULT_FOCUS_DOMAIN_MATCH_COUNT,
        help="Minimum number of focus-domain keyword matches required for a topic to qualify when focus domains are supplied.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run extraction without writing an artifact.",
    )
    args = parser.parse_args()

    summary = run_principle_extraction(
        topic_analysis_path=Path(args.topic_analysis_path),
        output_path=Path(args.output_path) if args.output_path else None,
        ollama_model=args.ollama_model,
        ollama_base_url=args.ollama_base_url,
        ollama_timeout_seconds=args.ollama_timeout_seconds,
        min_topic_section_count=args.min_topic_section_count,
        max_topics=args.max_topics,
        max_principles_per_topic=args.max_principles_per_topic,
        focus_domains=args.focus_domain,
        min_focus_term_matches=args.min_focus_term_matches,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
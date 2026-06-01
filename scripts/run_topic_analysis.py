import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests


TOPIC_ANALYSIS_SCHEMA_VERSION = "topic_analysis_v1"
DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
DEFAULT_MIN_TOPIC_SIZE = 8
DEFAULT_REPRESENTATIVE_CHUNK_COUNT = 5
DEFAULT_SECTION_GAP_MS = 90000
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_TOPIC_SYNTHESIS_SECTION_LIMIT = 8
DEFAULT_SECTION_SUMMARY_LIMIT_PER_TOPIC = 3
DEFAULT_SECTION_SUMMARY_MIN_CHAR_COUNT = 500

TRANSCRIPT_FILLER_STOPWORDS = {
    "actually",
    "basically",
    "bro",
    "boys",
    "care",
    "cool",
    "day",
    "don",
    "freaking",
    "fuck",
    "fucking",
    "going",
    "gonna",
    "good",
    "got",
    "guys",
    "just",
    "kind",
    "kinda",
    "know",
    "let",
    "ll",
    "like",
    "lot",
    "literally",
    "make",
    "man",
    "maybe",
    "nice",
    "oh",
    "okay",
    "probably",
    "really",
    "right",
    "second",
    "sort",
    "stuff",
    "super",
    "team",
    "thing",
    "things",
    "think",
    "time",
    "today",
    "uh",
    "want",
    "wanna",
    "way",
    "yeah",
    "hey",
    "huge",
}

LOW_SIGNAL_LABEL_TERMS = TRANSCRIPT_FILLER_STOPWORDS.union(
    {
        "chat",
        "grand",
        "prix",
    }
)

SEED_TOPICS = {
    "investing_markets": {
        "description": "Investing discussion, stock analysis, market commentary, valuation, and portfolio talk.",
        "keywords": [
            "invest",
            "investing",
            "stock",
            "stocks",
            "market",
            "portfolio",
            "valuation",
            "earnings",
            "shareholder",
            "index fund",
            "s&p 500",
            "public markets",
        ],
    },
    "business_acquisition": {
        "description": "Buying businesses, deal process, due diligence, rollups, and SMB acquisition talk.",
        "keywords": [
            "acquisition",
            "acquire",
            "buy a business",
            "holding company",
            "deal",
            "sba",
            "seller",
            "diligence",
            "rollup",
            "lower middle market",
            "cash flow",
            "ebitda",
        ],
    },
    "operations_execution": {
        "description": "Operatorship, workflow improvement, hiring, systems, and execution talk.",
        "keywords": [
            "operations",
            "operator",
            "hiring",
            "team",
            "margin",
            "process",
            "workflow",
            "capacity",
            "project management",
            "crm",
            "logistics",
            "execution",
        ],
    },
    "career_building": {
        "description": "Career advice, work ethic, learning, interviews, and professional development.",
        "keywords": [
            "career",
            "job",
            "interview",
            "banking",
            "private equity",
            "hedge fund",
            "learn",
            "student",
            "analyst",
            "work hard",
            "discipline",
            "build yourself",
        ],
    },
    "ai_technology": {
        "description": "AI, semiconductors, robotics, software tools, and technology infrastructure.",
        "keywords": [
            "ai",
            "artificial intelligence",
            "semiconductor",
            "chip",
            "memory",
            "robot",
            "robotics",
            "data center",
            "software",
            "automation",
            "bertopic",
            "model",
        ],
    },
    "community_banter": {
        "description": "Chat Capital community language, shout-outs, stream banter, and in-group culture.",
        "keywords": [
            "chat",
            "shredlord",
            "goop",
            "gulag",
            "like button",
            "discord",
            "stream",
            "w in the chat",
            "top dog",
            "smart money moves",
            "fam",
            "chat capital",
        ],
    },
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def log_progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def keyword_match_count(text: str, keyword: str) -> int:
    pattern = rf"(?<!\w){re.escape(keyword.casefold())}(?!\w)"
    return len(re.findall(pattern, text.casefold()))


def score_seed_topics(text: str) -> list[dict]:
    scored_topics: list[dict] = []
    for topic_id, topic_config in SEED_TOPICS.items():
        matched_keywords: list[dict] = []
        total_matches = 0
        for keyword in topic_config["keywords"]:
            match_count = keyword_match_count(text, keyword)
            if not match_count:
                continue
            matched_keywords.append({"keyword": keyword, "count": match_count})
            total_matches += match_count

        if not total_matches:
            continue

        scored_topics.append(
            {
                "topic_id": topic_id,
                "match_count": total_matches,
                "matched_keywords": matched_keywords,
            }
        )

    scored_topics.sort(key=lambda item: (-item["match_count"], item["topic_id"]))
    return scored_topics


def find_analysis_json_files(channel_root: Path) -> list[Path]:
    return sorted(path for path in channel_root.glob("*.json") if path.is_file())


def collect_chunk_records(channel_root: Path) -> list[dict]:
    chunk_records: list[dict] = []
    for analysis_path in find_analysis_json_files(channel_root):
        payload = load_json(analysis_path)
        source = payload.get("source") or {}
        video_id = source.get("video_id") or analysis_path.stem
        title = source.get("title")
        channel_slug = source.get("channel_slug") or channel_root.name

        for chunk in ((payload.get("chunks") or {}).get("items") or []):
            chunk_text = (chunk.get("text") or "").strip()
            if not chunk_text:
                continue

            chunk_records.append(
                {
                    "channel_slug": channel_slug,
                    "video_id": video_id,
                    "title": title,
                    "analysis_json_path": analysis_path.as_posix(),
                    "chunk_id": chunk.get("chunk_id"),
                    "text": chunk_text,
                    "character_count": chunk.get("character_count") or len(chunk_text),
                    "source_provenance": chunk.get("source_provenance") or {},
                    "seed_topic_scores": score_seed_topics(chunk_text),
                }
            )

    return chunk_records


def build_seed_topic_list() -> list[list[str]]:
    return [topic_config["keywords"] for topic_config in SEED_TOPICS.values()]


def load_topic_packages():
    from bertopic import BERTopic
    from hdbscan import HDBSCAN
    from sentence_transformers import SentenceTransformer
    from sklearn.feature_extraction.text import CountVectorizer, ENGLISH_STOP_WORDS
    from umap import UMAP

    return BERTopic, HDBSCAN, SentenceTransformer, CountVectorizer, ENGLISH_STOP_WORDS, UMAP


def fit_bertopic_model(
    texts: list[str],
    embedding_model_name: str = DEFAULT_EMBEDDING_MODEL,
    min_topic_size: int = DEFAULT_MIN_TOPIC_SIZE,
):
    BERTopic, HDBSCAN, SentenceTransformer, CountVectorizer, ENGLISH_STOP_WORDS, UMAP = load_topic_packages()

    embedding_model = SentenceTransformer(embedding_model_name)
    vectorizer_min_df = 1 if len(texts) < 20 else 2
    stop_words = sorted(set(ENGLISH_STOP_WORDS).union(TRANSCRIPT_FILLER_STOPWORDS))
    vectorizer_model = CountVectorizer(
        stop_words=stop_words,
        ngram_range=(1, 2),
        min_df=vectorizer_min_df,
    )
    umap_model = UMAP(
        n_neighbors=min(15, max(2, len(texts) - 1)),
        n_components=5,
        min_dist=0.0,
        metric="cosine",
        random_state=42,
    )
    hdbscan_model = HDBSCAN(
        min_cluster_size=max(2, min_topic_size),
        metric="euclidean",
        cluster_selection_method="eom",
        prediction_data=False,
    )
    topic_model = BERTopic(
        embedding_model=embedding_model,
        vectorizer_model=vectorizer_model,
        umap_model=umap_model,
        hdbscan_model=hdbscan_model,
        seed_topic_list=build_seed_topic_list(),
        min_topic_size=max(2, min_topic_size),
        calculate_probabilities=False,
        verbose=False,
    )
    topics, _ = topic_model.fit_transform(texts)
    return topic_model, topics


def build_topic_label(topic_id: int, topic_terms: list[tuple[str, float]]) -> str:
    if topic_id == -1:
        return "outlier"

    filtered_terms = [
        term
        for term, _score in topic_terms
        if term not in LOW_SIGNAL_LABEL_TERMS and not any(part in LOW_SIGNAL_LABEL_TERMS for part in term.split())
    ]
    top_terms = filtered_terms[:3]
    if not top_terms:
        top_terms = [term for term, _score in topic_terms[:3]]
    return ", ".join(top_terms) if top_terms else f"topic_{topic_id}"


def build_representative_chunk(record: dict) -> dict:
    return {
        "video_id": record["video_id"],
        "title": record["title"],
        "analysis_json_path": record["analysis_json_path"],
        "chunk_id": record["chunk_id"],
        "text": record["text"],
        "source_provenance": record["source_provenance"],
    }


def build_semantic_topic_entries(
    topic_model,
    chunk_records: list[dict],
    topics: list[int],
    representative_chunk_count: int,
) -> list[dict]:
    topic_to_records: dict[int, list[dict]] = defaultdict(list)
    for record, topic_id in zip(chunk_records, topics):
        topic_to_records[topic_id].append(record)

    semantic_topics: list[dict] = []
    for topic_id, topic_records in sorted(topic_to_records.items(), key=lambda item: (-len(item[1]), item[0])):
        topic_terms = topic_model.get_topic(topic_id) or []
        sorted_records = sorted(
            topic_records,
            key=lambda record: (
                -record["character_count"],
                record["video_id"],
                record["chunk_id"] or "",
            ),
        )
        semantic_topics.append(
            {
                "semantic_topic_id": topic_id,
                "semantic_topic_label": build_topic_label(topic_id, topic_terms),
                "chunk_count": len(topic_records),
                "top_terms": [term for term, _score in topic_terms[:10]],
                "representative_chunks": [
                    build_representative_chunk(record)
                    for record in sorted_records[:representative_chunk_count]
                ],
            }
        )

    return semantic_topics


def build_chunk_assignments(chunk_records: list[dict], topics: list[int]) -> list[dict]:
    assignments: list[dict] = []
    for record, semantic_topic_id in zip(chunk_records, topics):
        seed_scores = record["seed_topic_scores"]
        primary_seed_topic = seed_scores[0]["topic_id"] if seed_scores else None
        assignments.append(
            {
                "video_id": record["video_id"],
                "title": record["title"],
                "analysis_json_path": record["analysis_json_path"],
                "chunk_id": record["chunk_id"],
                "text": record["text"],
                "source_provenance": record["source_provenance"],
                "primary_seed_topic": primary_seed_topic,
                "seed_topic_scores": seed_scores,
                "semantic_topic_id": semantic_topic_id,
            }
        )

    return assignments


def build_seed_topic_summary(chunk_assignments: list[dict]) -> list[dict]:
    topic_counter = Counter(
        assignment["primary_seed_topic"]
        for assignment in chunk_assignments
        if assignment["primary_seed_topic"] is not None
    )
    return [
        {
            "seed_topic_id": topic_id,
            "description": SEED_TOPICS[topic_id]["description"],
            "chunk_count": topic_counter.get(topic_id, 0),
        }
        for topic_id in sorted(SEED_TOPICS)
    ]


def chunk_sort_key(assignment: dict) -> tuple:
    provenance = assignment.get("source_provenance") or {}
    start_offset_ms = provenance.get("start_offset_ms")
    normalized_start_offset = start_offset_ms if start_offset_ms is not None else -1
    return (assignment["video_id"], normalized_start_offset, assignment.get("chunk_id") or "")


def should_start_new_section(
    previous_assignment: dict | None,
    current_assignment: dict,
    max_section_gap_ms: int,
) -> bool:
    if previous_assignment is None:
        return True

    if previous_assignment["video_id"] != current_assignment["video_id"]:
        return True

    if previous_assignment["semantic_topic_id"] != current_assignment["semantic_topic_id"]:
        return True

    if previous_assignment["primary_seed_topic"] != current_assignment["primary_seed_topic"]:
        return True

    previous_provenance = previous_assignment.get("source_provenance") or {}
    current_provenance = current_assignment.get("source_provenance") or {}
    previous_end_offset_ms = previous_provenance.get("end_offset_ms")
    current_start_offset_ms = current_provenance.get("start_offset_ms")
    if previous_end_offset_ms is None or current_start_offset_ms is None:
        return False

    return current_start_offset_ms - previous_end_offset_ms > max_section_gap_ms


def finalize_section(
    section_index: int,
    section_assignments: list[dict],
    semantic_labels: dict[int, str],
) -> dict:
    first_assignment = section_assignments[0]
    last_assignment = section_assignments[-1]
    first_provenance = first_assignment.get("source_provenance") or {}
    last_provenance = last_assignment.get("source_provenance") or {}
    section_text = " ".join(assignment["text"] for assignment in section_assignments)

    return {
        "section_id": f"section_{section_index:04d}",
        "video_id": first_assignment["video_id"],
        "title": first_assignment["title"],
        "analysis_json_path": first_assignment["analysis_json_path"],
        "topic_link": {
            "semantic_topic_id": first_assignment["semantic_topic_id"],
            "semantic_topic_label": semantic_labels[first_assignment["semantic_topic_id"]],
            "primary_seed_topic": first_assignment["primary_seed_topic"],
        },
        "chunk_count": len(section_assignments),
        "chunk_ids": [assignment["chunk_id"] for assignment in section_assignments],
        "character_count": sum(assignment.get("character_count") or len(assignment["text"]) for assignment in section_assignments),
        "text": section_text,
        "source_provenance": {
            "start_offset_ms": first_provenance.get("start_offset_ms"),
            "end_offset_ms": last_provenance.get("end_offset_ms"),
            "start_source_chunk_index": first_provenance.get("start_source_chunk_index"),
            "end_source_chunk_index": last_provenance.get("end_source_chunk_index"),
            "duration_ms": (
                None
                if first_provenance.get("start_offset_ms") is None or last_provenance.get("end_offset_ms") is None
                else last_provenance.get("end_offset_ms") - first_provenance.get("start_offset_ms")
            ),
        },
        "section_summary": None,
    }


def build_topic_sections(
    chunk_assignments: list[dict],
    semantic_topic_entries: list[dict],
    max_section_gap_ms: int = DEFAULT_SECTION_GAP_MS,
) -> list[dict]:
    semantic_labels = {
        topic_entry["semantic_topic_id"]: topic_entry["semantic_topic_label"]
        for topic_entry in semantic_topic_entries
    }
    ordered_assignments = sorted(chunk_assignments, key=chunk_sort_key)

    topic_sections: list[dict] = []
    current_section_assignments: list[dict] = []
    previous_assignment: dict | None = None
    for assignment in ordered_assignments:
        if should_start_new_section(previous_assignment, assignment, max_section_gap_ms):
            if current_section_assignments:
                topic_sections.append(
                    finalize_section(len(topic_sections) + 1, current_section_assignments, semantic_labels)
                )
            current_section_assignments = [assignment]
        else:
            current_section_assignments.append(assignment)
        previous_assignment = assignment

    if current_section_assignments:
        topic_sections.append(finalize_section(len(topic_sections) + 1, current_section_assignments, semantic_labels))

    return topic_sections


def build_section_summary_prompt(section: dict) -> str:
    topic_link = section["topic_link"]
    return (
        "You are summarizing one reconstructed transcript section from a Kenny Finance stream. "
        "Write a concise summary of what the conversation was actually about during this timestamp span. "
        "Keep jargon if it is meaningful. Focus on the concrete substance of the discussion so the summary can later support higher-level principle extraction.\n\n"
        f"Semantic topic: {topic_link['semantic_topic_label']}\n"
        f"Primary seed topic: {topic_link['primary_seed_topic']}\n"
        f"Video title: {section['title']}\n"
        f"Video id: {section['video_id']}\n"
        f"Section id: {section['section_id']}\n"
        f"Start offset ms: {section['source_provenance'].get('start_offset_ms')}\n"
        f"End offset ms: {section['source_provenance'].get('end_offset_ms')}\n\n"
        "Transcript section:\n"
        f"{section['text']}\n\n"
        "Return plain text only."
    )


def summarize_section_with_ollama(section: dict, ollama_base_url: str, ollama_model: str, timeout_seconds: int) -> dict:
    response = requests.post(
        f"{ollama_base_url.rstrip('/')}/api/generate",
        json={
            "model": ollama_model,
            "prompt": build_section_summary_prompt(section),
            "stream": False,
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    summary_text = (payload.get("response") or "").strip()
    return {
        "provider": "ollama",
        "model": ollama_model,
        "summary_text": summary_text,
    }


def summarize_topic_sections(
    topic_sections: list[dict],
    ollama_base_url: str,
    ollama_model: str,
    ollama_timeout_seconds: int,
) -> list[dict]:
    for section in topic_sections:
        log_progress(
            f"[topic-analysis] Summarizing {section['section_id']} for {section['video_id']} via Ollama"
        )
        section["section_summary"] = summarize_section_with_ollama(
            section,
            ollama_base_url=ollama_base_url,
            ollama_model=ollama_model,
            timeout_seconds=ollama_timeout_seconds,
        )
    return topic_sections


def section_priority_key(section: dict) -> tuple:
    topic_link = section["topic_link"]
    duration_ms = (section.get("source_provenance") or {}).get("duration_ms") or 0
    primary_seed_topic = topic_link.get("primary_seed_topic")
    seed_topic_signal = 1 if primary_seed_topic is not None else 0
    outlier_penalty = 0 if topic_link.get("semantic_topic_id") == -1 else 1
    return (
        outlier_penalty,
        seed_topic_signal,
        section["chunk_count"],
        section["character_count"],
        duration_ms,
    )


def select_sections_for_summary(
    topic_sections: list[dict],
    section_summary_limit_per_topic: int = DEFAULT_SECTION_SUMMARY_LIMIT_PER_TOPIC,
    section_summary_min_char_count: int = DEFAULT_SECTION_SUMMARY_MIN_CHAR_COUNT,
) -> list[dict]:
    grouped_sections: dict[int, list[dict]] = defaultdict(list)
    all_grouped_sections: dict[int, list[dict]] = defaultdict(list)
    for section in topic_sections:
        semantic_topic_id = section["topic_link"]["semantic_topic_id"]
        all_grouped_sections[semantic_topic_id].append(section)
        if section["character_count"] < section_summary_min_char_count:
            continue
        grouped_sections[semantic_topic_id].append(section)

    selected_sections: list[dict] = []
    for semantic_topic_id, all_grouped in all_grouped_sections.items():
        if semantic_topic_id == -1:
            continue
        grouped = grouped_sections.get(semantic_topic_id) or all_grouped
        ordered_sections = sorted(grouped, key=section_priority_key, reverse=True)
        selected_sections.extend(ordered_sections[:section_summary_limit_per_topic])

    selected_sections.sort(key=lambda section: section["section_id"])
    return selected_sections


def build_topic_synthesis_prompt(topic_group: dict) -> str:
    section_lines: list[str] = []
    for section in topic_group["sections"]:
        section_summary = section.get("section_summary") or {}
        summary_text = section_summary.get("summary_text") or section["text"]
        section_lines.append(
            "\n".join(
                [
                    f"Section id: {section['section_id']}",
                    f"Video id: {section['video_id']}",
                    f"Start offset ms: {section['source_provenance'].get('start_offset_ms')}",
                    f"End offset ms: {section['source_provenance'].get('end_offset_ms')}",
                    f"Section note: {summary_text}",
                ]
            )
        )

    return (
        "You are synthesizing multiple transcript sections that were independently linked to the same topic across one channel corpus. "
        "Write a concise topic-level summary that combines the repeated ideas across these different timestamp ranges. "
        "Preserve meaningful jargon. Focus on what repeatedly comes up, how the discussion differs across sections, and what higher-level theme ties them together.\n\n"
        f"Semantic topic: {topic_group['semantic_topic_label']}\n"
        f"Primary seed topics observed: {', '.join(topic_group['primary_seed_topics']) if topic_group['primary_seed_topics'] else 'none'}\n"
        f"Section count: {topic_group['section_count']}\n"
        f"Video count: {topic_group['video_count']}\n\n"
        "Sections:\n\n"
        + "\n\n---\n\n".join(section_lines)
        + "\n\nReturn plain text only."
    )


def summarize_topic_group_with_ollama(
    topic_group: dict,
    ollama_base_url: str,
    ollama_model: str,
    timeout_seconds: int,
) -> dict:
    response = requests.post(
        f"{ollama_base_url.rstrip('/')}/api/generate",
        json={
            "model": ollama_model,
            "prompt": build_topic_synthesis_prompt(topic_group),
            "stream": False,
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    return {
        "provider": "ollama",
        "model": ollama_model,
        "summary_text": (payload.get("response") or "").strip(),
    }


def build_topic_synthesis_entries(
    topic_sections: list[dict],
    topic_synthesis_section_limit: int = DEFAULT_TOPIC_SYNTHESIS_SECTION_LIMIT,
) -> list[dict]:
    grouped_sections: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for section in topic_sections:
        topic_link = section["topic_link"]
        group_key = (
            topic_link["semantic_topic_id"],
            topic_link["semantic_topic_label"],
        )
        grouped_sections[group_key].append(section)

    topic_synthesis_entries: list[dict] = []
    for (semantic_topic_id, semantic_topic_label), grouped in sorted(
        grouped_sections.items(),
        key=lambda item: (-len(item[1]), item[0][0]),
    ):
        ordered_sections = sorted(
            grouped,
            key=lambda section: (
                -section["character_count"],
                section["video_id"],
                section["section_id"],
            ),
        )
        selected_sections = ordered_sections[:topic_synthesis_section_limit]
        primary_seed_topics = sorted(
            {
                section["topic_link"].get("primary_seed_topic")
                for section in grouped
                if section["topic_link"].get("primary_seed_topic") is not None
            }
        )
        topic_synthesis_entries.append(
            {
                "semantic_topic_id": semantic_topic_id,
                "semantic_topic_label": semantic_topic_label,
                "section_count": len(grouped),
                "video_count": len({section["video_id"] for section in grouped}),
                "primary_seed_topics": primary_seed_topics,
                "source_section_ids": [section["section_id"] for section in selected_sections],
                "sections": selected_sections,
                "topic_summary": None,
            }
        )

    return topic_synthesis_entries


def summarize_topic_synthesis_entries(
    topic_synthesis_entries: list[dict],
    ollama_base_url: str,
    ollama_model: str,
    ollama_timeout_seconds: int,
) -> list[dict]:
    for topic_group in topic_synthesis_entries:
        log_progress(
            f"[topic-analysis] Synthesizing topic {topic_group['semantic_topic_label']} across {topic_group['section_count']} sections via Ollama"
        )
        topic_group["topic_summary"] = summarize_topic_group_with_ollama(
            topic_group,
            ollama_base_url=ollama_base_url,
            ollama_model=ollama_model,
            timeout_seconds=ollama_timeout_seconds,
        )
    return topic_synthesis_entries


def build_video_topic_summaries(
    chunk_assignments: list[dict],
    semantic_topic_entries: list[dict],
) -> list[dict]:
    semantic_labels = {
        topic["semantic_topic_id"]: topic["semantic_topic_label"] for topic in semantic_topic_entries
    }
    videos: dict[str, dict] = {}
    for assignment in chunk_assignments:
        video_id = assignment["video_id"]
        video_summary = videos.setdefault(
            video_id,
            {
                "video_id": video_id,
                "title": assignment["title"],
                "analysis_json_path": assignment["analysis_json_path"],
                "chunk_count": 0,
                "seed_topic_counts": Counter(),
                "semantic_topic_counts": Counter(),
            },
        )

        video_summary["chunk_count"] += 1
        if assignment["primary_seed_topic"] is not None:
            video_summary["seed_topic_counts"][assignment["primary_seed_topic"]] += 1
        video_summary["semantic_topic_counts"][semantic_labels[assignment["semantic_topic_id"]]] += 1

    serialized_summaries: list[dict] = []
    for video_summary in sorted(videos.values(), key=lambda item: item["video_id"]):
        serialized_summaries.append(
            {
                "video_id": video_summary["video_id"],
                "title": video_summary["title"],
                "analysis_json_path": video_summary["analysis_json_path"],
                "chunk_count": video_summary["chunk_count"],
                "seed_topic_counts": dict(sorted(video_summary["seed_topic_counts"].items())),
                "semantic_topic_counts": dict(sorted(video_summary["semantic_topic_counts"].items())),
            }
        )

    return serialized_summaries


def build_topic_analysis_payload(
    channel_slug: str,
    chunk_records: list[dict],
    topic_model,
    topics: list[int],
    embedding_model_name: str,
    representative_chunk_count: int,
    source_analysis_root: Path,
    max_section_gap_ms: int,
    ollama_model: str | None,
    ollama_base_url: str,
    topic_synthesis_section_limit: int,
) -> dict:
    semantic_topic_entries = build_semantic_topic_entries(
        topic_model,
        chunk_records,
        topics,
        representative_chunk_count=representative_chunk_count,
    )
    chunk_assignments = build_chunk_assignments(chunk_records, topics)
    topic_sections = build_topic_sections(
        chunk_assignments,
        semantic_topic_entries,
        max_section_gap_ms=max_section_gap_ms,
    )
    topic_synthesis = build_topic_synthesis_entries(
        topic_sections,
        topic_synthesis_section_limit=topic_synthesis_section_limit,
    )

    return {
        "schema_version": TOPIC_ANALYSIS_SCHEMA_VERSION,
        "record_type": "youtube_chunk_topic_analysis",
        "source": {
            "analysis_root": source_analysis_root.as_posix(),
            "channel_slug": channel_slug,
            "analysis_record_count": len({record["analysis_json_path"] for record in chunk_records}),
            "chunk_count": len(chunk_records),
        },
        "topic_analysis": {
            "method": "hybrid_seed_topics_plus_bertopic_v1",
            "embedding_model": embedding_model_name,
            "generated_at": utc_now_iso(),
            "section_reconstruction": {
                "strategy": "merge_adjacent_chunk_assignments_by_topic_v1",
                "max_section_gap_ms": max_section_gap_ms,
            },
            "section_summaries": {
                "enabled": bool(ollama_model),
                "provider": "ollama" if ollama_model else None,
                "model": ollama_model,
                "base_url": ollama_base_url if ollama_model else None,
                "section_summary_limit_per_topic": DEFAULT_SECTION_SUMMARY_LIMIT_PER_TOPIC,
                "section_summary_min_char_count": DEFAULT_SECTION_SUMMARY_MIN_CHAR_COUNT,
            },
            "topic_synthesis": {
                "enabled": bool(ollama_model),
                "strategy": "aggregate_topic_sections_across_timestamps_v1",
                "provider": "ollama" if ollama_model else None,
                "model": ollama_model,
                "base_url": ollama_base_url if ollama_model else None,
                "topic_synthesis_section_limit": topic_synthesis_section_limit,
            },
            "seed_topics": [
                {
                    "seed_topic_id": topic_id,
                    "description": topic_config["description"],
                    "keywords": topic_config["keywords"],
                }
                for topic_id, topic_config in SEED_TOPICS.items()
            ],
            "seed_topic_summary": build_seed_topic_summary(chunk_assignments),
            "semantic_topics": semantic_topic_entries,
            "video_topic_summaries": build_video_topic_summaries(chunk_assignments, semantic_topic_entries),
            "chunk_assignments": chunk_assignments,
            "topic_sections": topic_sections,
            "topic_synthesis_entries": topic_synthesis,
        },
    }


def iter_channel_roots(analysis_root: Path, channel_slug: str | None) -> list[Path]:
    if channel_slug:
        channel_root = analysis_root / channel_slug
        return [channel_root] if channel_root.exists() else []

    return sorted(path for path in analysis_root.iterdir() if path.is_dir())


def run_topic_analysis(
    analysis_root: Path,
    output_root: Path,
    channel_slug: str | None = None,
    embedding_model_name: str = DEFAULT_EMBEDDING_MODEL,
    min_topic_size: int = DEFAULT_MIN_TOPIC_SIZE,
    representative_chunk_count: int = DEFAULT_REPRESENTATIVE_CHUNK_COUNT,
    max_section_gap_ms: int = DEFAULT_SECTION_GAP_MS,
    ollama_model: str | None = None,
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL,
    ollama_timeout_seconds: int = 120,
    topic_synthesis_section_limit: int = DEFAULT_TOPIC_SYNTHESIS_SECTION_LIMIT,
    section_summary_limit_per_topic: int = DEFAULT_SECTION_SUMMARY_LIMIT_PER_TOPIC,
    section_summary_min_char_count: int = DEFAULT_SECTION_SUMMARY_MIN_CHAR_COUNT,
    limit_chunks: int | None = None,
    dry_run: bool = False,
) -> list[dict]:
    summaries: list[dict] = []
    for channel_root in iter_channel_roots(analysis_root, channel_slug):
        log_progress(f"[topic-analysis] Loading chunk corpus from {channel_root}")
        chunk_records = collect_chunk_records(channel_root)
        if limit_chunks is not None:
            chunk_records = chunk_records[:limit_chunks]
            log_progress(
                f"[topic-analysis] Applying chunk limit {limit_chunks} for {channel_root.name}"
            )
        if not chunk_records:
            log_progress(f"[topic-analysis] No chunks found for {channel_root.name}; skipping")
            continue

        log_progress(
            f"[topic-analysis] Collected {len(chunk_records)} chunks for {channel_root.name}; fitting BERTopic"
        )

        topic_model, topics = fit_bertopic_model(
            [record["text"] for record in chunk_records],
            embedding_model_name=embedding_model_name,
            min_topic_size=min_topic_size,
        )
        log_progress(f"[topic-analysis] BERTopic fit finished for {channel_root.name}; building artifact")
        semantic_topic_entries = build_semantic_topic_entries(
            topic_model,
            chunk_records,
            topics,
            representative_chunk_count=representative_chunk_count,
        )
        chunk_assignments = build_chunk_assignments(chunk_records, topics)
        topic_sections = build_topic_sections(
            chunk_assignments,
            semantic_topic_entries,
            max_section_gap_ms=max_section_gap_ms,
        )
        if ollama_model:
            selected_sections = select_sections_for_summary(
                topic_sections,
                section_summary_limit_per_topic=section_summary_limit_per_topic,
                section_summary_min_char_count=section_summary_min_char_count,
            )
            log_progress(
                f"[topic-analysis] Summarizing {len(selected_sections)} high-value sections out of {len(topic_sections)} reconstructed sections with Ollama model {ollama_model}"
            )
            summarize_topic_sections(
                selected_sections,
                ollama_base_url=ollama_base_url,
                ollama_model=ollama_model,
                ollama_timeout_seconds=ollama_timeout_seconds,
            )
        topic_synthesis_entries = build_topic_synthesis_entries(
            topic_sections,
            topic_synthesis_section_limit=topic_synthesis_section_limit,
        )
        if ollama_model:
            log_progress(
                f"[topic-analysis] Synthesizing {len(topic_synthesis_entries)} topics across timestamps with Ollama model {ollama_model}"
            )
            summarize_topic_synthesis_entries(
                topic_synthesis_entries,
                ollama_base_url=ollama_base_url,
                ollama_model=ollama_model,
                ollama_timeout_seconds=ollama_timeout_seconds,
            )
        payload = build_topic_analysis_payload(
            channel_slug=channel_root.name,
            chunk_records=chunk_records,
            topic_model=topic_model,
            topics=topics,
            embedding_model_name=embedding_model_name,
            representative_chunk_count=representative_chunk_count,
            source_analysis_root=analysis_root,
            max_section_gap_ms=max_section_gap_ms,
            ollama_model=ollama_model,
            ollama_base_url=ollama_base_url,
            topic_synthesis_section_limit=topic_synthesis_section_limit,
        )
        payload["topic_analysis"]["semantic_topics"] = semantic_topic_entries
        payload["topic_analysis"]["chunk_assignments"] = chunk_assignments
        payload["topic_analysis"]["video_topic_summaries"] = build_video_topic_summaries(
            chunk_assignments,
            semantic_topic_entries,
        )
        payload["topic_analysis"]["seed_topic_summary"] = build_seed_topic_summary(chunk_assignments)
        payload["topic_analysis"]["topic_sections"] = topic_sections
        payload["topic_analysis"]["topic_synthesis_entries"] = topic_synthesis_entries
        output_path = output_root / channel_root.name / "topic_analysis.json"

        if not dry_run:
            log_progress(f"[topic-analysis] Writing artifact to {output_path}")
            write_json(output_path, payload)
        else:
            log_progress(
                f"[topic-analysis] Dry run complete for {channel_root.name}; artifact not written"
            )

        summaries.append(
            {
                "channel_slug": channel_root.name,
                "analysis_root": str(channel_root),
                "output_path": str(output_path),
                "chunk_count": len(chunk_records),
                "semantic_topic_count": len(payload["topic_analysis"]["semantic_topics"]),
                "dry_run": dry_run,
            }
        )
        log_progress(
            f"[topic-analysis] Completed {channel_root.name} with {len(payload['topic_analysis']['semantic_topics'])} semantic topics"
        )

    return summaries


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Run hybrid topic analysis directly over the committed chunk-level analysis corpus."
    )
    parser.add_argument(
        "--analysis-root",
        default=str(repo_root / "data" / "analysis" / "youtube"),
        help="Root directory containing analysis-ready JSON records.",
    )
    parser.add_argument(
        "--output-root",
        default=str(repo_root / "data" / "topic_analysis" / "youtube"),
        help="Root directory where topic analysis artifacts will be written.",
    )
    parser.add_argument(
        "--channel-slug",
        help="Optional channel slug to analyze instead of every channel directory under the analysis root.",
    )
    parser.add_argument(
        "--embedding-model",
        default=DEFAULT_EMBEDDING_MODEL,
        help="SentenceTransformers embedding model name passed into BERTopic.",
    )
    parser.add_argument(
        "--min-topic-size",
        type=int,
        default=DEFAULT_MIN_TOPIC_SIZE,
        help="Minimum cluster size used for BERTopic topic formation.",
    )
    parser.add_argument(
        "--representative-chunk-count",
        type=int,
        default=DEFAULT_REPRESENTATIVE_CHUNK_COUNT,
        help="Maximum number of representative chunks to store per semantic topic.",
    )
    parser.add_argument(
        "--max-section-gap-ms",
        type=int,
        default=DEFAULT_SECTION_GAP_MS,
        help="Maximum timestamp gap allowed when merging adjacent chunk assignments into one topic section.",
    )
    parser.add_argument(
        "--ollama-model",
        default=os.getenv("OLLAMA_MODEL"),
        help="Optional Ollama model name used to summarize reconstructed topic sections.",
    )
    parser.add_argument(
        "--ollama-base-url",
        default=os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL),
        help="Base URL for the local Ollama server.",
    )
    parser.add_argument(
        "--ollama-timeout-seconds",
        type=int,
        default=120,
        help="Timeout in seconds for each Ollama section-summary request.",
    )
    parser.add_argument(
        "--topic-synthesis-section-limit",
        type=int,
        default=DEFAULT_TOPIC_SYNTHESIS_SECTION_LIMIT,
        help="Maximum number of reconstructed sections to include when synthesizing one topic across timestamps.",
    )
    parser.add_argument(
        "--section-summary-limit-per-topic",
        type=int,
        default=DEFAULT_SECTION_SUMMARY_LIMIT_PER_TOPIC,
        help="Maximum number of reconstructed sections to summarize per semantic topic.",
    )
    parser.add_argument(
        "--section-summary-min-char-count",
        type=int,
        default=DEFAULT_SECTION_SUMMARY_MIN_CHAR_COUNT,
        help="Minimum section character count required before a reconstructed section is eligible for LLM summarization.",
    )
    parser.add_argument(
        "--limit-chunks",
        type=int,
        help="Optional limit for quick iteration during local development.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the analysis without writing output artifacts.",
    )
    args = parser.parse_args()

    summaries = run_topic_analysis(
        analysis_root=Path(args.analysis_root),
        output_root=Path(args.output_root),
        channel_slug=args.channel_slug,
        embedding_model_name=args.embedding_model,
        min_topic_size=args.min_topic_size,
        representative_chunk_count=args.representative_chunk_count,
        max_section_gap_ms=args.max_section_gap_ms,
        ollama_model=args.ollama_model,
        ollama_base_url=args.ollama_base_url,
        ollama_timeout_seconds=args.ollama_timeout_seconds,
        topic_synthesis_section_limit=args.topic_synthesis_section_limit,
        section_summary_limit_per_topic=args.section_summary_limit_per_topic,
        section_summary_min_char_count=args.section_summary_min_char_count,
        limit_chunks=args.limit_chunks,
        dry_run=args.dry_run,
    )
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
# Chat Capital Boring Business Bot

This repo is the initial release of a transcript and dataset workflow for the Kenny Finance channel and the Chat Capital community.

Today, the project is focused on one concrete job: collecting Kenny Finance stream metadata and transcripts, storing them in a consistent local structure, and keeping the dataset organized enough to support later search, analysis, and bot-style workflows.

This is not a full application yet. The current state of the repo is a practical data pipeline for building and maintaining the underlying transcript dataset.

## What This Repo Does Today

- Builds a structured transcript dataset from the Kenny Finance channel for Chat Capital workflows.
- Saves YouTube streams-tab metadata into structured JSON files.
- Enriches those saved records with transcript workflow state.
- Fetches transcripts with Supadata and stores transcript artifacts locally.
- Maintains a flat queue CSV for tracking transcript readiness and status.
- Keeps the raw source metadata and transcript outputs in a repo-local data layout.

## Repo Layout

```text
.
├── docs/
│   └── workflow.md
├── data/
│   ├── raw/
│   │   └── youtube/
│   │       ├── transcript_queue.csv
│   │       └── <channel>-streams/
│   │           ├── collection.json
│   │           ├── manifest.csv
│   │           └── videos/
│   │               └── <video_id>.json
│   └── transcripts/
│       └── youtube/
│           └── <channel_slug>/
│               ├── <video_id>.json
│               └── <video_id>.txt
│   └── analysis/
│       └── youtube/
│           └── <channel_slug>/
│               └── <video_id>.json
├── scripts/
│   ├── save_stream_video_index.py
│   ├── enrich_video_metadata.py
│   └── fetch_transcripts.py
│   └── build_analysis_corpus.py
├── tests/
│   ├── test_enrich_video_metadata.py
│   └── test_fetch_transcripts.py
└── .env
```

## Docs

- See [docs/workflow.md](docs/workflow.md) for the current transcript pipeline, main artifacts, and workflow states.
- See [docs/analysis-plan.md](docs/analysis-plan.md) for the planned transcript-cleaning, lexicon, topic-analysis, and principle-extraction workflow.

## Key Scripts

### `scripts/save_stream_video_index.py`

Discovers videos from a YouTube channel streams tab and saves per-video metadata into `data/raw/youtube/...`.

### `scripts/enrich_video_metadata.py`

Normalizes each saved video JSON into a transcript-focused schema and regenerates `data/raw/youtube/transcript_queue.csv`.

### `scripts/fetch_transcripts.py`

Processes queued videos, calls Supadata for transcript text, writes transcript artifacts, and updates the source metadata records.

The script is meant to be rerun as the local dataset grows or as transcript artifacts need to be refreshed to match the current schema.

### `scripts/build_analysis_corpus.py`

Builds cleaned analysis-ready transcript records, preserves community lexicon terms, and writes derived analysis artifacts into `data/analysis/youtube/...`.

### `scripts/run_topic_analysis.py`

Runs a hybrid topic-analysis pass directly over the chunk-level analysis corpus using seeded topic buckets plus BERTopic semantic clustering, reconstructs topic-linked sections from adjacent chunk assignments, can optionally summarize those sections through Ollama, and can synthesize topic-level summaries across multiple timestamp-separated sections before writing derived topic artifacts into `data/topic_analysis/youtube/...`.

## Current Data Flow

1. Discover stream videos and save raw metadata.
2. Enrich those records with transcript workflow fields.
3. Fetch transcripts for eligible videos.
4. Store transcript artifacts and refresh the queue/index.

## Next Planned Phase

The transcript collection phase is effectively complete for the current Kenny Finance dataset.

The next planned work is the analysis layer:

1. Build a community lexicon for domain-specific lingo such as recurring Chat Capital and Kenny Finance terms.
2. Clean and normalize transcript text while preserving meaningful jargon.
3. Chunk cleaned transcript content into analysis-ready units.
4. Run topic analysis across the corpus.
5. Extract practical guidelines and principles from the highest-signal transcript segments.

The current Phase 4 direction is a hybrid seeded-plus-BERTopic pass over the committed chunk corpus rather than a separate flattened export.

That Phase 4 output is now intended to feed a second layer of section summaries tied back to topic-linked timestamp spans so later principle extraction can use more faithful notes about what the conversation was actually about.

The pipeline now also supports a cross-timestamp topic-synthesis layer so repeated sections linked to the same topic can be summarized into higher-level topic notes before principle extraction.

See [docs/analysis-plan.md](docs/analysis-plan.md) for the working plan that will be updated as this phase is implemented.

## Environment

This project currently expects:

- Python in a local virtual environment.
- A `.env` file with `supadata_api_key` for transcript fetching.
- `python-dotenv` for loading environment variables.

## Tests

This repo includes a small unit-test baseline for the metadata enrichment flow and transcript queue behavior.

Run the test suite with:

```bash
python -m unittest discover -s tests -p "test_*.py"
```

Install the direct Python dependencies for the current analysis workflow with:

```bash
pip install -r requirements.txt
```

If you want section summaries from a local LLM pass, run Ollama separately and pass `--ollama-model <model-name>` to the topic-analysis script, or set `OLLAMA_MODEL` in the environment.

## Notes

- This repo is released in its current form as a dataset-building workflow, not a finished bot interface.
- The scope is intentionally narrow: Kenny Finance channel content for the Chat Capital community's research workflow.
- Transcript artifacts and raw metadata are treated as first-class project data, not temporary build output.

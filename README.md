# Chat Capital Boring Business Bot

This repo is the initial release of a transcript, analysis, and principle-packaging workflow for the Kenny Finance channel and the Chat Capital community.

Today, the project covers the full first-pass research pipeline: collecting Kenny Finance stream metadata and transcripts, converting that corpus into analysis-ready artifacts, running topic and principle extraction, and packaging a narrower consumer layer for downstream readers, bots, or agents.

This is not a full application yet. The current state of the repo is a practical research pipeline plus committed derived artifacts.

## What This Repo Does Today

- Builds a structured transcript dataset from the Kenny Finance channel for Chat Capital workflows.
- Saves YouTube streams-tab metadata into structured JSON files.
- Enriches those saved records with transcript workflow state.
- Fetches transcripts with Supadata and stores transcript artifacts locally.
- Maintains a flat queue CSV for tracking transcript readiness and status.
- Builds cleaned analysis-ready transcript artifacts.
- Runs topic analysis and topic-synthesis over the cleaned corpus.
- Extracts principle candidates from the strongest topic-level synthesis entries.
- Packages a first-pass curated consumer layer for public equity, private equity, and personal finance.
- Keeps the raw, derived, and curated outputs in a repo-local data layout.

## Repo Layout

```text
.
├── docs/
│   ├── analysis-plan.md
│   ├── community-lexicon.md
│   ├── principles/
│   │   ├── README.md
│   │   ├── personal-finance.md
│   │   ├── private-equity.md
│   │   └── public-equity.md
│   └── workflow.md
├── data/
│   ├── analysis/
│   │   └── youtube/
│   │       └── <channel_slug>/
│   │           └── <video_id>.json
│   ├── principles/
│   │   └── youtube/
│   │       └── <channel_slug>/
│   │           ├── principles.json
│   │           └── principles_investing_focus.json
│   ├── raw/
│   │   └── youtube/
│   │       ├── transcript_queue.csv
│   │       └── <channel>-streams/
│   │           ├── collection.json
│   │           ├── manifest.csv
│   │           └── videos/
│   │               └── <video_id>.json
│   ├── topic_analysis/
│       └── youtube/
│           └── <channel_slug>/
│               └── topic_analysis.json
│   └── transcripts/
│       └── youtube/
│           └── <channel_slug>/
│               ├── <video_id>.json
│               └── <video_id>.txt
├── scripts/
│   ├── build_analysis_corpus.py
│   ├── enrich_video_metadata.py
│   ├── fetch_transcripts.py
│   ├── run_principle_extraction.py
│   ├── run_topic_analysis.py
│   └── save_stream_video_index.py
├── tests/
│   ├── test_build_analysis_corpus.py
│   ├── test_enrich_video_metadata.py
│   ├── test_fetch_transcripts.py
│   ├── test_run_principle_extraction.py
│   ├── test_run_topic_analysis.py
│   └── test_save_stream_video_index.py
└── .env
```

## Docs

- See [docs/workflow.md](docs/workflow.md) for the current transcript pipeline, main artifacts, and workflow states.
- See [docs/analysis-plan.md](docs/analysis-plan.md) for the working transcript-cleaning, lexicon, topic-analysis, principle-extraction, and consumer-packaging workflow.

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

### `scripts/run_principle_extraction.py`

Reads the topic-analysis artifact, filters to high-signal synthesized topics, uses Ollama to extract principle candidates into `data/principles/youtube/...`, and then ranks and exact-deduplicates those candidates before writing the artifact.

## Current End-To-End Flow

1. Discover stream videos and save raw metadata.
2. Enrich those records with transcript workflow fields.
3. Fetch transcripts for eligible videos.
4. Store transcript artifacts and refresh the queue/index.
5. Build cleaned analysis-ready transcript records.
6. Run topic analysis and topic synthesis.
7. Extract principle candidates and curate consumer docs.

## Current Status

The transcript collection and first-pass analysis workflow are both usable for the current Kenny Finance dataset.

The repo now includes completed first-pass artifacts for:

- transcript ingestion
- analysis corpus building and chunking
- topic analysis and topic synthesis
- principle extraction
- curated consumer packaging

The main follow-up work is now refinement rather than net-new pipeline creation: improving principle relevance, curating focused artifacts further, and preparing downstream bot or agent workflows.

A first-pass human-curated consumer layer for the investing-focused principle artifact now lives under `docs/principles/`, split into public equity, private equity, and personal finance docs.

See [docs/analysis-plan.md](docs/analysis-plan.md) for the working plan that will be updated as this phase is implemented.

## Environment

This project currently expects:

- Python in a local virtual environment.
- A `.env` file with `supadata_api_key` for transcript fetching.
- `python-dotenv` for loading environment variables.

## Tests

This repo includes focused unit tests across ingestion, analysis-corpus building, topic analysis, and principle extraction.

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

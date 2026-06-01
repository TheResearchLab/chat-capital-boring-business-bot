# Workflow

This repo currently focuses on building a transcript dataset from Kenny Finance YouTube stream content for the Chat Capital community.

The workflow is intentionally simple:

1. Discover stream videos from a YouTube channel.
2. Save raw per-video metadata into JSON files.
3. Enrich those records with transcript workflow fields.
4. Fetch transcripts for eligible records.
5. Write transcript artifacts and refresh the derived queue.

## Current Status

For the Kenny Finance dataset currently stored in this repo, transcript collection is effectively complete.

That means this workflow has done its job for the current phase: it produced the transcript-ready corpus that the next analysis stage will build on.

## Main Artifacts

### Raw channel metadata

- `data/raw/youtube/<channel>-streams/collection.json`
- `data/raw/youtube/<channel>-streams/manifest.csv`
- `data/raw/youtube/<channel>-streams/videos/<video_id>.json`

These files represent the source-of-truth metadata discovered from the channel streams tab.

### Derived transcript queue

- `data/raw/youtube/transcript_queue.csv`

This is a flat queue view built from the per-video JSON records. It is useful for quickly seeing which videos are ready, completed, failed, or need review.

### Transcript artifacts

- `data/transcripts/youtube/<channel_slug>/<video_id>.json`
- `data/transcripts/youtube/<channel_slug>/<video_id>.txt`

These files store fetched transcript payloads and plain text output.

The JSON artifact is the richer form. It now supports both:

- flattened transcript text in `content`
- timestamped transcript chunks in `chunks`

## Script Responsibilities

### `scripts/save_stream_video_index.py`

Discovers videos from a YouTube channel streams page and saves raw metadata files.

### `scripts/enrich_video_metadata.py`

Normalizes raw video records into a transcript-focused schema and regenerates the queue CSV.

### `scripts/fetch_transcripts.py`

Loads eligible records, fetches transcripts through Supadata, stores transcript artifacts, updates per-video workflow state, and refreshes the queue.

The script is designed to be rerun whenever the local dataset needs to be refreshed, completed records need to be normalized to the current artifact shape, or newly indexed videos are ready for transcript collection.

## Workflow States

The current workflow is centered on two top-level sections inside each enriched video record:

- `workflow`
- `transcript`

Common values include:

- `workflow.status`: `ready_for_transcript`, `transcript_in_progress`, `transcript_ready`, `needs_review`
- `transcript.status`: `not_started`, `in_progress`, `completed`, `failed`

This keeps the repo focused on one concrete problem: turning a set of saved stream videos into a transcript-ready dataset that can later support search, analysis, and agent-style tooling.

In practice, that means this workflow is not intended as a generic multi-channel ingestion system right now. It is specifically aimed at Kenny Finance channel material and the research needs of Chat Capital.

## Planned Analysis Workflow

The next stage is documented separately in [docs/analysis-plan.md](analysis-plan.md).

At a high level, the planned analysis workflow is:

1. Build a lexicon of community-specific lingo so domain terms are preserved rather than discarded as noise.
2. Clean and normalize transcript text for downstream analysis.
3. Chunk transcript content into analysis-ready units.
4. Run topic analysis over the cleaned corpus.
5. Extract repeatable guidelines and principles from the most useful segments.
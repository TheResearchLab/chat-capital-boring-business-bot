# Analysis Plan

This document tracks the next phase of the repo after transcript collection: turning the Kenny Finance transcript corpus into an analysis-ready dataset that can support topic discovery, principle extraction, and later bot or agent workflows.

## Current Starting Point

- The repo already has a stable transcript ingestion pipeline.
- Raw stream metadata is stored under `data/raw/youtube/...`.
- Transcript artifacts are stored under `data/transcripts/youtube/...`.
- The current corpus is treated as complete for the active Kenny Finance channel scope.
- The current analysis corpus contains 124 cleaned analysis records under `data/analysis/youtube/...`.

The practical implication is that the next work should focus on transcript preparation and analysis, not more ingestion work.

## Why This Stage Exists

Raw transcripts are good enough for storage and manual reading, but they are not yet ideal for structured analysis.

In particular, this corpus includes:

- stream-style filler language
- repeated phrases and conversational noise
- community-specific jargon
- shifts between serious analysis, banter, and chat interaction

If those signals are not handled deliberately, topic analysis and principle extraction will be noisy and less trustworthy.

## Phase 1: Community Lexicon

Before heavy cleaning, build a small lexicon of recurring community-specific language.

The first-pass lexicon now lives in `docs/community-lexicon.md` and should be treated as the source document for native community terms until a machine-readable artifact is added.

The purpose of this lexicon is to preserve meaningful jargon that a generic NLP pipeline might otherwise treat as noise.

Examples already observed in the corpus include:

- `shredlord`
- `goop`
- `chalked`
- `gulag`

The lexicon should eventually capture fields such as:

- `term`
- `normalized_term`
- `meaning`
- `sentiment_or_signal`
- `example_usage`
- `notes`

Expected outcome:

- domain language is retained during cleaning
- later topic labels become more interpretable
- principle extraction is less likely to confuse jargon with noise

## Phase 2: Transcript Cleaning And Normalization

Create an analysis-prep step that reads transcript artifacts and produces cleaned text while preserving useful semantics.

Initial implementation status:

- `scripts/build_analysis_corpus.py` now creates one cleaned analysis JSON record per transcript JSON artifact.
- The cleaner now removes a broader set of stage-direction style artifacts such as bracketed singing or music markers and strips lingering `>>` transcript markers.
- The current implementation records lexicon term hits for the initial native vocabulary while preserving the community terms themselves in cleaned text.
- Derived analysis records are written under `data/analysis/youtube/...`.
- The current corpus build has been regenerated after the cleaner refinement and now covers 124 transcript files.
- The current cleaner plus chunking slice has been validated with focused unit tests and the regenerated analysis corpus has been committed so the repo state matches the derived artifacts on disk.

Likely cleaning tasks:

- remove obvious transcript markup noise such as repeated stage-like artifacts
- normalize whitespace and punctuation
- reduce repeated filler where it adds no meaning
- preserve high-signal slang, finance language, and community terms
- keep enough provenance to trace cleaned text back to the source video and, when possible, timestamped chunks

Expected output shape:

- one analysis-ready record per video
- optional one analysis-ready record per chunk or segment

Immediate next step:

- start topic analysis on top of the committed chunk-level corpus rather than extending cleaning or chunking first
- decide whether topic analysis should consume the existing JSON analysis corpus directly or whether a flattened chunk export should be generated first

## Phase 3: Chunking Strategy

Once text is normalized, split the corpus into analysis-ready units.

The chunking step should aim to preserve coherent meaning rather than just fixed token windows.

Current implementation decision:

- chunking now happens while building each analysis record by aggregating the source transcript's timed `chunks`
- each analysis chunk is built from one or more cleaned transcript chunks instead of being cut from the full cleaned blob alone
- each chunk now keeps source provenance including source chunk index range plus start and end offsets in milliseconds
- the current strategy uses a lightweight bounded-character aggregation pass so the first chunking layer stays deterministic and traceable

Desired properties:

- each chunk should represent one idea, topic, or argument when possible
- chunk size should be appropriate for downstream topic analysis and retrieval
- chunks should keep metadata such as `video_id`, `channel_slug`, and source offsets when available

Expected output:

- a chunk-level dataset for downstream analysis

Current output shape inside each analysis record:

- top-level `source` metadata now includes derived `video_id` and `channel_slug`
- top-level `chunks.items` stores analysis chunks with cleaned text, character count, and source provenance
- `analysis_status.chunking_complete` is now true when chunk items are present

Current status:

- the first chunking slice is implemented and committed
- the derived analysis corpus has been regenerated across the current 124-video scope
- the next repo-level work should move to topic analysis instead of more chunking work unless a concrete corpus defect is found

## Phase 4: Topic Analysis

After cleaning and chunking, run topic analysis across the corpus.

Implementation direction:

- topic analysis should consume the existing chunk-level JSON corpus directly rather than adding a separate flattened export first
- the first implementation path should be a hybrid approach that combines explicit seeded topic buckets with BERTopic semantic clustering over chunk text
- the seeded layer should stabilize interpretation around expected channel themes such as investing, business acquisition, operations, career development, AI, and community banter
- the BERTopic layer should surface semantic clusters, topic terms, and representative examples that the seeded layer would miss on its own
- the output should be a derived channel-level topic artifact that remains traceable back to per-video and per-chunk sources
- after initial topic assignment, adjacent chunk assignments should be merged back into topic-linked sections so later analysis can recover what was actually being discussed around a timestamp span rather than only isolated chunk labels
- those reconstructed sections should optionally receive section summaries from a local LLM pass such as Ollama so the repo can store notes that describe the real substance of the discussion while still linking back to the originally detected topic
- those section summaries should be treated as an intermediate layer between topic discovery and principle extraction, because they make it easier to reason about higher-level heuristics, norms, and operating principles without losing source traceability
- after section summaries exist, the pipeline should also synthesize across multiple timestamp-separated sections that share a topic so the repo captures a cross-section topic summary instead of stopping at isolated local notes
- this cross-timestamp synthesis layer should aggregate the most informative reconstructed sections per topic and produce topic-level notes that describe repeated themes, recurring arguments, and variation across different videos or moments in the stream archive

This stage should answer questions such as:

- what subjects recur most often across the channel?
- which topics are central to the Chat Capital community?
- how often does the content shift between investing, business acquisition, career advice, operations, and community banter?

Desired outputs:

- topic labels
- representative chunks or examples per topic
- optional per-video topic summaries

Planned first-pass artifact:

- one topic analysis JSON summary per channel under a dedicated derived output path
- chunk-level topic assignments that preserve `video_id`, `chunk_id`, and source offsets
- seeded topic summaries plus BERTopic-derived semantic topic clusters
- per-video topic rollups for later principle extraction
- reconstructed topic sections that merge neighboring chunk assignments from the same video back into timestamped conversational spans
- optional section summaries that point back to each reconstructed topic section and act as higher-signal notes for later principle extraction
- topic-level synthesis entries that summarize one topic across multiple timestamp-separated sections while keeping references back to the contributing sections

## Phase 5: Principle Extraction

After topics are reasonably stable, extract practical guidance and repeatable principles from the strongest transcript segments.

Implementation note:

- principle extraction should prefer reconstructed topic sections and their section summaries over raw isolated chunks whenever those richer artifacts are available
- the goal is to move from "this chunk matched a topic" to "this timestamp span was substantively about X, and here is a concise note describing why that matters"
- when available, principle extraction should also consume the topic-level synthesis layer because those cross-timestamp summaries are a better bridge from repeated local observations to higher-level heuristics and principles
- the first implementation pass should start from non-outlier topic synthesis entries that already have topic summaries and sufficient section support, so principle extraction begins from the cleanest high-signal slice rather than the entire raw topic surface
- the extraction output should be lightly normalized after generation: stronger candidates should rank ahead of weaker ones, and exact duplicate principles should be removed before downstream review or agent use

This stage should focus on high-signal content such as:

- investing heuristics
- business acquisition principles
- diligence patterns
- work habits and decision rules
- community norms or repeated operating philosophies

Desired outputs:

- extracted principle statements
- source examples that justify each principle
- optional grouping by topic or confidence

## Implementation Order

The intended build order is:

1. Create a first-pass jargon lexicon.
2. Build transcript cleaning and normalization outputs.
3. Add chunking for downstream analysis.
4. Run topic analysis on the prepared corpus.
5. Add principle extraction on top of the topic-aware dataset.

Working completion state:

- steps 1 through 5 now have a usable first pass in-repo
- topic analysis and principle extraction both have generated artifacts for the Kenny Finance corpus
- the current follow-up work is refinement: tighten principle relevance, curate focused artifacts, and prepare downstream bot or agent workflows

## Working Notes

- Do not over-clean the transcripts early. The jargon and community voice are part of the dataset's value.
- Keep every downstream artifact traceable back to a source transcript file.
- Prefer explicit intermediate artifacts over one large opaque analysis step.
- When cleaning reveals a real-corpus defect, fix that specific slice and regenerate the derived artifacts so the on-disk analysis corpus stays in sync with the script behavior.
- Update this document as implementation decisions become concrete.
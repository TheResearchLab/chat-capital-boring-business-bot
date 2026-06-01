# Community Lexicon

This document is the first-pass lexicon for native Kenny Finance and Chat Capital community language.

The goal is to preserve terms that carry real meaning in the corpus so later cleaning and topic analysis do not throw them away as generic noise.

## Scope

For now, this lexicon is intentionally small.

Per the current working assumption, the main native terms worth preserving are:

- `shredlord`
- `goop`
- `chalked`
- `gulag`

This file should stay short and only grow when a term is clearly native to the community and materially useful for downstream analysis.

## Terms

### `shredlord`

- Normalized term: `shredlord`
- Meaning: a highly focused, disciplined, ambitious community member who is building, investing, learning, and generally moving with intent
- Signal: strong positive identity marker
- Typical usage: praise, belonging, community status, welcoming someone into the culture
- Notes: this is the clearest explicit native term in the corpus because it is directly defined on-stream

Example usage:

> "Shredlords is our term for like super focused, locked in guys that are just building, investing, making smart money moves, and crushing it in all forms of life."

Source:

- `data/transcripts/youtube/kenny-finance-streams/-5-80f9PSTM.json`

### `goop`

- Normalized term: `goop`
- Meaning: high-value information, promising research, a good idea, useful insight, or a strong opportunity
- Signal: strong positive endorsement marker
- Typical usage: marks something as valuable, interesting, alpha-generating, or worth paying attention to
- Notes: this term appears across research, investing, business ideas, and community interaction; it often means "this is the good stuff"

Example usage:

> "This is good goop right here."

Source:

- `data/transcripts/youtube/kenny-finance-streams/-KztJ9ctruk.json`

### `chalked`

- Normalized term: `chalked`
- Meaning: broken, weak, unattractive, outdated, not worth the trouble, or operationally poor
- Signal: negative quality judgment
- Typical usage: used when dismissing a workflow, interface, setup, or opportunity as not worth pursuing
- Notes: in the current corpus it reads less like community identity language and more like native in-group slang applied during evaluation

Example usage:

> "If the website's kind of chalked, you got to ask yourself..."

Source:

- `data/transcripts/youtube/kenny-finance-streams/-KztJ9ctruk.json`

### `gulag`

- Normalized term: `gulag`
- Meaning: joking punishment state for bad takes, spam, low-quality behavior, or community rule violations; effectively a ban, timeout, removal, or exile bit
- Signal: humorous negative enforcement marker
- Typical usage: moderation language, social discipline, joking threats, community boundaries
- Notes: this term is clearly recurring and not incidental; it is used for Discord moderation, chat discipline, and bad investing behavior

Example usage:

> "We had to send some people to the gulag the other day."

Additional example usage:

> "You trying to get sent to the gulag, you know my thoughts on day trading."

Sources:

- `data/transcripts/youtube/kenny-finance-streams/3RZQIXTkCq8.json`
- `data/transcripts/youtube/kenny-finance-streams/2arUCdauzg0.json`

## Working Rules

- Preserve these terms during transcript cleaning.
- Do not auto-normalize them into generic English replacements.
- Treat them as analysis signals for tone, endorsement, identity, and moderation.
- Expand this lexicon only when a new term is both recurring and clearly meaningful in the community.
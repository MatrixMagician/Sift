# API Coverage — Phase 15

No external API integration: Phase 15 ships a pure local library module (TOML rules loader, symbol
normaliser, frame classifier) that reads package data and `Event.raw` strings — it makes no HTTP
call, imports no SDK, adds no dependency, and does not touch `src/sift/llm/`, the only module in the
project permitted to speak HTTP.

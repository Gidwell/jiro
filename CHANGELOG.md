# Jiro Changelog

## v1.1.0 — 2026-02-20

### Features
- `?ask` hotkey: include `?ask` anywhere in a text message to get a TTS voice reply

### Fixes
- Fixed SQLite "cannot commit transaction" error by closing cursors before committing and serializing all DB access through write lock
- Reverted from Railway to local hosting (Railway polling conflicts were unresolvable)

## v1.0.0 — 2026-02-16

Initial build and Railway deployment attempt. Voice-first Japanese speaking coach for Telegram.

### Features
- Voice message input via STT (speech-to-text) and TTS (text-to-speech) responses
- Conversation management with Claude AI backend
- Learning curriculum and planner with spaced repetition
- Question generator for active recall practice
- Commands: `/start`, `/talk`, `/mode`, `/plan`, `/review`, `/stats`, `/strict`, `/settime`, `/repeat`, `/delete`
- Background tasks (questions, summaries, learner updates) powered by Haiku 4.5
- SQLite database for user data, conversation history, and learning progress
- Dual-mode database (SQLite local / PostgreSQL Railway) with auto SQL dialect conversion

### Fixes Applied During Deployment
- Switched from polling to webhook mode to resolve 409 Conflict on Railway
- Fixed `audioop` missing module error on Python 3.13
- Fixed `asyncpg` date type errors and SQLite `date()` conversion incompatibilities

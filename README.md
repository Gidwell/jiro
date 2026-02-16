# JIRO — Japanese Instruction, Review, Output

Voice-first Japanese speaking coach that lives in Telegram. Send a voice note in Japanese, get back a graded voice reply with feedback, corrections, and a follow-up question to keep you talking.

## Prerequisites

- Python 3.11+
- [ffmpeg](https://ffmpeg.org/) installed and on your PATH
- API keys for: Telegram, Anthropic (Claude), ElevenLabs

## Getting API Keys

| Service | Where | Notes |
|---------|-------|-------|
| **Telegram** | Message [@BotFather](https://t.me/BotFather) on Telegram, `/newbot` | Copy the bot token |
| **Anthropic** | [console.anthropic.com](https://console.anthropic.com/) | Create an API key, add credits |
| **ElevenLabs** | [elevenlabs.io](https://elevenlabs.io/) | Paid plan required for TTS. Get your API key from Profile Settings. Pick a voice from the Voice Library and copy its Voice ID |

To find your **Telegram user ID**, message [@userinfobot](https://t.me/userinfobot) on Telegram.

## Quick Start

```bash
# Clone and enter the project
git clone <your-repo-url> && cd jiro

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Python 3.13+ only — needed for pydub compatibility
pip install audioop-lts

# Configure
cp .env.example .env
# Edit .env and fill in your API keys

# Run
python3 main.py
```

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message and setup |
| `/talk` | Start a free conversation |
| `/review` | Practice due review items |
| `/stats` | View your scores and streak |
| `/plan` | See your learning plan |
| `/mode` | Switch between conversation / drill / free talk |
| `/settime` | Set daily question delivery time |
| `/repeat` | Replay the last voice reply |
| `/strict` | Toggle strict correction mode |
| `/delete` | Delete all your data |

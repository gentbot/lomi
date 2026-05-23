<div align="center">

# **omi**

### A 2nd brain you trust more than your 1st

Omi captures your screen and conversations, transcribes in real-time, generates summaries and action items, and gives you an AI chat that remembers everything you've seen and heard. Works on desktop, phone and wearables. Fully open source.

Trusted by 300,000+ professionals.


[![Discord](https://img.shields.io/discord/1192313062041067520?label=Discord&logo=discord&logoColor=white&style=for-the-badge)](http://discord.omi.me)&ensp;
[![GitHub Repo stars](https://img.shields.io/github/stars/BasedHardware/Omi?style=for-the-badge)](https://github.com/BasedHardware/Omi)&ensp;
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)

[Website](https://omi.me/) · [Docs](https://docs.omi.me/) · [Discord](http://discord.omi.me) · [Twitter](https://x.com/kodjima33) · [DeepWiki](https://deepwiki.com/BasedHardware/omi)

</div>

## Quick Start



```bash
git clone https://github.com/BasedHardware/omi.git && cd omi/desktop && ./run.sh --yolo
```

Builds the macOS app, connects to the cloud backend, and launches. No env files, no credentials, no local backend.

> **Requirements:** macOS 14+, [Xcode](https://developer.apple.com/xcode/) (includes Swift & code signing), [Node.js](https://nodejs.org/)

<details>
  <summary>Full Installation</summary>
  
For local development with the full backend stack:

1. Install prerequisites

```bash
xcode-select --install
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```

2. Clone and configure

```bash
git clone https://github.com/BasedHardware/omi.git
cd omi/desktop
cp Backend-Rust/.env.example Backend-Rust/.env
```

3. Build and run

```bash
./run.sh
```

See [desktop/README.md](desktop/README.md) for environment variables and credential setup.


### Mobile App

```bash
cd app && bash setup.sh ios    # or: bash setup.sh android
```

</details>

---

## Running Locally — No Cloud Required

This fork runs entirely on your own machine: no Firebase, no Deepgram, no OpenAI, no data leaving your network.

| Upstream service | Local replacement |
|-----------------|------------------|
| Firebase Auth | Local JWT (`AUTH_PROVIDER=local`) |
| Firestore | SQLite (`DB_PROVIDER=sqlite`) |
| Deepgram STT | faster-whisper (`STT_PROVIDER=local`) |
| OpenAI LLM | Ollama (`LLM_PROVIDER=ollama`) |
| Pinecone | Qdrant in Docker (`VECTOR_DB_PROVIDER=qdrant`) |

**Prerequisites:** macOS, [Docker Desktop](https://www.docker.com/products/docker-desktop/), [Ollama](https://ollama.com), Homebrew + conda (Miniforge) — the setup guide installs the last two.

**Quick start:**

```bash
# 1. Clone and configure
git clone https://github.com/gentbot/lomi.git && cd lomi

cp backend/.env.local.example backend/.env
# Edit backend/.env — change LOCAL_JWT_SECRET and ENCRYPTION_SECRET to unique values
# Generate: python3 -c "import secrets; print(secrets.token_hex(32))"

# 2. Pull a model
ollama pull qwen3:0.6b

# 3. Start everything
cd backend && bash start_local.sh
```

The API starts on `http://localhost:8088`. Browse to `/docs` for the Swagger UI.

**First time on a new machine** — follow the full guide: [`docs-local/SETUP_FROM_SCRATCH.md`](docs-local/SETUP_FROM_SCRATCH.md). Covers installing all prerequisites from scratch (~30–60 min).

**Day-to-day operations, connecting clients, troubleshooting:** [`README-LOCAL.md`](README-LOCAL.md)

---
<details>
  <summary>How it works</summary>


```
┌─────────────────────────────────────────────────────────┐
│                      Your Devices                       │
│                                                         │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ Omi      │  │ macOS App    │  │ Mobile App        │  │
│  │ Wearable │  │ (Swift/Rust) │  │ (Flutter)         │  │
│  └────┬─────┘  └──────┬───────┘  └────────┬──────────┘  │
│       │    BLE         │   HTTPS/WS        │             │
└───────┼────────────────┼───────────────────┼─────────────┘
        │                │                   │
        ▼                ▼                   ▼
┌─────────────────────────────────────────────────────────┐
│                    Omi Backend (Python)                  │
│                                                         │
│  ┌─────────┐  ┌──────────┐  ┌─────────┐  ┌──────────┐  │
│  │ Listen  │  │ Pusher   │  │ VAD     │  │ Diarizer │  │
│  │ (REST)  │  │ (WS)     │  │ (GPU)   │  │ (GPU)    │  │
│  └─────────┘  └──────────┘  └─────────┘  └──────────┘  │
│                                                         │
│  ┌─────────┐  ┌──────────┐  ┌─────────┐  ┌──────────┐  │
│  │ Deepgram│  │ Firestore│  │ Redis   │  │ LLMs     │  │
│  │ (STT)   │  │ (DB)     │  │ (Cache) │  │ (AI)     │  │
│  └─────────┘  └──────────┘  └─────────┘  └──────────┘  │
└─────────────────────────────────────────────────────────┘
```

| Component | Path | Stack |
|-----------|------|-------|
| **macOS app** | [`desktop/`](desktop/) | Swift, SwiftUI, Rust backend |
| Mobile app | [`app/`](app/) | Flutter (iOS & Android) |
| Backend API | [`backend/`](backend/) | Python, FastAPI, Firebase |
| Firmware | [`omi/`](omi/) | nRF, Zephyr, C |
| Omi Glass | [`omiGlass/`](omiGlass/) | ESP32-S3, C |
| SDKs | [`sdks/`](sdks/) | React Native, Swift, Python |
| AI Personas | [`web/personas-open-source/`](web/personas-open-source/) | Next.js |

</details>

## Documentation

### Local Mode (No Cloud)
- [Full Setup Guide](docs-local/SETUP_FROM_SCRATCH.md) — install everything from scratch on a new machine
- [Operations Runbook](docs-local/RUNBOOK.md) — clients, pin bridge, day-to-day ops
- [What Works Locally](docs-local/LOCAL_CAPABILITIES.md) — feature parity vs cloud
- [Upstream Sync Guide](docs-local/FORK_AND_MERGE_GUIDE.md) — keeping the fork current with BasedHardware/omi
- [Environment Variables](backend/.env.reference) — every config option documented

### Getting Started
- [Introduction](https://docs.omi.me/)
- [Quick Start Guide](https://docs.omi.me/quickstart)
- [macOS App Development](desktop/README.md)
- [Mobile App Setup](https://docs.omi.me/doc/developer/AppSetup)
- [Backend Setup](https://docs.omi.me/doc/developer/backend/Backend_Setup)
- [Contributing](https://docs.omi.me/doc/developer/Contribution)

### Building Apps
- [App Development Guide](https://docs.omi.me/doc/developer/apps/Introduction)
- [Example Apps](https://docs.omi.me/doc/developer/apps/examples/Github) — GitHub, Slack, OmiMentor
- [Audio Streaming Apps](https://docs.omi.me/doc/developer/apps/AudioStreaming)
- [Custom Chat Tools](https://docs.omi.me/doc/developer/apps/ChatTools)
- [Submit to App Store](https://docs.omi.me/doc/developer/apps/Submitting)

### API & SDKs
- [API Reference](https://docs.omi.me/api-reference/introduction) — REST endpoints for memories, conversations, action items
- [Python SDK](sdks/python/)
- [Swift SDK](sdks/swift/)
- [React Native SDK](sdks/react-native/)
- [MCP Server](mcp/) — Model Context Protocol integration

### Architecture
- [Backend Deep Dive](https://docs.omi.me/doc/developer/backend/backend_deepdive)
- [Transcription Pipeline](https://docs.omi.me/doc/developer/backend/transcription)
- [Chat System](https://docs.omi.me/doc/developer/backend/chat_system)
- [Audio Streaming Pipeline](https://docs.omi.me/doc/developer/backend/listen_pusher_pipeline)
- [BLE Protocol](https://docs.omi.me/doc/developer/Protocol)

- [Buy Omi](https://www.omi.me/pages/product)
- [Buy Omi Glass Dev Kit](https://www.omi.me/glass) — ESP32-S3, camera + audio
- [Open Source Hardware Designs](https://docs.omi.me/doc/hardware/consumer/electronics)
- [Buying Guide](https://docs.omi.me/doc/assembly/Buying_Guide)
- [Build the Device](https://docs.omi.me/doc/assembly/Build_the_device)
- [Flash Firmware](https://docs.omi.me/doc/get_started/Flash_device)
- [Integrate Your Wearable](https://docs.omi.me/doc/integrations)
- [Hardware Specs](https://docs.omi.me/doc/hardware/DevKit2)

## License

MIT — see [LICENSE](LICENSE)

# Unfixable Features — Local Deployment

These are features from `COMPLETED_UPDATES.md §15` that **cannot be made functional in a fully local, zero-cloud setup** regardless of how much code is written. Each item depends on an external party — a licensed financial network, a platform-operated push channel, a third-party SaaS API, or Apple/Google hardware infrastructure — that cannot be self-hosted or replaced with a local equivalent inside this codebase.

This document exists to prevent future effort being spent chasing these. If a feature here appears in a backlog or gap tracker, the right answer is to document the limitation, not to open a ticket.

---

## How to read this document

Items are grouped by the type of external dependency. Within each group, the **Why it's unfixable** section explains the specific blocker — not just "requires a key," but what the key unlocks and why no local substitute exists.

Items that are merely *not yet implemented* but could in principle run locally (Piper TTS, Memgraph, local SMTP, Redis via Docker) are **not listed here**. Those belong in the implementation backlog.

---

## 1. Regulated Financial Infrastructure

### Stripe / payments

**Feature:** Subscription billing, per-seat pricing, usage metering, payment method capture.

**Why it's unfixable:** Stripe is a licensed payment facilitator. Processing real card transactions requires a contract with Visa/Mastercard and compliance with PCI-DSS. There is no self-hosted equivalent — what exists (e.g., open-source billing UIs) still delegate card authorization to a cloud processor. The integration is exclusively in `routers/payment.py`, which requires `STRIPE_API_KEY`. No local simulation exists and building one would not be useful — it would not test real payment flows.

**What it affects:** Any Omi subscription tier gating, premium feature checks, usage caps enforced by payment status.

**What works locally instead:** The backend simply skips all Stripe guards when `STRIPE_API_KEY` is absent (fail-open). All features that would be subscription-gated are available unconditionally in local mode.

---

## 2. Mobile Push Notification Channels

### Push notifications (iOS / Android)

**Feature:** The app receives proactive alerts about completed conversations, extracted memories, reminders, and agent messages when the app is in the background.

**Why it's unfixable:** iOS push notifications route through Apple Push Notification service (APNs). Android uses Firebase Cloud Messaging (FCM). Both are operated by Apple and Google respectively. A device's push token is issued by APNs/FCM and is only valid through those networks — it is not possible to deliver a push notification to a real device without a connection to Apple's or Google's servers. There is no self-hosted drop-in: services like ntfy or Gotify only work if the app is specifically built to register with them instead, which requires a custom fork of the Omi app.

**What it affects:** All background alerts and proactive notifications the mobile app relies on.

**What works locally instead:** The WebSocket event system (`/ws?token=...`) delivers real-time events to the app while it is foreground and connected. Memory-created and action-item events are already pushed this way. Background delivery is simply absent.

---

## 3. Telephony / PSTN

### Twilio phone calls

**Feature:** Users can call an Omi-hosted number; the conversation is transcribed and stored.

**Why it's unfixable:** Receiving a PSTN phone call requires a carrier-issued phone number and SIP trunk to the public telephone network. Twilio owns this infrastructure. Running a local SIP server (Asterisk, FreeSWITCH) would still require purchasing a DID (phone number) from a carrier and paying for PSTN interconnect — making it cloud-dependent by definition. The feature is specifically engineered around Twilio's TwiML callback architecture.

**What it affects:** The phone call transcription flow in `routers/phone_calls.py`.

**What works locally instead:** Nothing. This feature requires a real phone network. Not applicable to a LAN-only deployment.

---

## 4. Third-Party OAuth Integrations

These features all require registering an OAuth application with the respective platform and obtaining client credentials. The credentials are platform-specific, tied to a verified developer account, and grant access only to that platform's servers. No amount of local code can substitute for the authorization server at the other end.

### Google / Apple sign-in

**Why it's unfixable:** OAuth 2.0 ID token issuance happens on Google's and Apple's authorization servers. When a user taps "Sign in with Google," their device contacts Google, Google authenticates the user, and Google returns a signed ID token. The backend verifies this token against Google's public keys. There is no way to forge or locally issue a token that claims to come from Google or Apple — the signature would fail validation. Local JWT auth (`AUTH_PROVIDER=local`) is already the replacement for this use case.

### Google Calendar & Google Drive integrations

**Why it's unfixable:** Accessing a user's Calendar or Drive requires that the user authorize the Omi OAuth application registered in Google Cloud Console. The OAuth consent screen, redirect URIs, and token issuance all happen on Google's servers. Even if Omi's credentials were available, they would only work for users who have a Google account and complete the OAuth flow against google.com.

### Notion integration

**Why it's unfixable:** Same structure — Notion's OAuth server issues tokens for Notion workspaces. Requires Notion app credentials and a user who completes the OAuth flow on Notion's web UI.

### Whoop integration

**Why it's unfixable:** Whoop health data (recovery, HRV, sleep) is stored on Whoop's cloud servers and accessible only via their OAuth-protected API. The wearable does not expose data locally; it syncs to Whoop's cloud only.

### Twitter / X integration

**Why it's unfixable:** Twitter/X's API requires app credentials issued by X Corp. API access requires an approved developer account and tier. X Corp has sole control over which apps receive tokens.

---

## 5. Cloud AI Services (Specific Provider Paths)

These are features that use a specific external AI provider. In some cases a local alternative already exists (Whisper replaces Deepgram); in others no equivalent is wired yet.

### Deepgram STT (the Deepgram path specifically)

**Why it's unfixable:** Deepgram's API (`STT_PROVIDER=deepgram`) sends audio to Deepgram's cloud servers for transcription. This path is unfixable without a Deepgram API key and therefore cannot be validated locally.

**What works locally instead:** `STT_PROVIDER=local` uses faster-whisper and is fully functional. Deepgram as a provider is simply not used in local mode.

### ElevenLabs TTS (the ElevenLabs path specifically)

**Why it's unfixable:** ElevenLabs synthesis (`/v2/tts/synthesize`) sends text to ElevenLabs' cloud API and streams back audio. Requires `ELEVENLABS_API_KEY`. The service is proprietary and cannot be self-hosted.

**What works locally instead:** `routers_local/tts.py` returns 501. A local alternative (Piper TTS, macOS `say`) could be wired here and is tracked in the implementation backlog — that is fixable, just not yet done. The ElevenLabs path itself is permanently cloud-only.

### Perplexity web search (the Perplexity path specifically)

**Why it's unfixable:** The RAG chat web-search tool calls Perplexity's API to retrieve real-time internet results. Requires `PERPLEXITY_API_KEY` and Perplexity's hosted index. There is no self-hosted Perplexity.

**What works locally instead:** A SearXNG integration is tracked in `LOCAL_IMPLEMENTATION_PLAN.md §G` as a local replacement and is fixable. The Perplexity path itself is permanently cloud-only.

### LangSmith tracing

**Why it's unfixable:** LangSmith is a SaaS observability and prompt-management platform operated by LangChain, Inc. The `LANGSMITH_API_KEY` and `LANGSMITH_ENDPOINT` both point to `smith.langchain.com`. There is no self-hosted LangSmith server. Open-source alternatives (LangFuse, Helicone) exist but would require re-integrating their SDKs — they are not drop-in replacements for the existing LangSmith calls.

**What works locally instead:** `LANGSMITH_TRACING=false` (the default). All LLM calls function normally; trace data is simply not collected.

---

## 6. Google Cloud Infrastructure

### GCS storage buckets (`BUCKET_SPEECH_PROFILES`, `BUCKET_BACKUPS`, `BUCKET_PLUGINS_LOGOS`)

**Why it's unfixable:** These buckets exist in a specific Google Cloud project and are accessed using a `GOOGLE_APPLICATION_CREDENTIALS` service account JSON. The bucket names, IAM policies, and object paths are hardcoded to Omi's production project. Even if GCS were replaced with an S3-compatible store (MinIO), every upload/download call would need to be re-targeted to the new endpoint — that is a code change, not a configuration change, and it is tracked as a future option in the implementation backlog rather than an unfixable constraint.

**What works locally instead:** Audio backup, speech profile storage, and plugin logo hosting are unavailable. This has no impact on transcription, storage, or chat in local mode.

### HuggingFace gated models

**Why it's unfixable:** Some models on HuggingFace (e.g., pyannote speaker diarization, certain LLaMA checkpoints) require accepting a usage agreement via a logged-in HuggingFace account. The `HUGGINGFACE_TOKEN` env var authenticates the download request. Without an approved token the download is rejected by HuggingFace's servers. An account is free but registration and agreement acceptance cannot be automated or faked.

**What works locally instead:** All models used in the default local configuration — `faster-whisper`, `sentence-transformers/all-MiniLM-L6-v2`, all standard Ollama models — are publicly downloadable with no token required. Only gated models are affected.

---

## 7. Requires Custom iOS/macOS Build (Apple Developer Account)

### iOS Flutter app URL redirect (`API_BASE_URL`)

**Why it can't be done without the user:** Redirecting the iOS app to the local backend requires editing `app/.dev.env`, setting `API_BASE_URL=http://<lan-ip>:8088/`, and rebuilding the app with `flutter build ios`. This requires:
- An Apple Developer Program membership ($99/year) to sign the build
- Xcode installed on a Mac
- The Flutter + Dart toolchain installed and configured

No code change in this repository can substitute for the build step — the compiled app binary contains the URL that was set at build time.

**What works locally instead:** The macOS Desktop app redirects with a single env var (`OMI_PYTHON_API_URL`), requiring no build. The `pin_bridge.py` script connects directly to the local backend. Full instructions in `PIN_LOCAL_GUIDE.md §5`.

### iOS App Transport Security (ATS) exception for plain HTTP

**Why it can't be done without the user:** ATS is enforced by the iOS operating system. Allowing plain HTTP connections to a specific LAN IP requires adding a `NSExceptionAllowsInsecureHTTPLoads` entry to `ios/Runner/Info.plist` and rebuilding the app. Same Apple Developer + Xcode requirements as above. The `Info.plist` change itself is a one-line edit, but it only takes effect after a new signed build is installed on the device.

**What works locally instead:** The HTTPS / TLS plan (`IMPLEMENTATION_PLAN.md PLAN-1`) using Caddy eliminates the need for this exception entirely by providing a trusted local certificate.

---

## Summary table

| Feature | Blocking party | Local alternative exists? |
|---------|---------------|--------------------------|
| Stripe payments | Visa/Mastercard network via Stripe | No — all features unlock in local mode anyway |
| iOS/Android push notifications | Apple APNs / Google FCM | WebSocket events (foreground only) |
| Twilio phone calls | PSTN carrier network via Twilio | No — not applicable on LAN |
| Google/Apple OAuth sign-in | Google / Apple auth servers | Yes — local JWT (`AUTH_PROVIDER=local`) |
| Google Calendar/Drive | Google OAuth + API servers | No |
| Notion | Notion OAuth + API servers | No |
| Whoop | Whoop cloud API | No |
| Twitter/X | X Corp API | No |
| Deepgram STT | Deepgram cloud API | Yes — faster-whisper (`STT_PROVIDER=local`) |
| ElevenLabs TTS | ElevenLabs cloud API | Piper TTS (not yet wired) |
| Perplexity web search | Perplexity cloud API | SearXNG (not yet wired) |
| LangSmith tracing | LangChain, Inc. SaaS | No — tracing simply disabled |
| GCS storage buckets | Google Cloud project | MinIO (would require re-integration) |
| HuggingFace gated models | HuggingFace account agreement | Yes — only affects gated models |
| iOS app URL redirect | Apple Developer + Xcode build | macOS Desktop app (env var only) |
| iOS ATS exception | Apple OS enforcement + signed build | HTTPS/TLS via Caddy (PLAN-1) |

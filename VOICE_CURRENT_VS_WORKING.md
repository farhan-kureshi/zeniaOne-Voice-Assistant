# VOICE CURRENT VS LAST WORKING

| Component | Last Working Implementation (Inferred) | Current Implementation | Changed? | Potential Effect |
| :--- | :--- | :--- | :--- | :--- |
| **Welcome playback** | udio/mpeg Blob URL | udio/mpeg Blob URL | Restored | Resolves PCM corruption, plays correctly. |
| **Microphone startup** | Waited for udio.onended | Starts concurrently with TTS | Yes | Prevents stalled WebSocket if TTS fails, but can race with udio.play() user-gesture context. |
| **AudioContext** | Standard init | Standard init | No | N/A |
| **WebSocket** | Opens after mic access | Opens after mic access | No | N/A |
| **STT** | Base64 strings sent via WS | Base64 strings sent via WS | No | N/A |
| **Voice state** | Listening triggered by udio.onended | Listening triggered by ws.onopen and udio.onended | Yes | UI indicates "Listening" prematurely during audio fetch/playback. |
| **Session token** | StrictMode token check | StrictMode token check | No | Valid protection against duplicate mounts. |
| **isProcessingRef** | Prevents concurrent loops | Prevents concurrent loops | No | Standard behavior. |
| **TTS transport** | /speak returns audio Blob | /speak returns Base64 audio | No | Standard behavior. |
| **Response playback** | Binary WS messages | Binary WS messages | No | N/A |
| **Cleanup** | eleaseAll resets refs | eleaseAll resets refs | No | N/A |
| **StrictMode** | Handles double-mount | Handles double-mount | No | Safe initialization. |
| **Duplicate effects** | None observed | None observed | No | N/A |

# Alvarez ✦ Universal Terminal HUD & Vibe Companion for Antigravity CLI

**Alvarez** is a high-performance, cross-platform terminal HUD, dual quota monitor, interactive audio visualizer, background stream manager, and live AI thought stream processor engineered for Google Antigravity CLI vibe coders.

---

## ⚡ Features
- 📊 **Dual Quota & Credit Monitor**: Real-time tracking of Gemini model quotas, Claude/GPT 3P quotas, and remaining credits.
- 🎵 **5-Row ANSI Audio Visualizer**: Responsive 60FPS frequency spectrum visualizer powered by FFT.
- 📻 **Dynamic Audio Stream Manager**: Non-repeating shuffle deck for local audio streams, Spotify, and YouTube streams. Any subfolder created in `~/Streams/` is automatically discovered.
- 💬 **Live Thought Processor**: Color-coded live stream of AI thoughts, tool execution introspection (Read/Edit/Exec), and step counters.
- 💻 **Hardware Telemetry**: Sub-millisecond CPU, RAM, Disk (with root filesystem hard lock protection), and GPU telemetry across Linux, macOS, and Windows.

---

## 🚀 Installation

### Quick Install (Linux & macOS)
```bash
git clone https://github.com/sirgonyat/alvarez.git
cd alvarez
./install.sh
```

### Python Package Install (All Platforms)
```bash
pip install -e .
```

---

## 🎮 Usage

Launch the full interactive HUD & thought stream:
```bash
alvarez
```

Control audio streams independently:
```bash
alvarez-stream Popular       # Play custom ~/Streams/Popular stream
alvarez-stream synth         # Play Synthwave rotation
alvarez-stream ambient       # Play Ambient rotation
alvarez-stream lofi          # Play Lofi radio
alvarez-stream deep          # Play Deep Space radio
alvarez-stream stop          # Stop playback
alvarez-stream status        # Check current playback status
alvarez-stream next          # Skip track
```

---

## ⌨️ Hotkeys in HUD (`alvarez`)
- **`S`**: Skip track
- **`V`**: Cycle stream vibe category
- **`P` / `Space`**: Toggle play/pause stream
- **`↑` / `↓`**: Scroll thought stream buffer
- **`Q`**: Exit HUD

---

## 🛡️ Storage Safety
Alvarez strictly respects storage boundary rules. Disk telemetry is hard-locked to the host system's primary root mount (`/` or `C:\`) and will never mount or query secondary OS partitions (such as `/dev/nvme0n1*`).

---

## 📄 License
MIT License. Created by Sir Gonyat & Antigravity Engineering Pair.

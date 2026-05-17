#!/usr/bin/env python3
"""
Free Live TV Viewer Builder
Fetches public M3U playlists from iptv-org and generates a self-contained HTML viewer.
"""

import urllib.request
import json
import re
import sys
import os
from datetime import datetime

# Public M3U playlist sources (iptv-org community project)
PLAYLIST_SOURCES = [
    {
        "name": "USA Channels",
        "url": "https://iptv-org.github.io/iptv/countries/us.m3u",
    },
    {
        "name": "News Channels",
        "url": "https://iptv-org.github.io/iptv/categories/news.m3u",
    },
]

def fetch_m3u(url, timeout=15):
    """Fetch M3U playlist from URL."""
    print(f"  Fetching: {url}")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; IPTVViewer/1.0)"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  Warning: Failed to fetch {url}: {e}")
        return None

def parse_m3u(content):
    """Parse M3U content into list of channel dicts."""
    channels = []
    if not content or not content.strip().startswith("#EXTM3U"):
        return channels

    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF"):
            meta = {
                "name": "Unknown Channel",
                "logo": "",
                "group": "General",
                "language": "",
                "country": "",
                "url": "",
            }
            # Parse attributes from #EXTINF line
            attr_matches = re.findall(r'([\w-]+)="([^"]*)"', line)
            for key, val in attr_matches:
                k = key.lower()
                if k == "tvg-name":
                    meta["name"] = val.strip() or meta["name"]
                elif k == "tvg-logo":
                    meta["logo"] = val.strip()
                elif k == "group-title":
                    meta["group"] = val.strip() or "General"
                elif k == "tvg-language":
                    meta["language"] = val.strip()
                elif k == "tvg-country":
                    meta["country"] = val.strip()

            # Fallback: grab display name after last comma
            comma_idx = line.rfind(",")
            if comma_idx != -1:
                display = line[comma_idx + 1:].strip()
                if display and meta["name"] == "Unknown Channel":
                    meta["name"] = display

            # Next non-comment line should be the stream URL
            j = i + 1
            while j < len(lines) and lines[j].strip().startswith("#"):
                j += 1
            if j < len(lines):
                url = lines[j].strip()
                if url and (url.startswith("http") or url.startswith("rtmp")):
                    meta["url"] = url
                    i = j
            if meta["url"]:
                channels.append(meta)
        i += 1
    return channels

def deduplicate(channels):
    """Remove duplicate channels by URL."""
    seen_urls = set()
    seen_names = set()
    unique = []
    for ch in channels:
        key = ch["url"]
        name_key = ch["name"].lower().strip()
        if key not in seen_urls and name_key not in seen_names:
            seen_urls.add(key)
            seen_names.add(name_key)
            unique.append(ch)
    return unique

def filter_streamable(channels):
    """Keep only HLS (.m3u8) and MP4 streams (browser-playable). Skip RTMP etc."""
    streamable = []
    for ch in channels:
        url = ch["url"].lower()
        if ".m3u8" in url or url.endswith(".mp4") or "playlist" in url:
            streamable.append(ch)
    return streamable

def sort_channels(channels):
    """Sort by group then name."""
    return sorted(channels, key=lambda c: (c["group"].lower(), c["name"].lower()))

def build_channel_json(channels):
    """Convert channel list to JSON-serializable structure."""
    return [
        {
            "name": c["name"],
            "url": c["url"],
            "logo": c["logo"],
            "group": c["group"] or "General",
            "language": c["language"],
            "country": c["country"],
        }
        for c in channels
    ]

def generate_html(channels_json, output_path):
    """Generate self-contained HTML viewer."""
    data_str = json.dumps(channels_json, ensure_ascii=False)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    count = len(channels_json)

    # Collect unique groups for filter UI
    groups = sorted(set(c["group"] for c in channels_json if c["group"]))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Free Live TV</title>
<!-- hls.js for HLS stream playback in browsers -->
<script src="https://cdn.jsdelivr.net/npm/hls.js@latest/dist/hls.min.js"></script>
<style>
  :root {{
    --bg: #0a0a0f;
    --panel: #12121a;
    --card: #1a1a26;
    --accent: #00e5ff;
    --accent2: #7b5ea7;
    --text: #e0e0f0;
    --muted: #6060a0;
    --border: #2a2a40;
    --active: #00e5ff22;
    --error: #ff4466;
    --green: #00ff88;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{ height: 100%; background: var(--bg); color: var(--text);
    font-family: 'Courier New', 'Lucida Console', monospace; overflow: hidden; }}

  /* ── Layout ── */
  #app {{ display: grid; grid-template-rows: 48px 1fr; grid-template-columns: 300px 1fr;
    height: 100vh; gap: 0; }}
  #topbar {{ grid-column: 1/-1; background: var(--panel); border-bottom: 1px solid var(--border);
    display: flex; align-items: center; padding: 0 16px; gap: 16px; z-index: 10; }}
  #sidebar {{ background: var(--panel); border-right: 1px solid var(--border);
    display: flex; flex-direction: column; overflow: hidden; }}
  #main {{ display: flex; flex-direction: column; overflow: hidden; background: #000; }}

  /* ── Topbar ── */
  .logo {{ font-size: 18px; font-weight: bold; color: var(--accent);
    letter-spacing: 3px; text-transform: uppercase; white-space: nowrap; }}
  .logo span {{ color: var(--accent2); }}
  .meta {{ font-size: 11px; color: var(--muted); flex: 1; }}
  #search {{ background: var(--card); border: 1px solid var(--border); color: var(--text);
    padding: 6px 12px; border-radius: 4px; font-family: inherit; font-size: 12px;
    width: 200px; outline: none; transition: border-color .2s; }}
  #search:focus {{ border-color: var(--accent); }}
  #search::placeholder {{ color: var(--muted); }}
  #status-dot {{ width: 8px; height: 8px; border-radius: 50%; background: var(--muted);
    flex-shrink: 0; transition: background .3s; }}
  #status-dot.live {{ background: var(--green); box-shadow: 0 0 8px var(--green); animation: pulse 2s infinite; }}
  #status-dot.error {{ background: var(--error); }}
  @keyframes pulse {{ 0%,100% {{ opacity:1; }} 50% {{ opacity:.4; }} }}
  #status-text {{ font-size: 11px; color: var(--muted); }}

  /* ── Group filter ── */
  #group-bar {{ display: flex; gap: 4px; padding: 8px 10px; overflow-x: auto;
    border-bottom: 1px solid var(--border); flex-shrink: 0; scrollbar-width: none; }}
  #group-bar::-webkit-scrollbar {{ display: none; }}
  .group-btn {{ background: transparent; border: 1px solid var(--border); color: var(--muted);
    padding: 3px 10px; border-radius: 20px; cursor: pointer; font-size: 10px;
    font-family: inherit; white-space: nowrap; transition: all .15s; }}
  .group-btn:hover {{ border-color: var(--accent); color: var(--accent); }}
  .group-btn.active {{ background: var(--accent); border-color: var(--accent); color: #000;
    font-weight: bold; }}

  /* ── Channel list ── */
  #channel-count {{ padding: 6px 12px; font-size: 10px; color: var(--muted);
    border-bottom: 1px solid var(--border); flex-shrink: 0; }}
  #channel-list {{ flex: 1; overflow-y: auto; scrollbar-width: thin;
    scrollbar-color: var(--border) transparent; }}
  #channel-list::-webkit-scrollbar {{ width: 4px; }}
  #channel-list::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 2px; }}
  .ch-item {{ display: flex; align-items: center; gap: 10px; padding: 8px 12px;
    cursor: pointer; border-bottom: 1px solid #1a1a2600; transition: background .1s; }}
  .ch-item:hover {{ background: var(--card); }}
  .ch-item.active {{ background: var(--active); border-left: 2px solid var(--accent); }}
  .ch-logo {{ width: 36px; height: 27px; object-fit: contain; border-radius: 3px;
    background: var(--card); flex-shrink: 0; }}
  .ch-logo-placeholder {{ width: 36px; height: 27px; background: var(--card);
    border-radius: 3px; display: flex; align-items: center; justify-content: center;
    font-size: 14px; flex-shrink: 0; }}
  .ch-info {{ flex: 1; min-width: 0; }}
  .ch-name {{ font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .ch-group {{ font-size: 10px; color: var(--muted); margin-top: 2px; }}

  /* ── Player ── */
  #player-wrap {{ flex: 1; position: relative; background: #000; }}
  video {{ width: 100%; height: 100%; display: block; background: #000; }}
  #overlay {{ position: absolute; inset: 0; display: flex; flex-direction: column;
    align-items: center; justify-content: center; gap: 12px; background: #00000088; }}
  #overlay.hidden {{ display: none; }}
  .overlay-icon {{ font-size: 48px; }}
  .overlay-title {{ font-size: 14px; color: var(--accent); letter-spacing: 2px; }}
  .overlay-sub {{ font-size: 11px; color: var(--muted); text-align: center; max-width: 320px; }}
  #loading-bar {{ position: absolute; bottom: 0; left: 0; height: 2px;
    background: var(--accent); width: 0; transition: width .3s; }}

  /* ── Bottom info strip ── */
  #now-playing {{ background: var(--panel); border-top: 1px solid var(--border);
    padding: 6px 16px; display: flex; align-items: center; gap: 12px; flex-shrink: 0; }}
  #np-name {{ font-size: 13px; color: var(--accent); flex: 1;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  #np-group {{ font-size: 10px; color: var(--muted); }}
  #np-url {{ font-size: 9px; color: var(--border); flex: 2;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}

  /* ── Error toast ── */
  #toast {{ position: fixed; bottom: 60px; right: 20px; background: var(--error);
    color: #fff; padding: 8px 16px; border-radius: 4px; font-size: 12px;
    opacity: 0; transition: opacity .3s; pointer-events: none; z-index: 100; }}
  #toast.show {{ opacity: 1; }}

  /* ── Retry btn ── */
  .retry-btn {{ background: transparent; border: 1px solid var(--accent); color: var(--accent);
    padding: 6px 18px; border-radius: 3px; cursor: pointer; font-family: inherit;
    font-size: 12px; letter-spacing: 1px; transition: all .15s; }}
  .retry-btn:hover {{ background: var(--accent); color: #000; }}
</style>
</head>
<body>
<div id="app">

  <!-- Topbar -->
  <div id="topbar">
    <div class="logo">FREE<span>.</span>TV</div>
    <div class="meta">▸ {count} channels · built {timestamp}</div>
    <input id="search" type="search" placeholder="Search channels…" autocomplete="off">
    <div id="status-dot"></div>
    <div id="status-text">idle</div>
  </div>

  <!-- Sidebar -->
  <div id="sidebar">
    <div id="group-bar">
      <button class="group-btn active" data-group="ALL">ALL</button>
      {''.join(f'<button class="group-btn" data-group="{g}">{g}</button>' for g in groups)}
    </div>
    <div id="channel-count"></div>
    <div id="channel-list"></div>
  </div>

  <!-- Main -->
  <div id="main">
    <div id="player-wrap">
      <video id="video" controls playsinline></video>
      <div id="overlay">
        <div class="overlay-icon">📡</div>
        <div class="overlay-title">FREE.TV</div>
        <div class="overlay-sub">Select a channel from the list to start streaming.<br>
          Uses HLS — streams play natively in supported browsers.</div>
      </div>
      <div id="loading-bar"></div>
    </div>
    <div id="now-playing">
      <div id="np-name">No channel selected</div>
      <div id="np-group"></div>
      <div id="np-url"></div>
    </div>
  </div>

</div>
<div id="toast"></div>

<script>
const CHANNELS = {data_str};

let hls = null;
let currentIdx = -1;
let activeGroup = "ALL";
let filtered = [...CHANNELS];

// ── DOM refs ──
const video      = document.getElementById("video");
const list       = document.getElementById("channel-list");
const countEl    = document.getElementById("channel-count");
const searchEl   = document.getElementById("search");
const overlay    = document.getElementById("overlay");
const statusDot  = document.getElementById("status-dot");
const statusText = document.getElementById("status-text");
const loadingBar = document.getElementById("loading-bar");
const npName     = document.getElementById("np-name");
const npGroup    = document.getElementById("np-group");
const npUrl      = document.getElementById("np-url");
const toast      = document.getElementById("toast");

// ── Group filter ──
document.getElementById("group-bar").addEventListener("click", e => {{
  const btn = e.target.closest(".group-btn");
  if (!btn) return;
  document.querySelectorAll(".group-btn").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
  activeGroup = btn.dataset.group;
  applyFilters();
}});

searchEl.addEventListener("input", applyFilters);

function applyFilters() {{
  const q = searchEl.value.toLowerCase().trim();
  filtered = CHANNELS.filter(c => {{
    const groupMatch = activeGroup === "ALL" || c.group === activeGroup;
    const searchMatch = !q || c.name.toLowerCase().includes(q) || c.group.toLowerCase().includes(q);
    return groupMatch && searchMatch;
  }});
  renderList();
}}

// ── Render channel list ──
function renderList() {{
  countEl.textContent = filtered.length + " channel" + (filtered.length !== 1 ? "s" : "");
  list.innerHTML = "";
  filtered.forEach((ch, i) => {{
    const div = document.createElement("div");
    div.className = "ch-item" + (ch === CHANNELS[currentIdx] ? " active" : "");
    div.dataset.idx = CHANNELS.indexOf(ch);

    const logoEl = ch.logo
      ? `<img class="ch-logo" src="${{ch.logo}}" alt="" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">`
        + `<div class="ch-logo-placeholder" style="display:none">📺</div>`
      : `<div class="ch-logo-placeholder">📺</div>`;

    div.innerHTML = logoEl +
      `<div class="ch-info">
        <div class="ch-name">${{escHtml(ch.name)}}</div>
        <div class="ch-group">${{escHtml(ch.group)}}</div>
      </div>`;
    div.addEventListener("click", () => playChannel(parseInt(div.dataset.idx)));
    list.appendChild(div);
  }});
}}

function escHtml(s) {{
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}}

// ── Play channel ──
function playChannel(idx) {{
  const ch = CHANNELS[idx];
  if (!ch) return;
  currentIdx = idx;

  // Highlight in list
  document.querySelectorAll(".ch-item").forEach(el => {{
    el.classList.toggle("active", parseInt(el.dataset.idx) === idx);
  }});

  overlay.classList.add("hidden");
  npName.textContent  = ch.name;
  npGroup.textContent = ch.group;
  npUrl.textContent   = ch.url;
  setStatus("loading", "connecting…");
  loadingBar.style.width = "30%";

  if (hls) {{ hls.destroy(); hls = null; }}
  video.pause();
  video.removeAttribute("src");
  video.load();

  const url = ch.url;

  if (url.includes(".m3u8") || url.includes("m3u8")) {{
    if (Hls.isSupported()) {{
      hls = new Hls({{ enableWorker: true, lowLatencyMode: false,
        maxBufferLength: 30, maxMaxBufferLength: 60 }});
      hls.loadSource(url);
      hls.attachMedia(video);
      hls.on(Hls.Events.MANIFEST_PARSED, () => {{
        video.play().catch(() => {{}});
        loadingBar.style.width = "100%";
        setTimeout(() => {{ loadingBar.style.width = "0"; }}, 600);
      }});
      hls.on(Hls.Events.ERROR, (evt, data) => {{
        if (data.fatal) {{
          setStatus("error", "stream error");
          showOverlayError(ch.name);
        }}
      }});
    }} else if (video.canPlayType("application/vnd.apple.mpegurl")) {{
      // Safari native HLS
      video.src = url;
      video.play().catch(() => {{}});
    }} else {{
      setStatus("error", "HLS not supported");
      showToast("Your browser doesn't support HLS playback.");
    }}
  }} else {{
    // Direct MP4 / other
    video.src = url;
    video.play().catch(() => {{}});
  }}

  video.onplaying = () => setStatus("live", "live");
  video.onerror   = () => {{ setStatus("error", "error"); showOverlayError(ch.name); }};
  video.onwaiting = () => setStatus("loading", "buffering…");
}}

function showOverlayError(name) {{
  overlay.classList.remove("hidden");
  overlay.innerHTML = `
    <div class="overlay-icon">⚠️</div>
    <div class="overlay-title">Stream Unavailable</div>
    <div class="overlay-sub">${{escHtml(name)}}<br>
      This stream may be offline or geo-restricted.<br>Try another channel.</div>
    <button class="retry-btn" onclick="playChannel(${{currentIdx}})">↻ Retry</button>
  `;
}}

function setStatus(state, label) {{
  statusDot.className = "status-dot";
  if (state === "live")    statusDot.classList.add("live");
  if (state === "error")   statusDot.classList.add("error");
  statusText.textContent = label;
}}

function showToast(msg) {{
  toast.textContent = msg;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 3500);
}}

// ── Keyboard nav ──
document.addEventListener("keydown", e => {{
  if (e.target === searchEl) return;
  if (e.key === "ArrowUp" || e.key === "ArrowDown") {{
    e.preventDefault();
    const items = [...document.querySelectorAll(".ch-item")];
    const active = items.findIndex(el => el.classList.contains("active"));
    let next = e.key === "ArrowDown" ? active + 1 : active - 1;
    if (next < 0) next = items.length - 1;
    if (next >= items.length) next = 0;
    if (items[next]) {{
      items[next].click();
      items[next].scrollIntoView({{ block: "nearest" }});
    }}
  }}
}});

// ── Init ──
applyFilters();
</script>
</body>
</html>"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return output_path

def main():
    output_path = "/mnt/user-data/outputs/free_tv.html"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    all_channels = []
    for source in PLAYLIST_SOURCES:
        print(f"\n[→] {source['name']}")
        content = fetch_m3u(source["url"])
        if content:
            channels = parse_m3u(content)
            print(f"  Parsed: {len(channels)} channels")
            all_channels.extend(channels)
        else:
            print(f"  Skipped (fetch failed)")

    print(f"\n[→] Total raw channels: {len(all_channels)}")

    all_channels = deduplicate(all_channels)
    print(f"[→] After deduplicate: {len(all_channels)}")

    all_channels = filter_streamable(all_channels)
    print(f"[→] After HLS/MP4 filter: {len(all_channels)}")

    all_channels = sort_channels(all_channels)

    channels_json = build_channel_json(all_channels)

    print(f"\n[→] Generating HTML viewer…")
    generate_html(channels_json, output_path)
    print(f"[✓] Done! → {output_path}")
    print(f"    {len(channels_json)} channels embedded.")
    print(f"\n    Open free_tv.html in your browser to watch.")

if __name__ == "__main__":
    main()

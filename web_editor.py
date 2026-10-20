import os
import sys
import json
import urllib.parse
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler

PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "output"

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ToneDeaf - Joysound 橫向大音程條與防殘影旋律預覽系統</title>
  <style>
    :root {
      --bg: #070a12;
      --panel-bg: #0e1526;
      --card-bg: #141c2e;
      --card-hover: #1c2740;
      --text: #f8fafc;
      --text-muted: #8494ab;
      --accent: #38bdf8;
      --accent-glow: rgba(56, 189, 248, 0.5);
      --gold: #fbbf24;
      --gold-glow: rgba(251, 191, 36, 0.6);
      --border: #1e293b;
      --canvas-height: 540px;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang TC", "Microsoft JhengHei", sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      overflow-x: hidden;
      user-select: none;
    }

    header {
      background: rgba(14, 21, 38, 0.95);
      backdrop-filter: blur(16px);
      border-bottom: 1px solid var(--border);
      padding: 10px 20px;
      position: sticky;
      top: 0;
      z-index: 100;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 1.15rem;
      font-weight: 800;
      color: var(--accent);
      letter-spacing: -0.3px;
    }
    .brand-badge {
      font-size: 0.65rem;
      background: linear-gradient(135deg, #0284c7, #38bdf8);
      color: #000;
      font-weight: 800;
      padding: 2px 6px;
      border-radius: 4px;
      text-transform: uppercase;
    }

    .controls {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }

    .ctrl-group {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 0.82rem;
      color: var(--text-muted);
    }

    select, button, input[type="range"] {
      background: #141d30;
      color: var(--text);
      border: 1px solid var(--border);
      padding: 5px 10px;
      border-radius: 6px;
      font-size: 0.85rem;
      cursor: pointer;
      outline: none;
      transition: all 0.2s;
    }
    select:hover, button:hover {
      border-color: var(--accent);
      background: var(--card-hover);
    }

    .sync-controller {
      display: flex;
      align-items: center;
      gap: 4px;
      background: rgba(20, 29, 48, 0.7);
      padding: 3px 8px;
      border-radius: 6px;
      border: 1px solid var(--border);
    }
    .sync-val {
      font-family: monospace;
      font-size: 0.82rem;
      color: var(--accent);
      font-weight: bold;
      min-width: 50px;
      text-align: center;
    }
    .btn-step {
      padding: 1px 6px;
      font-size: 0.75rem;
      border-radius: 4px;
    }

    /* 主舞台區域 */
    main {
      flex: 1;
      display: flex;
      flex-direction: column;
      position: relative;
      padding: 12px 18px;
      gap: 12px;
      max-width: 1680px;
      margin: 0 auto;
      width: 100%;
    }

    .collapsible-section {
      background: var(--panel-bg);
      border: 1px solid var(--border);
      border-radius: 10px;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      transition: all 0.25s ease;
    }
    .section-header {
      background: rgba(19, 28, 48, 0.75);
      padding: 8px 14px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 1px solid rgba(51, 65, 85, 0.3);
      cursor: pointer;
      user-select: none;
      flex-wrap: wrap;
      gap: 8px;
    }
    .section-header:hover {
      background: rgba(30, 41, 59, 0.9);
    }
    .section-title {
      font-size: 0.88rem;
      font-weight: 700;
      color: var(--accent);
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .section-toggle-btn {
      font-size: 0.75rem;
      color: var(--text-muted);
      background: transparent;
      border: 1px solid var(--border);
      padding: 2px 8px;
      border-radius: 4px;
    }
    .collapsible-content {
      display: flex;
      flex-direction: column;
    }
    .collapsed .collapsible-content {
      display: none !important;
    }
    .collapsed .section-header {
      border-bottom: none;
    }

    /* =======================================
       核心焦點 1：頂部 HUD 當前即時音高狀態列
       ======================================= */
    .hud-bar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      background: var(--panel-bg);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px 18px;
      gap: 14px;
      flex-wrap: wrap;
    }

    .hud-now-singing {
      display: flex;
      align-items: center;
      gap: 16px;
    }
    .hud-title {
      font-size: 0.72rem;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .hud-pitch-badge {
      display: flex;
      align-items: center;
      gap: 14px;
      background: rgba(2, 132, 199, 0.15);
      border: 1.5px solid rgba(56, 189, 248, 0.4);
      border-radius: 10px;
      padding: 6px 18px;
      min-width: 220px;
      transition: all 0.2s;
    }
    .hud-jianpu-big {
      font-size: 2.3rem;
      font-weight: 900;
      color: var(--gold);
      text-shadow: 0 0 16px var(--gold-glow);
      font-family: "Courier New", Courier, monospace;
      line-height: 1;
      min-width: 32px;
      text-align: center;
    }
    .hud-note-info {
      display: flex;
      flex-direction: column;
      gap: 2px;
    }
    .hud-note-name {
      font-size: 1.25rem;
      font-weight: 800;
      color: #ffffff;
    }
    .hud-note-meta {
      font-size: 0.75rem;
      color: var(--text-muted);
    }

    .hud-time-display {
      font-family: monospace;
      font-size: 1.35rem;
      font-weight: 800;
      color: var(--accent);
      letter-spacing: 1px;
    }

    .hud-quick-tools {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    /* =======================================
       核心元件：鋼琴捲軸上方播放控制列 (含時間軸拖曳滑桿)
       ======================================= */
    .player-toolbar {
      background: var(--panel-bg);
      border: 1.5px solid rgba(56, 189, 248, 0.4);
      border-radius: 10px;
      padding: 10px 18px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
    }

    .toolbar-left {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }

    .btn-circle {
      width: 42px;
      height: 42px;
      border-radius: 50%;
      background: linear-gradient(135deg, #0284c7, #38bdf8);
      color: white;
      border: none;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 1.25rem;
      cursor: pointer;
      transition: all 0.2s;
      box-shadow: 0 0 16px rgba(2, 132, 199, 0.5);
      flex-shrink: 0;
    }
    .btn-circle:hover {
      background: #38bdf8;
      transform: scale(1.08);
      box-shadow: 0 0 20px rgba(56, 189, 248, 0.8);
    }

    .btn-action {
      background: #151e32;
      color: #f1f5f9;
      border: 1px solid var(--border);
      padding: 6px 12px;
      border-radius: 6px;
      font-size: 0.82rem;
      font-weight: 700;
      cursor: pointer;
      transition: all 0.15s;
    }
    .btn-action:hover {
      background: #1e293b;
      border-color: var(--accent);
      color: var(--accent);
    }

    /* 時間軸拖曳進度條 */
    .toolbar-center {
      flex: 1;
      min-width: 260px;
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .scrub-time-label {
      font-family: monospace;
      font-size: 0.88rem;
      font-weight: 800;
      color: var(--accent);
      min-width: 58px;
    }

    .scrub-track-wrapper {
      flex: 1;
      height: 12px;
      background: #080d1a;
      border: 1px solid rgba(56, 189, 248, 0.35);
      border-radius: 6px;
      position: relative;
      cursor: pointer;
      user-select: none;
      box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.6);
    }
    .scrub-track-wrapper:hover {
      border-color: var(--accent);
    }

    .scrub-progress-fill {
      height: 100%;
      width: 0%;
      background: linear-gradient(90deg, #0284c7, #38bdf8, #fbbf24);
      border-radius: 5px;
      transition: width 0.05s linear;
    }

    .scrub-handle {
      position: absolute;
      top: 50%;
      left: 0%;
      transform: translate(-50%, -50%);
      width: 18px;
      height: 18px;
      border-radius: 50%;
      background: #fbbf24;
      border: 2px solid #ffffff;
      box-shadow: 0 0 10px rgba(251, 191, 36, 0.8);
      cursor: grab;
      transition: transform 0.1s;
    }
    .scrub-handle:hover, .scrub-handle:active {
      transform: translate(-50%, -50%) scale(1.25);
      cursor: grabbing;
    }

    .toolbar-right {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }

    /* A-B 循環練唱段落工具組 */
    .loop-station-group {
      display: flex;
      align-items: center;
      gap: 7px;
      background: rgba(14, 21, 38, 0.85);
      border: 1px solid rgba(16, 185, 129, 0.45);
      padding: 3px 10px;
      border-radius: 8px;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
      transition: all 0.2s ease;
      flex-wrap: wrap;
    }
    .loop-station-group.loop-active {
      border-color: #10b981;
      background: rgba(6, 78, 59, 0.28);
      box-shadow: 0 0 14px rgba(16, 185, 129, 0.35);
    }
    .loop-point-box {
      display: flex;
      align-items: center;
      gap: 4px;
    }
    .loop-tag {
      font-size: 0.76rem;
      font-weight: 800;
      padding: 2px 6px;
      border-radius: 4px;
      white-space: nowrap;
    }
    .loop-tag-a {
      background: rgba(16, 185, 129, 0.22);
      color: #34d399;
      border: 1px solid rgba(16, 185, 129, 0.6);
    }
    .loop-tag-b {
      background: rgba(245, 158, 11, 0.22);
      color: #fbbf24;
      border: 1px solid rgba(245, 158, 11, 0.6);
    }
    .loop-input {
      width: 58px;
      background: #080d1a;
      border: 1px solid rgba(56, 189, 248, 0.35);
      border-radius: 5px;
      color: #f8fafc;
      font-family: monospace;
      font-size: 0.85rem;
      font-weight: 800;
      padding: 3px 4px;
      text-align: center;
      outline: none;
    }
    .loop-input:focus {
      border-color: #38bdf8;
      box-shadow: 0 0 6px rgba(56, 189, 248, 0.5);
    }
    .loop-toggle-label {
      display: flex;
      align-items: center;
      gap: 4px;
      font-size: 0.8rem;
      font-weight: 800;
      color: #94a3b8;
      cursor: pointer;
      user-select: none;
      padding: 3px 8px;
      border-radius: 6px;
      border: 1px solid rgba(148, 163, 184, 0.25);
      background: rgba(15, 23, 42, 0.6);
      transition: all 0.15s;
    }
    .loop-toggle-label:hover {
      color: #ffffff;
      border-color: rgba(56, 189, 248, 0.5);
    }
    .loop-toggle-label.active {
      color: #34d399;
      background: rgba(16, 185, 129, 0.25);
      border-color: #10b981;
      box-shadow: 0 0 8px rgba(16, 185, 129, 0.3);
    }
    .scrub-loop-highlight {
      position: absolute;
      top: 0;
      height: 100%;
      background: rgba(16, 185, 129, 0.35);
      border-left: 2px solid #10b981;
      border-right: 2px solid #f59e0b;
      pointer-events: none;
      display: none;
      z-index: 1;
    }
    .btn-anchor {
      background: rgba(16, 185, 129, 0.18);
      border-color: rgba(16, 185, 129, 0.5);
      color: #6ee7b7;
    }
    .btn-anchor:hover {
      background: rgba(16, 185, 129, 0.35);
      border-color: #34d399;
      color: #ffffff;
    }
    .btn-b-point {
      background: rgba(245, 158, 11, 0.18);
      border-color: rgba(245, 158, 11, 0.5);
      color: #fbbf24;
    }
    .btn-b-point:hover {
      background: rgba(245, 158, 11, 0.35);
      border-color: #f59e0b;
      color: #ffffff;
    }
    .btn-reset {
      background: rgba(239, 68, 68, 0.12);
      border-color: rgba(239, 68, 68, 0.4);
      color: #fca5a5;
    }
    .btn-reset:hover {
      background: rgba(239, 68, 68, 0.25);
      border-color: #ef4444;
      color: #ffffff;
    }

    .drag-tip-badge {
      font-size: 0.75rem;
      color: #94a3b8;
      background: rgba(30, 41, 59, 0.5);
      padding: 4px 8px;
      border-radius: 6px;
      border: 1px solid rgba(51, 65, 85, 0.4);
      white-space: nowrap;
    }

    /* =======================================
       核心焦點 3：Joysound 橫向鋼琴捲軸 (放大加寬版)
       ======================================= */
    .roll-stage {
      height: var(--canvas-height);
      min-height: 480px;
      background: #060913;
      position: relative;
      overflow: hidden;
      box-shadow: inset 0 0 40px rgba(0, 0, 0, 0.75);
      cursor: crosshair;
    }

    canvas#rollCanvas {
      width: 100%;
      height: 100%;
      display: block;
    }

    .minimap-canvas-wrapper {
      height: 38px;
      width: 100%;
      position: relative;
      cursor: pointer;
      overflow: hidden;
      background: #060a12;
    }
    canvas#minimapCanvas {
      width: 100%;
      height: 100%;
      display: block;
    }

    audio#nativeAudio { display: none; }

    .toast {
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: var(--panel-bg);
      color: var(--text);
      border: 1px solid var(--border);
      padding: 10px 18px;
      border-radius: 8px;
      box-shadow: 0 10px 25px rgba(0,0,0,0.6);
      display: none;
      align-items: center;
      gap: 8px;
      z-index: 999;
      font-size: 0.88rem;
      animation: fadeIn 0.25s;
    }
    @keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
  </style>
</head>
<body>

  <header>
    <div class="brand">
      <span>ToneDeaf</span>
      <span class="brand-badge">PRO MELODY</span>
    </div>

    <div class="controls">
      <div class="ctrl-group">
        <label for="trackSelect">曲目：</label>
        <select id="trackSelect" onchange="loadTrack(this.value)"></select>
      </div>

      <div class="ctrl-group">
        <label for="audioSourceSelect">聲道：</label>
        <select id="audioSourceSelect" onchange="changeAudioSource(this.value)">
          <option value="vocals" selected>🎤 純人聲 (超清晰)</option>
          <option value="original">🎵 完整原曲 (伴奏)</option>
        </select>
      </div>

      <div class="ctrl-group">
        <label for="keySelect">調性 (1=)：</label>
        <select id="keySelect" onchange="updateKeyOffset(this.value)">
          <option value="0" selected>1 = C</option>
          <option value="1">1 = C# / Db</option>
          <option value="2">1 = D</option>
          <option value="3">1 = D# / Eb</option>
          <option value="4">1 = E</option>
          <option value="5">1 = F</option>
          <option value="6">1 = F# / Gb</option>
          <option value="7">1 = G</option>
          <option value="8">1 = G# / Ab</option>
          <option value="9">1 = A</option>
          <option value="10">1 = A# / Bb</option>
          <option value="11">1 = B</option>
        </select>
      </div>

      <div class="sync-controller" title="藍牙耳機請微調負值補償延遲">
        <span style="font-size:0.75rem; color:var(--text-muted);">耳機補償:</span>
        <button class="btn-step" onclick="adjustOffset(-10)">-10</button>
        <span class="sync-val" id="syncVal">0ms</span>
        <button class="btn-step" onclick="adjustOffset(+10)">+10</button>
      </div>
    </div>
  </header>

  <main>
    <!-- =======================================
         核心焦點 1：頂部 HUD 當前即時音高狀態
         ======================================= -->
    <div class="hud-bar">
      <div class="hud-now-singing">
        <div>
          <div class="hud-title">當前演唱音高 (LIVE PITCH)</div>
          <div class="hud-pitch-badge" id="hudPitchBadge">
            <div class="hud-jianpu-big" id="hudJianpu">-</div>
            <div class="hud-note-info">
              <div class="hud-note-name" id="hudNoteName">準備中</div>
              <div class="hud-note-meta" id="hudNoteMeta">等待音符開唱</div>
            </div>
          </div>
        </div>
      </div>

      <div class="hud-time-display" id="hudTimeDisplay">00:00.0 / 00:00.0</div>

      <div class="hud-quick-tools">
        <button onclick="setPresetOffset(0)" style="font-size:0.75rem;">⚡ 0ms 內建喇叭</button>
        <button onclick="setPresetOffset(-180)" style="font-size:0.75rem;">🎧 -180ms 藍牙耳機</button>
      </div>
    </div>

    <!-- =======================================
         核心元件：播放控制列 (含時間軸拖曳進度條，位於鋼琴捲軸正上方)
         ======================================= -->
    <div class="player-toolbar" id="playerToolbar">
      <div class="toolbar-left">
        <button class="btn-circle" id="playBtn" onclick="togglePlay()" title="空白鍵播放/暫停">▶</button>
        <button class="btn-action" onclick="seekDelta(-5)">⏪ -5s</button>
        <button class="btn-action" onclick="seekDelta(+5)">⏩ +5s</button>
        <button class="btn-action" onclick="seekDelta(-30)">⏮ 前段</button>
        <button class="btn-action" onclick="seekDelta(+30)">⏭ 後段</button>

        <div class="ctrl-group">
          <label for="speedSelect">倍速：</label>
          <select id="speedSelect" onchange="changeSpeed(this.value)">
            <option value="0.75">0.75x</option>
            <option value="1.0" selected>1.0x</option>
            <option value="1.25">1.25x</option>
            <option value="1.5">1.5x</option>
          </select>
        </div>
      </div>

      <div class="toolbar-center">
        <span class="scrub-time-label" id="scrubCurTime">00:00.0</span>
        <div class="scrub-track-wrapper" id="scrubTrackWrapper" title="點擊或拖曳時間軸進度，放開立即繼續播放">
          <div class="scrub-loop-highlight" id="scrubLoopHighlight"></div>
          <div class="scrub-progress-fill" id="scrubProgressFill"></div>
          <div class="scrub-handle" id="scrubHandle"></div>
        </div>
        <span class="scrub-time-label" id="scrubTotalTime">00:00.0</span>
      </div>

      <div class="toolbar-right">
        <!-- A-B 區間循環練唱工具組 -->
        <div class="loop-station-group" id="loopStationGroup" title="A-B 區間循環練唱：設定 A 點與 B 點反覆練習">
          <!-- A 點 (起點) -->
          <div class="loop-point-box">
            <span class="loop-tag loop-tag-a">📍 A 點</span>
            <input type="number" id="loopAInput" min="0" step="0.1" value="0.0" onchange="setLoopAManual(this.value)" class="loop-input" title="A 點（循環起點）秒數，可按鍵盤 [ 設為當前" />
            <span style="font-size:0.75rem; color:var(--text-muted);">s</span>
            <button class="btn-action btn-anchor" onclick="setLoopAFromCurrent()" title="將目前播放時間記為 A 點（快捷鍵 [）">📍 記 A</button>
          </div>

          <!-- B 點 (終點) -->
          <div class="loop-point-box">
            <span class="loop-tag loop-tag-b">🏁 B 點</span>
            <input type="number" id="loopBInput" min="0" step="0.1" value="0.0" onchange="setLoopBManual(this.value)" class="loop-input" title="B 點（循環終點）秒數，可按鍵盤 ] 設為當前" />
            <span style="font-size:0.75rem; color:var(--text-muted);">s</span>
            <button class="btn-action btn-b-point" onclick="setLoopBFromCurrent()" title="將目前播放時間記為 B 點（快捷鍵 ]）">🏁 記 B</button>
          </div>

          <!-- 循環開關 -->
          <label class="loop-toggle-label" id="loopToggleLabel" title="勾選開啟 A-B 區間循環播放（快捷鍵 L）">
            <input type="checkbox" id="loopEnableCheckbox" onchange="toggleLoop(this.checked)" style="accent-color:#10b981; cursor:pointer;" />
            <span>🔁 循環</span>
          </label>

          <!-- 快速跳轉與清除 -->
          <button class="btn-action" onclick="jumpToLoopA()" title="跳轉至 A 點播放（快捷鍵 R）">⏮ 跳至 A</button>
          <button class="btn-action btn-reset" onclick="clearLoopAB()" title="重置清除 A-B 循環設定">🔄 清除</button>
        </div>

        <span class="drag-tip-badge">🖱️ 拖曳：往左快轉 ⏩ / 往右倒帶 ⏪ | 快捷鍵：[ 設 A / ] 設 B / L 循環</span>
      </div>
    </div>

    <!-- =======================================
         核心焦點 3：Joysound 橫向鋼琴捲軸 (防殘影高對比大音程條)
         ======================================= -->
    <div class="collapsible-section" id="rollSection">
      <div class="section-header" onclick="toggleSection('rollSection')">
        <div class="section-title">
          <span>🎹 橫向鋼琴捲軸 (Joysound 滾動大音程條)</span>
          <span style="font-size:0.75rem; color:#38bdf8; font-weight:normal;">[全音符必顯英文代號 / 黑曜防殘影底標 / 靜態靶心]</span>
        </div>

        <div class="ctrl-group" onclick="event.stopPropagation();">
          <label for="pitchRangeSelect" style="font-size:0.75rem;">音高跨度：</label>
          <select id="pitchRangeSelect" onchange="updatePitchSpan(this.value)" style="padding:2px 6px; font-size:0.78rem;">
            <option value="compact" selected>🎯 緊湊聚焦 (最聚焦大音符)</option>
            <option value="standard">標準人聲 (適中)</option>
            <option value="wide">全音域範圍 (較小)</option>
          </select>

          <label for="canvasHeightSelect" style="font-size:0.75rem; margin-left:4px;">捲軸高度：</label>
          <select id="canvasHeightSelect" onchange="updateCanvasHeight(this.value)" style="padding:2px 6px; font-size:0.78rem;">
            <option value="460">標準 (460px)</option>
            <option value="540" selected>放大 (540px - 推薦)</option>
            <option value="660">超大 (660px)</option>
          </select>

          <!-- 防殘影核心控制：視野橫向速度 -->
          <label for="zoomSelect" style="font-size:0.75rem; margin-left:4px;">視野橫向速度：</label>
          <select id="zoomSelect" onchange="updateZoom(this.value)" style="padding:2px 6px; font-size:0.78rem;">
            <option value="8.0" selected>🛡️ 超慢無殘影 (8 秒視野 - 推薦)</option>
            <option value="10.0">極致悠閒 (10 秒視野 - 最平穩)</option>
            <option value="6.0">標準速度 (6 秒視野)</option>
            <option value="4.0">緊湊視野 (4 秒視野)</option>
          </select>

          <button class="section-toggle-btn" id="rollSectionBtn" onclick="event.stopPropagation(); toggleSection('rollSection');">▲ 收合</button>
        </div>
      </div>

      <div class="collapsible-content">
        <div class="roll-stage" id="rollContainer">
          <canvas id="rollCanvas"></canvas>
        </div>
      </div>
    </div>

    <!-- =======================================
         可摺疊組件：全曲縮圖導航條 (Minimap)
         ======================================= -->
    <div class="collapsible-section collapsed" id="minimapSection">
      <div class="section-header" onclick="toggleSection('minimapSection')">
        <div class="section-title">
          <span>🗺️ 全曲縮圖導航 (點擊或拖曳跳轉)</span>
          <span id="minimapNoteCount" style="font-size:0.72rem; color:var(--text-muted); font-weight:normal;">- 個音符</span>
        </div>
        <button class="section-toggle-btn" id="minimapSectionBtn">▼ 展開</button>
      </div>

      <div class="collapsible-content">
        <div class="minimap-canvas-wrapper" id="minimapWrapper">
          <canvas id="minimapCanvas"></canvas>
        </div>
      </div>
    </div>

    <!-- 底部資訊提示 -->
    <div style="font-size:0.82rem; color:var(--text-muted); text-align:center; padding: 6px 0;">
      💡 提示：按 <b>空白鍵 (Space)</b> 播放/暫停；<b>← / →</b> 快轉倒帶；<b>[ / ]</b> 標記 A/B 點；<b>L</b> 切換循環；<b>R</b> 跳回 A 點！直接在<b>鋼琴捲軸</b>或<b>時間軸</b>拖曳，放開即繼續播放！
    </div>
  </main>

  <audio id="nativeAudio" preload="auto"></audio>
  <div class="toast" id="toast"></div>

  <script>
    let currentData = null;
    let currentFileName = "";
    let syncOffsetSec = 0.0;
    let keyOffset = 0;
    let visibleTimeSpan = 8.0; // 預設 8 秒視野：大幅放慢橫向滑動速度，彻底消除殘影！
    let pitchSpanMode = "compact";

    const audio = document.getElementById("nativeAudio");
    const rollCanvas = document.getElementById("rollCanvas");
    const rollCtx = rollCanvas.getContext("2d");
    const minimapCanvas = document.getElementById("minimapCanvas");
    const minimapCtx = minimapCanvas.getContext("2d");

    const playBtn = document.getElementById("playBtn");
    const hudJianpu = document.getElementById("hudJianpu");
    const hudNoteName = document.getElementById("hudNoteName");
    const hudNoteMeta = document.getElementById("hudNoteMeta");
    const hudTimeDisplay = document.getElementById("hudTimeDisplay");
    const syncValEl = document.getElementById("syncVal");

    // 音名半音與簡譜對照
    const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
    const CHROMATIC_SCALE = [
      { num: "1", acc: "", hue: "#38bdf8" },
      { num: "1", acc: "#", hue: "#0ea5e9" },
      { num: "2", acc: "", hue: "#60a5fa" },
      { num: "2", acc: "#", hue: "#3b82f6" },
      { num: "3", acc: "", hue: "#34d399" },
      { num: "4", acc: "", hue: "#4ade80" },
      { num: "4", acc: "#", hue: "#22c55e" },
      { num: "5", acc: "", hue: "#fbbf24" },
      { num: "5", acc: "#", hue: "#f59e0b" },
      { num: "6", acc: "", hue: "#fb923c" },
      { num: "6", acc: "#", hue: "#ea580c" },
      { num: "7", acc: "", hue: "#f472b6" }
    ];

    function toggleSection(sectionId) {
      const section = document.getElementById(sectionId);
      if (!section) return;
      section.classList.toggle("collapsed");
      const isCollapsed = section.classList.contains("collapsed");
      const btn = document.getElementById(sectionId + "Btn");
      if (btn) btn.textContent = isCollapsed ? "▼ 展開" : "▲ 收合";

      if (!isCollapsed && sectionId === "rollSection") {
        setTimeout(resizeCanvas, 50);
      }
    }

    function updateCanvasHeight(val) {
      document.documentElement.style.setProperty("--canvas-height", val + "px");
      setTimeout(resizeCanvas, 30);
      showToast(`捲軸高度已調整為 ${val}px`);
    }

    function updatePitchSpan(val) {
      pitchSpanMode = val;
      calculateVocalRange();
      showToast(`音高跨度已切換為：${val === 'compact' ? '🎯 緊湊聚焦 (音符最大)' : (val === 'standard' ? '標準人聲' : '全音域')}`);
    }

    try {
      const savedOffset = localStorage.getItem("tonedeaf_sync_offset");
      if (savedOffset !== null) syncOffsetSec = parseFloat(savedOffset) || 0.0;
    } catch (e) {}

    function updateSyncDisplay() {
      const ms = Math.round(syncOffsetSec * 1000);
      syncValEl.textContent = (ms > 0 ? "+" : "") + ms + "ms";
      try { localStorage.setItem("tonedeaf_sync_offset", syncOffsetSec.toString()); } catch (e) {}
    }
    updateSyncDisplay();

    function adjustOffset(deltaMs) {
      syncOffsetSec += (deltaMs / 1000);
      syncOffsetSec = Math.round(syncOffsetSec * 1000) / 1000;
      updateSyncDisplay();
      showToast("延遲校準已調整為 " + Math.round(syncOffsetSec * 1000) + "ms");
    }

    function setPresetOffset(targetMs) {
      syncOffsetSec = targetMs / 1000;
      updateSyncDisplay();
      showToast("已套用延遲預設：" + targetMs + "ms");
    }

    function updateZoom(val) {
      visibleTimeSpan = parseFloat(val);
      const zSelect = document.getElementById("zoomSelect");
      if (zSelect) zSelect.value = val;
      resizeCanvas();
      showToast(`滾動視野已設為 ${val} 秒 (視野越寬速度越慢，越抗殘影)`);
    }

    function updateKeyOffset(val) {
      keyOffset = parseInt(val, 10);
    }

    function changeSpeed(val) {
      audio.playbackRate = parseFloat(val);
    }

    function changeAudioSource(type) {
      if (!currentData) return;
      const prevTime = audio.currentTime;
      const isPlaying = !audio.paused;

      if (type === "vocals") {
        audio.src = "/audio/" + currentData.track + "_vocals.wav";
      } else {
        audio.src = "/audio/" + currentData.track + ".mp3";
      }

      audio.onloadedmetadata = () => {
        audio.currentTime = prevTime;
        if (isPlaying) audio.play();
      };
    }

    // ==========================================
    // A-B 區間循環練唱核心狀態管理
    // ==========================================
    let loopA = 0.0;
    let loopB = 0.0;
    let isLoopActive = false;

    try {
      const sA = localStorage.getItem("tonedeaf_loop_a");
      if (sA !== null) loopA = parseFloat(sA) || 0.0;
      const sB = localStorage.getItem("tonedeaf_loop_b");
      if (sB !== null) loopB = parseFloat(sB) || 0.0;
      const sAct = localStorage.getItem("tonedeaf_loop_active");
      if (sAct !== null) isLoopActive = (sAct === "true");
    } catch (e) {}

    function updateLoopUI() {
      const inputA = document.getElementById("loopAInput");
      const inputB = document.getElementById("loopBInput");
      const chk = document.getElementById("loopEnableCheckbox");
      const grp = document.getElementById("loopStationGroup");
      const lbl = document.getElementById("loopToggleLabel");

      if (inputA) inputA.value = loopA.toFixed(1);
      if (inputB) inputB.value = loopB.toFixed(1);
      if (chk) chk.checked = isLoopActive;
      if (grp) grp.classList.toggle("loop-active", isLoopActive);
      if (lbl) lbl.classList.toggle("active", isLoopActive);

      updateScrubLoopRegion();
    }
    setTimeout(updateLoopUI, 100);

    function saveLoopState() {
      try {
        localStorage.setItem("tonedeaf_loop_a", loopA.toString());
        localStorage.setItem("tonedeaf_loop_b", loopB.toString());
        localStorage.setItem("tonedeaf_loop_active", isLoopActive.toString());
      } catch (e) {}
    }

    function setLoopAFromCurrent() {
      loopA = Math.round(audio.currentTime * 10) / 10;
      if (loopB > 0 && loopB <= loopA) loopB = 0;
      saveLoopState();
      updateLoopUI();
      showToast(`📍 已設定 A 點（起點）：${loopA.toFixed(1)}s (${formatTime(loopA)})`);
    }

    function setLoopAManual(val) {
      const v = parseFloat(val);
      loopA = isNaN(v) ? 0.0 : Math.max(0, Math.min(audio.duration || 9999, Math.round(v * 10) / 10));
      if (loopB > 0 && loopB <= loopA) loopB = 0;
      saveLoopState();
      updateLoopUI();
      showToast(`📍 已設定 A 點（起點）：${loopA.toFixed(1)}s (${formatTime(loopA)})`);
    }

    function setLoopBFromCurrent() {
      const cur = Math.round(audio.currentTime * 10) / 10;
      if (cur <= loopA) {
        showToast("⚠️ B 點（終點）必須大於 A 點！請將時間軸拉到 A 點之後", true);
        return;
      }
      loopB = cur;
      isLoopActive = true;
      saveLoopState();
      updateLoopUI();
      showToast(`🏁 已設定 B 點（終點）：${loopB.toFixed(1)}s (${formatTime(loopB)})，已啟動循環！`);
    }

    function setLoopBManual(val) {
      const v = parseFloat(val);
      const targetB = isNaN(v) ? 0.0 : Math.max(0, Math.min(audio.duration || 9999, Math.round(v * 10) / 10));
      if (targetB > 0 && targetB <= loopA) {
        showToast("⚠️ B 點必須大於 A 點！", true);
        return;
      }
      loopB = targetB;
      saveLoopState();
      updateLoopUI();
      showToast(`🏁 已設定 B 點（終點）：${loopB.toFixed(1)}s (${formatTime(loopB)})`);
    }

    function toggleLoop(active) {
      if (active && (!loopB || loopB <= loopA)) {
        showToast("⚠️ 請先設定有效的 B 點（終點秒數）！", true);
        const chk = document.getElementById("loopEnableCheckbox");
        if (chk) chk.checked = false;
        isLoopActive = false;
        saveLoopState();
        updateLoopUI();
        return;
      }
      isLoopActive = active;
      saveLoopState();
      updateLoopUI();
      showToast(isLoopActive ? `🔁 已啟用 A-B 區間循環 (${formatTime(loopA)} ~ ${formatTime(loopB)})` : "已關閉循環播放");
    }

    function jumpToLoopA() {
      audio.currentTime = loopA;
      updateScrubSlider(loopA, audio.duration);
      if (audio.paused) {
        audio.play();
        playBtn.textContent = "⏸";
      }
      showToast(`⏮ 跳至 A 點 ${formatTime(loopA)} 繼續播放 ▶`);
    }

    function clearLoopAB() {
      loopA = 0.0;
      loopB = 0.0;
      isLoopActive = false;
      saveLoopState();
      updateLoopUI();
      showToast("🔄 已清除 A-B 循環設定");
    }

    function updateScrubLoopRegion() {
      const highlight = document.getElementById("scrubLoopHighlight");
      if (!highlight) return;
      if (loopB > loopA && audio.duration) {
        const leftPct = (loopA / audio.duration) * 100;
        const widthPct = ((loopB - loopA) / audio.duration) * 100;
        highlight.style.left = leftPct + "%";
        highlight.style.width = widthPct + "%";
        highlight.style.display = "block";
        highlight.style.background = isLoopActive ? "rgba(16, 185, 129, 0.4)" : "rgba(148, 163, 184, 0.2)";
        highlight.style.borderLeft = isLoopActive ? "2px solid #10b981" : "2px solid #94a3b8";
        highlight.style.borderRight = isLoopActive ? "2px solid #f59e0b" : "2px solid #94a3b8";
      } else {
        highlight.style.display = "none";
      }
    }

    function togglePlay() {
      if (audio.paused) {
        if (isLoopActive && loopB > loopA) {
          if (audio.currentTime < loopA || audio.currentTime >= loopB) {
            audio.currentTime = loopA;
          }
        } else if (audio.currentTime === 0 && loopA > 0) {
          audio.currentTime = loopA;
        }
        audio.play();
        playBtn.textContent = "⏸";
      } else {
        audio.pause();
        playBtn.textContent = "▶";
      }
    }

    function seekDelta(sec) {
      if (sec === -30 && loopA > 0) {
        audio.currentTime = loopA;
      } else {
        const minBound = (sec < 0 && isLoopActive && loopA > 0 && audio.currentTime >= loopA) ? loopA : 0;
        let newT = audio.currentTime + sec;
        if (isLoopActive && loopB > loopA && newT >= loopB) {
          newT = loopA;
        }
        audio.currentTime = Math.max(minBound, Math.min(audio.duration || 9999, newT));
      }
      updateScrubSlider(audio.currentTime, audio.duration);
    }

    function seekToTime(t) {
      audio.currentTime = Math.max(0, t - 0.05);
      if (audio.paused) togglePlay();
      showToast(`已跳轉至 ${t.toFixed(2)}s`);
    }

    window.addEventListener("keydown", (e) => {
      if (["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName)) {
        return;
      }
      if (e.code === "Space") {
        e.preventDefault();
        togglePlay();
      } else if (e.code === "ArrowLeft") {
        e.preventDefault();
        seekDelta(-3);
      } else if (e.code === "ArrowRight") {
        e.preventDefault();
        seekDelta(+3);
      } else if (e.key === "[" || e.code === "BracketLeft") {
        e.preventDefault();
        setLoopAFromCurrent();
      } else if (e.key === "]" || e.code === "BracketRight") {
        e.preventDefault();
        setLoopBFromCurrent();
      } else if (e.key.toLowerCase() === "l") {
        e.preventDefault();
        toggleLoop(!isLoopActive);
      } else if (e.key.toLowerCase() === "r" || e.code === "Backspace") {
        e.preventDefault();
        jumpToLoopA();
      }
    });

    function midiToJianpuInfo(midi, kOffset = 0) {
      if (!midi || midi <= 0) return { number: "-", dotsTop: 0, dotsBottom: 0, acc: "" };

      const relativeSemitone = (midi - kOffset) % 12;
      const normalizedSemitone = (relativeSemitone + 12) % 12;
      const jianpuInfo = CHROMATIC_SCALE[normalizedSemitone];

      const effectiveMidi = midi - kOffset;
      const octave = Math.floor(effectiveMidi / 12) - 1;

      let dotsTop = 0;
      let dotsBottom = 0;

      if (octave > 4) dotsTop = octave - 4;
      else if (octave < 4) dotsBottom = 4 - octave;

      return {
        number: jianpuInfo.num,
        acc: jianpuInfo.acc,
        dotsTop: Math.min(dotsTop, 2),
        dotsBottom: Math.min(dotsBottom, 2)
      };
    }

    function formatTime(sec) {
      if (isNaN(sec)) return "00:00.0";
      const m = Math.floor(sec / 60);
      const s = Math.floor(sec % 60);
      const ms = Math.floor((sec % 1) * 10);
      return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${ms}`;
    }

    async function init() {
      try {
        const res = await fetch("/api/tracks");
        const tracks = await res.json();
        const select = document.getElementById("trackSelect");
        select.innerHTML = "";

        if (tracks.length === 0) {
          select.innerHTML = "<option>無可用的 JSON 檔案</option>";
          return;
        }

        tracks.forEach(t => {
          const opt = document.createElement("option");
          opt.value = t;
          opt.textContent = t;
          select.appendChild(opt);
        });

        loadTrack(tracks[0]);
      } catch (err) {
        showToast("載入曲目失敗: " + err, true);
      }
    }

    let minMidi = 48; // C3
    let maxMidi = 72; // C5

    function calculateVocalRange() {
      if (!currentData || !currentData.data || currentData.data.length === 0) return;
      const midis = currentData.data.map(n => n.midi).filter(m => m > 0);
      const sorted = [...midis].sort((a, b) => a - b);

      if (pitchSpanMode === "compact") {
        const p2 = sorted[Math.floor(sorted.length * 0.015)] || sorted[0];
        const p98 = sorted[Math.floor(sorted.length * 0.985)] || sorted[sorted.length - 1];
        minMidi = Math.max(36, p2 - 1);
        maxMidi = Math.min(84, p98 + 1);
        if (maxMidi - minMidi < 14) maxMidi = minMidi + 14;
      } else if (pitchSpanMode === "standard") {
        minMidi = Math.max(36, Math.min(...midis) - 1);
        maxMidi = Math.min(84, Math.max(...midis) + 1);
      } else {
        minMidi = Math.max(36, Math.min(...midis) - 2);
        maxMidi = Math.min(84, Math.max(...midis) + 2);
      }
    }

    async function loadTrack(fileName) {
      currentFileName = fileName;
      try {
        const res = await fetch("/api/load?file=" + encodeURIComponent(fileName));
        const json = await res.json();
        currentData = json;

        calculateVocalRange();
        document.getElementById("minimapNoteCount").textContent = `${json.total_notes} 個音符`;

        const srcType = document.getElementById("audioSourceSelect").value;
        if (srcType === "vocals") {
          audio.src = "/audio/" + json.track + "_vocals.wav";
        } else {
          audio.src = "/audio/" + json.track + ".mp3";
        }

        resizeCanvas();
        drawMinimap();
        updateScrubSlider(0, audio.duration || 1);
      } catch (err) {
        showToast("讀取曲目內容失敗: " + err, true);
      }
    }

    let dpr = window.devicePixelRatio || 1;
    let stageWidth = 1000;
    let stageHeight = 540;

    function resizeCanvas() {
      const container = document.getElementById("rollContainer");
      if (container && container.clientHeight > 0) {
        stageWidth = container.clientWidth;
        stageHeight = container.clientHeight;

        rollCanvas.width = stageWidth * dpr;
        rollCanvas.height = stageHeight * dpr;
        rollCtx.resetTransform();
        rollCtx.scale(dpr, dpr);
      }

      const mWrapper = document.getElementById("minimapWrapper");
      if (mWrapper && mWrapper.clientWidth > 0) {
        minimapCanvas.width = mWrapper.clientWidth * dpr;
        minimapCanvas.height = mWrapper.clientHeight * dpr;
        minimapCtx.resetTransform();
        minimapCtx.scale(dpr, dpr);
        drawMinimap();
      }
    }
    window.addEventListener("resize", resizeCanvas);

    // ==========================================
    // 時間軸互動核心 (支援進度條拖曳 + 鋼琴捲軸左右拖曳，放開繼續播放)
    // ==========================================
    const scrubTrackWrapper = document.getElementById("scrubTrackWrapper");
    let isSliderScrubbing = false;
    let wasPlayingBeforeSlider = false;

    if (scrubTrackWrapper) {
      scrubTrackWrapper.addEventListener("mousedown", (e) => {
        if (!audio.duration) return;
        isSliderScrubbing = true;
        wasPlayingBeforeSlider = !audio.paused;
        audio.pause();
        handleSliderMove(e);
      });
    }

    function handleSliderMove(e) {
      if (!scrubTrackWrapper || !audio.duration) return;
      const rect = scrubTrackWrapper.getBoundingClientRect();
      const clickX = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
      const ratio = clickX / rect.width;
      const newTime = ratio * audio.duration;
      audio.currentTime = newTime;
      updateScrubSlider(newTime, audio.duration);
    }

    function updateScrubSlider(cur, total) {
      if (!total) return;
      const pct = Math.min(100, Math.max(0, (cur / total) * 100));
      const fill = document.getElementById("scrubProgressFill");
      const handle = document.getElementById("scrubHandle");
      const curLabel = document.getElementById("scrubCurTime");
      const totLabel = document.getElementById("scrubTotalTime");
      if (fill) fill.style.width = pct + "%";
      if (handle) handle.style.left = pct + "%";
      if (curLabel) curLabel.textContent = formatTime(cur);
      if (totLabel) totLabel.textContent = formatTime(total);
    }

    // 鋼琴捲軸滑鼠拖曳時間軸互動
    let isRollScrubbing = false;
    let wasPlayingBeforeRollScrub = false;
    let scrubStartX = 0;
    let scrubStartTime = 0;
    let hasScrubMoved = false;

    rollCanvas.addEventListener("mousedown", (e) => {
      if (!currentData || !audio.duration) return;
      if (e.button !== 0) return; // 僅限左鍵

      isRollScrubbing = true;
      hasScrubMoved = false;
      wasPlayingBeforeRollScrub = !audio.paused;
      audio.pause();

      scrubStartX = e.clientX;
      scrubStartTime = audio.currentTime;
      rollCanvas.style.cursor = "grabbing";
    });

    window.addEventListener("mousemove", (e) => {
      if (isSliderScrubbing) {
        handleSliderMove(e);
      }
      if (isRollScrubbing) {
        const deltaX = e.clientX - scrubStartX;
        if (Math.abs(deltaX) > 3) {
          hasScrubMoved = true;
        }

        const playheadX = stageWidth * 0.24;
        const pxPerSec = (stageWidth - playheadX) / visibleTimeSpan;

        // 往右拖曳 = 往前倒帶（時間減少）；往左拖曳 = 往後快轉（時間增加）
        let newTime = scrubStartTime - (deltaX / pxPerSec);
        newTime = Math.max(0, Math.min(audio.duration || 9999, newTime));

        audio.currentTime = newTime;
        updateScrubSlider(newTime, audio.duration);
      }
    });

    window.addEventListener("mouseup", (e) => {
      // 處理進度條拖曳放開
      if (isSliderScrubbing) {
        isSliderScrubbing = false;
        if (wasPlayingBeforeSlider) {
          audio.play();
          playBtn.textContent = "⏸";
          showToast(`已跳轉至 ${formatTime(audio.currentTime)}，繼續播放 ▶`);
        } else {
          showToast(`已跳轉至 ${formatTime(audio.currentTime)}`);
        }
      }

      // 處理鋼琴捲軸拖曳放開
      if (isRollScrubbing) {
        isRollScrubbing = false;
        rollCanvas.style.cursor = "crosshair";

        // 若無明顯位移（單純點擊），直接跳轉至點擊的音符/時間位置
        if (!hasScrubMoved) {
          const rect = rollCanvas.getBoundingClientRect();
          const clickX = e.clientX - rect.left;
          const playheadX = stageWidth * 0.24;
          const pxPerSec = (stageWidth - playheadX) / visibleTimeSpan;
          const targetTime = Math.max(0, Math.min(audio.duration || 9999, scrubStartTime + (clickX - playheadX) / pxPerSec));
          audio.currentTime = targetTime;
          updateScrubSlider(targetTime, audio.duration);
        }

        // 【核心需求：放開後再繼續播放】
        if (wasPlayingBeforeRollScrub) {
          audio.play();
          playBtn.textContent = "⏸";
          showToast(`已跳轉至 ${formatTime(audio.currentTime)}，繼續播放 ▶`);
        } else {
          showToast(`已定位至 ${formatTime(audio.currentTime)}`);
        }
      }
    });

    // ==========================================
    // 橫向滾動 Joysound 渲染核心 (全音符必顯英文名 + 黑曜防殘影底標 + 靜態靶心)
    // ==========================================
    function renderRollFrame() {
      requestAnimationFrame(renderRollFrame);
      if (!currentData || !currentData.data) return;

      const curTime = Math.max(0, audio.currentTime - syncOffsetSec);
      const totalDur = audio.duration || 1;

      // A-B 區間循環判定：播放超過 B 點時，自動無縫跳回 A 點重播
      if (isLoopActive && loopB > loopA + 0.1 && !audio.paused && !isSliderScrubbing && !isRollScrubbing) {
        if (curTime >= loopB) {
          audio.currentTime = loopA + syncOffsetSec;
          showToast(`🔁 循環跳轉：回到 A 點 (${formatTime(loopA)})`);
        }
      }

      updateScrubSlider(curTime, totalDur);
      hudTimeDisplay.textContent = `${formatTime(curTime)} / ${formatTime(totalDur)}`;

      let activeNote = null;
      let lastEndedNote = null;
      let nextUpcomingNote = null;
      let minNextGap = 9999;
      let minPrevGap = 9999;
      const allNotes = currentData.data;

      for (let i = 0; i < allNotes.length; i++) {
        const n = allNotes[i];
        if (curTime >= n.start && curTime <= n.end) {
          activeNote = n;
        }
        if (n.start > curTime && (n.start - curTime) < minNextGap) {
          minNextGap = n.start - curTime;
          nextUpcomingNote = n;
        }
        if (n.end < curTime && (curTime - n.end) < minPrevGap) {
          minPrevGap = curTime - n.end;
          lastEndedNote = n;
        }
      }

      // 咬字輔音連音平滑：若處於兩個音符之間微小間隙（<= 180ms，清輔音咬字閉合），視為同一樂句連音，不閃爍「休止」
      const isArticulating = (!activeNote && lastEndedNote && nextUpcomingNote && minPrevGap <= 0.18 && minNextGap <= 0.18);

      if (activeNote) {
        const jianpu = midiToJianpuInfo(activeNote.midi, keyOffset);
        let jianpuSymbol = jianpu.number + (jianpu.acc || "");
        if (jianpu.dotsTop > 0) jianpuSymbol = "•" + jianpuSymbol;
        if (jianpu.dotsBottom > 0) jianpuSymbol = jianpuSymbol + "•";

        hudJianpu.textContent = jianpuSymbol;
        hudNoteName.textContent = activeNote.pitch;
        hudNoteMeta.textContent = `時長 ${activeNote.duration}s | MIDI ${activeNote.midi}`;
        document.getElementById("hudPitchBadge").style.borderColor = "#fbbf24";
      } else if (isArticulating && lastEndedNote) {
        const jianpu = midiToJianpuInfo(lastEndedNote.midi, keyOffset);
        let jianpuSymbol = jianpu.number + (jianpu.acc || "");
        if (jianpu.dotsTop > 0) jianpuSymbol = "•" + jianpuSymbol;
        if (jianpu.dotsBottom > 0) jianpuSymbol = jianpuSymbol + "•";

        hudJianpu.textContent = jianpuSymbol;
        hudNoteName.textContent = lastEndedNote.pitch;
        hudNoteMeta.textContent = `咬字連音過渡中 (~${(minNextGap * 1000).toFixed(0)}ms)`;
        document.getElementById("hudPitchBadge").style.borderColor = "#fbbf24";
      } else {
        hudJianpu.textContent = "-";
        if (nextUpcomingNote && minNextGap <= 2.5) {
          hudNoteName.textContent = "即將開唱 (準備)";
          hudNoteMeta.textContent = `距離下個音符【${nextUpcomingNote.pitch}】還有 ${minNextGap.toFixed(1)}s`;
        } else {
          hudNoteName.textContent = "☕ 樂句休止中";
          hudNoteMeta.textContent = nextUpcomingNote ? `距下句歌唱還有 ${minNextGap.toFixed(1)}s` : "目前無演唱音符";
        }
        document.getElementById("hudPitchBadge").style.borderColor = "rgba(56, 189, 248, 0.25)";
      }

      const rollSection = document.getElementById("rollSection");
      if (!rollSection.classList.contains("collapsed") && stageWidth > 0 && stageHeight > 0) {
        rollCtx.fillStyle = "#070b16";
        rollCtx.fillRect(0, 0, stageWidth, stageHeight);

        const playheadX = stageWidth * 0.24;
        const pxPerSec = (stageWidth - playheadX) / visibleTimeSpan;

        const totalSemis = maxMidi - minMidi + 1;
        const laneH = stageHeight / totalSemis;
        const pianoKeyWidth = 56; // 寬琴鍵尺規

        // 1. 繪製寬闊的半音橫向軌道 (琴鍵網格)
        for (let m = minMidi; m <= maxMidi; m++) {
          const y = stageHeight - (m - minMidi + 1) * laneH;
          const noteIdx = m % 12;
          const isBlackKey = [1, 3, 6, 8, 10].includes(noteIdx);
          const isC = (noteIdx === 0);
          const isThisLaneActive = activeNote && (activeNote.midi === m);

          // 軌道背景色
          if (isThisLaneActive) {
            rollCtx.fillStyle = "rgba(56, 189, 248, 0.12)"; // 當前音高軌道整條微亮！
          } else if (isBlackKey) {
            rollCtx.fillStyle = "rgba(0, 0, 0, 0.32)";
          } else {
            rollCtx.fillStyle = "rgba(255, 255, 255, 0.04)";
          }
          rollCtx.fillRect(pianoKeyWidth, y, stageWidth - pianoKeyWidth, laneH);

          // 分隔線
          rollCtx.strokeStyle = isThisLaneActive ? "rgba(251, 191, 36, 0.7)" : (isC ? "rgba(56, 189, 248, 0.45)" : "rgba(30, 41, 59, 0.4)");
          rollCtx.lineWidth = isThisLaneActive ? 2 : (isC ? 1.8 : 1);
          rollCtx.beginPath();
          rollCtx.moveTo(pianoKeyWidth, y + laneH);
          rollCtx.lineTo(stageWidth, y + laneH);
          rollCtx.stroke();

          // 左側固定琴鍵音名標籤 (靜態無殘影標尺)
          rollCtx.fillStyle = isThisLaneActive ? "#0284c7" : (isBlackKey ? "#151e30" : "#22314d");
          rollCtx.fillRect(0, y, pianoKeyWidth, laneH);

          rollCtx.fillStyle = isThisLaneActive ? "#ffffff" : (isC ? "#38bdf8" : (isBlackKey ? "#94a3b8" : "#f1f5f9"));
          const keyFontSize = Math.max(11, Math.min(laneH * 0.55, 14));
          rollCtx.font = `bold ${keyFontSize}px system-ui, sans-serif`;
          rollCtx.textAlign = "center";
          rollCtx.textBaseline = "middle";

          const octave = Math.floor(m / 12) - 1;
          const nameStr = `${NOTE_NAMES[noteIdx]}${octave}`;
          rollCtx.fillText(nameStr, pianoKeyWidth / 2, y + laneH / 2);
        }

        // 2. 判定線發光雷射特效
        const beamGrad = rollCtx.createLinearGradient(playheadX - 8, 0, playheadX + 8, 0);
        beamGrad.addColorStop(0, "rgba(56, 189, 248, 0)");
        beamGrad.addColorStop(0.5, "rgba(56, 189, 248, 0.95)");
        beamGrad.addColorStop(1, "rgba(56, 189, 248, 0)");
        rollCtx.fillStyle = beamGrad;
        rollCtx.fillRect(playheadX - 8, 0, 16, stageHeight);

        rollCtx.strokeStyle = "#ffffff";
        rollCtx.lineWidth = 2.2;
        rollCtx.beginPath();
        rollCtx.moveTo(playheadX, 0);
        rollCtx.lineTo(playheadX, stageHeight);
        rollCtx.stroke();

        // 3. 【防殘影核心神器】判定線靶心靜止標靶 (Stationary Target HUD)
        // 眼睛只要注視此處，完全不用追著移動音符看，100% 告別殘影！
        // 嚴格落實：發聲時精準顯示音高；休止/間奏時絕不殘留假音高
        let hudText = "";
        let hudIsActive = false;
        let hudIsUpcoming = false;

        if (activeNote) {
          const tJianpu = midiToJianpuInfo(activeNote.midi, keyOffset);
          let tLabel = tJianpu.number + (tJianpu.acc || "");
          if (tJianpu.dotsTop > 0) tLabel = "•" + tLabel;
          if (tJianpu.dotsBottom > 0) tLabel = tLabel + "•";
          hudText = `🎯 當前音高：【 ${tLabel} ${activeNote.pitch} 】`;
          hudIsActive = true;
        } else if (isArticulating && lastEndedNote) {
          const tJianpu = midiToJianpuInfo(lastEndedNote.midi, keyOffset);
          let tLabel = tJianpu.number + (tJianpu.acc || "");
          if (tJianpu.dotsTop > 0) tLabel = "•" + tLabel;
          if (tJianpu.dotsBottom > 0) tLabel = tLabel + "•";
          hudText = `🎯 咬字連音：【 ${tLabel} ${lastEndedNote.pitch} 】`;
          hudIsActive = true;
        } else if (nextUpcomingNote && minNextGap <= 2.5) {
          const tJianpu = midiToJianpuInfo(nextUpcomingNote.midi, keyOffset);
          let tLabel = tJianpu.number + (tJianpu.acc || "");
          if (tJianpu.dotsTop > 0) tLabel = "•" + tLabel;
          if (tJianpu.dotsBottom > 0) tLabel = tLabel + "•";
          hudText = `⏳ 準備進歌：【 ${tLabel} ${nextUpcomingNote.pitch} 】 (${minNextGap.toFixed(1)}s)`;
          hudIsUpcoming = true;
        } else {
          // 純休止或間奏中：明確標註休止，絕不顯示假音高！
          hudText = nextUpcomingNote ? `☕ 樂句休止中 (距下句 ${minNextGap.toFixed(1)}s)` : `☕ 樂句休止中`;
        }

        if (hudText) {
          rollCtx.save();
          rollCtx.font = "bold 13px system-ui, sans-serif";
          const tw = rollCtx.measureText(hudText).width;
          const hX = Math.max(pianoKeyWidth + 8, playheadX - tw / 2);
          const hY = 8;

          // 靜止底框樣式自適應
          if (hudIsActive) {
            rollCtx.fillStyle = "rgba(251, 191, 36, 0.22)";
            rollCtx.strokeStyle = "#fbbf24";
          } else if (hudIsUpcoming) {
            rollCtx.fillStyle = "rgba(14, 21, 38, 0.9)";
            rollCtx.strokeStyle = "#38bdf8";
          } else {
            rollCtx.fillStyle = "rgba(15, 23, 42, 0.85)";
            rollCtx.strokeStyle = "rgba(148, 163, 184, 0.35)";
          }
          rollCtx.lineWidth = 1.5;
          rollCtx.beginPath();
          rollCtx.roundRect(hX - 8, hY, tw + 16, 26, 6);
          rollCtx.fill();
          rollCtx.stroke();

          if (hudIsActive) rollCtx.fillStyle = "#fbbf24";
          else if (hudIsUpcoming) rollCtx.fillStyle = "#38bdf8";
          else rollCtx.fillStyle = "#94a3b8";

          rollCtx.textAlign = "left";
          rollCtx.textBaseline = "middle";
          rollCtx.fillText(hudText, hX, hY + 13);
          rollCtx.restore();
        }

        // 4. 繪製音符條 (Note Bars) - 強制顯示「數字 + 英文代號」+ 黑曜防殘影底標
        const viewStart = curTime - (playheadX / pxPerSec) - 1.0;
        const viewEnd = curTime + ((stageWidth - playheadX) / pxPerSec) + 1.0;

        for (let i = 0; i < allNotes.length; i++) {
          const n = allNotes[i];
          if (n.end < viewStart || n.start > viewEnd) continue;

          const x = playheadX + (n.start - curTime) * pxPerSec;
          const w = Math.max(n.duration * pxPerSec, 8);
          const y = stageHeight - (n.midi - minMidi + 1) * laneH + 2;
          const h = Math.max(laneH - 4, 14);
          const radius = Math.min(h / 2, 8);

          const isCurrentlySinging = (curTime >= n.start && curTime <= n.end);

          rollCtx.beginPath();
          rollCtx.roundRect(x, y, w, h, radius);

          if (isCurrentlySinging) {
            rollCtx.fillStyle = "#fbbf24";
            rollCtx.fill();
            rollCtx.lineWidth = 2.5;
            rollCtx.strokeStyle = "#ffffff";
            rollCtx.stroke();

            rollCtx.save();
            rollCtx.shadowColor = "#fbbf24";
            rollCtx.shadowBlur = 24;
            rollCtx.fillStyle = "#ffffff";
            rollCtx.beginPath();
            rollCtx.arc(playheadX, y + h / 2, Math.max(h * 0.55, 8), 0, Math.PI * 2);
            rollCtx.fill();
            rollCtx.restore();

          } else if (n.end < curTime) {
            rollCtx.fillStyle = "rgba(2, 132, 199, 0.45)";
            rollCtx.fill();
            rollCtx.strokeStyle = "rgba(56, 189, 248, 0.35)";
            rollCtx.lineWidth = 1.2;
            rollCtx.stroke();

          } else {
            const barGrad = rollCtx.createLinearGradient(x, y, x, y + h);
            barGrad.addColorStop(0, "#38bdf8");
            barGrad.addColorStop(1, "#0284c7");
            rollCtx.fillStyle = barGrad;
            rollCtx.fill();
            rollCtx.strokeStyle = "rgba(255, 255, 255, 0.6)";
            rollCtx.lineWidth = 1.4;
            rollCtx.stroke();
          }

          // ========================================================
          // 【強制設定：全音符 100% 顯示「數字 + 英文音名」+ 防殘影膠囊底標】
          // ========================================================
          const jianpu = midiToJianpuInfo(n.midi, keyOffset);
          let label = jianpu.number + (jianpu.acc || "");
          if (jianpu.dotsTop > 0) label = "•" + label;
          if (jianpu.dotsBottom > 0) label = label + "•";

          // 強制所有音符條均拼出 "簡譜 + 英文代號"，例如 "5̇ G4"、"1 C4"
          const fullLabelText = `${label} ${n.pitch}`;

          const fontSize = Math.max(12, Math.min(h * 0.72, 18));
          rollCtx.font = `900 ${fontSize}px "Courier New", system-ui, sans-serif`;

          const textMetrics = rollCtx.measureText(fullLabelText);
          const textW = textMetrics.width;

          // 膠囊底框寬度自適應 (即使音符短，底標也不會截斷文字)
          const badgeW = Math.max(w - 2, textW + 10);
          const badgeH = Math.max(h - 4, 18);
          const badgeX = x + (w - badgeW) / 2;
          const badgeY = y + (h - badgeH) / 2;

          rollCtx.save();
          // 繪製【黑曜高對比防殘影底框】：隔離動態背景，邊緣極致銳利，徹底告別色彩拖尾與殘影
          rollCtx.fillStyle = isCurrentlySinging ? "rgba(0, 0, 0, 0.88)" : "rgba(8, 13, 24, 0.9)";
          rollCtx.strokeStyle = isCurrentlySinging ? "#fbbf24" : "rgba(56, 189, 248, 0.65)";
          rollCtx.lineWidth = 1;
          rollCtx.beginPath();
          rollCtx.roundRect(badgeX, badgeY, badgeW, badgeH, 5);
          rollCtx.fill();
          rollCtx.stroke();

          // 繪製特高對比度文字
          rollCtx.fillStyle = isCurrentlySinging ? "#fbbf24" : "#ffffff";
          rollCtx.textAlign = "center";
          rollCtx.textBaseline = "middle";
          rollCtx.fillText(fullLabelText, badgeX + badgeW / 2, badgeY + badgeH / 2);
          rollCtx.restore();
        }

        // 5. 繪製「🔁 A-B 循環練唱區間」高亮光帶與 A/B 點地標
        if (loopB > loopA) {
          const xA = playheadX + (loopA - curTime) * pxPerSec;
          const xB = playheadX + (loopB - curTime) * pxPerSec;
          const clampXA = Math.max(pianoKeyWidth, xA);
          const clampXB = Math.min(stageWidth, xB);

          if (clampXB > clampXA) {
            rollCtx.save();
            rollCtx.fillStyle = isLoopActive ? "rgba(16, 185, 129, 0.08)" : "rgba(148, 163, 184, 0.04)";
            rollCtx.fillRect(clampXA, 0, clampXB - clampXA, stageHeight);

            // 頂部循環區域條
            if (isLoopActive) {
              rollCtx.fillStyle = "rgba(16, 185, 129, 0.4)";
              rollCtx.fillRect(clampXA, 0, clampXB - clampXA, 4);

              // 循環區間中央提示浮水印
              if (clampXB - clampXA > 140) {
                rollCtx.font = "bold 11px system-ui, sans-serif";
                rollCtx.fillStyle = "rgba(16, 185, 129, 0.4)";
                rollCtx.textAlign = "center";
                rollCtx.fillText("🔁 A-B 循環練習區間", (clampXA + clampXB) / 2, 40);
              }
            }
            rollCtx.restore();
          }
        }

        // 繪製 A 點垂直地標線
        if (loopA > 0) {
          const xA = playheadX + (loopA - curTime) * pxPerSec;
          if (xA >= pianoKeyWidth && xA <= stageWidth) {
            rollCtx.save();
            rollCtx.strokeStyle = "#10b981";
            rollCtx.lineWidth = 2.2;
            rollCtx.setLineDash([5, 4]);
            rollCtx.beginPath();
            rollCtx.moveTo(xA, 0);
            rollCtx.lineTo(xA, stageHeight);
            rollCtx.stroke();
            rollCtx.setLineDash([]);

            // 底部 A 點旗標標籤
            const textA = `📍 A 點 ${formatTime(loopA)}`;
            rollCtx.font = "bold 11px system-ui, sans-serif";
            const twA = rollCtx.measureText(textA).width;
            rollCtx.fillStyle = "rgba(6, 78, 59, 0.95)";
            rollCtx.strokeStyle = "#10b981";
            rollCtx.lineWidth = 1.2;
            rollCtx.beginPath();
            rollCtx.roundRect(xA - twA / 2 - 6, stageHeight - 26, twA + 12, 20, 4);
            rollCtx.fill();
            rollCtx.stroke();

            rollCtx.fillStyle = "#6ee7b7";
            rollCtx.textAlign = "center";
            rollCtx.textBaseline = "middle";
            rollCtx.fillText(textA, xA, stageHeight - 16);
            rollCtx.restore();
          }
        }

        // 繪製 B 點垂直地標線
        if (loopB > 0) {
          const xB = playheadX + (loopB - curTime) * pxPerSec;
          if (xB >= pianoKeyWidth && xB <= stageWidth) {
            rollCtx.save();
            rollCtx.strokeStyle = "#f59e0b";
            rollCtx.lineWidth = 2.2;
            rollCtx.setLineDash([5, 4]);
            rollCtx.beginPath();
            rollCtx.moveTo(xB, 0);
            rollCtx.lineTo(xB, stageHeight);
            rollCtx.stroke();
            rollCtx.setLineDash([]);

            // 底部 B 點旗標標籤
            const textB = `🏁 B 點 ${formatTime(loopB)}`;
            rollCtx.font = "bold 11px system-ui, sans-serif";
            const twB = rollCtx.measureText(textB).width;
            rollCtx.fillStyle = "rgba(120, 53, 15, 0.95)";
            rollCtx.strokeStyle = "#f59e0b";
            rollCtx.lineWidth = 1.2;
            rollCtx.beginPath();
            rollCtx.roundRect(xB - twB / 2 - 6, stageHeight - 26, twB + 12, 20, 4);
            rollCtx.fill();
            rollCtx.stroke();

            rollCtx.fillStyle = "#fbbf24";
            rollCtx.textAlign = "center";
            rollCtx.textBaseline = "middle";
            rollCtx.fillText(textB, xB, stageHeight - 16);
            rollCtx.restore();
          }
        }

        // 6. 【即時拖曳時間軸 HUD 浮層提示】
        if (isRollScrubbing) {
          const deltaT = audio.currentTime - scrubStartTime;
          const sign = deltaT >= 0 ? "+" : "";
          const icon = deltaT >= 0 ? "⏩ 拖曳快轉" : "⏪ 拖曳倒帶";
          const scrubHudText = `${icon}：${formatTime(audio.currentTime)} (${sign}${deltaT.toFixed(1)}s) ── 放開滑鼠立即接續播放`;

          rollCtx.save();
          rollCtx.font = "bold 15px system-ui, sans-serif";
          const stw = rollCtx.measureText(scrubHudText).width;
          const shx = Math.max(10, (stageWidth - stw) / 2);
          const shy = 42;

          rollCtx.fillStyle = "rgba(10, 16, 28, 0.95)";
          rollCtx.strokeStyle = "#fbbf24";
          rollCtx.lineWidth = 2.2;
          rollCtx.shadowColor = "rgba(251, 191, 36, 0.6)";
          rollCtx.shadowBlur = 18;
          rollCtx.beginPath();
          rollCtx.roundRect(shx - 16, shy - 14, stw + 32, 34, 8);
          rollCtx.fill();
          rollCtx.stroke();

          rollCtx.fillStyle = "#fbbf24";
          rollCtx.textAlign = "center";
          rollCtx.textBaseline = "middle";
          rollCtx.fillText(scrubHudText, stageWidth / 2, shy + 3);
          rollCtx.restore();
        }
      }

      const miniSection = document.getElementById("minimapSection");
      if (!miniSection.classList.contains("collapsed")) {
        updateMinimapPlayhead(curTime);
      }
    }

    // ==========================================
    // 底部全曲 Minimap 繪製與點擊跳轉
    // ==========================================
    function drawMinimap() {
      if (!currentData || !currentData.data) return;
      const mW = minimapCanvas.width / dpr;
      const mH = minimapCanvas.height / dpr;
      if (mW === 0 || mH === 0) return;
      const totalDur = audio.duration || (currentData.data[currentData.data.length - 1].end + 5);

      minimapCtx.fillStyle = "#080c17";
      minimapCtx.fillRect(0, 0, mW, mH);

      const totalSemis = maxMidi - minMidi + 1;
      const mPxPerSec = mW / totalDur;

      minimapCtx.fillStyle = "#0284c7";
      for (const n of currentData.data) {
        const x = n.start * mPxPerSec;
        const w = Math.max(n.duration * mPxPerSec, 1.5);
        const y = mH - ((n.midi - minMidi + 1) / totalSemis) * mH;
        const h = Math.max(mH / totalSemis, 2);
        minimapCtx.fillRect(x, y, w, h);
      }
    }

    function updateMinimapPlayhead(curTime) {
      if (!currentData || !audio.duration) return;
      const mW = minimapCanvas.width / dpr;
      const mH = minimapCanvas.height / dpr;
      if (mW === 0 || mH === 0) return;
      const totalDur = audio.duration;
      const mPxPerSec = mW / totalDur;

      drawMinimap();

      const playheadX = stageWidth * 0.24;
      const pxPerSec = (stageWidth - playheadX) / visibleTimeSpan;
      const viewStart = Math.max(0, curTime - (playheadX / pxPerSec));
      const viewEnd = Math.min(totalDur, curTime + ((stageWidth - playheadX) / pxPerSec));

      const boxX = viewStart * mPxPerSec;
      const boxW = Math.max((viewEnd - viewStart) * mPxPerSec, 4);

      minimapCtx.fillStyle = "rgba(56, 189, 248, 0.18)";
      minimapCtx.fillRect(boxX, 0, boxW, mH);
      minimapCtx.strokeStyle = "rgba(56, 189, 248, 0.6)";
      minimapCtx.lineWidth = 1;
      minimapCtx.strokeRect(boxX, 0, boxW, mH);

      // 繪製 A-B 循環區間在縮圖上的覆蓋標示
      if (loopB > loopA) {
        const loopStartM = loopA * mPxPerSec;
        const loopEndM = loopB * mPxPerSec;
        minimapCtx.fillStyle = isLoopActive ? "rgba(16, 185, 129, 0.35)" : "rgba(148, 163, 184, 0.2)";
        minimapCtx.fillRect(loopStartM, 0, Math.max(3, loopEndM - loopStartM), mH);
      }

      const curX = curTime * mPxPerSec;
      minimapCtx.fillStyle = "#fbbf24";
      minimapCtx.fillRect(curX - 1.5, 0, 3, mH);
    }

    const minimapWrapper = document.getElementById("minimapWrapper");
    function handleMinimapSeek(e) {
      if (!audio.duration) return;
      const rect = minimapWrapper.getBoundingClientRect();
      const clickX = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
      const targetTime = (clickX / rect.width) * audio.duration;
      audio.currentTime = targetTime;
      updateScrubSlider(targetTime, audio.duration);
    }
    minimapWrapper.addEventListener("click", handleMinimapSeek);

    audio.addEventListener("play", () => { playBtn.textContent = "⏸"; });
    audio.addEventListener("pause", () => { playBtn.textContent = "▶"; });
    audio.addEventListener("ended", () => {
      if (isLoopActive && loopB > loopA) {
        audio.currentTime = loopA;
        audio.play();
        playBtn.textContent = "⏸";
        updateScrubSlider(loopA, audio.duration);
        showToast(`🔁 循環：已回到 A 點 ${formatTime(loopA)} 繼續播放`);
      } else {
        audio.currentTime = loopA;
        playBtn.textContent = "▶";
        updateScrubSlider(loopA, audio.duration);
        showToast(`歌曲結束，已回到起點 ${formatTime(loopA)}`);
      }
    });
    audio.addEventListener("seeked", () => {
      updateScrubSlider(audio.currentTime, audio.duration);
    });

    function showToast(msg, isError = false) {
      const toast = document.getElementById("toast");
      toast.textContent = msg;
      toast.style.borderColor = isError ? "#ef4444" : "#38bdf8";
      toast.style.color = isError ? "#f87171" : "#38bdf8";
      toast.style.display = "flex";
      setTimeout(() => { toast.style.display = "none"; }, 2000);
    }

    window.onload = () => {
      init();
      requestAnimationFrame(renderRollFrame);
    };
  </script>
</body>
</html>
"""

class ToneDeafHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)

            if path == "/" or path == "/index.html":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
                return

            elif path == "/api/tracks":
                files = set()
                for p in OUTPUT_DIR.glob("*_pitch.json"):
                    files.add(p.name)
                for p in OUTPUT_DIR.glob("*_lyrics_pitch.json"):
                    files.add(p.name)
                json_files = sorted(list(files))
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps(json_files).encode("utf-8"))
                return

            elif path == "/api/load":
                file_name = query.get("file", [""])[0]
                target = OUTPUT_DIR / file_name
                if target.exists() and target.is_file():
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    with open(target, "rb") as f:
                        self.wfile.write(f.read())
                    return
                else:
                    self.send_error(404, "File not found")
                    return

            elif path.startswith("/audio/"):
                audio_name = path[len("/audio/"):]
                audio_path = OUTPUT_DIR / audio_name
                if not audio_path.exists():
                    audio_path = PROJECT_ROOT / audio_name

                if audio_path.exists() and audio_path.is_file():
                    file_size = audio_path.stat().st_size
                    content_type = "audio/wav" if audio_path.suffix.lower() == ".wav" else "audio/mpeg"

                    range_header = self.headers.get("Range")
                    if range_header and range_header.startswith("bytes="):
                        range_val = range_header[len("bytes="):].strip()
                        parts = range_val.split("-")
                        start = int(parts[0]) if parts[0] else 0
                        end = int(parts[1]) if len(parts) > 1 and parts[1] else file_size - 1
                        end = min(end, file_size - 1)
                        content_len = end - start + 1

                        self.send_response(206)
                        self.send_header("Content-Type", content_type)
                        self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                        self.send_header("Content-Length", str(content_len))
                        self.send_header("Accept-Ranges", "bytes")
                        self.end_headers()

                        with open(audio_path, "rb") as f:
                            f.seek(start)
                            remaining = content_len
                            while remaining > 0:
                                chunk_size = min(64 * 1024, remaining)
                                chunk = f.read(chunk_size)
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                                remaining -= len(chunk)
                        return
                    else:
                        self.send_response(200)
                        self.send_header("Content-Type", content_type)
                        self.send_header("Content-Length", str(file_size))
                        self.send_header("Accept-Ranges", "bytes")
                        self.end_headers()
                        with open(audio_path, "rb") as f:
                            while chunk := f.read(64 * 1024):
                                self.wfile.write(chunk)
                        return
                else:
                    self.send_error(404, "Audio not found")
                    return

            else:
                self.send_error(404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            try:
                self.send_error(500, str(e))
            except Exception:
                pass

def run_server(start_port=8765):
    from http.server import ThreadingHTTPServer
    port = start_port
    while port < start_port + 50:
        try:
            server_address = ("127.0.0.1", port)
            ThreadingHTTPServer.allow_reuse_address = True
            httpd = ThreadingHTTPServer(server_address, ToneDeafHandler)
            print("=" * 60)
            print(f"🎵 ToneDeaf 防殘影全代號版伺服器已啟動！")
            print(f"👉 請在瀏覽器打開：http://localhost:{port}")
            print("=" * 60)
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print("\n伺服器已停止。")
                httpd.server_close()
            break
        except OSError as e:
            if e.errno == 48:
                port += 1
            else:
                raise

if __name__ == "__main__":
    port = 8765
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    run_server(port)

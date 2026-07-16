from __future__ import annotations

import json

# ブラウザ側フレーム送信間隔(ミリ秒)。サーバー側の受信レートと整合させる。
_SEND_INTERVAL_MS = 500

# 画面選択ページのテンプレート。{token} と {send_interval_ms} を埋め込んで配信する。
_CAPTURE_PAGE_TEMPLATE = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8" />
<title>Screen Translation - 画面選択</title>
<style>
  body {{ font-family: sans-serif; background: #111; color: #eee; margin: 0; padding: 24px; }}
  h1 {{ font-size: 18px; }}
  button {{
    font-size: 16px; padding: 10px 20px; border-radius: 6px; border: none;
    background: #2f8fff; color: #fff; cursor: pointer; margin-right: 8px;
  }}
  button:disabled {{ background: #555; cursor: default; }}
  #status {{ margin-top: 16px; white-space: pre-wrap; }}
  video {{ margin-top: 16px; max-width: 100%; border: 1px solid #444; background: #000; }}
</style>
</head>
<body>
<h1>Screen Translation: 翻訳する画面を選択してください</h1>
<button id="start">画面を選択して開始</button>
<button id="stop" disabled>共有を停止</button>
<div id="status">画面、ウィンドウ、またはタブを選択してください。</div>
<video id="preview" autoplay muted playsinline hidden></video>
<script>
(function () {{
  // このタブに割り当てられたセッショントークン。再選択のたびに更新され、
  // 古いトークンからの送信はサーバー側で拒否される。
  const SESSION_TOKEN = {token_json};
  const SEND_INTERVAL_MS = {send_interval_ms};
  const startButton = document.getElementById("start");
  const stopButton = document.getElementById("stop");
  const statusEl = document.getElementById("status");
  const video = document.getElementById("preview");
  const canvas = document.createElement("canvas");
  let stream = null;
  let sendTimer = null;

  function setStatus(text) {{
    statusEl.textContent = text;
  }}

  function sendFrame() {{
    if (!video.videoWidth || !video.videoHeight) {{
      return;
    }}
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const context = canvas.getContext("2d");
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(
      function (blob) {{
        if (!blob) {{
          return;
        }}
        fetch("/frame", {{
          method: "POST",
          headers: {{
            "Content-Type": "image/jpeg",
            "X-Capture-Token": SESSION_TOKEN,
          }},
          body: blob,
        }})
          .then(function (response) {{
            // 403 はセッション失効(停止・再選択)を意味するので送信を止める。
            if (response.status === 403) {{
              stopSharing();
              setStatus("このタブのセッションは終了しました。アプリ側で選び直してください。");
            }}
          }})
          .catch(function () {{}});
      }},
      "image/jpeg",
      0.8
    );
  }}

  function stopSharing() {{
    if (sendTimer !== null) {{
      clearInterval(sendTimer);
      sendTimer = null;
    }}
    if (stream !== null) {{
      stream.getTracks().forEach(function (track) {{
        track.stop();
      }});
      stream = null;
    }}
    video.hidden = true;
    startButton.disabled = false;
    stopButton.disabled = true;
  }}

  function stopByUser() {{
    stopSharing();
    setStatus("共有を終了しました。もう一度「画面を選択して開始」を押すと選び直せます。");
  }}

  async function startSharing() {{
    try {{
      stream = await navigator.mediaDevices.getDisplayMedia({{
        video: {{ frameRate: 5 }},
        audio: false,
      }});
    }} catch (error) {{
      setStatus("画面の選択がキャンセルされたか、失敗しました: " + error);
      return;
    }}
    video.srcObject = stream;
    video.hidden = false;
    startButton.disabled = true;
    stopButton.disabled = false;
    setStatus("送信中です。このタブは翻訳中も開いたままにしてください。");
    stream.getVideoTracks()[0].addEventListener("ended", stopByUser);
    sendTimer = setInterval(sendFrame, SEND_INTERVAL_MS);
  }}

  startButton.addEventListener("click", startSharing);
  stopButton.addEventListener("click", stopByUser);
  window.addEventListener("pagehide", stopSharing);
}})();
</script>
</body>
</html>
"""


def render_capture_page(token: str) -> str:
    """セッショントークンを埋め込んだ画面選択ページのHTMLを生成する。"""
    return _CAPTURE_PAGE_TEMPLATE.format(
        token_json=json.dumps(token),
        send_interval_ms=_SEND_INTERVAL_MS,
    )

(() => {
  "use strict";
  if (window.__peakcutCustomLayoutLoaded) return;
  window.__peakcutCustomLayoutLoaded = true;

  const $ = (s, r = document) => r.querySelector(s);
  const clamp = (n, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, n));
  const clone = v => JSON.parse(JSON.stringify(v));
  const defaults = () => ({
    version: 1,
    source: {facecam: null, gameplay: null},
    frames: {facecam: [0, 0, 1, 0.36], gameplay: [0, 0.36, 1, 0.64]}
  });

  const style = document.createElement("style");
  style.textContent =
    ".pc-custom-layout{margin:14px 0;padding:14px;border:1px solid var(--line-2);border-radius:14px;background:var(--muted);display:grid;gap:14px}" +
    ".pc-custom-layout[hidden]{display:none!important}" +
    ".pc-layout-head{display:flex;justify-content:space-between;align-items:center;gap:8px}.pc-layout-head h3{margin:0}" +
    ".pc-layout-grid{display:grid;grid-template-columns:minmax(0,1fr);gap:20px;align-items:start}" +
    ".pc-layout-section{min-width:0;display:grid;gap:9px}.pc-layout-section h4{margin:0;font-size:13px}" +
    ".pc-layout-tools,.pc-layout-presets{display:flex;flex-wrap:wrap;gap:6px}" +
    ".pc-layout-tools button,.pc-layout-presets button{font-size:12px;padding:7px 9px}" +
    ".pc-layout-tools button.on,.pc-layout-presets button.on{background:var(--brand-soft);border-color:var(--brand);color:var(--brand-deep)}" +
    ".pc-source-stage{position:relative;width:100%;max-width:100%;aspect-ratio:16/9;background:#171310;border:1px solid var(--line-2);border-radius:10px;overflow:hidden;touch-action:none}" +
    ".pc-source-stage video{position:absolute;inset:0;width:100%;height:100%;object-fit:fill;background:#171310}" +
    ".pc-source-overlay{position:absolute;inset:0;touch-action:none;cursor:crosshair}" +
    ".pc-source-box{position:absolute;border:3px solid #20d7cf;background:rgba(32,215,207,.12);box-sizing:border-box;pointer-events:auto}" +
    ".pc-source-box.gameplay{border-color:#ff9b43;background:rgba(255,155,67,.10)}" +
    ".pc-source-box span{position:absolute;left:0;top:0;max-width:100%;padding:3px 6px;background:#111d;color:#fff;font-size:12px;white-space:nowrap}" +
    ".pc-handle{position:absolute;right:-7px;bottom:-7px;width:16px;height:16px;border-radius:3px;background:#fff;border:1px solid #222;cursor:nwse-resize}" +
    ".pc-source-help{font-size:12px;color:var(--dim);line-height:1.4}" +
    ".pc-source-play{display:flex;gap:8px;align-items:center}.pc-source-play input{min-width:0;flex:1}" +
    ".pc-output-wrap{display:flex;justify-content:center;min-width:0}" +
    ".pc-output-stage{position:relative;width:min(100%,360px);min-width:0;line-height:0}" +
    ".pc-output-canvas{width:100%;height:auto;display:block;border:1px solid var(--line-2);border-radius:10px;background:#171310;touch-action:none;cursor:grab}" +
    ".pc-output-canvas:active{cursor:grabbing}" +
    ".pc-output-guides{position:absolute;inset:0;pointer-events:none}" +
    ".pc-output-guide{position:absolute;box-sizing:border-box;border:3px solid;pointer-events:none}" +
    ".pc-output-guide.facecam{border-color:#20d7cf}.pc-output-guide.gameplay{border-color:#ff9b43}" +
    ".pc-output-guide span{position:absolute;left:3px;top:3px;padding:2px 5px;background:#111d;color:#fff;font:10px/1.2 sans-serif;white-space:nowrap}" +
    ".pc-output-guide i{position:absolute;right:-2px;bottom:-2px;width:8px;height:8px;background:#fff;border:1px solid #222}" +
    ".pc-layout-message{font-size:12px;color:var(--dim);min-height:18px}.pc-layout-section:first-child,.pc-layout-section:nth-child(2){width:100%}.pc-layout-message.bad{color:var(--bad)}" +
    "@media(max-width:760px){.pc-layout-grid{grid-template-columns:1fr}.pc-output-stage{width:min(70%,360px)}}";
  document.head.append(style);

  const presets = {
    top: {facecam:[0,0,1,.36], gameplay:[0,.36,1,.64]},
    bottom: {gameplay:[0,0,1,.64], facecam:[0,.64,1,.36]},
    overlay: {gameplay:[0,0,1,1], facecam:[.64,.035,.32,.22]},
    side: {facecam:[0,0,.5,1], gameplay:[.5,0,.5,1]}
  };

  let panel = null, mount = null, state = null, video = null, canvas = null;
  let outputFaceGuide = null, outputGameGuide = null, videoFramePending = false;
  let activeSource = "facecam", drag = null;

  function validSource() {
    return !!(state && state.source.facecam && state.source.gameplay);
  }
  function saveHidden() {
    const input = $("#pcCustomLayoutValue", panel);
    if (input) input.value = validSource() ? JSON.stringify(state) : "";
  }
  function message(text, bad = false) {
    const el = $("#pcLayoutMessage", panel);
    if (!el) return;
    el.textContent = text;
    el.classList.toggle("bad", bad);
  }
  function sourceBoxMarkup(name, rect) {
    if (!rect) return "";
    const cls = name === "gameplay" ? "gameplay" : "";
    return '<div class="pc-source-box ' + cls + '" data-pc-source-box="' + name +
      '" style="left:' + (rect[0]*100) + '%;top:' + (rect[1]*100) + '%;width:' + (rect[2]*100) +
      '%;height:' + (rect[3]*100) + '%"><span>' +
      (name === "facecam" ? "STREAMER FACECAM" : "GAMEPLAY AREA") + '</span><i class="pc-handle"></i></div>';
  }
  function drawSourceBoxes() {
    const layer = $("#pcSourceOverlay", panel);
    if (layer) layer.innerHTML = sourceBoxMarkup("gameplay", state.source.gameplay) + sourceBoxMarkup("facecam", state.source.facecam);
  }
  function drawCanvas() {
    if (!canvas || !panel || panel.hidden) return;
    const ctx = canvas.getContext("2d"), w = canvas.width, h = canvas.height;
    ctx.fillStyle = "#171310"; ctx.fillRect(0, 0, w, h);
    const vw = video ? video.videoWidth : 0, vh = video ? video.videoHeight : 0;
    const ready = video && video.readyState >= 2;
    for (const name of ["gameplay", "facecam"]) {
      const src = state.source[name], frame = state.frames[name];
      const dx = frame[0]*w, dy = frame[1]*h, dw = frame[2]*w, dh = frame[3]*h;
      if (ready && src) {
        try {
          // Match FFmpeg's scale-to-fill then centre-crop behaviour, so the preview
          // shows the same crop as the exported clip.
          let sx = src[0]*vw, sy = src[1]*vh, sw = src[2]*vw, sh = src[3]*vh;
          const targetRatio = dw / Math.max(1, dh), sourceRatio = sw / Math.max(1, sh);
          if (sourceRatio > targetRatio) {
            const croppedWidth = sh * targetRatio;
            sx += (sw - croppedWidth) / 2;
            sw = croppedWidth;
          } else {
            const croppedHeight = sw / targetRatio;
            sy += (sh - croppedHeight) / 2;
            sh = croppedHeight;
          }
          ctx.drawImage(video, sx, sy, sw, sh, dx, dy, dw, dh);
        } catch {
          ctx.fillStyle = "#28211c"; ctx.fillRect(dx, dy, dw, dh);
        }
      } else {
        ctx.fillStyle = "#28211c"; ctx.fillRect(dx, dy, dw, dh);
        ctx.fillStyle = "#f4eeea"; ctx.font = "bold 15px sans-serif"; ctx.textAlign = "center";
        ctx.fillText(src ? name.toUpperCase() : "SELECT " + name.toUpperCase(), dx+dw/2, dy+dh/2);
      }
    }
  }
  function drawOutputGuides() {
    if (!panel || panel.hidden) return;
    const set = (node, rect) => {
      if (!node || !rect) return;
      node.style.left = (rect[0] * 100) + "%";
      node.style.top = (rect[1] * 100) + "%";
      node.style.width = (rect[2] * 100) + "%";
      node.style.height = (rect[3] * 100) + "%";
    };
    set(outputGameGuide, state.frames.gameplay);
    set(outputFaceGuide, state.frames.facecam);
  }
  function scheduleVideoFrame() {
    if (!video || !panel || panel.hidden || video.paused ||
        typeof video.requestVideoFrameCallback !== "function" || videoFramePending) return;
    videoFramePending = true;
    video.requestVideoFrameCallback(() => {
      videoFramePending = false;
      if (!video || !panel || panel.hidden || video.paused) return;
      if (!drag) drawCanvas();
      scheduleVideoFrame();
    });
  }
  function refresh() { drawSourceBoxes(); drawCanvas(); drawOutputGuides(); saveHidden(); }
  function setActiveSource(name) {
    activeSource = name;
    panel.querySelectorAll("[data-pc-source]").forEach(b => b.classList.toggle("on", b.dataset.pcSource === name));
    message("Drag on the original video to select the " +
      (name === "facecam" ? "streamer's facecam" : "gameplay") +
      " area. Drag an existing box to move it or its corner to resize it.");
  }
  function applyPreset(name) {
    state.frames = clone(presets[name]);
    panel.querySelectorAll("[data-pc-preset]").forEach(b => b.classList.toggle("on", b.dataset.pcPreset === name));
    refresh();
  }
  function buildPanel() {
    const host = document.createElement("section");
    host.className = "pc-custom-layout";
    host.id = "pcCustomLayoutPanel";
    host.hidden = true;
    host.innerHTML =
      '<div class="pc-layout-head"><h3>Custom 9:16 layout editor</h3><span class="sub">Original source → vertical Short</span></div>' +
      '<div class="pc-layout-grid"><div class="pc-layout-section"><h4>1. Select areas from the original video</h4>' +
      '<div class="pc-layout-tools"><button type="button" class="btn sm on" data-pc-source="facecam">Select streamer facecam</button>' +
      '<button type="button" class="btn sm" data-pc-source="gameplay">Select gameplay</button></div>' +
      '<div class="pc-source-stage" id="pcSourceStage"><video id="pcSourceVideo" muted playsinline preload="metadata"></video>' +
      '<div class="pc-source-overlay" id="pcSourceOverlay"></div></div>' +
      '<div class="pc-source-play"><button type="button" class="btn sm" id="pcSourcePlay">Play</button>' +
      '<input type="range" id="pcSourceSeek" min="0" max="1000" value="0" aria-label="Preview time"></div>' +
      '<p class="pc-source-help">Choose facecam and gameplay separately. Drag a new box over the source video; move existing boxes or resize their lower-right corner.</p></div>' +
      '<div class="pc-layout-section"><h4>2. Arrange both areas on the 9:16 output</h4><div class="pc-layout-presets">' +
      '<button type="button" class="btn sm on" data-pc-preset="top">Facecam top</button><button type="button" class="btn sm" data-pc-preset="bottom">Facecam bottom</button>' +
      '<button type="button" class="btn sm" data-pc-preset="overlay">Facecam overlay</button><button type="button" class="btn sm" data-pc-preset="side">Side by side</button></div>' +
      '<div class="pc-output-wrap"><div class="pc-output-stage">' +
      '<canvas class="pc-output-canvas" id="pcOutputCanvas" width="360" height="640" aria-label="Drag frames to arrange the vertical output"></canvas>' +
      '<div class="pc-output-guides" aria-hidden="true">' +
      '<div class="pc-output-guide gameplay" id="pcOutputGameplayGuide"><span>GAMEPLAY</span><i></i></div>' +
      '<div class="pc-output-guide facecam" id="pcOutputFacecamGuide"><span>FACECAM</span><i></i></div>' +
      '</div></div></div>' +
      '<p class="pc-source-help">Drag either outline to move it. Drag its lower-right corner to resize it. The video preview refreshes when you release, keeping movement smooth. Gameplay is placed first, then facecam.</p>' +
      '<button type="button" class="btn sm" id="pcSwapFrames">Swap frame positions</button><p class="pc-layout-message" id="pcLayoutMessage" aria-live="polite"></p></div></div>' +
      '<input type="hidden" data-f="custom_layout" id="pcCustomLayoutValue" value="">';
    mount.append(host);
    panel = host;
    video = $("#pcSourceVideo", panel);
    canvas = $("#pcOutputCanvas", panel);
    outputGameGuide = $("#pcOutputGameplayGuide", panel);
    outputFaceGuide = $("#pcOutputFacecamGuide", panel);
    video.src = "/api/jobs/" + encodeURIComponent(mount.dataset.jid) +
      "/clips/" + encodeURIComponent(mount.dataset.cid) + "/source";
    video.addEventListener("loadedmetadata", () => {
      $("#pcSourceStage", panel).style.aspectRatio = video.videoWidth + "/" + video.videoHeight;
      const start = Math.max(0, Number(mount.dataset.start || 0) - Number(mount.dataset.offset || 0));
      try { video.currentTime = Math.min(start, Math.max(0, video.duration - .1)); } catch {}
      refresh();
      message("Original video loaded. Select the facecam and gameplay areas.");
    });
    video.addEventListener("loadeddata", drawCanvas);
    video.addEventListener("seeked", () => { if (!drag) drawCanvas(); });
    video.addEventListener("play", scheduleVideoFrame);
    video.addEventListener("pause", () => { if (!drag) drawCanvas(); });
    video.addEventListener("timeupdate", () => {
      $("#pcSourceSeek", panel).value = String(Math.round(video.currentTime / Math.max(video.duration, .001) * 1000));
      if (typeof video.requestVideoFrameCallback !== "function" && !drag) drawCanvas();
    });
    video.addEventListener("error", () => message("The original source preview is unavailable for this clip. Try a clip whose source video is still saved.", true));
    $("#pcSourcePlay", panel).addEventListener("click", async () => {
      const b = $("#pcSourcePlay", panel);
      if (video.paused) {
        try { await video.play(); b.textContent = "Pause"; }
        catch { message("The source preview could not play.", true); }
      } else {
        video.pause(); b.textContent = "Play";
      }
    });
    $("#pcSourceSeek", panel).addEventListener("input", e => {
      if (video.duration) video.currentTime = Number(e.target.value) / 1000 * video.duration;
    });
    panel.querySelectorAll("[data-pc-source]").forEach(b => b.addEventListener("click", () => setActiveSource(b.dataset.pcSource)));
    panel.querySelectorAll("[data-pc-preset]").forEach(b => b.addEventListener("click", () => applyPreset(b.dataset.pcPreset)));
    $("#pcSwapFrames", panel).addEventListener("click", () => {
      const a = state.frames.facecam;
      state.frames.facecam = state.frames.gameplay;
      state.frames.gameplay = a;
      refresh();
    });
    bindSourceDragging();
    bindOutputDragging();
    refresh();
  }
  function bindSourceDragging() {
    const stage = $("#pcSourceStage", panel), overlay = $("#pcSourceOverlay", panel);
    overlay.addEventListener("pointerdown", e => {
      const rect = stage.getBoundingClientRect();
      const p = {x:clamp((e.clientX-rect.left)/rect.width), y:clamp((e.clientY-rect.top)/rect.height)};
      const boxEl = e.target.closest("[data-pc-source-box]");
      let name = activeSource, mode = "draw";
      if (boxEl) {
        name = boxEl.dataset.pcSourceBox;
        mode = e.target.closest(".pc-handle") ? "resize" : "move";
        activeSource = name; setActiveSource(name);
      }
      const before = state.source[name] ? [...state.source[name]] : [p.x,p.y,.03,.03];
      if (mode === "draw") state.source[name] = [p.x,p.y,.001,.001];
      drag = {kind:"source",name,mode,start:p,before};
      overlay.setPointerCapture(e.pointerId);
      e.preventDefault();
    });
    overlay.addEventListener("pointermove", e => {
      if (!drag || drag.kind !== "source") return;
      const rect = stage.getBoundingClientRect();
      const p = {x:clamp((e.clientX-rect.left)/rect.width), y:clamp((e.clientY-rect.top)/rect.height)};
      const d=drag, b=d.before;
      if (d.mode === "draw") {
        state.source[d.name] = [Math.min(d.start.x,p.x),Math.min(d.start.y,p.y),Math.abs(p.x-d.start.x),Math.abs(p.y-d.start.y)];
      } else if (d.mode === "move") {
        state.source[d.name] = [clamp(b[0]+p.x-d.start.x,0,1-b[2]),clamp(b[1]+p.y-d.start.y,0,1-b[3]),b[2],b[3]];
      } else {
        state.source[d.name] = [b[0],b[1],clamp(b[2]+p.x-d.start.x,.02,1-b[0]),clamp(b[3]+p.y-d.start.y,.02,1-b[1])];
      }
      drawSourceBoxes();
    });
    const end = () => {
      if (!drag || drag.kind !== "source") return;
      const b=state.source[drag.name];
      if (!b || b[2]<.02 || b[3]<.02) state.source[drag.name]=null;
      drag=null; refresh();
      message(validSource() ? "Both source areas are selected. Arrange the frames, then save and re-make the clip." :
        "Select both the streamer facecam and gameplay areas before re-making the clip.", !validSource());
    };
    overlay.addEventListener("pointerup",end);
    overlay.addEventListener("pointercancel",end);
  }
  function bindOutputDragging() {
    canvas.addEventListener("pointerdown", e => {
      const rect=canvas.getBoundingClientRect(), x=(e.clientX-rect.left)/rect.width, y=(e.clientY-rect.top)/rect.height;
      const name=["facecam","gameplay"].find(n => {
        const b=state.frames[n]; return x>=b[0] && x<=b[0]+b[2] && y>=b[1] && y<=b[1]+b[3];
      });
      if (!name) return;
      const b=[...state.frames[name]], resize=x>b[0]+b[2]-.045 && y>b[1]+b[3]-.045;
      drag={kind:"output",name,mode:resize?"resize":"move",start:{x,y},before:b};
      canvas.setPointerCapture(e.pointerId); e.preventDefault();
    });
    canvas.addEventListener("pointermove", e => {
      if (!drag || drag.kind!=="output") return;
      const rect=canvas.getBoundingClientRect(), p={x:clamp((e.clientX-rect.left)/rect.width), y:clamp((e.clientY-rect.top)/rect.height)};
      const d=drag,b=d.before;
      if (d.mode==="move") state.frames[d.name]=[clamp(b[0]+p.x-d.start.x,0,1-b[2]),clamp(b[1]+p.y-d.start.y,0,1-b[3]),b[2],b[3]];
      else state.frames[d.name]=[b[0],b[1],clamp(b[2]+p.x-d.start.x,.05,1-b[0]),clamp(b[3]+p.y-d.start.y,.05,1-b[1])];
      drawOutputGuides();
    });
    const end=()=>{if(drag?.kind==="output"){drag=null;saveHidden();drawOutputGuides();drawCanvas();}};
    canvas.addEventListener("pointerup",end);
    canvas.addEventListener("pointercancel",end);
  }
  function ensure() {
    const dlg=$("#clipdlg");
    if (!dlg) return;
    const layout=$('[data-f="layout"]',dlg), m=$("#pc-layout-mount",dlg);
    if (!layout || !m) return;
    // buildPanel() appends the editor to this dynamically-created mount element.
    // Keep the current clip dialog mount in the module state before building it.
    mount = m;
    if (![...layout.options].some(o=>o.value==="custom")) {
      const option=document.createElement("option"); option.value="custom"; option.textContent="Custom layout editor"; layout.add(option);
    }
    if (!m.dataset.ready) {
      m.dataset.ready="1";
      try {
        const parsed=JSON.parse(m.dataset.custom || "{}");
        state=parsed && parsed.version===1 ? parsed : defaults();
      } catch { state=defaults(); }
      if (!state.source || !state.frames || !state.frames.facecam || !state.frames.gameplay) state=defaults();
    }
    if (layout.value==="custom") {
      // Build the heavier preview UI only when the user actually selects the custom editor.
      if (!panel || panel.parentElement !== m) buildPanel();
      panel.hidden=false;
      if (!video.paused) scheduleVideoFrame();
      if (panel.dataset.initialized !== "1") {
        panel.dataset.initialized="1";
        refresh();
        if (!validSource()) message("Select the streamer facecam and gameplay areas from the original video.");
      }
    } else if (panel) {
      panel.hidden=true;
      panel.dataset.initialized="";
      if (video && !video.paused) {
        video.pause();
        $("#pcSourcePlay", panel).textContent = "Play";
      }
    }
  }
  document.addEventListener("change", e => {
    if (e.target.matches('#clipdlg [data-f="layout"]')) ensure();
  });
  document.addEventListener("click", e => {
    const button=e.target.closest('[data-act="remake"]');
    if (!button) return;
    const layout=$('#clipdlg [data-f="layout"]');
    if (layout && layout.value==="custom") {
      ensure(); saveHidden();
      if (!validSource()) {
        e.preventDefault(); e.stopImmediatePropagation();
        message("Select both the streamer facecam and gameplay areas before re-making this clip.",true);
      }
    }
  }, true);
  // Explicit initializer for PeakCut's dynamically-created clip dialog.
  // Do not observe dialog mutations: drawing our own selection boxes would trigger
  // the observer again and can freeze the browser in a recursive refresh loop.
  window.initPeakCutCustomLayout = ensure;
})();

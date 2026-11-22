// NovaStream - Content Script (Yüzen Video İndirme HUD Widget'ı + DOM Medya & Altyazı Tarayıcı)

(function () {
  "use strict";

  if (window.__novastream_injected) return;
  window.__novastream_injected = true;

  function extAlive() {
    try {
      return Boolean(chrome.runtime && chrome.runtime.id);
    } catch {
      return false;
    }
  }
  function safeSendMessage(msg, cb) {
    if (!extAlive()) return Promise.resolve(undefined);
    try {
      if (cb) {
        chrome.runtime.sendMessage(msg, (res) => {
          try {
            void chrome.runtime.lastError;
          } catch {}
          cb(res);
        });
        return undefined;
      }
      return chrome.runtime.sendMessage(msg).catch(() => undefined);
    } catch {
      return Promise.resolve(undefined);
    }
  }

  const isYouTube =
    window.location.hostname.includes("youtube.com") ||
    window.location.hostname.includes("youtu.be");

  let floatingButtonEnabled = true;
  let tabMediaItems = [];
  let frameMediaItems = [];
  let tabSubtitles = [];
  let frameSubtitles = [];
  const activeDownloads = new Map();
  const videoOverlayMap = new Map(); // videoElement -> record
  const dismissedVideos = new WeakSet();
  const reportedTrackUrls = new Set();

  // 1. Kullanıcı Tercihini (Yüzen Buton Açık/Kapalı) Yükle
  chrome.storage.local.get({ showFloatingButton: true }, (res) => {
    floatingButtonEnabled = res.showFloatingButton !== false;
    updateAllOverlays();
  });

  // 2. Arka plandan mevcut medya ve altyazı listesini iste
  function queryTabMedia() {
    try {
      safeSendMessage({ type: "GET_MEDIA_FOR_TAB" }, (res) => {
        if (!res) return;
        if (Array.isArray(res.media)) tabMediaItems = res.media;
        if (Array.isArray(res.frameMedia)) frameMediaItems = res.frameMedia;
        if (Array.isArray(res.subtitles)) tabSubtitles = res.subtitles;
        if (Array.isArray(res.frameSubtitles)) frameSubtitles = res.frameSubtitles;
        updateAllOverlays();
      });
    } catch {}
  }

  // DOM içindeki <video><track src="..."> altyazılarını tara ve bildir
  function scanVideoTracks() {
    const found = [];
    document.querySelectorAll("video track[src]").forEach((tr) => {
      const kind = (tr.getAttribute("kind") || "").toLowerCase();
      if (kind && kind !== "subtitles" && kind !== "captions") return;
      const rawSrc = tr.getAttribute("src");
      if (!rawSrc) return;
      let absUrl = "";
      try {
        absUrl = new URL(rawSrc, window.location.href).href;
      } catch {}
      if (!absUrl || !/^https?:/i.test(absUrl) || reportedTrackUrls.has(absUrl)) return;
      reportedTrackUrls.add(absUrl);
      found.push({
        url: absUrl,
        label: tr.getAttribute("label") || "",
        srclang: tr.getAttribute("srclang") || ""
      });
    });
    if (found.length > 0) {
      safeSendMessage({
        type: "SUBTITLES_DETECTED",
        tracks: found,
        refererUrl: window.location.href
      });
    }
  }

  // Alt frame kapanırken / değişirken eski medya kayıtlarını temizle
  if (window !== window.top) {
    window.addEventListener("pagehide", () => {
      safeSendMessage({ type: "FRAME_UNLOAD" });
    });
  }

  // 3. Arka plan mesajlarını dinle
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === "TOGGLE_FLOATING_BUTTON") {
      floatingButtonEnabled = Boolean(msg.enabled);
      if (!floatingButtonEnabled) {
        for (const entry of videoOverlayMap.values()) {
          entry.host.style.display = "none";
          entry.host.style.opacity = "0";
          entry.host.style.pointerEvents = "none";
        }
      } else {
        scheduleUpdate();
      }
    } else if (msg.type === "MEDIA_DETECTED") {
      if (Array.isArray(msg.allItems)) {
        tabMediaItems = msg.allItems;
      } else if (msg.item && !tabMediaItems.some((i) => i.url === msg.item.url)) {
        tabMediaItems.push(msg.item);
      }
      if (Array.isArray(msg.frameItems)) {
        frameMediaItems = msg.frameItems;
      }
      if (Array.isArray(msg.subtitles)) {
        tabSubtitles = msg.subtitles;
      }
      if (Array.isArray(msg.frameSubtitles)) {
        frameSubtitles = msg.frameSubtitles;
      }
      updateAllOverlays();
    } else if (msg.type === "DOWNLOAD_PROGRESS") {
      activeDownloads.set(msg.id, {
        percent: msg.percent,
        speedMb: msg.speedMb,
        mbTotal: msg.mbTotal,
        eta: msg.eta
      });
      updateAllOverlays();
    } else if (msg.type === "DOWNLOAD_FINISHED") {
      activeDownloads.delete(msg.id);
      notifyDownloadFinished(msg.id, msg.success, msg.filename, msg.error);
    } else if (msg.type === "DOWNLOAD_HANDOFF") {
      activeDownloads.delete(msg.id);
      for (const record of videoOverlayMap.values()) {
        const { elements } = record;
        if (elements.currentDownloadId === msg.id) {
          elements.isDownloading = false;
          elements.mainPill.classList.add("success");
          elements.pillLabel.textContent = "NovaStream'e aktarıldı";
          elements.progFill.style.width = "100%";
          setTimeout(() => {
            elements.mainPill.classList.remove("success");
            elements.pillLabel.textContent = "İndir";
            elements.progTrack.style.display = "none";
          }, 3000);
        }
      }
    }
  });

  function reportVideoDimensions(video) {
    if (!video) return;
    const w = video.videoWidth;
    const h = video.videoHeight;
    if (w > 0 && h > 0) {
      safeSendMessage({
        type: "VIDEO_DIMENSIONS_UPDATE",
        videoSrc: video.currentSrc || video.src || "",
        width: w,
        height: h
      });
    }
  }

  // 4. Utilitarian HUD İndirme Butonu (Shadow DOM)
  function createVideoOverlay(video) {
    if (videoOverlayMap.has(video)) return videoOverlayMap.get(video);

    const host = document.createElement("div");
    host.className = "novastream-video-overlay-host";
    host.style.cssText = `
      position: fixed;
      z-index: 2147483647;
      pointer-events: none;
      opacity: 0;
      transform: translateY(-2px);
      display: none;
      transition: opacity 0.18s ease, transform 0.18s ease;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    `;

    const shadow = host.attachShadow({ mode: "open" });

    shadow.innerHTML = `
      <style>
        :host {
          all: initial;
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }
        * {
          box-sizing: border-box;
          margin: 0;
          padding: 0;
        }
        .hud-container {
          position: relative;
          display: inline-flex;
          flex-direction: column;
          align-items: flex-end;
          gap: 4px;
        }
        .hud-pill {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          background: rgba(18, 20, 26, 0.94);
          backdrop-filter: blur(8px);
          -webkit-backdrop-filter: blur(8px);
          border: 1px solid rgba(255, 255, 255, 0.14);
          border-radius: 4px;
          padding: 3px 8px;
          color: #f0f3f6;
          font-size: 11px;
          font-weight: 600;
          box-shadow: 0 4px 12px rgba(0, 0, 0, 0.45);
          cursor: pointer;
          user-select: none;
          transition: background 0.12s ease, border-color 0.12s ease;
          height: 26px;
        }
        .hud-pill:hover {
          background: rgba(26, 30, 39, 0.98);
          border-color: rgba(255, 255, 255, 0.25);
        }
        .icon-dl {
          color: #ffffff;
          display: flex;
          align-items: center;
        }
        .icon-dl svg {
          width: 12px;
          height: 12px;
          stroke-width: 2.2;
        }
        .pill-text {
          white-space: nowrap;
          color: #f0f3f6;
          font-size: 11px;
        }
        .badge-res {
          background: #1e3a8a;
          color: #93c5fd;
          font-size: 9.5px;
          font-weight: 700;
          padding: 1px 5px;
          border-radius: 3px;
          text-transform: uppercase;
          letter-spacing: 0.2px;
          flex-shrink: 0;
        }
        .badge-sub {
          background: #064e3b;
          color: #6ee7b7;
          font-size: 9px;
          font-weight: 700;
          padding: 1px 5px;
          border-radius: 3px;
          text-transform: uppercase;
          flex-shrink: 0;
        }
        .btn-chevron {
          display: flex;
          align-items: center;
          opacity: 0.75;
          transition: transform 0.15s ease;
        }
        .btn-chevron svg {
          width: 10px;
          height: 10px;
        }
        .btn-chevron.open {
          transform: rotate(180deg);
        }
        .btn-dismiss {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          margin-left: 2px;
          padding: 1px 3px;
          opacity: 0.6;
          border-radius: 3px;
          cursor: pointer;
          transition: opacity 0.12s, background 0.12s;
        }
        .btn-dismiss:hover {
          opacity: 1;
          background: rgba(239, 68, 68, 0.25);
          color: #ef4444;
        }
        .btn-dismiss svg {
          width: 11px;
          height: 11px;
        }

        .progress-track {
          width: 100%;
          height: 2.5px;
          background: rgba(255, 255, 255, 0.15);
          border-radius: 1px;
          overflow: hidden;
          display: none;
        }
        .progress-fill {
          height: 100%;
          width: 0%;
          background: #2563eb;
          transition: width 0.25s ease;
        }

        .hud-pill.success {
          background: #10b981;
          border-color: #059669;
          color: #ffffff;
        }
        .hud-pill.error {
          background: #ef4444;
          border-color: #dc2626;
          color: #ffffff;
        }

        /* Kalite / Çözünürlük & Altyazı Menüsü */
        .quality-menu {
          display: none;
          flex-direction: column;
          background: #181b22;
          border: 1px solid #2d3340;
          border-radius: 5px;
          padding: 5px;
          min-width: 245px;
          max-width: 340px;
          max-height: 280px;
          overflow-y: auto;
          box-shadow: 0 10px 24px rgba(0, 0, 0, 0.65);
        }
        .quality-menu.show {
          display: flex;
        }
        .menu-title {
          font-size: 9.5px;
          text-transform: uppercase;
          color: #8b949e;
          font-weight: 700;
          padding: 4px 6px;
          letter-spacing: 0.4px;
          border-bottom: 1px solid #272c37;
          margin-bottom: 3px;
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 8px;
        }
        .menu-section-title {
          font-size: 9px;
          text-transform: uppercase;
          color: #6ee7b7;
          font-weight: 700;
          padding: 5px 6px 3px 6px;
          margin-top: 4px;
          border-top: 1px solid #272c37;
          letter-spacing: 0.4px;
        }
        .quality-item {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 10px;
          padding: 5px 6px;
          border-radius: 3px;
          font-size: 11px;
          color: #f0f3f6;
          cursor: pointer;
          transition: background 0.1s ease;
        }
        .quality-item:hover {
          background: #242935;
        }
        .quality-item-left {
          display: flex;
          align-items: center;
          gap: 6px;
          min-width: 0;
          flex: 1;
        }
        .item-label {
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .quality-item-right {
          font-size: 10px;
          color: #8b949e;
          white-space: nowrap;
          flex-shrink: 0;
        }
        .audio-pill-bar {
          display: flex;
          flex-wrap: wrap;
          gap: 4px;
          padding: 4px 6px 6px 6px;
          margin-bottom: 3px;
          border-bottom: 1px solid #272c37;
        }
        .audio-pill {
          font-size: 10px;
          font-weight: 600;
          padding: 2px 7px;
          border-radius: 3px;
          background: #232834;
          border: 1px solid #323949;
          color: #cbd5e1;
          cursor: pointer;
          transition: background 0.1s, border-color 0.1s, color 0.1s;
        }
        .audio-pill:hover {
          background: #2b3242;
        }
        .audio-pill.active {
          background: #1e3a8a;
          border-color: #3b82f6;
          color: #dbeafe;
        }
      </style>

      <div class="hud-container" id="container">
        <div class="hud-pill" id="main-pill">
          <span class="icon-dl" id="dl-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="7 10 12 15 17 10"></polyline>
              <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
          </span>
          <span class="pill-text" id="pill-label">İndir</span>
          <span class="badge-res" id="pill-res" style="display:none">1080p</span>
          <span class="btn-chevron" id="btn-chevron" style="display:none">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="6 9 12 15 18 9"></polyline>
            </svg>
          </span>
          <span class="btn-dismiss" id="btn-dismiss" title="Bu videoda gizle">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </span>
        </div>

        <div class="progress-track" id="prog-track">
          <div class="progress-fill" id="prog-fill"></div>
        </div>

        <div class="quality-menu" id="quality-menu">
          <div class="menu-title" id="menu-title">Çözünürlük Seçin</div>
          <div id="quality-list"></div>
        </div>
      </div>
    `;

    const elements = {
      host,
      shadow,
      container: shadow.getElementById("container"),
      mainPill: shadow.getElementById("main-pill"),
      dlIcon: shadow.getElementById("dl-icon"),
      pillLabel: shadow.getElementById("pill-label"),
      pillRes: shadow.getElementById("pill-res"),
      btnChevron: shadow.getElementById("btn-chevron"),
      btnDismiss: shadow.getElementById("btn-dismiss"),
      progTrack: shadow.getElementById("prog-track"),
      progFill: shadow.getElementById("prog-fill"),
      qualityMenu: shadow.getElementById("quality-menu"),
      menuTitle: shadow.getElementById("menu-title"),
      qualityList: shadow.getElementById("quality-list"),
      currentDownloadId: null,
      isDownloading: false,
      fadeTimeout: null
    };

    elements.btnDismiss.addEventListener("click", (e) => {
      e.stopPropagation();
      dismissedVideos.add(video);
      host.style.display = "none";
      host.style.opacity = "0";
      host.style.pointerEvents = "none";
    });

    elements.mainPill.addEventListener("click", (e) => {
      e.stopPropagation();
      if (elements.isDownloading) return;

      const items = getApplicableMedia(video);
      const subs = getApplicableSubtitles();

      if (isYouTube) {
        startDownload({
          id: crypto.randomUUID(),
          url: window.location.href,
          title: (document.title || "YouTube Video").replace(/\s*-\s*YouTube/gi, "").trim(),
          isYouTube: true
        }, elements);
        return;
      }

      const multiOptionItem = items.find(
        (it) => (Array.isArray(it.qualities) && it.qualities.length > 1) ||
                (Array.isArray(it.audioTracks) && it.audioTracks.length > 1)
      );
      if (multiOptionItem && items.length === 1) {
        const quals = Array.isArray(multiOptionItem.qualities) && multiOptionItem.qualities.length > 0
          ? multiOptionItem.qualities
          : [{ url: multiOptionItem.targetUrl || multiOptionItem.url, qualityLabel: multiOptionItem.resolution || "HD", height: 0, hasExternalAudio: Boolean(multiOptionItem.hasExternalAudio) }];
        toggleQualityMenu(elements, quals, multiOptionItem, subs);
        return;
      }

      if (items.length > 1 || (items.length === 1 && subs.length > 0)) {
        toggleMultipleMediaMenu(elements, items, false, subs);
        return;
      }

      if (items.length === 1) {
        startDownload(items[0], elements);
        return;
      }

      const fallbackItem = extractFromVideoTag(video);
      if (fallbackItem) {
        startDownload(fallbackItem, elements);
      } else {
        elements.pillLabel.textContent = "Algılanıyor...";
        setTimeout(() => {
          elements.pillLabel.textContent = "İndir";
        }, 1500);
      }
    });

    function getPlayerContainer(v) {
      return (
        v.closest("#movie_player, .html5-video-player, .player-container, .video-js, .jwplayer, [class*='player' i]") ||
        v.parentElement ||
        v
      );
    }
    const playerContainer = getPlayerContainer(video);

    function showOverlay() {
      if (!floatingButtonEnabled || dismissedVideos.has(video)) return;
      clearTimeout(elements.fadeTimeout);
      host.style.opacity = "1";
      host.style.pointerEvents = "auto";
      host.style.transform = "translateY(0)";
    }

    function scheduleHide(delay = 2000) {
      clearTimeout(elements.fadeTimeout);
      if (elements.isDownloading || elements.qualityMenu.classList.contains("show")) {
        return;
      }
      elements.fadeTimeout = setTimeout(() => {
        if (!elements.isDownloading && !elements.qualityMenu.classList.contains("show")) {
          host.style.opacity = "0";
          host.style.pointerEvents = "none";
          host.style.transform = "translateY(-2px)";
        }
      }, delay);
    }

    playerContainer.addEventListener("mouseenter", showOverlay, { passive: true });
    playerContainer.addEventListener("mousemove", () => {
      showOverlay();
      scheduleHide(2400);
    }, { passive: true });
    playerContainer.addEventListener("mouseleave", () => scheduleHide(600), { passive: true });

    host.addEventListener("mouseenter", showOverlay);
    host.addEventListener("mouseleave", () => scheduleHide(1200));

    video.addEventListener("loadedmetadata", () => {
      reportVideoDimensions(video);
      scanVideoTracks();
    }, { passive: true });
    video.addEventListener("play", () => {
      reportVideoDimensions(video);
      scanVideoTracks();
    }, { passive: true });
    reportVideoDimensions(video);
    scanVideoTracks();

    const record = { video, host, elements, playerContainer };
    videoOverlayMap.set(video, record);
    return record;
  }

  function appendSubtitlesToMenu(elements, subs) {
    if (!subs || subs.length === 0) return;
    const sec = document.createElement("div");
    sec.className = "menu-section-title";
    sec.textContent = "Altyazılar (.SRT)";
    elements.qualityList.appendChild(sec);

    subs.forEach((sub) => {
      const row = document.createElement("div");
      row.className = "quality-item";
      row.title = sub.url;
      row.innerHTML = `
        <div class="quality-item-left">
          <span class="badge-sub">${escapeHtml(sub.langCode || "ALT")}</span>
          <span class="item-label">${escapeHtml(sub.label || "Altyazı")}</span>
        </div>
        <div class="quality-item-right">${escapeHtml(sub.sourceLabel || "SRT")}</div>
      `;
      row.addEventListener("click", (e) => {
        e.stopPropagation();
        elements.qualityMenu.classList.remove("show");
        elements.btnChevron.classList.remove("open");
        startSubtitleDownload(sub, elements);
      });
      elements.qualityList.appendChild(row);
    });
  }

  // Master Playlist Çözünürlük & Ses Dili Menüsü
  function toggleQualityMenu(elements, qualities, parentItem, subs = []) {
    const isShowing = elements.qualityMenu.classList.contains("show");
    if (isShowing) {
      elements.qualityMenu.classList.remove("show");
      elements.btnChevron.classList.remove("open");
      return;
    }

    const srcTag = parentItem.sourceLabel ? ` • ${parentItem.sourceLabel}` : "";
    const audios = Array.isArray(parentItem.audioTracks) ? parentItem.audioTracks : [];
    const hasMultiAudio = audios.length > 1;
    const hasMultiQuality = qualities.length > 1;

    elements.qualityList.innerHTML = "";

    if (hasMultiAudio && !hasMultiQuality) {
      elements.menuTitle.textContent = `Ses & İndirme Seçin${srcTag}`;
      const q = qualities[0] || { url: parentItem.targetUrl || parentItem.url, qualityLabel: parentItem.resolution || "HD", height: 0 };
      audios.forEach((a) => {
        const row = document.createElement("div");
        row.className = "quality-item";
        row.title = parentItem.masterUrl || parentItem.url;
        row.innerHTML = `
          <div class="quality-item-left">
            <span class="badge-res">${escapeHtml(q.qualityLabel || parentItem.resolution || "HD")}</span>
            <span class="item-label">${escapeHtml(a.label || a.rawName || "Ses")}</span>
          </div>
          <div class="quality-item-right">${escapeHtml((a.language || "SES").toUpperCase())}</div>
        `;
        row.addEventListener("click", (e) => {
          e.stopPropagation();
          elements.qualityMenu.classList.remove("show");
          elements.btnChevron.classList.remove("open");
          startDownload({
            id: crypto.randomUUID(),
            url: q.url,
            masterUrl: parentItem.masterUrl || parentItem.url,
            hasExternalAudio: true,
            quality: q.height ? String(q.height) : "best",
            audioLang: a.language || "",
            audioName: a.rawName || a.name || "",
            refererUrl: parentItem.refererUrl || window.location.href,
            title: parentItem.title,
            format: q.qualityLabel,
            isStream: true
          }, elements);
        });
        elements.qualityList.appendChild(row);
      });

      const dualRow = document.createElement("div");
      dualRow.className = "quality-item";
      dualRow.title = "Tüm ses dillerini tek dosyada birleştirir";
      dualRow.innerHTML = `
        <div class="quality-item-left">
          <span class="badge-res">${escapeHtml(q.qualityLabel || parentItem.resolution || "HD")}</span>
          <span class="item-label">Çift Ses (Tüm Diller)</span>
        </div>
        <div class="quality-item-right">MP4</div>
      `;
      dualRow.addEventListener("click", (e) => {
        e.stopPropagation();
        elements.qualityMenu.classList.remove("show");
        elements.btnChevron.classList.remove("open");
        startDownload({
          id: crypto.randomUUID(),
          url: q.url,
          masterUrl: parentItem.masterUrl || parentItem.url,
          hasExternalAudio: true,
          quality: q.height ? String(q.height) : "best",
          audioLang: "all",
          audioName: "",
          refererUrl: parentItem.refererUrl || window.location.href,
          title: parentItem.title,
          format: q.qualityLabel,
          isStream: true
        }, elements);
      });
      elements.qualityList.appendChild(dualRow);
    } else {
      elements.menuTitle.textContent = hasMultiAudio ? `Çözünürlük & Ses Seçin${srcTag}` : `Çözünürlük Seçin${srcTag}`;
      let selectedAudio = audios.find((a) => a.isDefault) || audios[0] || null;

      if (hasMultiAudio) {
        const bar = document.createElement("div");
        bar.className = "audio-pill-bar";
        const choices = audios.map((a) => ({ label: a.label || a.rawName || "Ses", language: a.language || "", rawName: a.rawName || a.name || "" }));
        choices.push({ label: "Çift Ses", language: "all", rawName: "" });

        choices.forEach((ch, idx) => {
          const pill = document.createElement("span");
          const isDef = selectedAudio ? (ch.language === selectedAudio.language && ch.rawName === (selectedAudio.rawName || selectedAudio.name || "")) : idx === 0;
          pill.className = `audio-pill${isDef ? " active" : ""}`;
          pill.textContent = ch.label;
          pill.addEventListener("click", (e) => {
            e.stopPropagation();
            selectedAudio = ch;
            bar.querySelectorAll(".audio-pill").forEach((el) => el.classList.remove("active"));
            pill.classList.add("active");
          });
          bar.appendChild(pill);
        });
        elements.qualityList.appendChild(bar);
      }

      qualities.forEach((q) => {
        const row = document.createElement("div");
        row.className = "quality-item";
        row.title = q.url;
        const rightTag = q.hasExternalAudio ? "Ses+Video" : "MP4";
        row.innerHTML = `
          <div class="quality-item-left">
            <span class="badge-res">${escapeHtml(q.qualityLabel)}</span>
            <span class="item-label">${escapeHtml(q.bwLabel || (parentItem.sourceLabel || "Akış"))}</span>
          </div>
          <div class="quality-item-right">${escapeHtml(rightTag)}</div>
        `;
        row.addEventListener("click", (e) => {
          e.stopPropagation();
          elements.qualityMenu.classList.remove("show");
          elements.btnChevron.classList.remove("open");
          startDownload({
            id: crypto.randomUUID(),
            url: q.url,
            masterUrl: parentItem.masterUrl || parentItem.url,
            hasExternalAudio: Boolean(q.hasExternalAudio || parentItem.hasExternalAudio),
            quality: q.height ? String(q.height) : "best",
            audioLang: selectedAudio ? selectedAudio.language : null,
            audioName: selectedAudio ? (selectedAudio.rawName || selectedAudio.name || "") : null,
            refererUrl: parentItem.refererUrl || window.location.href,
            title: parentItem.title,
            format: q.qualityLabel,
            isStream: true
          }, elements);
        });
        elements.qualityList.appendChild(row);
      });
    }

    appendSubtitlesToMenu(elements, subs);
    elements.qualityMenu.classList.add("show");
    elements.btnChevron.classList.add("open");
  }

  function formatStreamDescriptor(item) {
    const parts = [];
    parts.push(item.sourceLabel || "Video");
    if (item.hasExternalAudio) parts.push("Ses+Video");
    else if (item.isStream) parts.push("HLS");
    else if (item.ext) parts.push(item.ext.toUpperCase());
    return parts.join(" • ");
  }

  function toggleMultipleMediaMenu(elements, items, showMinor = false, subs = []) {
    const isShowing = elements.qualityMenu.classList.contains("show");
    if (isShowing && !showMinor) {
      elements.qualityMenu.classList.remove("show");
      elements.btnChevron.classList.remove("open");
      return;
    }

    elements.menuTitle.textContent = items.length > 1 ? "Video / Akış Seçin" : "İndirme Seçenekleri";
    elements.qualityList.innerHTML = "";
    const basePool = frameMediaItems.length > 0 ? frameMediaItems : tabMediaItems;
    const minorItems = basePool.filter((it) => it.minor && !items.includes(it));
    const shown = showMinor ? items.concat(minorItems) : items;

    shown.forEach((item) => {
      const row = document.createElement("div");
      row.className = "quality-item";
      row.title = item.url;
      const resText = item.resolution || item.format || "MP4";
      const leftDesc = formatStreamDescriptor(item);
      const rightMeta = item.sizeFormatted || (item.isStream ? "HLS" : "");
      row.innerHTML = `
        <div class="quality-item-left">
          <span class="badge-res">${escapeHtml(resText)}</span>
          <span class="item-label">${escapeHtml(leftDesc)}</span>
        </div>
        <div class="quality-item-right">${escapeHtml(rightMeta)}</div>
      `;
      row.addEventListener("click", (e) => {
        e.stopPropagation();
        const hasQ = Array.isArray(item.qualities) && item.qualities.length > 1;
        const hasA = Array.isArray(item.audioTracks) && item.audioTracks.length > 1;
        if (hasQ || hasA) {
          elements.qualityMenu.classList.remove("show");
          const quals = hasQ
            ? item.qualities
            : [{ url: item.targetUrl || item.url, qualityLabel: item.resolution || "HD", height: 0, hasExternalAudio: Boolean(item.hasExternalAudio || hasA) }];
          toggleQualityMenu(elements, quals, item, subs);
          return;
        }
        elements.qualityMenu.classList.remove("show");
        elements.btnChevron.classList.remove("open");
        startDownload(item, elements);
      });
      elements.qualityList.appendChild(row);
    });

    if (!showMinor && minorItems.length > 0) {
      const more = document.createElement("div");
      more.className = "quality-item";
      more.innerHTML = `<div class="quality-item-left"><span class="item-label">Diğer ${minorItems.length} kısa öğe (reklam/parça olabilir)</span></div>`;
      more.style.opacity = "0.7";
      more.addEventListener("click", (e) => {
        e.stopPropagation();
        toggleMultipleMediaMenu(elements, items, true, subs);
      });
      elements.qualityList.appendChild(more);
    }

    appendSubtitlesToMenu(elements, subs);
    elements.qualityMenu.classList.add("show");
    elements.btnChevron.classList.add("open");
  }

  function extractFromVideoTag(video) {
    const src = video.src || video.currentSrc;
    if (src && src.startsWith("http") && !src.startsWith("blob:")) {
      const h = video.videoHeight;
      const res = h >= 1080 ? "1080p" : (h >= 720 ? "720p" : (h > 0 ? `${h}p` : "MP4"));
      return {
        id: crypto.randomUUID(),
        url: src,
        refererUrl: window.location.href,
        title: (document.title || "video").replace(/[^\w\.-]/g, "_") + ".mp4",
        format: res,
        resolution: res,
        isStream: false,
        sizeFormatted: "Doğrudan Medya"
      };
    }
    return null;
  }

  function getApplicableMedia(video) {
    if (isYouTube) {
      return [{
        id: "yt-" + window.location.href,
        url: window.location.href,
        title: (document.title || "YouTube Video").replace(/\s*-\s*YouTube/gi, "").trim() + ".mp4",
        format: "1080p / 4K",
        resolution: "1080p",
        isYouTube: true,
        sizeFormatted: "Oturum Açık • Orijinal"
      }];
    }

    const pool = frameMediaItems.length > 0 ? frameMediaItems : tabMediaItems;
    if (pool.length > 0) {
      const main = pool.filter((it) => !it.minor && !it.duplicate);
      return main.length > 0 ? main : pool;
    }

    const fallback = extractFromVideoTag(video);
    return fallback ? [fallback] : [];
  }

  function getApplicableSubtitles() {
    if (isYouTube) return [];
    return frameSubtitles.length > 0 ? frameSubtitles : tabSubtitles;
  }

  function startSubtitleDownload(sub, elements) {
    elements.pillLabel.textContent = "Altyazı indiriliyor...";
    elements.host.style.opacity = "1";
    safeSendMessage({
      type: "DOWNLOAD_SUBTITLE",
      url: sub.url,
      refererUrl: sub.refererUrl || window.location.href,
      title: sub.title || document.title || "altyazi",
      langCode: sub.langCode || "",
      ext: sub.ext || "vtt",
      isHlsSubtitle: Boolean(sub.isHlsSubtitle),
      convertToSrt: true
    }, (res) => {
      if (res?.success) {
        elements.mainPill.classList.add("success");
        elements.pillLabel.textContent = "Altyazı kaydedildi";
        setTimeout(() => {
          elements.mainPill.classList.remove("success");
          elements.pillLabel.textContent = "İndir";
        }, 2500);
      } else {
        elements.mainPill.classList.add("error");
        elements.pillLabel.textContent = "Altyazı hatası";
        setTimeout(() => {
          elements.mainPill.classList.remove("error");
          elements.pillLabel.textContent = "İndir";
        }, 2500);
      }
    });
  }

  function startDownload(item, elements) {
    const downloadId = item.id || crypto.randomUUID();
    elements.currentDownloadId = downloadId;
    elements.isDownloading = true;

    elements.mainPill.classList.remove("success", "error");
    elements.pillLabel.textContent = "Bağlanıyor...";
    elements.progTrack.style.display = "block";
    elements.progFill.style.width = "2%";
    elements.btnChevron.style.display = "none";
    elements.qualityMenu.classList.remove("show");
    elements.host.style.opacity = "1";

    const msgType = item.isYouTube ? "START_YOUTUBE_DOWNLOAD" : "START_STREAM_DOWNLOAD";

    safeSendMessage({
      type: msgType,
      id: downloadId,
      url: item.targetUrl || item.url,
      streamUrl: item.targetUrl || item.url,
      masterUrl: item.masterUrl || (item.isMaster ? item.url : ""),
      hasExternalAudio: Boolean(item.hasExternalAudio),
      quality: item.quality || null,
      audioLang: item.audioLang || null,
      audioName: item.audioName || null,
      refererUrl: item.refererUrl || window.location.href,
      title: item.title,
      isYouTube: Boolean(item.isYouTube),
      isStream: Boolean(item.isStream)
    }, (res) => {
      if (res?.success && res.desktop && res.tracking) {
        return;
      }
      if (res?.success && res.desktop) {
        elements.isDownloading = false;
        elements.mainPill.classList.add("success");
        elements.pillLabel.textContent = "NovaStream'e aktarıldı";
        elements.progFill.style.width = "100%";
        setTimeout(() => {
          elements.mainPill.classList.remove("success");
          elements.pillLabel.textContent = "İndir";
          elements.progTrack.style.display = "none";
        }, 3000);
        return;
      }
      if (!res?.success) {
        elements.isDownloading = false;
        elements.mainPill.classList.add("error");
        elements.pillLabel.textContent = "Hata";
        elements.progTrack.style.display = "none";
        setTimeout(() => {
          elements.mainPill.classList.remove("error");
          elements.pillLabel.textContent = "İndir";
        }, 2500);
      }
    });
  }

  function notifyDownloadFinished(id, success, filename, error) {
    for (const record of videoOverlayMap.values()) {
      const { elements } = record;
      if (elements.currentDownloadId === id || elements.isDownloading) {
        elements.isDownloading = false;
        elements.progTrack.style.display = "none";

        if (success) {
          elements.mainPill.classList.add("success");
          elements.pillLabel.textContent = "İndirildi";
          setTimeout(() => {
            elements.mainPill.classList.remove("success");
            elements.pillLabel.textContent = "İndir";
            elements.currentDownloadId = null;
          }, 3500);
        } else {
          elements.mainPill.classList.add("error");
          elements.pillLabel.textContent = error === "İptal edildi" ? "İptal edildi" : "Hata";
          setTimeout(() => {
            elements.mainPill.classList.remove("error");
            elements.pillLabel.textContent = "İndir";
            elements.currentDownloadId = null;
          }, 3500);
        }
      }
    }
  }

  function isEligibleVideo(video) {
    if (!floatingButtonEnabled) return false;
    if (!video || dismissedVideos.has(video)) return false;
    if (!video.isConnected) return false;

    const rect = video.getBoundingClientRect();

    if (rect.width < 280 || rect.height < 160) {
      return false;
    }

    if (
      rect.bottom <= 0 ||
      rect.top >= window.innerHeight ||
      rect.right <= 0 ||
      rect.left >= window.innerWidth
    ) {
      return false;
    }

    if (isYouTube) {
      const isMainWatch = video.closest("#movie_player, ytd-watch-flexy, #ytd-player");
      const isShorts = video.closest("ytd-reel-video-renderer[is-active], ytd-reel-video-renderer");
      if (!isMainWatch && !isShorts) {
        return false;
      }
      if (
        video.closest(
          "ytd-thumbnail, #inline-preview-player, .ytd-thumbnail, ytd-compact-video-renderer #thumbnail, ytd-moving-thumbnail-renderer"
        )
      ) {
        return false;
      }
    }

    const previewContainer = video.closest(
      "ytd-thumbnail, [class*='thumbnail' i], [id*='thumbnail' i], [class*='preview' i], [id*='preview' i], [class*='teaser' i], [class*='avatar' i], [class*='badge' i], [class*='story' i], [class*='card-media' i]"
    );
    if (previewContainer) {
      if (rect.width < 450 || rect.height < 250) {
        return false;
      }
    }

    if (video.loop && video.muted && (video.duration < 12 || isNaN(video.duration))) {
      if (rect.width < 500 || rect.height < 300) {
        return false;
      }
    }

    return true;
  }

  function updateOverlayPosition(video, record) {
    const { host, elements } = record;

    if (!isEligibleVideo(video)) {
      host.style.display = "none";
      host.style.opacity = "0";
      host.style.pointerEvents = "none";
      return;
    }

    const rect = video.getBoundingClientRect();
    host.style.display = "block";

    const fsEl =
      document.fullscreenElement ||
      document.webkitFullscreenElement ||
      document.mozFullScreenElement;
    if (fsEl) {
      if (host.parentElement !== fsEl) {
        fsEl.appendChild(host);
      }
    } else {
      if (host.parentElement !== document.body) {
        document.body.appendChild(host);
      }
    }
    host.style.position = "fixed";
    host.style.top = `${Math.max(10, rect.top + 10)}px`;
    host.style.right = `${Math.max(10, window.innerWidth - rect.right + 10)}px`;

    if (elements.isDownloading && elements.currentDownloadId) {
      host.style.opacity = "1";
      host.style.pointerEvents = "auto";
      host.style.transform = "translateY(0)";
      const prog = activeDownloads.get(elements.currentDownloadId);
      if (prog) {
        elements.pillLabel.textContent = `${prog.percent}% • ${prog.speedMb || "İndiriliyor"}`;
        elements.progFill.style.width = `${prog.percent}%`;
        elements.progTrack.style.display = "block";
      }
      return;
    }

    const items = getApplicableMedia(video);
    const subs = getApplicableSubtitles();
    const hasMultipleQualities = items.some((it) => Array.isArray(it.qualities) && it.qualities.length > 1);
    const hasMultipleAudios = items.some((it) => Array.isArray(it.audioTracks) && it.audioTracks.length > 1);

    if (hasMultipleQualities || hasMultipleAudios || items.length > 1 || (items.length === 1 && subs.length > 0)) {
      elements.btnChevron.style.display = "inline-flex";
    } else {
      elements.btnChevron.style.display = "none";
    }

    let detectedRes = "";
    if (items.length > 0) {
      detectedRes = items[0].resolution || "";
      if (!detectedRes && items[0].format) {
        const m = items[0].format.match(/(4K|2K|1080p|720p|480p|360p)/i);
        if (m) detectedRes = m[1];
      }
    }
    if (!detectedRes && video.videoHeight > 0) {
      const h = video.videoHeight;
      detectedRes = h >= 1080 ? (h >= 2160 ? "4K" : "1080p") : (h >= 720 ? "720p" : `${h}p`);
    }

    if (detectedRes) {
      elements.pillRes.style.display = "inline-block";
      elements.pillRes.textContent = detectedRes;
    } else {
      elements.pillRes.style.display = "none";
    }
  }

  function updateAllOverlays() {
    for (const [v, rec] of videoOverlayMap.entries()) {
      if (!v.isConnected || !document.contains(v) || !floatingButtonEnabled) {
        rec.host.remove();
        clearTimeout(rec.elements.fadeTimeout);
        videoOverlayMap.delete(v);
      }
    }

    if (!floatingButtonEnabled) return;

    const videos = document.querySelectorAll("video");
    videos.forEach((v) => {
      if (!isEligibleVideo(v)) {
        const existing = videoOverlayMap.get(v);
        if (existing) {
          existing.host.style.display = "none";
          existing.host.style.opacity = "0";
          existing.host.style.pointerEvents = "none";
        }
        return;
      }

      let record = videoOverlayMap.get(v);
      if (!record) {
        record = createVideoOverlay(v);
      }
      updateOverlayPosition(v, record);
    });
  }

  let ticking = false;
  function scheduleUpdate() {
    if (!ticking) {
      ticking = true;
      requestAnimationFrame(() => {
        scanVideoTracks();
        updateAllOverlays();
        ticking = false;
      });
    }
  }

  window.addEventListener("scroll", scheduleUpdate, { passive: true });
  window.addEventListener("resize", scheduleUpdate, { passive: true });
  document.addEventListener("fullscreenchange", scheduleUpdate, { passive: true });
  document.addEventListener("webkitfullscreenchange", scheduleUpdate, { passive: true });
  document.addEventListener("mozfullscreenchange", scheduleUpdate, { passive: true });

  document.addEventListener("play", scheduleUpdate, { capture: true, passive: true });
  document.addEventListener("loadedmetadata", scheduleUpdate, { capture: true, passive: true });

  const observer = new MutationObserver(() => {
    scheduleUpdate();
  });
  observer.observe(document.documentElement || document.body, {
    childList: true,
    subtree: true
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      scanVideoTracks();
      queryTabMedia();
      scheduleUpdate();
    }, { once: true });
  } else {
    scanVideoTracks();
    queryTabMedia();
    scheduleUpdate();
  }

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }
})();

// NovaStream - Content Script (Yüzen Video İndirme HUD Widget'ı + DOM Medya Tarayıcı)

(function () {
  "use strict";

  if (window.__novastream_injected) return;
  window.__novastream_injected = true;

  // Eklenti yeniden yüklendiğinde eski sekmelerdeki betik "Extension context invalidated"
  // hatası fırlatır; bağlam geçersizse sessizce vazgeç.
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
  const activeDownloads = new Map();
  const videoOverlayMap = new Map(); // videoElement -> record
  const dismissedVideos = new WeakSet();

  // 1. Kullanıcı Tercihini (Yüzen Buton Açık/Kapalı) Yükle
  chrome.storage.local.get({ showFloatingButton: true }, (res) => {
    floatingButtonEnabled = res.showFloatingButton !== false;
    updateAllOverlays();
  });

  // 2. Arka plandan mevcut medya listesini iste
  function queryTabMedia() {
    try {
      safeSendMessage({ type: "GET_MEDIA_FOR_TAB" }, (res) => {
        if (!res) return;
        if (Array.isArray(res.media)) {
          tabMediaItems = res.media;
          updateAllOverlays();
        }
      });
    } catch {}
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

  // Video çözünürlüğünü arka plana bildir
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
          padding: 1px 4px;
          border-radius: 3px;
          text-transform: uppercase;
          letter-spacing: 0.2px;
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

        /* İlerleme Çubuğu */
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

        /* Kalite / Çözünürlük Menüsü */
        .quality-menu {
          display: none;
          flex-direction: column;
          background: #181b22;
          border: 1px solid #2d3340;
          border-radius: 4px;
          padding: 4px;
          min-width: 190px;
          max-width: 280px;
          max-height: 220px;
          overflow-y: auto;
          box-shadow: 0 8px 20px rgba(0, 0, 0, 0.6);
        }
        .quality-menu.show {
          display: flex;
        }
        .menu-title {
          font-size: 9.5px;
          text-transform: uppercase;
          color: #8b949e;
          font-weight: 700;
          padding: 3px 6px;
          letter-spacing: 0.4px;
          border-bottom: 1px solid #272c37;
          margin-bottom: 3px;
        }
        .quality-item {
          display: flex;
          align-items: center;
          justify-content: space-between;
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
          gap: 5px;
        }
        .quality-item-right {
          font-size: 10px;
          color: #8b949e;
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
          <span class="btn-dismiss" id="btn-dismiss" title="Kapatma Seçenekleri">
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
          <div class="menu-title">Çözünürlük Seçin</div>
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
      qualityList: shadow.getElementById("quality-list"),
      currentDownloadId: null,
      isDownloading: false,
      fadeTimeout: null
    };

    // Tek Tıkla Gizleme (Kalıcı kapatmak isteyen eklenti popup'ındaki switch'i kullanır)
    elements.btnDismiss.addEventListener("click", (e) => {
      e.stopPropagation();
      dismissedVideos.add(video);
      host.style.display = "none";
      host.style.opacity = "0";
      host.style.pointerEvents = "none";
    });

    // Ana Buton Tıklaması
    elements.mainPill.addEventListener("click", (e) => {
      e.stopPropagation();
      if (elements.isDownloading) return;

      const items = getApplicableMedia(video);

      if (isYouTube) {
        startDownload({
          id: crypto.randomUUID(),
          url: window.location.href,
          title: (document.title || "YouTube Video").replace(/\s*-\s*YouTube/gi, "").trim(),
          isYouTube: true
        }, elements);
        return;
      }

      // Master playlist kaliteleri var mı?
      const masterItem = items.find((it) => Array.isArray(it.qualities) && it.qualities.length > 1);
      if (masterItem) {
        toggleQualityMenu(elements, masterItem.qualities, masterItem);
        return;
      }

      if (items.length > 1) {
        toggleMultipleMediaMenu(elements, items);
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

    // Hover Mantığı
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
      if (
        elements.isDownloading ||
        elements.qualityMenu.classList.contains("show")
      ) {
        return;
      }
      elements.fadeTimeout = setTimeout(() => {
        if (
          !elements.isDownloading &&
          !elements.qualityMenu.classList.contains("show")
        ) {
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

    // Video olaylarını dinle (çözünürlüğü bildir)
    video.addEventListener("loadedmetadata", () => reportVideoDimensions(video), { passive: true });
    video.addEventListener("play", () => reportVideoDimensions(video), { passive: true });
    reportVideoDimensions(video);

    const record = { video, host, elements, playerContainer };
    videoOverlayMap.set(video, record);
    return record;
  }

  // Master Playlist Çözünürlük Menüsü
  function toggleQualityMenu(elements, qualities, parentItem) {
    const isShowing = elements.qualityMenu.classList.contains("show");
    if (isShowing) {
      elements.qualityMenu.classList.remove("show");
      elements.btnChevron.classList.remove("open");
    } else {
      elements.qualityList.innerHTML = "";
      qualities.forEach((q) => {
        const row = document.createElement("div");
        row.className = "quality-item";
        row.innerHTML = `
          <div class="quality-item-left">
            <span class="badge-res">${escapeHtml(q.qualityLabel)}</span>
            <span>${escapeHtml(q.bwLabel || "")}</span>
          </div>
          <div class="quality-item-right">MP4</div>
        `;
        row.addEventListener("click", (e) => {
          e.stopPropagation();
          elements.qualityMenu.classList.remove("show");
          elements.btnChevron.classList.remove("open");
          startDownload({
            id: crypto.randomUUID(),
            url: q.url,
            title: parentItem.title,
            format: q.qualityLabel,
            isStream: true
          }, elements);
        });
        elements.qualityList.appendChild(row);
      });
      elements.qualityMenu.classList.add("show");
      elements.btnChevron.classList.add("open");
    }
  }

  function toggleMultipleMediaMenu(elements, items, showMinor = false) {
    const isShowing = elements.qualityMenu.classList.contains("show");
    if (isShowing && !showMinor) {
      elements.qualityMenu.classList.remove("show");
      elements.btnChevron.classList.remove("open");
    } else {
      elements.qualityList.innerHTML = "";
      const minorItems = tabMediaItems.filter((it) => it.minor && !items.includes(it));
      const shown = showMinor ? items.concat(minorItems) : items;
      shown.forEach((item) => {
        const row = document.createElement("div");
        row.className = "quality-item";
        const resText = item.resolution || item.format || "MP4";
        row.innerHTML = `
          <div class="quality-item-left">
            <span class="badge-res">${escapeHtml(resText)}</span>
            <span>${escapeHtml(item.title.substring(0, 20))}...</span>
          </div>
          <div class="quality-item-right">${escapeHtml(item.sizeFormatted || "")}</div>
        `;
        row.addEventListener("click", (e) => {
          e.stopPropagation();
          elements.qualityMenu.classList.remove("show");
          elements.btnChevron.classList.remove("open");
          startDownload(item, elements);
        });
        elements.qualityList.appendChild(row);
      });
      if (!showMinor && minorItems.length > 0) {
        const more = document.createElement("div");
        more.className = "quality-item";
        more.innerHTML = `<div class="quality-item-left"><span>Diğer ${minorItems.length} kısa öğe (reklam/parça olabilir)</span></div>`;
        more.style.opacity = "0.7";
        more.addEventListener("click", (e) => {
          e.stopPropagation();
          toggleMultipleMediaMenu(elements, items, true);
        });
        elements.qualityList.appendChild(more);
      }
      elements.qualityMenu.classList.add("show");
      elements.btnChevron.classList.add("open");
    }
  }

  function extractFromVideoTag(video) {
    const src = video.src || video.currentSrc;
    if (src && src.startsWith("http") && !src.startsWith("blob:")) {
      const h = video.videoHeight;
      const res = h >= 1080 ? "1080p" : (h >= 720 ? "720p" : (h > 0 ? `${h}p` : "MP4"));
      return {
        id: crypto.randomUUID(),
        url: src,
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

    if (tabMediaItems.length > 0) {
      // Arka plan listeyi sıralar; kısa parçalar/reklamlar "minor" olarak gelir.
      const main = tabMediaItems.filter((it) => !it.minor && !it.duplicate);
      return main.length > 0 ? main : tabMediaItems;
    }

    const fallback = extractFromVideoTag(video);
    return fallback ? [fallback] : [];
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
      url: item.url,
      streamUrl: item.url,
      refererUrl: window.location.href,
      title: item.title,
      isYouTube: Boolean(item.isYouTube),
      isStream: Boolean(item.isStream)
    }, (res) => {
      if (res?.success && res.desktop && res.tracking) {
        // Uygulamaya devredildi; ilerleme uygulamadan okunup bu düğmede gösterilecek.
        return;
      }
      if (res?.success && res.desktop) {
        // İndirme masaüstü uygulamasına devredildi (onay penceresi); ilerleme orada izlenir.
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

    // Normal Durum: Çözünürlük Rozeti Belirleme
    const items = getApplicableMedia(video);
    const hasMultipleQualities = items.some((it) => Array.isArray(it.qualities) && it.qualities.length > 1);

    if (hasMultipleQualities || items.length > 1) {
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
      queryTabMedia();
      scheduleUpdate();
    }, { once: true });
  } else {
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

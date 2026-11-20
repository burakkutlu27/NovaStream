// NovaStream - Popup Script (Utilitarian Density, Resolution & Subtitle Support)

document.addEventListener("DOMContentLoaded", async () => {
  const mediaListEl = document.getElementById("media-list");
  const subtitleSectionEl = document.getElementById("subtitle-section");
  const subtitleListEl = document.getElementById("subtitle-list");
  const emptyStateEl = document.getElementById("empty-state");
  const mediaCountEl = document.getElementById("media-count");
  const toggleFloatingBtn = document.getElementById("toggle-floating-btn");

  // 1. Yüzen buton ayarını yükle ve dinle
  chrome.storage.local.get({ showFloatingButton: true }, (res) => {
    if (toggleFloatingBtn) {
      toggleFloatingBtn.checked = res.showFloatingButton !== false;
    }
  });

  toggleFloatingBtn?.addEventListener("change", () => {
    const enabled = toggleFloatingBtn.checked;
    chrome.storage.local.set({ showFloatingButton: enabled });
    chrome.runtime.sendMessage({ type: "TOGGLE_FLOATING_BUTTON", enabled });
  });

  // 2. Aktif sekmeyi sorgula
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.id) return;

  const isYouTube = tab.url && (tab.url.includes("youtube.com/watch") || tab.url.includes("youtube.com/shorts"));

  chrome.runtime.sendMessage({ type: "GET_MEDIA", tabId: tab.id }, async (response) => {
    let items = response?.media || [];
    const subtitles = isYouTube ? [] : (response?.subtitles || []);
    const activeDownloads = response?.activeDownloads || [];

    if (isYouTube) items = items.filter((i) => i.isYouTube);

    if (isYouTube && !items.some((i) => i.isYouTube)) {
      const cleanYtTitle = (tab.title || "YouTube Video").replace(/\s*-\s*YouTube/gi, "").trim();
      items.unshift({
        id: "yt-" + tab.id,
        url: tab.url,
        title: cleanYtTitle + ".mp4",
        format: "YouTube",
        resolution: "1080p / 4K",
        sizeFormatted: "Oturum Açık • Orijinal",
        isYouTube: true,
        isStream: false,
        webpage_url: tab.url
      });
    }

    const mainCount = items.filter((i) => !i.minor).length || items.length;
    mediaCountEl.textContent = mainCount;

    if (items.length === 0 && subtitles.length === 0) {
      emptyStateEl.style.display = "flex";
      mediaListEl.style.display = "none";
      if (subtitleSectionEl) subtitleSectionEl.style.display = "none";
      return;
    }

    emptyStateEl.style.display = "none";
    mediaListEl.style.display = items.length ? "flex" : "none";
    mediaListEl.innerHTML = "";

    const minorCount = items.filter((i) => i.minor).length;
    let minorToggle = null;
    items.forEach((item, idx) => {
      if (item.minor && !minorToggle) {
        minorToggle = document.createElement("button");
        minorToggle.className = "btn minor-toggle";
        minorToggle.textContent = `Diğer ${minorCount} kısa öğe (reklam/parça olabilir) ▾`;
        minorToggle.addEventListener("click", () => {
          const open = minorToggle.dataset.open === "1";
          minorToggle.dataset.open = open ? "0" : "1";
          minorToggle.textContent = `Diğer ${minorCount} kısa öğe (reklam/parça olabilir) ${open ? "▾" : "▴"}`;
          mediaListEl.querySelectorAll(".video-card.minor").forEach((c) => {
            c.style.display = open ? "none" : "";
          });
        });
        mediaListEl.appendChild(minorToggle);
      }
      const card = document.createElement("div");
      card.className = item.minor ? "video-card minor" : (idx === 0 && minorCount ? "video-card main" : "video-card");
      if (item.minor) card.style.display = "none";
      card.id = `card-${item.id}`;

      let resBadge = item.resolution || "";
      if (!resBadge && item.format) {
        const m = item.format.match(/(4K|2K|1080p|720p|480p|360p)/i);
        if (m) resBadge = m[1].toUpperCase();
      }
      if (!resBadge && item.title) {
        const m = item.title.match(/\[(4K|2K|1080p|720p|480p|360p)\]/i);
        if (m) resBadge = m[1].toUpperCase();
      }
      if (!resBadge && item.isStream) {
        resBadge = "HD";
      }

      let qualitySelectorHtml = "";
      if (Array.isArray(item.qualities) && item.qualities.length > 1) {
        qualitySelectorHtml = `<select class="quality-select" id="select-qual-${item.id}">`;
        for (const q of item.qualities) {
          const bwText = q.bwLabel ? ` (${q.bwLabel})` : "";
          qualitySelectorHtml += `<option value="${escapeHtml(q.url)}" data-height="${escapeHtml(String(q.height || ""))}">${escapeHtml(q.qualityLabel)}${bwText}</option>`;
        }
        qualitySelectorHtml += `</select>`;
      }

      let audioSelectorHtml = "";
      if (Array.isArray(item.audioTracks) && item.audioTracks.length > 1) {
        audioSelectorHtml = `<select class="quality-select audio-select" id="select-audio-${item.id}" title="Ses Dili Seçin">`;
        for (const a of item.audioTracks) {
          const langCode = (a.language || "").toUpperCase();
          const langBadge = langCode ? ` (${langCode})` : "";
          const sel = a.isDefault ? " selected" : "";
          audioSelectorHtml += `<option value="${escapeHtml(a.language || a.rawName || "")}" data-lang="${escapeHtml(a.language || "")}" data-name="${escapeHtml(a.rawName || a.name || "")}"${sel}>${escapeHtml(a.label || a.rawName || "Ses")}${escapeHtml(langBadge)}</option>`;
        }
        audioSelectorHtml += `<option value="all" data-lang="all" data-name="">Tüm Sesler (Çift Ses)</option></select>`;
      }

      const selectorsHtml = (qualitySelectorHtml || audioSelectorHtml)
        ? `<div class="video-selectors">${qualitySelectorHtml}${audioSelectorHtml}</div>`
        : "";

      const resBadgeHtml = resBadge ? `<span class="tag-res">${escapeHtml(resBadge)}</span>` : "";
      const sourceBadgeHtml = item.sourceLabel
        ? `<span class="tag-source">${escapeHtml(item.sourceLabel)}</span>`
        : "";
      const audioCountTag = Array.isArray(item.audioTracks) && item.audioTracks.length > 1
        ? `<span class="tag-format">${item.audioTracks.length} Ses</span>`
        : "";

      card.innerHTML = `
        <div class="video-header">
          <div class="video-title" title="${escapeHtml(item.url)}">${escapeHtml(item.title)}</div>
        </div>

        <div class="video-meta-row">
          <div class="video-meta-tags">
            ${resBadgeHtml}
            ${sourceBadgeHtml}
            <span class="tag-format">${escapeHtml(item.ext || "MP4")}</span>
            ${audioCountTag}
            <span class="tag-size">${escapeHtml(item.sizeFormatted || "")}</span>
          </div>
          ${selectorsHtml}
        </div>

        <div class="download-progress-wrap" id="prog-wrap-${item.id}">
          <div class="progress-labels">
            <span id="prog-label-${item.id}">İndiriliyor...</span>
            <span class="pct" id="prog-pct-${item.id}">0%</span>
          </div>
          <div class="progress-track">
            <div class="progress-bar" id="prog-bar-${item.id}"></div>
          </div>
        </div>

        <div class="card-actions">
          <button class="btn btn-primary" id="btn-dl-${item.id}">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="7 10 12 15 17 10"></polyline>
              <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
            ${item.isYouTube ? "YouTube İndir" : "İndir"}
          </button>
          <button class="btn btn-icon btn-ctl" id="btn-pause-${item.id}" data-id="${escapeHtml(item.id)}" title="Duraklat" style="display:none"></button>
          <button class="btn btn-icon btn-ctl" id="btn-cancel-${item.id}" data-id="${escapeHtml(item.id)}" title="İptal et" style="display:none">${ICON_CANCEL}</button>
          <button class="btn btn-icon btn-copy" data-url="${escapeHtml(item.url)}" title="Bağlantıyı Kopyala">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
            </svg>
          </button>
        </div>
      `;

      mediaListEl.appendChild(card);

      const dlBtn = card.querySelector(`#btn-dl-${item.id}`);
      const progWrap = card.querySelector(`#prog-wrap-${item.id}`);
      const progLabel = card.querySelector(`#prog-label-${item.id}`);
      const progPct = card.querySelector(`#prog-pct-${item.id}`);
      const progBar = card.querySelector(`#prog-bar-${item.id}`);
      const qualSelect = card.querySelector(`#select-qual-${item.id}`);
      const audioSelect = card.querySelector(`#select-audio-${item.id}`);

      const existing = activeDownloads.find((d) => d.id === item.id);
      if (existing) {
        dlBtn.disabled = true;
        dlBtn.textContent = "İndiriliyor...";
        progWrap.style.display = "flex";
        progPct.textContent = `${existing.percent}%`;
        progBar.style.width = `${existing.percent}%`;
        const speedText = existing.speedMb ? ` • ${existing.speedMb}` : "";
        const etaText = existing.eta ? ` (${existing.eta})` : "";
        progLabel.textContent = `${existing.percent}%${speedText}${etaText}`;
        updateControls(item.id, existing);
      }

      card.querySelector(`#btn-pause-${CSS.escape(item.id)}`).addEventListener("click", (e) => {
        const btn = e.currentTarget;
        const action = btn.dataset.state === "paused" ? "resume" : "pause";
        btn.disabled = true;
        chrome.runtime.sendMessage({ type: "DESKTOP_CONTROL", id: item.id, action }, (res) => {
          btn.disabled = false;
          if (!res?.success) progLabel.textContent = "Hata: " + (res?.error || "işlem yapılamadı");
        });
      });
      card.querySelector(`#btn-cancel-${CSS.escape(item.id)}`).addEventListener("click", (e) => {
        const btn = e.currentTarget;
        btn.disabled = true;
        chrome.runtime.sendMessage({ type: "DESKTOP_CONTROL", id: item.id, action: "cancel" }, (res) => {
          btn.disabled = false;
          if (!res?.success) progLabel.textContent = "Hata: " + (res?.error || "iptal edilemedi");
        });
      });

      dlBtn.addEventListener("click", () => {
        dlBtn.disabled = true;
        dlBtn.textContent = "Başlatılıyor...";
        progWrap.style.display = "flex";
        progPct.textContent = "1%";
        progBar.style.width = "1%";
        progLabel.textContent = "Bağlanıyor...";

        const msgType = item.isYouTube ? "START_YOUTUBE_DOWNLOAD" : "START_STREAM_DOWNLOAD";
        const selectedUrl = qualSelect ? qualSelect.value : (item.targetUrl || item.url);
        const selectedOpt = qualSelect ? qualSelect.options[qualSelect.selectedIndex] : null;
        const selectedQuality = selectedOpt?.dataset?.height || item.quality || null;
        const selectedAudioOpt = audioSelect ? audioSelect.options[audioSelect.selectedIndex] : null;
        const selectedAudioLang = selectedAudioOpt ? (selectedAudioOpt.dataset?.lang || null) : null;
        const selectedAudioName = selectedAudioOpt ? (selectedAudioOpt.dataset?.name || null) : null;

        chrome.runtime.sendMessage({
          type: msgType,
          id: item.id,
          url: selectedUrl,
          streamUrl: selectedUrl,
          masterUrl: item.masterUrl || (item.isMaster ? item.url : ""),
          hasExternalAudio: Boolean(item.hasExternalAudio || (item.audioTracks && item.audioTracks.length > 1)),
          quality: selectedQuality,
          audioLang: selectedAudioLang,
          audioName: selectedAudioName,
          refererUrl: item.refererUrl || item.webpage_url,
          title: item.title,
          isYouTube: Boolean(item.isYouTube),
          isStream: Boolean(item.isStream)
        }, (res) => {
          if (res?.success && res.desktop && !res.tracking) {
            progPct.textContent = "";
            progBar.style.width = "100%";
            progLabel.textContent = "NovaStream uygulamasına aktarıldı";
            dlBtn.textContent = "Uygulamada";
            return;
          }
          if (!res?.success) {
            progLabel.textContent = "Hata: " + (res?.error || "Başlatılamadı");
            dlBtn.disabled = false;
            dlBtn.textContent = "Tekrar Dene";
          }
        });
      });
    });

    // Altyazılar bölümü
    if (subtitleSectionEl && subtitleListEl && subtitles.length > 0) {
      subtitleSectionEl.style.display = "flex";
      subtitleListEl.innerHTML = "";
      subtitles.forEach((sub) => {
        const row = document.createElement("div");
        row.className = "subtitle-card";
        const formatText = sub.canConvertToSrt ? `${sub.format || "VTT"} → SRT` : (sub.format || "SRT");
        const metaParts = [sub.sourceLabel, formatText].filter(Boolean).join(" • ");
        row.innerHTML = `
          <div class="subtitle-info" title="${escapeHtml(sub.url)}">
            <span class="tag-lang">${escapeHtml(sub.langCode || "ALT")}</span>
            <span class="subtitle-label">${escapeHtml(sub.label || "Altyazı")}</span>
            <span class="subtitle-meta">${escapeHtml(metaParts)}</span>
          </div>
          <div class="subtitle-actions">
            <button class="btn btn-sub-dl" type="button">SRT İndir</button>
            <button class="btn btn-icon btn-copy" data-url="${escapeHtml(sub.url)}" title="Altyazı URL Kopyala">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
              </svg>
            </button>
          </div>
        `;
        const dlSubBtn = row.querySelector(".btn-sub-dl");
        dlSubBtn.addEventListener("click", () => {
          dlSubBtn.disabled = true;
          dlSubBtn.textContent = "İndiriliyor...";
          chrome.runtime.sendMessage({
            type: "DOWNLOAD_SUBTITLE",
            url: sub.url,
            refererUrl: sub.refererUrl || tab.url || "",
            title: sub.title || tab.title || "altyazi",
            langCode: sub.langCode || "",
            ext: sub.ext || "vtt",
            isHlsSubtitle: Boolean(sub.isHlsSubtitle),
            convertToSrt: true
          }, (res) => {
            dlSubBtn.disabled = false;
            dlSubBtn.textContent = res?.success ? "Kaydedildi ✓" : "Hata!";
            setTimeout(() => {
              dlSubBtn.textContent = "SRT İndir";
            }, 2500);
          });
        });
        subtitleListEl.appendChild(row);
      });
    } else if (subtitleSectionEl) {
      subtitleSectionEl.style.display = "none";
    }

    // Kopyalama butonları (video + altyazı)
    document.querySelectorAll(".btn-copy").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const url = btn.getAttribute("data-url");
        try {
          await navigator.clipboard.writeText(url);
          const original = btn.innerHTML;
          btn.textContent = "Kopyalandı";
          setTimeout(() => {
            btn.innerHTML = original;
          }, 1500);
        } catch {
          alert("Kopyalanamadı.");
        }
      });
    });
  });

  // Canlı İlerleme Dinleyicisi
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === "DOWNLOAD_PROGRESS") {
      const progWrap = document.getElementById(`prog-wrap-${msg.id}`);
      const progLabel = document.getElementById(`prog-label-${msg.id}`);
      const progPct = document.getElementById(`prog-pct-${msg.id}`);
      const progBar = document.getElementById(`prog-bar-${msg.id}`);
      const dlBtn = document.getElementById(`btn-dl-${msg.id}`);

      if (progWrap && dlBtn) {
        progWrap.style.display = "flex";
        dlBtn.disabled = true;
        dlBtn.textContent = msg.desktopState === "paused" ? "Duraklatıldı" : "İndiriliyor...";
        updateControls(msg.id, msg);
        progPct.textContent = `${msg.percent}%`;
        progBar.style.width = `${msg.percent}%`;

        const speedText = msg.speedMb ? ` • ${msg.speedMb}` : "";
        const sizeText = msg.mbTotal ? ` (${msg.mbTotal})` : "";
        const etaText = msg.eta ? ` [${msg.eta}]` : "";
        progLabel.textContent = `${msg.percent}%${sizeText}${speedText}${etaText}`;
      }
    } else if (msg.type === "DOWNLOAD_FINISHED") {
      const progWrap = document.getElementById(`prog-wrap-${msg.id}`);
      const progLabel = document.getElementById(`prog-label-${msg.id}`);
      const dlBtn = document.getElementById(`btn-dl-${msg.id}`);
      updateControls(msg.id, null);

      if (dlBtn) {
        dlBtn.disabled = false;
        dlBtn.textContent = msg.success ? "İndirildi" : "Hata!";
        if (!msg.success && progLabel && msg.error) {
          progLabel.textContent = "Hata: " + msg.error;
        } else if (progWrap) {
          setTimeout(() => {
            progWrap.style.display = "none";
          }, 2500);
        }
      }
    }
  });
});

const ICON_PAUSE = `<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16" rx="1"></rect><rect x="14" y="4" width="4" height="16" rx="1"></rect></svg>`;
const ICON_PLAY = `<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M7 4.5v15a1 1 0 0 0 1.5.86l12-7.5a1 1 0 0 0 0-1.72l-12-7.5A1 1 0 0 0 7 4.5z"></path></svg>`;
const ICON_CANCEL = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><line x1="6" y1="6" x2="18" y2="18"></line><line x1="18" y1="6" x2="6" y2="18"></line></svg>`;

function updateControls(id, rec) {
  const pauseBtn = document.getElementById(`btn-pause-${id}`);
  const cancelBtn = document.getElementById(`btn-cancel-${id}`);
  if (!pauseBtn || !cancelBtn) return;
  const show = Boolean(rec && rec.desktop);
  pauseBtn.style.display = show ? "" : "none";
  cancelBtn.style.display = show ? "" : "none";
  if (!show) return;
  const paused = rec.desktopState === "paused";
  if (pauseBtn.dataset.state !== (paused ? "paused" : "running")) {
    pauseBtn.dataset.state = paused ? "paused" : "running";
    pauseBtn.innerHTML = paused ? ICON_PLAY : ICON_PAUSE;
    pauseBtn.title = paused ? "Devam et" : "Duraklat";
  }
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

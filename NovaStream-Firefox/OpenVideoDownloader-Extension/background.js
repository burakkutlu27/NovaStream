// NovaStream - Service Worker (Ağ Yığını, Master Playlist Çözünürlük Ayrıştırıcı & Native Host Yöneticisi)

const tabMediaMap = new Map();
const tabKnownSubstreams = new Map(); // tabId -> Set of variant playlist URLs
const inspectingUrls = new Set();
const activeDownloads = new Map();
let nativePort = null;
let dnrCounter = 10000;

// Segment filtreleri (parçaları ana liste sanmamak için)
const SEGMENT_PATTERNS = [
  /\/segment\.(m4s|mp4|ts)(\?|$)/i,
  /\/seg-\d+/i,
  /\/(audio|video)_\d+/i,
  /\/\d+\.(m4s|ts)(\?|$)/i,
  /\.m4s(\?|$)/i,
  /\/chunk-\d+/i,
  /range\/\d+-\d+/i,
  /bytes=\d+-\d+/i,
  /\/init\.(m4s|mp4)(\?|$)/i,
  /\/cmf[av]/i,
  /st=audio/i,
  /type=audio/i
];

function isSegment(url) {
  return SEGMENT_PATTERNS.some((rx) => rx.test(url));
}

// YouTube oynatıcısının parça istekleri (googlevideo /videoplayback) tek başına
// indirilemez; birkaç KB'lık işe yaramaz dosya çıkar. YouTube videoları yt-dlp ile iner.
function isYouTubeChunk(url) {
  return /^https?:\/\/[^/]*googlevideo\.com\//i.test(url) || /\/videoplayback(\?|\/|$)/i.test(url);
}

function isYouTubePage(url) {
  return /^https?:\/\/([^/]*\.)?(youtube\.com|youtu\.be)(?=[\/:?#]|$)/i.test(url || "");
}

function parseVideoType(contentType, url) {
  const ct = (contentType || "").toLowerCase();
  const u = (url || "").toLowerCase();

  if (ct.includes("text/html") || ct.includes("application/json") || ct.includes("text/plain")) {
    return null;
  }

  if (ct.includes("mpegurl") || ct.includes("application/x-mpegurl") || u.includes(".m3u8")) {
    return { format: "HLS", ext: "mp4", isStream: true };
  }
  if (ct.includes("dash+xml") || u.includes(".mpd")) {
    return { format: "DASH", ext: "mpd", isStream: true };
  }
  if (ct.includes("video/mp4") || u.includes(".mp4")) {
    return { format: "MP4", ext: "mp4", isStream: false };
  }
  if (ct.includes("video/webm") || u.includes(".webm")) {
    return { format: "WebM", ext: "webm", isStream: false };
  }
  if (ct.includes("video/x-matroska") || u.includes(".mkv")) {
    return { format: "MKV", ext: "mkv", isStream: false };
  }
  if (ct.includes("video/quicktime") || u.includes(".mov")) {
    return { format: "MOV", ext: "mov", isStream: false };
  }
  if (ct.startsWith("video/")) {
    const subtype = ct.split("/")[1]?.split(";")[0] || "mp4";
    return { format: subtype.toUpperCase(), ext: subtype, isStream: false };
  }

  return null;
}

function getResLabel(height) {
  if (height >= 2160) return "4K UHD";
  if (height >= 1440) return "2K QHD";
  if (height >= 1080) return "1080p FHD";
  if (height >= 720) return "720p HD";
  if (height >= 480) return "480p";
  if (height >= 360) return "360p";
  if (height > 0) return `${height}p`;
  return "";
}

function extractResolutionFromUrl(url) {
  const m = url.match(/[\/_\.-](2160|1440|1080|720|480|360)p?(?:[\/_\.-]|$)/i);
  if (m) {
    const h = parseInt(m[1], 10);
    return getResLabel(h);
  }
  return null;
}

function getMediaDedupeKey(url) {
  try {
    const u = new URL(url);
    u.search = "";
    return (u.origin + u.pathname).toLowerCase();
  } catch {
    return url.split("?")[0].toLowerCase();
  }
}

// Master Playlist Ayrıştırıcı (#EXT-X-STREAM-INF)
function parseMasterPlaylist(text, baseUrl) {
  const lines = text.split("\n");
  const variants = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (line.startsWith("#EXT-X-STREAM-INF")) {
      const bwMatch = line.match(/BANDWIDTH=(\d+)/i);
      const resMatch = line.match(/RESOLUTION=(\d+)x(\d+)/i);
      const fpsMatch = line.match(/FRAME-RATE=([\d\.]+)/i);

      const bandwidth = bwMatch ? parseInt(bwMatch[1], 10) : 0;
      const width = resMatch ? parseInt(resMatch[1], 10) : 0;
      const height = resMatch ? parseInt(resMatch[2], 10) : 0;
      const fps = fpsMatch ? Math.round(parseFloat(fpsMatch[1])) : 0;

      let variantUrl = null;
      for (let j = i + 1; j < lines.length; j++) {
        const sub = lines[j].trim();
        if (sub && !sub.startsWith("#")) {
          try {
            variantUrl = new URL(sub, baseUrl).href;
          } catch {}
          break;
        }
      }

      if (variantUrl) {
        let qualityLabel = getResLabel(height);
        if (!qualityLabel) {
          qualityLabel = bandwidth > 0 ? `${Math.round(bandwidth / 1000)}k` : "HD";
        }
        if (fps && fps > 30) {
          qualityLabel += ` ${fps}fps`;
        }

        let bwLabel = "";
        if (bandwidth >= 1000000) {
          bwLabel = `${(bandwidth / 1000000).toFixed(1)} Mbps`;
        } else if (bandwidth > 0) {
          bwLabel = `${Math.round(bandwidth / 1000)} Kbps`;
        }

        variants.push({
          url: variantUrl,
          width,
          height,
          bandwidth,
          fps,
          qualityLabel,
          bwLabel
        });
      }
    }
  }

  // En yüksek kalite en başta olacak şekilde sırala
  variants.sort((a, b) => (b.height * 10000000 + b.bandwidth) - (a.height * 10000000 + a.bandwidth));
  return variants;
}

// Medya oynatma listesinin toplam süresi (sn). Canlı yayında (#EXT-X-ENDLIST yok) null.
function playlistDuration(text) {
  if (!text || !text.includes("#EXTINF")) return null;
  let total = 0;
  for (const m of text.matchAll(/#EXTINF:\s*([\d.]+)/g)) total += parseFloat(m[1]) || 0;
  return text.includes("#EXT-X-ENDLIST") ? Math.round(total) : null;
}

function formatDuration(sec) {
  if (!sec || sec <= 0) return "";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  if (h) return `${h} sa ${String(m).padStart(2, "0")} dk`;
  if (m) return `${m} dk ${String(s).padStart(2, "0")} sn`;
  return `${s} sn`;
}

// Bir sayfada yakalanan medyayı sıralar: asıl video(lar) başa, kısa parçalar/reklamlar
// "minor", aynı akışın kopyaları "duplicate" olarak işaretlenir.
const MAIN_MIN_DURATION = 5 * 60;          // 5 dk
const MAIN_MIN_BYTES = 30 * 1024 * 1024;   // 30 MB
function isMainCandidate(it) {
  if (it.durationSec) return it.durationSec >= MAIN_MIN_DURATION;
  if (it.sizeBytes) return it.sizeBytes >= MAIN_MIN_BYTES;
  return Boolean(it.isStream);             // süresi/boyutu bilinmeyen akış (ör. canlı yayın)
}

function rankMediaList(list) {
  const items = list.map((it) => ({ ...it, minor: false, duplicate: false }));
  // Aynı süreli akışlar (farklı imzalı adreslerle tekrar yüklenen aynı video) tek kayıt olsun
  const seenDur = [];
  for (const it of items) {
    if (!it.isStream || !it.durationSec) continue;
    const twin = seenDur.find((d) => Math.abs(d.durationSec - it.durationSec) <= 1);
    if (twin) {
      // Kalite seçenekleri olanı tut
      if ((it.qualities?.length || 0) > (twin.qualities?.length || 0)) {
        twin.duplicate = true;
        seenDur[seenDur.indexOf(twin)] = it;
      } else {
        it.duplicate = true;
      }
    } else {
      seenDur.push(it);
    }
  }
  const visible = items.filter((it) => !it.duplicate);
  const hasMain = visible.some(isMainCandidate);
  if (hasMain) for (const it of visible) it.minor = !isMainCandidate(it);
  const weight = (it) => (it.durationSec || 0) * 1e6 + (it.sizeBytes || 0) / 1024;
  visible.sort((a, b) => (a.minor - b.minor) || (weight(b) - weight(a)) || (b.timestamp - a.timestamp));
  return visible;
}

function cleanTitle(title, fallback) {
  if (!title) return fallback || "video";
  // Yalnızca dosya sistemlerinde yasak karakterleri değiştir; Türkçe ve diğer Unicode harfler korunur
  return title
    .replace(/[\\/:*?"<>|\u0000-\u001f]/g, "_")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/[. ]+$/, "")
    .substring(0, 120) || fallback || "video";
}

function formatBytes(bytes) {
  if (!bytes || bytes <= 0) return "Akış (HLS)";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let val = bytes;
  while (val >= 1024 && i < units.length - 1) {
    val /= 1024;
    i++;
  }
  return `${val.toFixed(1)} ${units[i]}`;
}

function updateBadge(tabId) {
  const items = rankMediaList(tabMediaMap.get(tabId) || []);
  const count = items.filter((it) => !it.minor).length;
  chrome.action.setBadgeText({
    tabId,
    text: count > 0 ? String(count) : ""
  });
  chrome.action.setBadgeBackgroundColor({
    tabId,
    color: "#2563eb"
  });
}

// Eski DNR kurallarını temizleme
async function cleanupAllDnrRules() {
  try {
    if (!chrome.declarativeNetRequest) return;
    const dyn = await chrome.declarativeNetRequest.getDynamicRules?.();
    if (dyn && dyn.length > 0) {
      await chrome.declarativeNetRequest.updateDynamicRules({
        removeRuleIds: dyn.map((r) => r.id)
      });
    }
    if (chrome.declarativeNetRequest.getSessionRules) {
      const ses = await chrome.declarativeNetRequest.getSessionRules();
      if (ses && ses.length > 0) {
        await chrome.declarativeNetRequest.updateSessionRules({
          removeRuleIds: ses.map((r) => r.id)
        });
      }
    }
  } catch (e) {
    console.warn("cleanupAllDnrRules error:", e);
  }
}

cleanupAllDnrRules();
chrome.runtime.onStartup.addListener(cleanupAllDnrRules);
chrome.runtime.onInstalled.addListener(cleanupAllDnrRules);

// Sağ tık menüsü: bağlantı / video / ses öğesini NovaStream ile indir
function setupContextMenu() {
  if (!chrome.contextMenus) return;
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: "novastream-download",
      title: "NovaStream ile indir",
      contexts: ["link", "video", "audio"]
    });
  });
}
chrome.runtime.onInstalled.addListener(setupContextMenu);
chrome.runtime.onStartup.addListener(setupContextMenu);

if (chrome.contextMenus) {
  chrome.contextMenus.onClicked.addListener(async (info, tab) => {
    if (info.menuItemId !== "novastream-download") return;
    const url = info.linkUrl || info.srcUrl;
    if (!url || !/^https?:/i.test(url)) return;
    const isYouTube = /(^|\.)(youtube\.com|youtu\.be)\//i.test(url.replace(/^https?:\/\//, ""));
    try {
      const where = await delegateToYtDlp({
        id: "ctx-" + Date.now(),
        url,
        refererUrl: tab?.url || "",
        title: "",
        isYouTube
      });
      chrome.notifications?.create({
        type: "basic",
        iconUrl: "icons/icon48.png",
        title: "NovaStream",
        message: where === "desktop" ? "İndirme NovaStream uygulamasına eklendi." : "İndirme başlatıldı."
      });
    } catch (e) {
      chrome.notifications?.create({
        type: "basic",
        iconUrl: "icons/icon48.png",
        title: "NovaStream",
        message: "İndirme başlatılamadı: " + e.message
      });
    }
  });
}

// Scoped Referer & Origin Kuralı
async function withScopedHeaders(targetUrls, refererUrl, taskFn) {
  if (!refererUrl || !refererUrl.startsWith("http")) {
    return await taskFn();
  }

  const hostnames = new Set();
  for (const u of targetUrls) {
    if (!u) continue;
    try {
      const host = new URL(u).hostname;
      if (host) hostnames.add(host);
    } catch {}
  }

  if (hostnames.size === 0) {
    return await taskFn();
  }

  let origin = "";
  try {
    origin = new URL(refererUrl).origin;
  } catch {}

  const rules = [];
  const addedIds = [];

  for (const host of hostnames) {
    const ruleId = ++dnrCounter;
    addedIds.push(ruleId);
    const headers = [{ header: "Referer", operation: "set", value: refererUrl }];
    if (origin) {
      headers.push({ header: "Origin", operation: "set", value: origin });
    }
    rules.push({
      id: ruleId,
      priority: 2,
      action: {
        type: "modifyHeaders",
        requestHeaders: headers
      },
      condition: {
        urlFilter: `||${host}`,
        resourceTypes: ["xmlhttprequest", "media", "other"]
      }
    });
  }

  try {
    if (chrome.declarativeNetRequest?.updateSessionRules) {
      await chrome.declarativeNetRequest.updateSessionRules({
        addRules: rules,
        removeRuleIds: addedIds
      });
    } else if (chrome.declarativeNetRequest?.updateDynamicRules) {
      await chrome.declarativeNetRequest.updateDynamicRules({
        addRules: rules,
        removeRuleIds: addedIds
      });
    }
  } catch (err) {
    console.warn("Scoped header error:", err);
  }

  try {
    return await taskFn();
  } finally {
    try {
      if (chrome.declarativeNetRequest?.updateSessionRules) {
        await chrome.declarativeNetRequest.updateSessionRules({
          removeRuleIds: addedIds
        });
      } else if (chrome.declarativeNetRequest?.updateDynamicRules) {
        await chrome.declarativeNetRequest.updateDynamicRules({
          removeRuleIds: addedIds
        });
      }
    } catch {}
  }
}

function broadcastToTabs(payload) {
  chrome.tabs.query({}, (tabs) => {
    for (const t of tabs) {
      if (t.id) {
        chrome.tabs.sendMessage(t.id, payload).catch(() => {});
      }
    }
  });
}

function addMediaItem(tabId, media) {
  if (!tabMediaMap.has(tabId)) {
    tabMediaMap.set(tabId, []);
  }
  const list = tabMediaMap.get(tabId);

  if (isSegment(media.url) || isYouTubeChunk(media.url) || isYouTubePage(media.webpage_url)) return;

  // Deduplication Kontrolü
  const dedupeKey = getMediaDedupeKey(media.url);
  const existingIdx = list.findIndex(
    (item) => item.url === media.url || getMediaDedupeKey(item.url) === dedupeKey
  );

  if (existingIdx >= 0) {
    const existing = list[existingIdx];
    // Eğer mevcut öğe generic HLS ve yeni öğe çözünürlük bilgisi içeriyorsa güncelle
    if (media.qualities && (!existing.qualities || existing.qualities.length === 0)) {
      list[existingIdx] = media;
      updateBadge(tabId);
      chrome.tabs.sendMessage(tabId, {
        type: "MEDIA_DETECTED",
        item: media,
        allItems: rankMediaList(list)
      }).catch(() => {});
    }
    return;
  }

  list.push(media);
  updateBadge(tabId);

  chrome.tabs.sendMessage(tabId, {
    type: "MEDIA_DETECTED",
    item: media,
    allItems: rankMediaList(list)
  }).catch(() => {});
}

// Ağ Dinleyicisi
chrome.webRequest.onHeadersReceived.addListener(
  (details) => {
    const { tabId, url, responseHeaders } = details;
    if (tabId < 0 || isSegment(url) || isYouTubeChunk(url)) return;
    if (isYouTubePage(details.initiator) || isYouTubePage(details.documentUrl)) return;

    // 1. Bilinen alt akış (variant) ise çift kayıt eklememek için atla
    const knownSubs = tabKnownSubstreams.get(tabId);
    if (knownSubs && knownSubs.has(url)) {
      return;
    }

    let contentType = "";
    let contentLength = 0;

    if (responseHeaders) {
      for (const h of responseHeaders) {
        const name = h.name.toLowerCase();
        if (name === "content-type") {
          contentType = h.value || "";
        } else if (name === "content-length") {
          contentLength = parseInt(h.value || "0", 10);
        }
      }
    }

    const videoType = parseVideoType(contentType, url);
    if (!videoType) return;

    if (!videoType.isStream && contentLength > 0 && contentLength < 300 * 1024) {
      return;
    }

    // Deduplication kontrolü
    const dedupeKey = getMediaDedupeKey(url);
    const existingList = tabMediaMap.get(tabId) || [];
    if (existingList.some((item) => getMediaDedupeKey(item.url) === dedupeKey)) {
      return;
    }

    chrome.tabs.get(tabId, async (tab) => {
      if (chrome.runtime.lastError || !tab) return;
      const pageTitle = cleanTitle(tab.title, "video");

      let mediaPlaylistDuration = null;
      // HLS Akışı ise Master Playlist kontrolü yap
      if (videoType.isStream && (url.includes(".m3u8") || contentType.includes("mpegurl"))) {
        if (!inspectingUrls.has(url)) {
          inspectingUrls.add(url);
          try {
            const resp = await fetch(url, { headers: { Referer: tab.url || "" } });
            if (resp.ok) {
              const text = await resp.text();
              if (text.includes("#EXT-X-STREAM-INF")) {
                const variants = parseMasterPlaylist(text, url);
                if (variants.length > 0) {
                  if (!tabKnownSubstreams.has(tabId)) {
                    tabKnownSubstreams.set(tabId, new Set());
                  }
                  const subs = tabKnownSubstreams.get(tabId);
                  for (const v of variants) {
                    subs.add(v.url);
                  }

                  const best = variants[0];
                  let durationSec = null;
                  try {
                    const vr = await fetch(best.url, { headers: { Referer: tab.url || "" } });
                    if (vr.ok) durationSec = playlistDuration(await vr.text());
                  } catch (e) {}
                  const durText = formatDuration(durationSec);
                  const item = {
                    id: crypto.randomUUID(),
                    url: url,
                    targetUrl: best.url,
                    webpage_url: tab.url || "",
                    title: `${pageTitle} [${best.qualityLabel}].mp4`,
                    format: best.qualityLabel,
                    resolution: best.qualityLabel,
                    ext: "mp4",
                    isStream: true,
                    sizeFormatted: [durText, best.bwLabel, "Akış"].filter(Boolean).join(" • "),
                    sizeBytes: 0,
                    durationSec,
                    qualities: variants,
                    timestamp: Date.now()
                  };
                  addMediaItem(tabId, item);
                  return;
                }
              } else {
                mediaPlaylistDuration = playlistDuration(text);
              }
            }
          } catch (e) {
            // fetch başarısız olursa normal eklemeye devam et
          }
        }
      }

      // Standart veya tekil medya
      const urlRes = extractResolutionFromUrl(url);
      const resLabel = urlRes || (videoType.isStream ? "HD" : "");
      const formatStr = resLabel ? `${resLabel} ${videoType.format}` : videoType.format;

      const item = {
        id: crypto.randomUUID(),
        url: url,
        webpage_url: tab.url || "",
        title: `${pageTitle}${resLabel ? " [" + resLabel + "]" : ""}.${videoType.ext}`,
        format: formatStr,
        resolution: resLabel,
        ext: videoType.ext,
        isStream: videoType.isStream,
        sizeFormatted: mediaPlaylistDuration
          ? `${formatDuration(mediaPlaylistDuration)} • Akış`
          : formatBytes(contentLength),
        sizeBytes: contentLength,
        durationSec: mediaPlaylistDuration,
        timestamp: Date.now()
      };

      addMediaItem(tabId, item);
    });
  },
  { urls: ["<all_urls>"] },
  ["responseHeaders"]
);

// Native Host Bağlantısı
function getNativePort() {
  if (!nativePort) {
    try {
      nativePort = chrome.runtime.connectNative("com.novastream.downloader");
    } catch (err) {
      console.error("connectNative exception:", err);
      nativePort = null;
      throw new Error("Native Host başlatılamadı: " + err.message);
    }

    nativePort.onMessage.addListener((msg) => {
      if (msg.type === "PROGRESS") {
        const itemInfo = activeDownloads.get(msg.id) || {};
        activeDownloads.set(msg.id, {
          ...itemInfo,
          id: msg.id,
          percent: msg.percent,
          speedMb: msg.speedMb,
          mbTotal: msg.mbTotal,
          eta: msg.eta,
          status: "indiriliyor"
        });

        chrome.action.setBadgeText({ text: `${msg.percent}%` });
        chrome.action.setBadgeBackgroundColor({ color: "#2563eb" });

        const progressPayload = {
          type: "DOWNLOAD_PROGRESS",
          id: msg.id,
          percent: msg.percent,
          speedMb: msg.speedMb,
          mbTotal: msg.mbTotal,
          eta: msg.eta,
          filename: itemInfo.filename || msg.filename || "",
          title: itemInfo.filename || msg.filename || "",
          status: "downloading"
        };
        chrome.runtime.sendMessage(progressPayload).catch(() => {});
        broadcastToTabs(progressPayload);
        reportProgressToDesktopApp(progressPayload);
      } else if (msg.type === "COMPLETE") {
        const itemInfo = activeDownloads.get(msg.id) || {};
        activeDownloads.delete(msg.id);
        chrome.action.setBadgeText({ text: msg.success ? "OK" : "ERR" });
        chrome.action.setBadgeBackgroundColor({ color: msg.success ? "#10b981" : "#ef4444" });

        const finalName = msg.filename || itemInfo.filename || "video.mp4";
        const finishedPayload = {
          type: "DOWNLOAD_FINISHED",
          id: msg.id,
          success: msg.success,
          filename: finalName,
          title: finalName,
          error: msg.error,
          status: msg.success ? "completed" : "error",
          percent: msg.success ? 100 : (itemInfo.percent || 0),
          speedMb: msg.success ? "Tamamlandı" : "Hata",
          eta: ""
        };
        chrome.runtime.sendMessage(finishedPayload).catch(() => {});
        broadcastToTabs(finishedPayload);
        reportProgressToDesktopApp(finishedPayload);

        setTimeout(() => {
          chrome.action.setBadgeText({ text: "" });
        }, 4000);
      }
    });

    nativePort.onDisconnect.addListener(() => {
      const lastError = chrome.runtime.lastError?.message || "Bağlantı kapandı";
      console.warn("NativePort kapandı:", lastError);
      nativePort = null;
    });
  }
  return nativePort;
}

function sendNativeMessage(port, msg) {
  let activePort = port || nativePort;
  if (!activePort) {
    try {
      activePort = getNativePort();
    } catch (e) {
      throw new Error("Native Host bağlantısı kurulamadı: " + e.message);
    }
  }
  try {
    activePort.postMessage(msg);
  } catch (err) {
    nativePort = null;
    throw new Error("Native Host ile bağlantı kurulamadı (" + err.message + ").");
  }
}

function uint8ToBase64(bytes) {
  let binary = "";
  const sliceSize = 0x8000;
  for (let i = 0; i < bytes.length; i += sliceSize) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + sliceSize));
  }
  return btoa(binary);
}

function sendBufferToNative(port, jobId, uint8Buf) {
  const MAX_IPC_CHUNK = 128 * 1024;
  for (let offset = 0; offset < uint8Buf.length; offset += MAX_IPC_CHUNK) {
    const slice = uint8Buf.subarray(offset, offset + MAX_IPC_CHUNK);
    sendNativeMessage(port, {
      action: "FILE_CHUNK",
      id: jobId,
      data: uint8ToBase64(slice)
    });
  }
}

function reportProgressToDesktopApp(payload) {
  fetch("http://127.0.0.1:9191/api/task_progress", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  }).catch(() => {});
}

function emitProgress(id, percent, speedMb, mbTotal, eta, filename = "", url = "", report = true, extra = {}) {
  const current = activeDownloads.get(id) || {};
  const effectiveFilename = filename || current.filename || "";
  const effectiveUrl = url || current.url || "";

  activeDownloads.set(id, {
    ...current,
    id,
    percent,
    speedMb,
    mbTotal,
    eta,
    filename: effectiveFilename,
    url: effectiveUrl,
    status: "indiriliyor",
    ...extra
  });

  chrome.action.setBadgeText({ text: `${percent}%` });
  chrome.action.setBadgeBackgroundColor({ color: "#2563eb" });

  const payload = {
    type: "DOWNLOAD_PROGRESS",
    id,
    percent,
    speedMb,
    mbTotal,
    eta,
    filename: effectiveFilename,
    title: effectiveFilename,
    url: effectiveUrl,
    status: "downloading",
    ...extra
  };
  chrome.runtime.sendMessage(payload).catch(() => {});
  broadcastToTabs(payload);
  if (report) reportProgressToDesktopApp(payload);
}

function emitFinished(id, success, filename, error, report = true) {
  const itemInfo = activeDownloads.get(id) || {};
  activeDownloads.delete(id);
  chrome.action.setBadgeText({ text: success ? "OK" : "ERR" });
  chrome.action.setBadgeBackgroundColor({ color: success ? "#10b981" : "#ef4444" });

  const finalName = filename || itemInfo.filename || "video.mp4";
  const payload = {
    type: "DOWNLOAD_FINISHED",
    id,
    success,
    filename: finalName,
    title: finalName,
    error,
    status: success ? "completed" : "error",
    percent: success ? 100 : 0,
    speedMb: success ? "Tamamlandı" : "Hata",
    eta: ""
  };
  chrome.runtime.sendMessage(payload).catch(() => {});
  broadcastToTabs(payload);
  if (report) reportProgressToDesktopApp(payload);
  setTimeout(() => {
    chrome.action.setBadgeText({ text: "" });
  }, 4000);
}

// Tarayıcı ağıyla birleştirilemeyen akışları (DASH, şifreli HLS, ayrı ses kanallı HLS) yt-dlp'ye devret.
// Önce açık masaüstü uygulamasına, değilse native host'taki yt-dlp'ye gönderilir.
function notifyHandoff(id, title) {
  activeDownloads.delete(id);
  chrome.action.setBadgeText({ text: "" });
  const payload = { type: "DOWNLOAD_HANDOFF", id, title };
  chrome.runtime.sendMessage(payload).catch(() => {});
  broadcastToTabs(payload);
}

// Masaüstü uygulamasına devredilen indirmelerin ilerlemesini uygulamadan okuyup
// eklentide (açılır pencere + video üstündeki düğme) gösterir.
const desktopTracked = new Map(); // eklenti id -> { desktopId, title, misses }
let desktopPollTimer = null;

function formatBytesShort(n) {
  if (!n || n <= 0) return "";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function trackDesktopTask(extId, desktopId, title) {
  if (!extId || !desktopId || desktopId === "pending_dialog") return false;
  desktopTracked.set(extId, { desktopId, title: title || "", misses: 0 });
  emitProgress(extId, 1, "NovaStream'de başlatılıyor...", "", "", title || "", "", false,
    { desktop: true, desktopState: "downloading" });
  const rec = activeDownloads.get(extId);
  if (rec) rec.desktop = true;
  if (!desktopPollTimer) desktopPollTimer = setTimeout(pollDesktopTasks, 700);
  return true;
}

async function pollDesktopTasks() {
  desktopPollTimer = null;
  if (desktopTracked.size === 0) return;

  let tasks = null;
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 2500);
    const res = await fetch("http://127.0.0.1:9191/api/tasks", { signal: controller.signal });
    clearTimeout(timer);
    if (res.ok) tasks = (await res.json()).tasks || [];
  } catch (e) {
    tasks = null;
  }

  for (const [extId, info] of desktopTracked) {
    const task = tasks ? tasks.find((t) => t.id === info.desktopId) : undefined;
    if (!task) {
      info.misses += 1;
      // Görev uygulamada silindiyse ~3 sn, uygulama kapandıysa ~15 sn sonra bırak.
      if (info.misses >= (tasks ? 3 : 15)) {
        desktopTracked.delete(extId);
        emitFinished(extId, false, info.title,
          tasks ? "İndirme uygulamada kaldırıldı" : "NovaStream uygulamasına ulaşılamıyor", false);
      }
      continue;
    }
    info.misses = 0;

    let name = task.filename || "";
    if (!name || /^https?:/i.test(name)) name = info.title;

    if (task.status === "completed") {
      desktopTracked.delete(extId);
      emitFinished(extId, true, name, null, false);
    } else if (task.status === "error") {
      desktopTracked.delete(extId);
      emitFinished(extId, false, name, task.error_message || "İndirme başarısız", false);
    } else {
      const pct = Math.max(1, Math.min(99, Math.floor(Number(task.percent) || 0)));
      let speed = task.speed || "İndiriliyor";
      if (task.status === "paused") speed = "Duraklatıldı";
      else if (task.status === "queued") speed = "Sırada bekliyor";
      const eta = task.status === "downloading" && task.eta && task.eta !== "--:--" ? task.eta : "";
      emitProgress(extId, pct, speed, formatBytesShort(task.total_bytes), eta, name, "", false,
        { desktop: true, desktopState: task.status });
    }
  }

  if (desktopTracked.size > 0) desktopPollTimer = setTimeout(pollDesktopTasks, 1000);
}

async function controlDesktopTask(extId, action) {
  const info = desktopTracked.get(extId);
  if (!info) return { success: false, error: "Bu indirme uygulamada izlenmiyor" };
  try {
    const res = await fetch("http://127.0.0.1:9191/api/control", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: info.desktopId, action })
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return { success: false, error: data.error || `HTTP ${res.status}` };
    if (action === "cancel") {
      desktopTracked.delete(extId);
      emitFinished(extId, false, info.title, "İptal edildi", false);
    } else if (["paused", "downloading", "queued"].includes(data.status)) {
      // Durumu hemen yansıt; ayrıntı bir sonraki sorguda gelir.
      const cur = activeDownloads.get(extId) || {};
      const paused = data.status === "paused";
      emitProgress(extId, cur.percent || 1, paused ? "Duraklatıldı" : "Devam ediyor...", cur.mbTotal || "",
        "", cur.filename || info.title, "", false, { desktop: true, desktopState: paused ? "paused" : "downloading" });
    }
    return { success: true, status: data.status };
  } catch (e) {
    return { success: false, error: "NovaStream uygulamasına ulaşılamıyor" };
  }
}

// yt-dlp'nin giriş gerektiren (ör. kanal üyeliği) videoları indirebilmesi için
// tarayıcıdaki oturum çerezlerini Netscape biçiminde toplar. Yalnızca yerel uygulamaya gider.
async function collectCookies(url, refererUrl) {
  if (!chrome.cookies?.getAll) return "";
  const seen = new Map();
  const add = (list) => {
    for (const c of list || []) seen.set(`${c.domain}|${c.path}|${c.name}`, c);
  };
  const safeGetAll = async (query) => {
    try {
      add(await chrome.cookies.getAll(query));
    } catch (e) {
      // Firefox'ta ilk taraf yalıtımı açıksa sorgu reddedilebilir
    }
  };
  const hostOf = (u) => {
    try { return new URL(u).hostname; } catch { return ""; }
  };
  for (const u of [url, refererUrl]) {
    const host = hostOf(u);
    if (!host) continue;
    if (/(^|\.)(youtube\.com|youtu\.be)$/i.test(host)) {
      await safeGetAll({ domain: "youtube.com" });
    } else {
      await safeGetAll({ url: u });
    }
  }
  if (seen.size === 0) return "";
  const lines = ["# Netscape HTTP Cookie File"];
  for (const c of seen.values()) {
    const domain = c.hostOnly ? c.domain.replace(/^\./, "") : (c.domain.startsWith(".") ? c.domain : "." + c.domain);
    lines.push([
      domain,
      c.hostOnly ? "FALSE" : "TRUE",
      c.path || "/",
      c.secure ? "TRUE" : "FALSE",
      c.session || !c.expirationDate ? "0" : String(Math.floor(c.expirationDate)),
      c.name,
      c.value
    ].join("\t"));
  }
  return lines.join("\n") + "\n";
}

async function delegateToYtDlp({ id, url, refererUrl, title, isYouTube = false }) {
  const cookies = await collectCookies(url, refererUrl);
  const sent = await sendToDesktopAppIfRunning({
    url,
    title,
    referer: refererUrl || "",
    isStream: !isYouTube,
    isYouTube,
    cookies
  });
  if (sent) {
    if (!trackDesktopTask(id, sent.id, title)) notifyHandoff(id, title);
    return "desktop";
  }
  const port = getNativePort();
  activeDownloads.set(id, { id, title, filename: title, percent: 2, speedMb: "yt-dlp ile indiriliyor...", status: "indiriliyor" });
  sendNativeMessage(port, {
    action: "YTDLP",
    url,
    title,
    id,
    referer: refererUrl || "",
    isYouTube,
    cookies
  });
  return "native";
}

function playlistNeedsYtDlp(text, url) {
  if (/\.mpd(\?|$)/i.test(url) || text.includes("<MPD")) return "DASH";
  if (/#EXT-X-MEDIA:[^\n]*TYPE=AUDIO[^\n]*URI=/i.test(text)) return "ayrı ses kanalı";
  const key = text.match(/#EXT-X-KEY:[^\n]*METHOD=([A-Z0-9-]+)/i);
  if (key && key[1].toUpperCase() !== "NONE") return "şifreli akış";
  return null;
}

// HLS Stream İndirici (Browser Fetch -> Native FFmpeg Disk Yazıcı)
async function downloadStreamViaChromeNetwork({ id, streamUrl, refererUrl, videoTitle }) {
  const finalFilename = `${cleanTitle(videoTitle, "video")}.mp4`;
  emitProgress(id, 1, "Bağlanıyor...", "", "", finalFilename, streamUrl);
  let targetUrl = streamUrl;
  let playlistText = "";

  try {
    const port = getNativePort();

    await withScopedHeaders([targetUrl], refererUrl, async () => {
      const res = await fetch(targetUrl);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      playlistText = await res.text();
    });

    if (playlistText.includes("<!DOCTYPE") || playlistText.includes("<html")) {
      throw new Error("Sunucu oynatma listesi yerine HTML döndü.");
    }

    // DASH veya ayrı ses kanallı ana liste: yt-dlp ses ve görüntüyü birlikte indirip birleştirir
    if (playlistNeedsYtDlp(playlistText, targetUrl)) {
      await delegateToYtDlp({ id, url: streamUrl, refererUrl, title: finalFilename });
      return;
    }

    // Master Playlist kontrolü
    if (playlistText.includes("#EXT-X-STREAM-INF")) {
      const variants = parseMasterPlaylist(playlistText, targetUrl);
      if (variants.length > 0) {
        targetUrl = variants[0].url;
        await withScopedHeaders([targetUrl], refererUrl, async () => {
          const subRes = await fetch(targetUrl);
          if (!subRes.ok) throw new Error(`Alt liste HTTP ${subRes.status}`);
          playlistText = await subRes.text();
        });
      }
    }

    // Init Segment (#EXT-X-MAP) + Parçaları ayrıştır
    let initSegmentUrl = null;
    const segmentUrls = [];
    let isFmp4 = false;

    for (const raw of playlistText.split("\n")) {
      const line = raw.trim();
      if (!line) continue;

      if (line.startsWith("#EXT-X-MAP:")) {
        const match = line.match(/URI="([^"]+)"/i);
        if (match && match[1]) {
          initSegmentUrl = new URL(match[1], targetUrl).href;
          isFmp4 = true;
        }
      } else if (!line.startsWith("#")) {
        if (line.includes(".m4s") || line.includes(".mp4")) {
          isFmp4 = true;
        }
        segmentUrls.push(new URL(line, targetUrl).href);
      }
    }

    // Şifreli (AES-128 / SAMPLE-AES) medya listesi: anahtar çözme yt-dlp'de
    if (playlistNeedsYtDlp(playlistText, targetUrl)) {
      await delegateToYtDlp({ id, url: streamUrl, refererUrl, title: finalFilename });
      return;
    }

    if (segmentUrls.length === 0) {
      throw new Error("Oynatma listesinde video parçası bulunamadı.");
    }

    sendNativeMessage(port, {
      action: "FILE_OPEN",
      id,
      title: finalFilename,
      filename: finalFilename,
      isFmp4
    });

    const allUrlsToScope = [];
    if (initSegmentUrl) allUrlsToScope.push(initSegmentUrl);
    allUrlsToScope.push(segmentUrls[0]);

    await withScopedHeaders(allUrlsToScope, refererUrl, async () => {
      // Varsa Başlatma (Init) Segmentini çek
      if (initSegmentUrl) {
        const initRes = await fetch(initSegmentUrl);
        if (initRes.ok) {
          const initBuf = await initRes.arrayBuffer();
          sendBufferToNative(port, id, new Uint8Array(initBuf));
        }
      }

      // Parçaları paralel havuzla indir
      const CONCURRENCY = 6;
      let completed = 0;
      let nextIndex = 0;
      let downloadedBytes = 0;
      const startTime = Date.now();
      const total = segmentUrls.length;
      const readyChunks = new Map();
      let nextWriteIndex = 0;

      function flushSequentialChunks() {
        while (readyChunks.has(nextWriteIndex)) {
          const chunkData = readyChunks.get(nextWriteIndex);
          readyChunks.delete(nextWriteIndex);
          sendBufferToNative(port, id, chunkData);
          nextWriteIndex++;
        }
      }

      async function worker() {
        while (nextIndex < total) {
          const idx = nextIndex++;
          const segUrl = segmentUrls[idx];
          let retries = 3;
          let segBuf = null;

          while (retries > 0) {
            try {
              const r = await fetch(segUrl);
              if (!r.ok) throw new Error(`HTTP ${r.status}`);
              segBuf = await r.arrayBuffer();
              break;
            } catch (err) {
              retries--;
              if (retries === 0) throw err;
              await new Promise((resolve) => setTimeout(resolve, 600));
            }
          }

          downloadedBytes += segBuf.byteLength;
          completed++;
          readyChunks.set(idx, new Uint8Array(segBuf));
          flushSequentialChunks();

          const pct = Math.round((completed / total) * 100);
          const elapsedSec = Math.max(0.1, (Date.now() - startTime) / 1000);
          const speedMb = ((downloadedBytes / (1024 * 1024)) / elapsedSec).toFixed(1) + " MB/s";
          const mbTotal = (downloadedBytes / (1024 * 1024)).toFixed(1) + " MB";
          const remSegs = total - completed;
          const avgSecPerSeg = elapsedSec / completed;
          const etaSec = Math.round(remSegs * avgSecPerSeg);
          const eta = etaSec < 60 ? `${etaSec}s` : `${Math.floor(etaSec / 60)}m ${etaSec % 60}s`;

          emitProgress(id, pct, speedMb, mbTotal, eta, finalFilename, streamUrl);
        }
      }

      const workers = [];
      for (let i = 0; i < Math.min(CONCURRENCY, total); i++) {
        workers.push(worker());
      }
      await Promise.all(workers);
      flushSequentialChunks();
    });

    sendNativeMessage(port, {
      action: "FILE_FINISH",
      id,
      title: finalFilename,
      filename: finalFilename
    });
  } catch (err) {
    console.error("Stream download hatası:", err);
    emitFinished(id, false, finalFilename, err.message);
  }
}

// Doğrudan MP4 / WebM İndirici
async function downloadDirectVideoViaChromeNetwork({ id, url, refererUrl, videoTitle }) {
  const finalFilename = `${cleanTitle(videoTitle, "video")}.mp4`;
  emitProgress(id, 1, "Bağlanıyor...", "", "", finalFilename, url);
  try {
    const port = getNativePort();

    sendNativeMessage(port, {
      action: "FILE_OPEN",
      id,
      title: finalFilename,
      filename: finalFilename,
      isFmp4: false
    });

    await withScopedHeaders([url], refererUrl, async () => {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const totalLen = parseInt(res.headers.get("content-length") || "0", 10);
      const reader = res.body.getReader();
      let downloaded = 0;
      const startTime = Date.now();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        downloaded += value.length;
        sendBufferToNative(port, id, value);

        const pct = totalLen > 0 ? Math.min(99, Math.round((downloaded / totalLen) * 100)) : 50;
        const elapsedSec = Math.max(0.1, (Date.now() - startTime) / 1000);
        const speedMb = ((downloaded / (1024 * 1024)) / elapsedSec).toFixed(1) + " MB/s";
        const mbTotal = (downloaded / (1024 * 1024)).toFixed(1) + " MB";
        let eta = "";
        if (totalLen > 0) {
          const remBytes = totalLen - downloaded;
          const bytesPerSec = downloaded / elapsedSec;
          const etaSec = Math.round(remBytes / bytesPerSec);
          eta = etaSec < 60 ? `${etaSec}s` : `${Math.floor(etaSec / 60)}m ${etaSec % 60}s`;
        }
        emitProgress(id, pct, speedMb, mbTotal, eta, finalFilename, url);
      }
    });

    sendNativeMessage(port, {
      action: "FILE_FINISH",
      id,
      title: finalFilename,
      filename: finalFilename
    });
  } catch (err) {
    console.error("Direct download hatası:", err);
    emitFinished(id, false, finalFilename, err.message);
  }
}

// Sekme Kapatıldığında veya Yenilendiğinde Temizle
chrome.tabs.onRemoved.addListener((tabId) => {
  tabMediaMap.delete(tabId);
  tabKnownSubstreams.delete(tabId);
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "loading" && changeInfo.url) {
    tabMediaMap.delete(tabId);
    tabKnownSubstreams.delete(tabId);
    updateBadge(tabId);
  }
});

// Masaüstü NovaStream-App Açık mı Kontrol Et ve İlet
async function sendToDesktopAppIfRunning(payload) {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 2500);
    const res = await fetch("http://127.0.0.1:9191/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal
    });
    clearTimeout(timer);
    if (res.ok) {
      const data = await res.json();
      return data?.success ? data : null;
    }
  } catch (e) {
    // Masaüstü uygulaması kapalıysa sessizce yerel Native Host'a devam et
  }
  return null;
}

// Mesajlaşma Merkezi
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const tabId = message.tabId || sender.tab?.id;

  if (message.type === "GET_MEDIA" || message.type === "GET_MEDIA_FOR_TAB") {
    sendResponse({
      media: rankMediaList((tabMediaMap.get(tabId) || []).filter((m) => !isYouTubeChunk(m.url) && !isYouTubePage(m.webpage_url))),
      activeDownloads: Array.from(activeDownloads.values())
    });
    return true;
  } else if (message.type === "TOGGLE_FLOATING_BUTTON") {
    broadcastToTabs({ type: "TOGGLE_FLOATING_BUTTON", enabled: message.enabled });
    sendResponse?.({ success: true });
    return true;
  } else if (message.type === "VIDEO_DIMENSIONS_UPDATE") {
    if (tabId && message.height > 0) {
      const items = tabMediaMap.get(tabId);
      if (items && items.length > 0) {
        const resLabel = getResLabel(message.height);
        if (resLabel) {
          // Oynatıcının çözünürlüğü yalnız asıl videoya aittir; reklam/parça öğelerine yazma.
          let updated = false;
          const main = rankMediaList(items).find((it) => !it.minor);
          const target = main && items.find((it) => it.id === main.id);
          if (target && (!target.resolution || target.resolution === "HD") && !(target.qualities?.length > 1)) {
            target.resolution = resLabel;
            target.format = `${resLabel} ${(target.ext || "mp4").toUpperCase()}`;
            updated = true;
          }
          if (updated) {
            updateBadge(tabId);
            chrome.tabs.sendMessage(tabId, {
              type: "MEDIA_DETECTED",
              allItems: rankMediaList(items)
            }).catch(() => {});
          }
        }
      }
    }
    return true;
  } else if (message.type === "DESKTOP_CONTROL") {
    controlDesktopTask(message.id, message.action).then(sendResponse);
    return true;
  } else if (message.type === "START_YOUTUBE_DOWNLOAD") {
    (async () => {
      const cookies = await collectCookies(message.url, sender.tab?.url || "");
      const sent = await sendToDesktopAppIfRunning({
        url: message.url,
        title: message.title,
        referer: sender.tab?.url || "",
        isStream: false,
        isYouTube: true,
        cookies
      });
      if (sent) {
        const tracking = trackDesktopTask(message.id, sent.id, message.title);
        sendResponse({ success: true, desktop: true, tracking });
        return;
      }

      try {
        const port = getNativePort();
        activeDownloads.set(message.id, {
          id: message.id,
          title: message.title,
          percent: 1,
          speedMb: "Google Oturumu Doğrulanıyor...",
          mbTotal: "",
          eta: "",
          status: "indiriliyor"
        });

        sendNativeMessage(port, {
          action: "YTDLP",
          url: message.url,
          title: message.title,
          id: message.id,
          isYouTube: true,
          cookies
        });
        sendResponse({ success: true });
      } catch (err) {
        sendResponse({ success: false, error: err.message });
      }
    })();
    return true;
  } else if (message.type === "START_STREAM_DOWNLOAD") {
    const isStream = message.isStream !== false;
    const downloadId = message.id || crypto.randomUUID();
    const downloadUrl = message.streamUrl || message.url;
    const referer = message.refererUrl || (sender.tab ? sender.tab.url : "");
    const title = message.title || message.videoTitle || "video";

    if (isStream) {
      downloadStreamViaChromeNetwork({
        id: downloadId,
        streamUrl: downloadUrl,
        refererUrl: referer,
        videoTitle: title
      });
      sendResponse({ success: true, id: downloadId });
    } else {
      downloadDirectVideoViaChromeNetwork({
        id: downloadId,
        url: downloadUrl,
        refererUrl: referer,
        videoTitle: title
      });
      sendResponse({ success: true, id: downloadId });
    }
    return true;
  }
});

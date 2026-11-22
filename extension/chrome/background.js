// NovaStream - Service Worker (Ağ Yığını, Master Playlist Ayrıştırıcı, Altyazı & Native Host Yöneticisi)

const tabMediaMap = new Map();         // tabId -> MediaItem[]
const tabSubtitleMap = new Map();      // tabId -> SubtitleItem[]
const tabKnownSubstreams = new Map();  // tabId -> Set<url | dedupeKey>
const inspectingKeys = new Set();      // dedupeKey currently being probed
const activeDownloads = new Map();
const requestHeaderCache = new Map();  // requestId -> { referer, origin, ts }
const hostCooldownUntil = new Map();   // hostname -> timestamp ms
const hostProbeChains = new Map();     // hostname -> Promise
const probeCache = new Map();          // url -> { ts, ok, status, text, rateLimited }

let nativePort = null;
let dnrCounter = 10000;

const PROBE_CACHE_TTL_MS = 120 * 1000;
const PROBE_SPACING_MS = 200;

// Segment filtreleri (parçaları ana liste sanmamak için)
const SEGMENT_PATTERNS = [
  /\/segment\.(m4s|mp4|ts|vtt|aac)(\?|$)/i,
  /\/seg-\d+/i,
  /\/(audio|video)_\d+/i,
  /\/\d+\.(m4s|ts|vtt|aac)(\?|$)/i,
  /\.m4s(\?|$)/i,
  /\/chunk-\d+/i,
  /range\/\d+-\d+/i,
  /bytes=\d+-\d+/i,
  /\/init\.(m4s|mp4)(\?|$)/i,
  /\/cmf[av]/i,
  /st=audio/i,
  /type=audio/i
];

const IGNORED_RESOURCE_TYPES = new Set([
  "stylesheet",
  "image",
  "font",
  "script",
  "ping",
  "csp_report",
  "websocket",
  "main_frame"
]);

const NOISE_URL_PATTERNS = [
  /doubleclick\.net/i,
  /googlesyndication\.com/i,
  /google-analytics\.com/i,
  /googletagmanager\.com/i,
  /kaspersky-labs\.com/i,
  /\/abn\/main\.css/i,
  /\/vast(?:\b|[\/.?_-])/i,
  /\/vpaid(?:\b|[\/.?_-])/i,
  /\b(preroll|midroll|postroll)\b/i,
  /\/sprites?\//i,
  /\/sprite[_-]?\d*\./i,
  /\/thumbnails?\//i,
  /thumb[_-]?\d*\.(jpg|jpeg|png|webp|vtt)/i
];

function isSegment(url) {
  return SEGMENT_PATTERNS.some((rx) => rx.test(url));
}

function isIgnoredNoiseUrl(url) {
  return NOISE_URL_PATTERNS.some((rx) => rx.test(url || ""));
}

// YouTube oynatıcısının parça istekleri (googlevideo /videoplayback) tek başına
// indirilemez; birkaç KB'lık işe yaramaz dosya çıkar. YouTube videoları yt-dlp ile iner.
function isYouTubeChunk(url) {
  return /^https?:\/\/[^/]*googlevideo\.com\//i.test(url) || /\/videoplayback(\?|\/|$)/i.test(url);
}

function isYouTubePage(url) {
  return /^https?:\/\/([^/]*\.)?(youtube\.com|youtu\.be)(?=[\/:?#]|$)/i.test(url || "");
}

function parseSubtitleType(contentType, url) {
  const ct = (contentType || "").toLowerCase();
  const u = (url || "").toLowerCase();
  const pathPart = u.split("?")[0].split("#")[0];

  if (ct.includes("text/vtt") || /\.webvtt$/.test(pathPart) || /\.vtt$/.test(pathPart)) {
    return { format: "VTT", ext: "vtt", canConvertToSrt: true };
  }
  if (ct.includes("application/x-subrip") || ct.includes("text/srt") || /\.srt$/.test(pathPart)) {
    return { format: "SRT", ext: "srt", canConvertToSrt: false };
  }
  if (/\.ass$/.test(pathPart) || /\.ssa$/.test(pathPart)) {
    return { format: pathPart.endsWith(".ssa") ? "SSA" : "ASS", ext: pathPart.endsWith(".ssa") ? "ssa" : "ass", canConvertToSrt: false };
  }
  if (ct.includes("application/ttml+xml") || /\.ttml$/.test(pathPart)) {
    return { format: "TTML", ext: "ttml", canConvertToSrt: false };
  }
  return null;
}

function parseVideoType(contentType, url) {
  const ct = (contentType || "").toLowerCase();
  const u = (url || "").toLowerCase();

  if (
    ct.includes("text/html") ||
    ct.includes("application/json") ||
    ct.includes("text/css") ||
    ct.includes("javascript") ||
    ct.startsWith("image/") ||
    ct.startsWith("font/")
  ) {
    return null;
  }

  // Bazı mirror sunucuları (Rapidrame/Close vb.) .m3u8 dosyalarını text/plain veya octet-stream ile döner;
  // text/plain reddinden ÖNCE akış manifest uzantılarını kontrol et.
  if (ct.includes("mpegurl") || ct.includes("application/x-mpegurl") || /\.m3u8(?:\?|$|#)/i.test(u) || u.includes(".m3u8")) {
    return { format: "HLS", ext: "mp4", isStream: true };
  }
  if (ct.includes("dash+xml") || /\.mpd(?:\?|$|#)/i.test(u) || u.includes(".mpd")) {
    return { format: "DASH", ext: "mpd", isStream: true };
  }

  if (ct.includes("text/plain")) {
    return null;
  }

  if (ct.includes("video/mp4") || /\.mp4(?:\?|$|#)/i.test(u)) {
    return { format: "MP4", ext: "mp4", isStream: false };
  }
  if (ct.includes("video/webm") || /\.webm(?:\?|$|#)/i.test(u)) {
    return { format: "WebM", ext: "webm", isStream: false };
  }
  if (ct.includes("video/x-matroska") || /\.mkv(?:\?|$|#)/i.test(u)) {
    return { format: "MKV", ext: "mkv", isStream: false };
  }
  if (ct.includes("video/quicktime") || /\.mov(?:\?|$|#)/i.test(u)) {
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
  const m = (url || "").match(/[\/_\.-](2160|1440|1080|720|480|360)p?(?:[\/_\.-]|$)/i);
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
    return String(url || "").split("?")[0].toLowerCase();
  }
}

function getHostname(url) {
  try {
    return new URL(url).hostname.toLowerCase();
  } catch {
    return "";
  }
}

function detectSourceLabel(refererUrl, mediaUrl) {
  const candidates = [refererUrl || "", mediaUrl || ""];
  for (const s of candidates) {
    if (!s) continue;
    if (/\/video\/embed\/|closeplayer/i.test(s)) return "Close";
    if (/\/rplayer\b|(?:https?:\/\/|\/)[^?]*rapidrame/i.test(s)) return "Rapidrame";
    if (/vidmoly/i.test(s)) return "Vidmoly";
    if (/ok\.ru|odnoklassniki/i.test(s)) return "OK.ru";
    if (/sibnet/i.test(s)) return "Sibnet";
    if (/streamtape/i.test(s)) return "Streamtape";
    if (/dood|ds2play|d000d/i.test(s)) return "Dood";
    if (/filemoon/i.test(s)) return "Filemoon";
    if (/mixdrop/i.test(s)) return "Mixdrop";
    if (/voe\.sx|\bvoe\b/i.test(s)) return "VOE";
  }
  const host = getHostname(refererUrl) || getHostname(mediaUrl);
  return host.replace(/^www\./i, "") || "Video";
}

function detectSubtitleLang(url, labelHint = "", langHint = "") {
  const combined = `${langHint || ""} ${labelHint || ""} ${url || ""}`.toLowerCase();
  const suffixes = [];
  if (/\bforced\b|zorunlu/i.test(combined)) suffixes.push("Forced");
  if (/\bsdh\b|cc\b/i.test(combined)) suffixes.push("SDH");
  const suffixStr = suffixes.length ? ` (${suffixes.join(", ")})` : "";

  const rules = [
    { rx: /(?:^|[\W_])(tr|tur|turkish|türkçe|turkce)(?:$|[\W_])/i, code: "TR", label: "Türkçe" },
    { rx: /(?:^|[\W_])(en|eng|english|ingilizce)(?:$|[\W_])/i, code: "EN", label: "English" },
    { rx: /(?:^|[\W_])(de|ger|deu|deutsch|german|almanca)(?:$|[\W_])/i, code: "DE", label: "Deutsch" },
    { rx: /(?:^|[\W_])(fr|fra|fre|french|français|fransızca)(?:$|[\W_])/i, code: "FR", label: "Français" },
    { rx: /(?:^|[\W_])(es|spa|spanish|español|ispanyolca)(?:$|[\W_])/i, code: "ES", label: "Español" },
    { rx: /(?:^|[\W_])(ar|ara|arabic|arapça)(?:$|[\W_])/i, code: "AR", label: "العربية" },
    { rx: /(?:^|[\W_])(ru|rus|russian|rusça)(?:$|[\W_])/i, code: "RU", label: "Русский" },
    { rx: /(?:^|[\W_])(az|aze|azerbaijani|azerice)(?:$|[\W_])/i, code: "AZ", label: "Azərbaycan" }
  ];

  for (const r of rules) {
    if (r.rx.test(langHint || "") || r.rx.test(labelHint || "") || r.rx.test(url || "")) {
      return { code: r.code, label: `${r.label}${suffixStr}` };
    }
  }
  const fallbackCode = (langHint || "ALT").replace(/[^a-z0-9]/gi, "").toUpperCase().slice(0, 4) || "ALT";
  const fallbackLabel = (labelHint || "Altyazı").trim() + suffixStr;
  return { code: fallbackCode, label: fallbackLabel };
}

function formatAudioTrackLabel(rawName = "", langCode = "") {
  const combined = `${langCode || ""} ${rawName || ""}`.trim().toLowerCase();
  if (/(?:^|[\W_])(tr|tur|turkish|türkçe|turkce)(?:$|[\W_])/i.test(combined)) return "Türkçe";
  if (/(?:^|[\W_])(en|eng|english|ingilizce|orijinal|original)(?:$|[\W_])/i.test(combined)) return "English (Orijinal)";
  if (/(?:^|[\W_])(de|ger|deu|deutsch|german|almanca)(?:$|[\W_])/i.test(combined)) return "Deutsch";
  if (/(?:^|[\W_])(fr|fra|fre|french|français|fransızca)(?:$|[\W_])/i.test(combined)) return "Français";
  if (/(?:^|[\W_])(es|spa|spanish|español)(?:$|[\W_])/i.test(combined)) return "Español";
  if (/(?:^|[\W_])(ar|ara|arabic|arapça)(?:$|[\W_])/i.test(combined)) return "العربية";
  if (/(?:^|[\W_])(ru|rus|russian|rusça)(?:$|[\W_])/i.test(combined)) return "Русский";
  return (rawName || "").trim() || (langCode || "").toUpperCase() || "Ses";
}

function stripMediaExts(name) {
  return String(name || "")
    .trim()
    .replace(/(?:\.(?:mp4|mkv|webm|mov|ts|m3u8|mpd))+$/i, "")
    .trim();
}

function parseHlsAttrs(line) {
  const attrs = {};
  const idx = line.indexOf(":");
  const body = idx >= 0 ? line.slice(idx + 1) : line;
  const rx = /([A-Z0-9-]+)=("([^"]*)"|([^,]*))/gi;
  let m;
  while ((m = rx.exec(body)) !== null) {
    const k = m[1].toUpperCase();
    const v = m[3] !== undefined ? m[3] : (m[4] || "");
    attrs[k] = v.trim();
  }
  return attrs;
}

// Master Playlist Ayrıştırıcı (#EXT-X-MEDIA + #EXT-X-STREAM-INF)
function parseMasterPlaylist(text, baseUrl) {
  const lines = String(text || "").split(/\r?\n/);
  const rawVariants = [];
  const audioTracks = [];
  const subtitleTracks = [];
  const allSubstreamUrls = new Set();

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;

    if (line.startsWith("#EXT-X-MEDIA:")) {
      const attrs = parseHlsAttrs(line);
      const mediaType = (attrs.TYPE || "").toUpperCase();
      let uri = null;
      if (attrs.URI) {
        try {
          uri = new URL(attrs.URI, baseUrl).href;
        } catch {}
      }
      if (uri) {
        allSubstreamUrls.add(uri);
        allSubstreamUrls.add(getMediaDedupeKey(uri));
      }
      if (mediaType === "AUDIO") {
        const rawName = attrs.NAME || attrs.LANGUAGE || "Ses";
        const language = (attrs.LANGUAGE || "").toLowerCase();
        audioTracks.push({
          groupId: attrs["GROUP-ID"] || "",
          rawName,
          name: rawName,
          language,
          label: formatAudioTrackLabel(rawName, language),
          isDefault: (attrs.DEFAULT || "").toUpperCase() === "YES",
          uri
        });
      } else if (mediaType === "SUBTITLES" && uri) {
        const langInfo = detectSubtitleLang(uri, attrs.NAME || "", attrs.LANGUAGE || "");
        subtitleTracks.push({
          groupId: attrs["GROUP-ID"] || "",
          name: attrs.NAME || langInfo.label,
          language: attrs.LANGUAGE || langInfo.code.toLowerCase(),
          langCode: langInfo.code,
          label: attrs.NAME ? `${langInfo.label}` : langInfo.label,
          isDefault: (attrs.DEFAULT || "").toUpperCase() === "YES",
          url: uri
        });
      }
      continue;
    }

    if (line.startsWith("#EXT-X-STREAM-INF:")) {
      const attrs = parseHlsAttrs(line);
      const bw = parseInt(attrs.BANDWIDTH || attrs["AVERAGE-BANDWIDTH"] || "0", 10) || 0;
      let width = 0;
      let height = 0;
      if (attrs.RESOLUTION) {
        const rm = attrs.RESOLUTION.match(/(\d+)x(\d+)/i);
        if (rm) {
          width = parseInt(rm[1], 10);
          height = parseInt(rm[2], 10);
        }
      }
      const fps = attrs["FRAME-RATE"] ? Math.round(parseFloat(attrs["FRAME-RATE"])) : 0;

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
        allSubstreamUrls.add(variantUrl);
        allSubstreamUrls.add(getMediaDedupeKey(variantUrl));

        let qualityLabel = getResLabel(height);
        if (!qualityLabel) {
          qualityLabel = bw > 0 ? `${Math.round(bw / 1000)}k` : "HD";
        }
        if (fps && fps > 30) {
          qualityLabel += ` ${fps}fps`;
        }

        let bwLabel = "";
        if (bw >= 1000000) {
          bwLabel = `${(bw / 1000000).toFixed(1)} Mbps`;
        } else if (bw > 0) {
          bwLabel = `${Math.round(bw / 1000)} Kbps`;
        }

        rawVariants.push({
          url: variantUrl,
          width,
          height,
          bandwidth: bw,
          fps,
          codecs: attrs.CODECS || "",
          audioGroup: attrs.AUDIO || "",
          subGroup: attrs.SUBTITLES || "",
          qualityLabel,
          bwLabel
        });
      }
    }
  }

  const audioGroupsWithUri = new Set(audioTracks.filter((a) => Boolean(a.uri)).map((a) => a.groupId));
  const anyExternalAudio = audioTracks.some((a) => Boolean(a.uri));

  // Aynı çözünürlük & yakın bit hızına sahip tekrarlı CDN aynalarını tekilleştir (en yüksek bit hızı kalsın)
  rawVariants.sort((a, b) => (b.height * 10000000 + b.bandwidth) - (a.height * 10000000 + a.bandwidth));
  const seenBucket = new Set();
  const variants = [];
  for (const v of rawVariants) {
    const bucket = `${v.height}:${Math.round(v.bandwidth / 150000)}`;
    if (seenBucket.has(bucket)) continue;
    seenBucket.add(bucket);
    const hasExtAudio = Boolean(
      (v.audioGroup && audioGroupsWithUri.has(v.audioGroup)) ||
      (!v.audioGroup && anyExternalAudio)
    );
    variants.push({
      ...v,
      hasExternalAudio: hasExtAudio
    });
  }

  const seenAudio = new Set();
  const dedupedAudioTracks = [];
  for (const a of audioTracks) {
    const key = `${(a.language || "").toLowerCase()}|${(a.rawName || a.label).toLowerCase()}`;
    if (seenAudio.has(key)) continue;
    seenAudio.add(key);
    dedupedAudioTracks.push(a);
  }

  return {
    variants,
    audioTracks: dedupedAudioTracks,
    subtitleTracks,
    allSubstreamUrls
  };
}

// Altyazı HLS oynatma listesi mi? (.vtt / .webvtt / .srt parçaları)
function isSubtitlePlaylist(url, text) {
  if (!text || !text.includes("#EXTINF")) return false;
  const segLines = text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith("#"));
  if (segLines.length === 0) return false;
  const subCount = segLines.filter((l) => /\.(vtt|webvtt|srt)(?:\?|$)/i.test(l)).length;
  return subCount > 0 && subCount >= Math.ceil(segLines.length / 2);
}

// Yalnızca ses içeren medya listesi mi?
function isAudioOnlyPlaylist(url, text) {
  const u = (url || "").toLowerCase();
  if (/(\/audio\/|[?&](st|type)=audio\b|_audio\.m3u8)/i.test(u)) return true;
  if (!text) return false;
  const segLines = text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith("#"));
  if (segLines.length > 0 && segLines.every((l) => /\.(aac|m4a|mp3|ac3|ec3|opus|oga)(?:\?|$)/i.test(l))) {
    return true;
  }
  return false;
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
  if (it.isAudioOnly) return false;
  if (it.qualities && it.qualities.length > 0) return true;
  if (it.durationSec) return it.durationSec >= MAIN_MIN_DURATION;
  if (it.sizeBytes) return it.sizeBytes >= MAIN_MIN_BYTES;
  return Boolean(it.isStream);             // süresi/boyutu bilinmeyen akış (ör. canlı yayın)
}

function rankMediaList(list, knownSubstreams = null) {
  const rawItems = (list || []).filter((it) => {
    if (!knownSubstreams) return true;
    return !knownSubstreams.has(it.url) && !knownSubstreams.has(getMediaDedupeKey(it.url));
  });

  const items = rawItems.map((it) => ({ ...it, minor: false, duplicate: false }));

  // Aynı frame içinde Master Playlist veya uzunluğu bilinen ana akış varsa,
  // aynı frame'deki süresi/kalitesi belirsiz yalın akış kayıtlarını gizle/ikincilleştir.
  const frameHasRichMain = new Map();
  for (const it of items) {
    const fKey = it.frameId ?? 0;
    const isRich = (it.qualities?.length || 0) > 0 || (it.durationSec && it.durationSec >= MAIN_MIN_DURATION);
    if (isRich) {
      if (!frameHasRichMain.has(fKey)) frameHasRichMain.set(fKey, new Set());
      frameHasRichMain.get(fKey).add(getHostname(it.url));
    }
  }
  for (const it of items) {
    const fKey = it.frameId ?? 0;
    const hosts = frameHasRichMain.get(fKey);
    if (hosts && it.isStream && !(it.qualities?.length > 0) && !it.durationSec) {
      if (hosts.has(getHostname(it.url))) {
        it.duplicate = true;
      } else {
        it.minor = true;
      }
    }
  }

  // Aynı süreli ve aynı kaynaklı akışlar (farklı imzalı adreslerle tekrar yüklenen aynı video) tek kayıt olsun
  const seenDur = [];
  for (const it of items) {
    if (it.duplicate || !it.isStream || !it.durationSec) continue;
    const srcKey = (it.sourceLabel || getHostname(it.refererUrl || it.url)).toLowerCase();
    const twinIdx = seenDur.findIndex((d) => {
      const dSrc = (d.sourceLabel || getHostname(d.refererUrl || d.url)).toLowerCase();
      return dSrc === srcKey && Math.abs(d.durationSec - it.durationSec) <= 2;
    });
    if (twinIdx >= 0) {
      const twin = seenDur[twinIdx];
      const itScore = (it.qualities?.length || 0) * 10000 + (parseInt(it.resolution, 10) || 0);
      const twinScore = (twin.qualities?.length || 0) * 10000 + (parseInt(twin.resolution, 10) || 0);
      if (itScore > twinScore) {
        twin.duplicate = true;
        seenDur[twinIdx] = it;
      } else {
        it.duplicate = true;
      }
    } else {
      seenDur.push(it);
    }
  }

  const visible = items.filter((it) => !it.duplicate);
  const hasMain = visible.some((it) => !it.minor && isMainCandidate(it));
  if (hasMain) {
    for (const it of visible) {
      if (!it.minor) {
        it.minor = !isMainCandidate(it);
      }
    }
  } else {
    for (const it of visible) {
      if (it.isAudioOnly) it.minor = true;
    }
  }

  const weight = (it) =>
    (it.qualities?.length ? 5e9 : 0) +
    (it.durationSec || 0) * 1e6 +
    (it.sizeBytes || 0) / 1024;
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
  if (!chrome.action?.setBadgeText) return;
  const known = tabKnownSubstreams.get(tabId);
  const items = rankMediaList(tabMediaMap.get(tabId) || [], known);
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

function notifyTabMedia(tabId, targetFrameId = null) {
  const known = tabKnownSubstreams.get(tabId);
  const allItems = rankMediaList(tabMediaMap.get(tabId) || [], known);
  const allSubs = tabSubtitleMap.get(tabId) || [];

  if (typeof targetFrameId === "number" && targetFrameId >= 0) {
    const frameItems = allItems.filter((it) => it.frameId === targetFrameId);
    const frameSubs = allSubs.filter((s) => s.frameId === targetFrameId);
    chrome.tabs.sendMessage(
      tabId,
      {
        type: "MEDIA_DETECTED",
        allItems,
        frameItems,
        subtitles: allSubs,
        frameSubtitles: frameSubs
      },
      { frameId: targetFrameId }
    ).catch(() => {});

    if (targetFrameId > 0) {
      chrome.tabs.sendMessage(
        tabId,
        {
          type: "MEDIA_DETECTED",
          allItems,
          subtitles: allSubs
        },
        { frameId: 0 }
      ).catch(() => {});
    }
    return;
  }

  chrome.tabs.sendMessage(tabId, {
    type: "MEDIA_DETECTED",
    allItems,
    subtitles: allSubs
  }).catch(() => {});
}

function clearFrameData(tabId, frameId) {
  if (typeof tabId !== "number" || tabId < 0) return;
  if (typeof frameId !== "number" || frameId === 0) {
    tabMediaMap.delete(tabId);
    tabSubtitleMap.delete(tabId);
    tabKnownSubstreams.delete(tabId);
    updateBadge(tabId);
    return;
  }
  const media = tabMediaMap.get(tabId);
  if (media) {
    tabMediaMap.set(tabId, media.filter((it) => it.frameId !== frameId));
  }
  const subs = tabSubtitleMap.get(tabId);
  if (subs) {
    tabSubtitleMap.set(tabId, subs.filter((s) => s.frameId !== frameId));
  }
  updateBadge(tabId);
  notifyTabMedia(tabId, frameId);
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
chrome.runtime?.onStartup?.addListener(cleanupAllDnrRules);
chrome.runtime?.onInstalled?.addListener(cleanupAllDnrRules);

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
chrome.runtime?.onInstalled?.addListener(setupContextMenu);
chrome.runtime?.onStartup?.addListener(setupContextMenu);

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
        refererUrl: info.frameUrl || tab?.url || "",
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

function parseRetryAfterMs(headerVal, defaultMs = 30000) {
  if (!headerVal) return defaultMs;
  const trimmed = String(headerVal).trim();
  if (/^\d+$/.test(trimmed)) {
    return Math.min(120000, Math.max(1000, parseInt(trimmed, 10) * 1000));
  }
  const dt = Date.parse(trimmed);
  if (!Number.isNaN(dt)) {
    return Math.min(120000, Math.max(1000, dt - Date.now()));
  }
  return defaultMs;
}

function enqueueHostProbe(host, taskFn) {
  const prev = hostProbeChains.get(host) || Promise.resolve();
  const next = prev.then(
    async () => {
      try {
        return await taskFn();
      } finally {
        await new Promise((r) => setTimeout(r, PROBE_SPACING_MS));
      }
    },
    async () => {
      try {
        return await taskFn();
      } finally {
        await new Promise((r) => setTimeout(r, PROBE_SPACING_MS));
      }
    }
  );
  hostProbeChains.set(host, next.catch(() => {}));
  return next;
}

async function probePlaylist(url, refererUrl) {
  const now = Date.now();
  const cached = probeCache.get(url);
  if (cached && now - cached.ts < PROBE_CACHE_TTL_MS) {
    return cached;
  }

  const host = getHostname(url) || "default";
  const cd = hostCooldownUntil.get(host) || 0;
  if (now < cd) {
    return { ts: now, ok: false, status: 429, text: "", rateLimited: true };
  }

  return await enqueueHostProbe(host, async () => {
    const innerNow = Date.now();
    const innerCached = probeCache.get(url);
    if (innerCached && innerNow - innerCached.ts < PROBE_CACHE_TTL_MS) {
      return innerCached;
    }
    if (innerNow < (hostCooldownUntil.get(host) || 0)) {
      return { ts: innerNow, ok: false, status: 429, text: "", rateLimited: true };
    }

    try {
      const result = await withScopedHeaders([url], refererUrl, async () => {
        const resp = await fetch(url, { credentials: "include" });
        if (resp.status === 429 || resp.status === 503) {
          const waitMs = parseRetryAfterMs(resp.headers.get("retry-after"), 30000);
          hostCooldownUntil.set(host, Date.now() + waitMs);
          return { ts: Date.now(), ok: false, status: resp.status, text: "", rateLimited: true };
        }
        if (!resp.ok) {
          return { ts: Date.now(), ok: false, status: resp.status, text: "", rateLimited: false };
        }
        const text = await resp.text();
        return { ts: Date.now(), ok: true, status: resp.status, text, rateLimited: false };
      });
      if (result.ok || result.status >= 400) {
        probeCache.set(url, result);
        if (probeCache.size > 300) {
          const firstKey = probeCache.keys().next().value;
          probeCache.delete(firstKey);
        }
      }
      return result;
    } catch {
      return { ts: Date.now(), ok: false, status: 0, text: "", rateLimited: false };
    }
  });
}

function addSubtitleItem(tabId, sub) {
  if (!sub || !sub.url) return;
  if (!tabSubtitleMap.has(tabId)) {
    tabSubtitleMap.set(tabId, []);
  }
  const list = tabSubtitleMap.get(tabId);
  const key = getMediaDedupeKey(sub.url);
  const idx = list.findIndex((s) => s.url === sub.url || getMediaDedupeKey(s.url) === key);
  if (idx >= 0) {
    if (!list[idx].label && sub.label) list[idx] = { ...list[idx], ...sub };
    return;
  }
  list.push(sub);
  notifyTabMedia(tabId, typeof sub.frameId === "number" ? sub.frameId : null);
}

function addMediaItem(tabId, media) {
  if (!tabMediaMap.has(tabId)) {
    tabMediaMap.set(tabId, []);
  }
  const list = tabMediaMap.get(tabId);

  if (isSegment(media.url) || isYouTubeChunk(media.url) || isYouTubePage(media.webpage_url)) return;
  const knownSubs = tabKnownSubstreams.get(tabId);
  const dedupeKey = getMediaDedupeKey(media.url);
  if (knownSubs && (knownSubs.has(media.url) || knownSubs.has(dedupeKey))) return;

  const existingIdx = list.findIndex(
    (item) => item.url === media.url || getMediaDedupeKey(item.url) === dedupeKey
  );

  if (existingIdx >= 0) {
    const existing = list[existingIdx];
    const shouldUpgrade =
      (media.qualities?.length && !existing.qualities?.length) ||
      (!existing.durationSec && media.durationSec) ||
      (!existing.refererUrl && media.refererUrl);
    if (shouldUpgrade) {
      list[existingIdx] = { ...existing, ...media };
      updateBadge(tabId);
      notifyTabMedia(tabId, typeof media.frameId === "number" ? media.frameId : null);
    }
    return;
  }

  list.push(media);
  updateBadge(tabId);
  notifyTabMedia(tabId, typeof media.frameId === "number" ? media.frameId : null);
}

// Giden istek başlıklarından gerçek Referer / Origin bilgisini yakala (iframe kaynakları için kritik)
if (chrome.webRequest?.onBeforeSendHeaders) {
  const beforeSendHandler = (details) => {
    if (details.tabId < 0 || !details.requestHeaders) return;
    let referer = "";
    let origin = "";
    for (const h of details.requestHeaders) {
      const name = h.name.toLowerCase();
      if (name === "referer") referer = h.value || "";
      else if (name === "origin") origin = h.value || "";
    }
    if (referer || origin) {
      requestHeaderCache.set(details.requestId, { referer, origin, ts: Date.now() });
      if (requestHeaderCache.size > 400) {
        const cutoff = Date.now() - 30000;
        for (const [k, v] of requestHeaderCache) {
          if (v.ts < cutoff || requestHeaderCache.size > 400) {
            requestHeaderCache.delete(k);
            if (requestHeaderCache.size <= 250) break;
          }
        }
      }
    }
  };
  try {
    chrome.webRequest.onBeforeSendHeaders.addListener(
      beforeSendHandler,
      { urls: ["<all_urls>"] },
      ["requestHeaders", "extraHeaders"]
    );
  } catch {
    // Firefox "extraHeaders" seçeneğini kabul etmez
    chrome.webRequest.onBeforeSendHeaders.addListener(
      beforeSendHandler,
      { urls: ["<all_urls>"] },
      ["requestHeaders"]
    );
  }
}

// Ağ Dinleyicisi
if (chrome.webRequest?.onHeadersReceived) {
  chrome.webRequest.onHeadersReceived.addListener(
    (details) => {
      const { tabId, frameId, url, responseHeaders, requestId, statusCode, type } = details;
      const cachedHdr = requestHeaderCache.get(requestId);
      requestHeaderCache.delete(requestId);

      if (tabId < 0) return;

      // Alt iframe yeniden yüklendiyse o frame'in eski kayıtlarını temizle
      if (type === "sub_frame" && typeof frameId === "number" && frameId > 0) {
        clearFrameData(tabId, frameId);
        return;
      }

      if (typeof statusCode === "number" && (statusCode < 200 || statusCode >= 300)) return;
      if (type && IGNORED_RESOURCE_TYPES.has(type)) return;
      if (isSegment(url) || isIgnoredNoiseUrl(url) || isYouTubeChunk(url)) return;
      if (isYouTubePage(details.initiator) || isYouTubePage(details.documentUrl)) return;

      const knownSubs = tabKnownSubstreams.get(tabId);
      const dedupeKey = getMediaDedupeKey(url);
      if (knownSubs && (knownSubs.has(url) || knownSubs.has(dedupeKey))) {
        return;
      }

      let contentType = "";
      let contentLength = 0;
      if (responseHeaders) {
        for (const h of responseHeaders) {
          const name = h.name.toLowerCase();
          if (name === "content-type") contentType = h.value || "";
          else if (name === "content-length") contentLength = parseInt(h.value || "0", 10);
        }
      }

      const actualReferer = cachedHdr?.referer || details.documentUrl || details.initiator || "";
      const sourceLabel = detectSourceLabel(actualReferer, url);

      // 1. Doğrudan altyazı dosyası mı?
      const subType = parseSubtitleType(contentType, url);
      if (subType) {
        chrome.tabs.get(tabId, (tab) => {
          if (chrome.runtime.lastError || !tab) return;
          const pageTitle = cleanTitle(tab.title, "altyazi");
          const langInfo = detectSubtitleLang(url);
          addSubtitleItem(tabId, {
            id: crypto.randomUUID(),
            url,
            refererUrl: actualReferer || tab.url || "",
            webpage_url: tab.url || "",
            frameId: typeof frameId === "number" ? frameId : 0,
            sourceLabel,
            title: pageTitle,
            label: langInfo.label,
            langCode: langInfo.code,
            format: subType.format,
            ext: subType.ext,
            canConvertToSrt: subType.canConvertToSrt,
            isHlsSubtitle: false,
            timestamp: Date.now()
          });
        });
        return;
      }

      // 2. Video / Akış mı?
      const videoType = parseVideoType(contentType, url);
      if (!videoType) return;

      if (!videoType.isStream && contentLength > 0 && contentLength < 300 * 1024) {
        return;
      }

      const existingList = tabMediaMap.get(tabId) || [];
      if (existingList.some((item) => getMediaDedupeKey(item.url) === dedupeKey)) {
        return;
      }

      chrome.tabs.get(tabId, async (tab) => {
        if (chrome.runtime.lastError || !tab) return;
        const pageTitle = cleanTitle(tab.title, "video");
        const effReferer = actualReferer || tab.url || "";
        const effSource = detectSourceLabel(effReferer, url);
        const effFrameId = typeof frameId === "number" ? frameId : 0;

        let mediaPlaylistDuration = null;
        let isAudioOnly = false;

        if (videoType.isStream && (url.includes(".m3u8") || contentType.toLowerCase().includes("mpegurl"))) {
          if (inspectingKeys.has(dedupeKey)) return;
          inspectingKeys.add(dedupeKey);
          try {
            const probe = await probePlaylist(url, effReferer);
            if (probe.ok && probe.text) {
              const text = probe.text;
              if (text.includes("#EXT-X-STREAM-INF")) {
                const parsed = parseMasterPlaylist(text, url);
                if (parsed.variants.length > 0) {
                  if (!tabKnownSubstreams.has(tabId)) {
                    tabKnownSubstreams.set(tabId, new Set());
                  }
                  const subs = tabKnownSubstreams.get(tabId);
                  for (const subUrl of parsed.allSubstreamUrls) {
                    subs.add(subUrl);
                  }

                  // Yarış durumu: alt liste master'dan önce yakalandıysa listeden temizle
                  const curMedia = tabMediaMap.get(tabId);
                  if (curMedia && curMedia.length > 0) {
                    tabMediaMap.set(
                      tabId,
                      curMedia.filter((m) => !subs.has(m.url) && !subs.has(getMediaDedupeKey(m.url)))
                    );
                  }

                  // Master içindeki altyazı kanallarını ekle
                  for (const st of parsed.subtitleTracks) {
                    addSubtitleItem(tabId, {
                      id: crypto.randomUUID(),
                      url: st.url,
                      refererUrl: effReferer,
                      webpage_url: tab.url || "",
                      frameId: effFrameId,
                      sourceLabel: effSource,
                      title: pageTitle,
                      label: st.label,
                      langCode: st.langCode,
                      format: "HLS VTT",
                      ext: "vtt",
                      canConvertToSrt: true,
                      isHlsSubtitle: true,
                      timestamp: Date.now()
                    });
                  }

                  const best = parsed.variants[0];
                  let durationSec = null;
                  const bestProbe = await probePlaylist(best.url, effReferer);
                  if (bestProbe.ok && bestProbe.text) {
                    durationSec = playlistDuration(bestProbe.text);
                  }
                  const durText = formatDuration(durationSec);
                  const hasExtAudio = parsed.variants.some((v) => v.hasExternalAudio);
                  const metaParts = [effSource, durText, best.bwLabel, hasExtAudio ? "Çoklu Ses" : "HLS"].filter(Boolean);

                  const item = {
                    id: crypto.randomUUID(),
                    url,
                    masterUrl: url,
                    targetUrl: best.url,
                    refererUrl: effReferer,
                    webpage_url: tab.url || "",
                    frameId: effFrameId,
                    sourceLabel: effSource,
                    title: `${pageTitle} [${best.qualityLabel}].mp4`,
                    format: best.qualityLabel,
                    resolution: best.qualityLabel,
                    ext: "mp4",
                    isStream: true,
                    isMaster: true,
                    hasExternalAudio: hasExtAudio,
                    audioTracks: parsed.audioTracks,
                    sizeFormatted: metaParts.join(" • "),
                    sizeBytes: 0,
                    durationSec,
                    qualities: parsed.variants,
                    timestamp: Date.now()
                  };
                  addMediaItem(tabId, item);
                  return;
                }
              } else if (isSubtitlePlaylist(url, text)) {
                const langInfo = detectSubtitleLang(url);
                addSubtitleItem(tabId, {
                  id: crypto.randomUUID(),
                  url,
                  refererUrl: effReferer,
                  webpage_url: tab.url || "",
                  frameId: effFrameId,
                  sourceLabel: effSource,
                  title: pageTitle,
                  label: langInfo.label,
                  langCode: langInfo.code,
                  format: "HLS VTT",
                  ext: "vtt",
                  canConvertToSrt: true,
                  isHlsSubtitle: true,
                  timestamp: Date.now()
                });
                return;
              } else {
                mediaPlaylistDuration = playlistDuration(text);
                isAudioOnly = isAudioOnlyPlaylist(url, text);
              }
            }
          } finally {
            inspectingKeys.delete(dedupeKey);
          }
        }

        // Eğer bu arada master listesi tarafından alt akış olarak işaretlendiyse ekleme
        const knownAfter = tabKnownSubstreams.get(tabId);
        if (knownAfter && (knownAfter.has(url) || knownAfter.has(dedupeKey))) {
          return;
        }

        const urlRes = extractResolutionFromUrl(url);
        const resLabel = isAudioOnly ? "SES" : (urlRes || (videoType.isStream ? "HD" : ""));
        const formatStr = resLabel ? `${resLabel} ${videoType.format}` : videoType.format;
        const durText = formatDuration(mediaPlaylistDuration);
        const sizeLabel = mediaPlaylistDuration
          ? [effSource, durText, isAudioOnly ? "Ses" : "HLS"].filter(Boolean).join(" • ")
          : [effSource, formatBytes(contentLength)].filter(Boolean).join(" • ");

        const item = {
          id: crypto.randomUUID(),
          url,
          refererUrl: effReferer,
          webpage_url: tab.url || "",
          frameId: effFrameId,
          sourceLabel: effSource,
          title: `${pageTitle}${resLabel ? " [" + resLabel + "]" : ""}.${videoType.ext}`,
          format: formatStr,
          resolution: resLabel,
          ext: videoType.ext,
          isStream: videoType.isStream,
          isAudioOnly,
          sizeFormatted: sizeLabel,
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
}

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
function notifyHandoff(id, title) {
  activeDownloads.delete(id);
  chrome.action.setBadgeText({ text: "" });
  const payload = { type: "DOWNLOAD_HANDOFF", id, title };
  chrome.runtime.sendMessage(payload).catch(() => {});
  broadcastToTabs(payload);
}

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
  } catch {
    tasks = null;
  }

  for (const [extId, info] of desktopTracked) {
    const task = tasks ? tasks.find((t) => t.id === info.desktopId) : undefined;
    if (!task) {
      info.misses += 1;
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
      const cur = activeDownloads.get(extId) || {};
      const paused = data.status === "paused";
      emitProgress(extId, cur.percent || 1, paused ? "Duraklatıldı" : "Devam ediyor...", cur.mbTotal || "",
        "", cur.filename || info.title, "", false, { desktop: true, desktopState: paused ? "paused" : "downloading" });
    }
    return { success: true, status: data.status };
  } catch {
    return { success: false, error: "NovaStream uygulamasına ulaşılamıyor" };
  }
}

async function collectCookies(url, refererUrl) {
  if (!chrome.cookies?.getAll) return "";
  const seen = new Map();
  const add = (list) => {
    for (const c of list || []) seen.set(`${c.domain}|${c.path}|${c.name}`, c);
  };
  const safeGetAll = async (query) => {
    try {
      add(await chrome.cookies.getAll(query));
    } catch {}
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

async function delegateToYtDlp({ id, url, refererUrl, title, isYouTube = false, quality = null, audioLang = null, audioName = null }) {
  const cookies = await collectCookies(url, refererUrl);
  const sent = await sendToDesktopAppIfRunning({
    url,
    title,
    referer: refererUrl || "",
    isStream: !isYouTube,
    isYouTube,
    quality: quality || undefined,
    audioLang: audioLang || undefined,
    audioName: audioName || undefined,
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
    audioLang: audioLang || undefined,
    audioName: audioName || undefined,
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

async function fetchWith429Backoff(url, maxRetries = 5) {
  let attempt = 0;
  while (true) {
    const res = await fetch(url, { credentials: "include" });
    if (res.status === 429 || res.status === 503) {
      attempt += 1;
      if (attempt > maxRetries) throw new Error(`HTTP ${res.status}`);
      const waitMs = parseRetryAfterMs(res.headers.get("retry-after"), Math.min(30000, 1500 * Math.pow(2, attempt - 1)));
      await new Promise((r) => setTimeout(r, waitMs));
      continue;
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res;
  }
}

// HLS Stream İndirici (Browser Fetch -> Native FFmpeg Disk Yazıcı, adaptif 429 korumalı)
async function downloadStreamViaChromeNetwork({ id, streamUrl, refererUrl, videoTitle, masterUrl = "", hasExternalAudio = false, quality = null, audioLang = null, audioName = null }) {
  const finalFilename = `${cleanTitle(stripMediaExts(videoTitle), "video")}.mp4`;

  // Ayrı ses kanallı akışta master URL varsa ses+görüntü birleştirme için yt-dlp'ye devret
  if (hasExternalAudio && masterUrl) {
    emitProgress(id, 1, "Ses + Görüntü aktarılıyor...", "", "", finalFilename, masterUrl, false);
    try {
      await delegateToYtDlp({ id, url: masterUrl, refererUrl, title: finalFilename, quality, audioLang, audioName });
    } catch (err) {
      emitFinished(id, false, finalFilename, err.message);
    }
    return;
  }

  emitProgress(id, 1, "Bağlanıyor...", "", "", finalFilename, streamUrl, false);
  let targetUrl = streamUrl;
  let playlistText = "";
  let fileOpened = false;
  let port = null;

  try {
    port = getNativePort();

    await withScopedHeaders([targetUrl], refererUrl, async () => {
      const res = await fetchWith429Backoff(targetUrl, 4);
      playlistText = await res.text();
    });

    if (playlistText.includes("<!DOCTYPE") || playlistText.includes("<html")) {
      throw new Error("Sunucu oynatma listesi yerine HTML döndü.");
    }

    if (playlistNeedsYtDlp(playlistText, targetUrl)) {
      await delegateToYtDlp({ id, url: masterUrl || streamUrl, refererUrl, title: finalFilename, quality, audioLang, audioName });
      return;
    }

    // Master Playlist kontrolü
    if (playlistText.includes("#EXT-X-STREAM-INF")) {
      const parsed = parseMasterPlaylist(playlistText, targetUrl);
      if (parsed.variants.length > 0) {
        const chosen = parsed.variants[0];
        if (chosen.hasExternalAudio) {
          await delegateToYtDlp({ id, url: targetUrl, refererUrl, title: finalFilename, quality, audioLang, audioName });
          return;
        }
        targetUrl = chosen.url;
        await withScopedHeaders([targetUrl], refererUrl, async () => {
          const subRes = await fetchWith429Backoff(targetUrl, 4);
          playlistText = await subRes.text();
        });
      }
    }

    if (playlistNeedsYtDlp(playlistText, targetUrl)) {
      await delegateToYtDlp({ id, url: masterUrl || streamUrl, refererUrl, title: finalFilename, quality, audioLang, audioName });
      return;
    }

    // Init Segment (#EXT-X-MAP) + Parçaları ayrıştır
    let initSegmentUrl = null;
    const segmentUrls = [];
    let isFmp4 = false;

    for (const raw of playlistText.split(/\r?\n/)) {
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
    fileOpened = true;

    // Tüm CDN hostlarını DNR kapsamına al (farklı segment CDN'leri için)
    const allUrlsToScope = [targetUrl];
    if (initSegmentUrl) allUrlsToScope.push(initSegmentUrl);
    for (const u of segmentUrls) allUrlsToScope.push(u);

    await withScopedHeaders(allUrlsToScope, refererUrl, async () => {
      if (initSegmentUrl) {
        const initRes = await fetchWith429Backoff(initSegmentUrl, 4);
        const initBuf = await initRes.arrayBuffer();
        sendBufferToNative(port, id, new Uint8Array(initBuf));
      }

      const MAX_CONCURRENCY = 4;
      let currentConcurrency = MAX_CONCURRENCY;
      let activeWorkers = 0;
      let rateLimitUntil = 0;
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

      async function waitForTurn(workerId) {
        while (true) {
          const wait = rateLimitUntil - Date.now();
          if (wait > 0) {
            await new Promise((r) => setTimeout(r, Math.min(wait + 50, 2000)));
            continue;
          }
          if (workerId < currentConcurrency) break;
          await new Promise((r) => setTimeout(r, 250));
          if (nextIndex >= total) break;
        }
      }

      async function worker(workerId) {
        while (true) {
          await waitForTurn(workerId);
          if (nextIndex >= total) break;
          const idx = nextIndex++;
          const segUrl = segmentUrls[idx];
          const maxRetries = 6;
          let segBuf = null;
          let lastErr = null;

          activeWorkers++;
          try {
            for (let attempt = 0; attempt <= maxRetries; attempt++) {
              const cdWait = rateLimitUntil - Date.now();
              if (cdWait > 0) {
                await new Promise((r) => setTimeout(r, cdWait));
              }
              try {
                const r = await fetch(segUrl, { credentials: "include" });
                if (r.status === 429 || r.status === 503) {
                  const backoff = Math.min(30000, 1500 * Math.pow(2, attempt)) + Math.floor(Math.random() * 500);
                  const waitMs = parseRetryAfterMs(r.headers.get("retry-after"), backoff);
                  rateLimitUntil = Math.max(rateLimitUntil, Date.now() + waitMs);
                  currentConcurrency = Math.max(1, Math.floor(currentConcurrency / 2));
                  emitProgress(
                    id,
                    Math.round((completed / total) * 100),
                    `Hız sınırı (${r.status}) — bekleniyor...`,
                    (downloadedBytes / (1024 * 1024)).toFixed(1) + " MB",
                    `${Math.ceil(waitMs / 1000)}s`,
                    finalFilename,
                    streamUrl
                  );
                  throw new Error(`HTTP ${r.status}`);
                }
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                segBuf = await r.arrayBuffer();
                break;
              } catch (err) {
                lastErr = err;
                if (attempt === maxRetries) throw lastErr;
                if (!String(err.message).includes("429") && !String(err.message).includes("503")) {
                  await new Promise((r) => setTimeout(r, 700 * (attempt + 1)));
                }
              }
            }
          } finally {
            activeWorkers--;
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
      for (let i = 0; i < Math.min(MAX_CONCURRENCY, total); i++) {
        workers.push(worker(i));
      }
      await Promise.all(workers);
      void activeWorkers;
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
    if (fileOpened && port) {
      try {
        sendNativeMessage(port, { action: "FILE_ABORT", id });
      } catch {}
    }
    emitFinished(id, false, finalFilename, err.message);
  }
}

// Doğrudan MP4 / WebM İndirici
async function downloadDirectVideoViaChromeNetwork({ id, url, refererUrl, videoTitle }) {
  const finalFilename = `${cleanTitle(stripMediaExts(videoTitle), "video")}.mp4`;
  emitProgress(id, 1, "Bağlanıyor...", "", "", finalFilename, url, false);
  let fileOpened = false;
  let port = null;
  try {
    port = getNativePort();

    sendNativeMessage(port, {
      action: "FILE_OPEN",
      id,
      title: finalFilename,
      filename: finalFilename,
      isFmp4: false
    });
    fileOpened = true;

    await withScopedHeaders([url], refererUrl, async () => {
      const res = await fetchWith429Backoff(url, 4);

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
    if (fileOpened && port) {
      try {
        sendNativeMessage(port, { action: "FILE_ABORT", id });
      } catch {}
    }
    emitFinished(id, false, finalFilename, err.message);
  }
}

// WebVTT -> SRT Dönüştürücü
function normalizeSrtTime(ts) {
  const m = String(ts || "").trim().match(/^(?:(\d{1,2}):)?(\d{2}):(\d{2})[.,](\d{3})/);
  if (!m) return null;
  const hh = (m[1] || "00").padStart(2, "0");
  const mm = m[2];
  const ss = m[3];
  const ms = m[4];
  return `${hh}:${mm}:${ss},${ms}`;
}

function vttToSrt(vttText) {
  const clean = String(vttText || "")
    .replace(/^\uFEFF/, "")
    .replace(/\r\n?/g, "\n");
  const blocks = clean.split(/\n{2,}/);
  const cues = [];

  for (const rawBlock of blocks) {
    const lines = rawBlock.split("\n").map((l) => l.trimEnd());
    while (lines.length && !lines[0].trim()) lines.shift();
    if (!lines.length) continue;

    const first = lines[0].trim();
    if (
      first.startsWith("WEBVTT") ||
      first.startsWith("NOTE") ||
      first.startsWith("STYLE") ||
      first.startsWith("REGION") ||
      first.startsWith("X-TIMESTAMP-MAP")
    ) {
      continue;
    }

    let timeIdx = lines.findIndex((l) => l.includes("-->"));
    if (timeIdx < 0) continue;

    const timeLine = lines[timeIdx];
    const parts = timeLine.split("-->");
    if (parts.length < 2) continue;
    const start = normalizeSrtTime(parts[0]);
    const end = normalizeSrtTime(parts[1].trim().split(/\s+/)[0]);
    if (!start || !end) continue;

    const textLines = lines
      .slice(timeIdx + 1)
      .map((l) => l.replace(/<\d{2}:[^>]+>/g, "").replace(/<\/?[^>]+>/g, "").trim())
      .filter(Boolean);

    if (!textLines.length) continue;
    const textBody = textLines.join("\n");

    // Ardışık yinelenen HLS altyazı satırlarını birleştir
    const prev = cues[cues.length - 1];
    if (prev && prev.text === textBody && prev.end === start) {
      prev.end = end;
      continue;
    }
    if (prev && prev.text === textBody && prev.start === start && prev.end === end) {
      continue;
    }

    cues.push({ start, end, text: textBody });
  }

  return cues.map((c, idx) => `${idx + 1}\n${c.start} --> ${c.end}\n${c.text}`).join("\n\n") + (cues.length ? "\n" : "");
}

async function downloadSubtitle({ url, refererUrl = "", title = "altyazi", langCode = "", ext = "vtt", isHlsSubtitle = false, convertToSrt = true }) {
  try {
    let rawText = "";
    const lowerUrl = (url || "").toLowerCase();
    const treatAsHls = Boolean(isHlsSubtitle || /\.m3u8(?:\?|$|#)/i.test(lowerUrl));

    if (treatAsHls) {
      let playlist = "";
      await withScopedHeaders([url], refererUrl, async () => {
        const res = await fetchWith429Backoff(url, 4);
        playlist = await res.text();
      });
      if (playlist.includes("#EXTINF")) {
        const segUrls = [];
        const seenSeg = new Set();
        for (const raw of playlist.split(/\r?\n/)) {
          const line = raw.trim();
          if (!line || line.startsWith("#")) continue;
          try {
            const abs = new URL(line, url).href;
            if (!seenSeg.has(abs)) {
              seenSeg.add(abs);
              segUrls.push(abs);
            }
          } catch {}
        }
        if (segUrls.length === 0) throw new Error("Altyazı parçası bulunamadı.");
        const chunks = [];
        await withScopedHeaders(segUrls, refererUrl, async () => {
          for (const seg of segUrls) {
            const r = await fetchWith429Backoff(seg, 4);
            chunks.push(await r.text());
          }
        });
        rawText = chunks.join("\n\n");
      } else {
        rawText = playlist;
      }
    } else {
      await withScopedHeaders([url], refererUrl, async () => {
        const res = await fetchWith429Backoff(url, 4);
        rawText = await res.text();
      });
    }

    const looksVtt = /^\s*(?:\uFEFF)?WEBVTT/i.test(rawText) || ext === "vtt" || treatAsHls;
    const finalExt = convertToSrt && looksVtt ? "srt" : (ext || "srt");
    const finalContent = convertToSrt && looksVtt ? vttToSrt(rawText) : rawText;
    if (!finalContent.trim()) {
      throw new Error("Altyazı içeriği boş.");
    }

    const base = cleanTitle(title, "altyazi");
    const langTag = langCode ? `.${langCode.toLowerCase()}` : "";
    const filename = `${base}${langTag}.${finalExt}`;

    // Önce açık NovaStream masaüstü uygulamasına göndermeyi dene
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 2500);
      const res = await fetch("http://127.0.0.1:9191/api/save_subtitle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename, content: finalContent }),
        signal: controller.signal
      });
      clearTimeout(timer);
      if (res.ok) {
        const data = await res.json();
        if (data?.success) {
          return { success: true, where: "desktop", filename: data.filename || filename };
        }
      }
    } catch {}

    // Masaüstü uygulaması kapalıysa tarayıcının indirme yöneticisiyle kaydet
    if (!chrome.downloads?.download) {
      throw new Error("Tarayıcı indirme API'si kullanılamıyor.");
    }
    const dataUrl = "data:text/plain;charset=utf-8," + encodeURIComponent(finalContent);
    await new Promise((resolve, reject) => {
      chrome.downloads.download({ url: dataUrl, filename, saveAs: false }, (dlId) => {
        if (chrome.runtime.lastError || !dlId) {
          reject(new Error(chrome.runtime.lastError?.message || "Altyazı indirilemedi"));
        } else {
          resolve(dlId);
        }
      });
    });
    return { success: true, where: "browser", filename };
  } catch (err) {
    return { success: false, error: err.message };
  }
}

// Sekme Kapatıldığında veya Yenilendiğinde Temizle
chrome.tabs?.onRemoved?.addListener((tabId) => {
  tabMediaMap.delete(tabId);
  tabSubtitleMap.delete(tabId);
  tabKnownSubstreams.delete(tabId);
});

chrome.tabs?.onUpdated?.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "loading" && changeInfo.url) {
    tabMediaMap.delete(tabId);
    tabSubtitleMap.delete(tabId);
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
  } catch {}
  return null;
}

// Mesajlaşma Merkezi
if (chrome.runtime?.onMessage) {
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    const tabId = message.tabId || sender.tab?.id;
    const senderFrameId = typeof sender.frameId === "number" ? sender.frameId : undefined;

    if (message.type === "GET_MEDIA" || message.type === "GET_MEDIA_FOR_TAB") {
      const known = tabKnownSubstreams.get(tabId);
      const allMedia = rankMediaList(
        (tabMediaMap.get(tabId) || []).filter((m) => !isYouTubeChunk(m.url) && !isYouTubePage(m.webpage_url)),
        known
      );
      const allSubs = tabSubtitleMap.get(tabId) || [];
      const frameMedia = typeof senderFrameId === "number"
        ? allMedia.filter((m) => m.frameId === senderFrameId)
        : allMedia;
      const frameSubtitles = typeof senderFrameId === "number"
        ? allSubs.filter((s) => s.frameId === senderFrameId)
        : allSubs;
      sendResponse({
        media: allMedia,
        frameMedia,
        subtitles: allSubs,
        frameSubtitles,
        activeDownloads: Array.from(activeDownloads.values())
      });
      return true;
    } else if (message.type === "SUBTITLES_DETECTED") {
      if (tabId && Array.isArray(message.tracks)) {
        for (const tr of message.tracks) {
          if (!tr?.url) continue;
          const langInfo = detectSubtitleLang(tr.url, tr.label || "", tr.srclang || "");
          const subType = parseSubtitleType("", tr.url) || { format: "VTT", ext: "vtt", canConvertToSrt: true };
          addSubtitleItem(tabId, {
            id: crypto.randomUUID(),
            url: tr.url,
            refererUrl: message.refererUrl || sender.url || sender.tab?.url || "",
            webpage_url: sender.tab?.url || "",
            frameId: typeof senderFrameId === "number" ? senderFrameId : 0,
            sourceLabel: detectSourceLabel(message.refererUrl || sender.url || "", tr.url),
            title: cleanTitle(sender.tab?.title, "altyazi"),
            label: tr.label ? `${langInfo.label}` : langInfo.label,
            langCode: langInfo.code,
            format: subType.format,
            ext: subType.ext,
            canConvertToSrt: subType.canConvertToSrt,
            isHlsSubtitle: false,
            timestamp: Date.now()
          });
        }
      }
      sendResponse?.({ success: true });
      return true;
    } else if (message.type === "FRAME_UNLOAD") {
      if (tabId && typeof senderFrameId === "number" && senderFrameId > 0) {
        clearFrameData(tabId, senderFrameId);
      }
      return false;
    } else if (message.type === "DOWNLOAD_SUBTITLE") {
      downloadSubtitle({
        url: message.url,
        refererUrl: message.refererUrl || sender.url || sender.tab?.url || "",
        title: message.title || cleanTitle(sender.tab?.title, "altyazi"),
        langCode: message.langCode || "",
        ext: message.ext || "vtt",
        isHlsSubtitle: Boolean(message.isHlsSubtitle),
        convertToSrt: message.convertToSrt !== false
      }).then(sendResponse);
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
            let updated = false;
            const known = tabKnownSubstreams.get(tabId);
            const ranked = rankMediaList(items, known);
            const main = (typeof senderFrameId === "number"
              ? ranked.find((it) => !it.minor && it.frameId === senderFrameId)
              : null) || ranked.find((it) => !it.minor);
            const target = main && items.find((it) => it.id === main.id);
            if (target && (!target.resolution || target.resolution === "HD") && !(target.qualities?.length > 1)) {
              target.resolution = resLabel;
              target.format = `${resLabel} ${(target.ext || "mp4").toUpperCase()}`;
              updated = true;
            }
            if (updated) {
              updateBadge(tabId);
              notifyTabMedia(tabId, typeof senderFrameId === "number" ? senderFrameId : null);
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
      const referer = message.refererUrl || sender.url || (sender.tab ? sender.tab.url : "");
      const title = message.title || message.videoTitle || "video";

      if (isStream) {
        downloadStreamViaChromeNetwork({
          id: downloadId,
          streamUrl: downloadUrl,
          refererUrl: referer,
          videoTitle: title,
          masterUrl: message.masterUrl || "",
          hasExternalAudio: Boolean(message.hasExternalAudio),
          quality: message.quality || null,
          audioLang: message.audioLang || null,
          audioName: message.audioName || null
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
}

// Node.js birim testleri için saf yardımcıları dışa aktar (Service Worker ortamında globalThis zarar görmez)
if (typeof globalThis !== "undefined") {
  globalThis.__NovaStreamTest = {
    parseMasterPlaylist,
    isSubtitlePlaylist,
    isAudioOnlyPlaylist,
    parseVideoType,
    parseSubtitleType,
    detectSourceLabel,
    detectSubtitleLang,
    rankMediaList,
    vttToSrt,
    isIgnoredNoiseUrl,
    getMediaDedupeKey,
    stripMediaExts,
    formatAudioTrackLabel
  };
}

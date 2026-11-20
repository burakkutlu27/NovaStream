import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1")), "..");
const BG_PATH = path.join(ROOT, "NovaStream-v2", "OpenVideoDownloader-Extension", "background.js");
const code = fs.readFileSync(BG_PATH, "utf8");

function makeChromeMock() {
  const noop = () => {};
  return {
    action: { setBadgeText: noop, setBadgeBackgroundColor: noop },
    runtime: {
      onStartup: { addListener: noop },
      onInstalled: { addListener: noop },
      onMessage: { addListener: noop },
      sendMessage: () => Promise.resolve(),
      lastError: null
    },
    tabs: {
      query: (_q, cb) => cb?.([]),
      sendMessage: () => Promise.resolve(),
      onRemoved: { addListener: noop },
      onUpdated: { addListener: noop }
    },
    webRequest: {
      onBeforeSendHeaders: { addListener: noop },
      onHeadersReceived: { addListener: noop }
    },
    declarativeNetRequest: {
      getDynamicRules: async () => [],
      updateDynamicRules: async () => {},
      getSessionRules: async () => [],
      updateSessionRules: async () => {}
    },
    contextMenus: {
      removeAll: (cb) => cb?.(),
      create: noop,
      onClicked: { addListener: noop }
    },
    notifications: { create: noop },
    downloads: { download: (_opts, cb) => cb?.(1) },
    cookies: { getAll: async () => [] }
  };
}

const sandbox = {
  console,
  URL,
  Map,
  Set,
  Promise,
  Date,
  Math,
  RegExp,
  Array,
  Object,
  String,
  Number,
  Boolean,
  Error,
  Uint8Array,
  crypto: { randomUUID: () => crypto.randomUUID() },
  setTimeout,
  clearTimeout,
  btoa: (s) => Buffer.from(s, "binary").toString("base64"),
  fetch: async () => { throw new Error("unexpected fetch in unit test"); },
  chrome: makeChromeMock(),
  globalThis: null
};
sandbox.globalThis = sandbox;
vm.runInNewContext(code, sandbox, { filename: "background.js" });

const ns = sandbox.__NovaStreamTest;
assert.ok(ns, "__NovaStreamTest helpers must be exported");

// 1. parseMasterPlaylist: Rapidrame tarzi master HLS (video + ayri ses + altyazi + tekrar ayna)
{
  const master = [
    "#EXTM3U",
    '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="Turkce",LANGUAGE="tr",DEFAULT=YES,URI="audio/tr.m3u8"',
    '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="Türkçe",LANGUAGE="tr",DEFAULT=YES,URI="subs/tr.m3u8"',
    '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="English",LANGUAGE="en",DEFAULT=NO,URI="subs/en.m3u8"',
    '#EXT-X-STREAM-INF:BANDWIDTH=4200000,RESOLUTION=1920x1080,FRAME-RATE=24,AUDIO="aud",SUBTITLES="subs"',
    "1080/index.m3u8?token=abc",
    '#EXT-X-STREAM-INF:BANDWIDTH=4180000,RESOLUTION=1920x1080,FRAME-RATE=24,AUDIO="aud",SUBTITLES="subs"',
    "1080/mirror2.m3u8?token=def",
    '#EXT-X-STREAM-INF:BANDWIDTH=2100000,RESOLUTION=1280x720,AUDIO="aud",SUBTITLES="subs"',
    "720/index.m3u8?token=ghi"
  ].join("\n");

  const parsed = ns.parseMasterPlaylist(master, "https://cdn.example.com/v/master.m3u8");
  assert.equal(parsed.variants.length, 2, "duplicate 1080p mirror should collapse");
  assert.equal(parsed.variants[0].height, 1080);
  assert.equal(parsed.variants[0].hasExternalAudio, true);
  assert.equal(parsed.variants[1].height, 720);
  assert.equal(parsed.subtitleTracks.length, 2);
  assert.equal(parsed.subtitleTracks[0].langCode, "TR");
  assert.equal(parsed.subtitleTracks[1].langCode, "EN");
  assert.ok(parsed.allSubstreamUrls.has("https://cdn.example.com/v/audio/tr.m3u8"));
  assert.ok(parsed.allSubstreamUrls.has("https://cdn.example.com/v/subs/tr.m3u8"));
  assert.ok(parsed.allSubstreamUrls.has("https://cdn.example.com/v/1080/index.m3u8?token=abc"));
  assert.ok(parsed.allSubstreamUrls.has("https://cdn.example.com/v/1080/index.m3u8"));

  // Çift sesli Close benzeri master playlist tekilleştirme & etiketleme kontrolü
  const dualMaster = [
    "#EXTM3U",
    '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a1",NAME="Turkish",LANGUAGE="tr",DEFAULT=YES,URI="a/tr.m3u8"',
    '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a1",NAME="English",LANGUAGE="en",DEFAULT=NO,URI="a/en.m3u8"',
    '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a2",NAME="Turkish",LANGUAGE="tr",DEFAULT=YES,URI="a/tr2.m3u8"',
    '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a2",NAME="English",LANGUAGE="en",DEFAULT=NO,URI="a/en2.m3u8"',
    '#EXT-X-STREAM-INF:BANDWIDTH=2000000,RESOLUTION=1280x720,AUDIO="a1"',
    "720/v.m3u8"
  ].join("\n");
  const dualParsed = ns.parseMasterPlaylist(dualMaster, "https://cdn.example.com/master.txt");
  assert.equal(dualParsed.audioTracks.length, 2, "duplicate audio tracks across groups should deduplicate");
  assert.equal(dualParsed.audioTracks[0].label, "Türkçe");
  assert.equal(dualParsed.audioTracks[0].language, "tr");
  assert.equal(dualParsed.audioTracks[0].rawName, "Turkish");
  assert.equal(dualParsed.audioTracks[1].label, "English (Orijinal)");
  assert.equal(dualParsed.audioTracks[1].language, "en");
  assert.equal(dualParsed.audioTracks[1].rawName, "English");

  assert.equal(ns.stripMediaExts("Film [720p HD].mp4.mp4"), "Film [720p HD]");
}

// 2. isSubtitlePlaylist & isAudioOnlyPlaylist & parseVideoType
{
  const subPl = "#EXTM3U\n#EXTINF:6.0,\nseg0.vtt\n#EXTINF:6.0,\nseg1.vtt\n#EXT-X-ENDLIST\n";
  const vidPl = "#EXTM3U\n#EXTINF:6.0,\nseg0.ts\n#EXTINF:6.0,\nseg1.ts\n#EXT-X-ENDLIST\n";
  const audPl = "#EXTM3U\n#EXTINF:6.0,\nseg0.aac\n#EXTINF:6.0,\nseg1.aac\n#EXT-X-ENDLIST\n";

  assert.equal(ns.isSubtitlePlaylist("https://cdn.example.com/sub.m3u8", subPl), true);
  assert.equal(ns.isSubtitlePlaylist("https://cdn.example.com/vid.m3u8", vidPl), false);
  assert.equal(ns.isAudioOnlyPlaylist("https://cdn.example.com/audio/stream.m3u8", audPl), true);
  assert.equal(ns.isAudioOnlyPlaylist("https://cdn.example.com/vid.m3u8", vidPl), false);

  const m3u8AsTextPlain = ns.parseVideoType("text/plain; charset=utf-8", "https://cdn.example.com/index.m3u8?t=1");
  assert.deepEqual({ ...m3u8AsTextPlain }, { format: "HLS", ext: "mp4", isStream: true });
  assert.equal(ns.parseVideoType("text/plain", "https://cdn.example.com/robots.txt"), null);
  assert.equal(ns.parseVideoType("text/html", "https://cdn.example.com/index.m3u8"), null);
}

// 3. detectSourceLabel & isIgnoredNoiseUrl
{
  assert.equal(
    ns.detectSourceLabel("https://www.example.com/rplayer/abc123xyz/", "https://cdn1.example.com/master.m3u8"),
    "Rapidrame"
  );
  assert.equal(
    ns.detectSourceLabel("https://example.org/video/embed/AbC123xYz/?rapidrame_id=abc123xyz", "https://cdn2.example.com/master.m3u8"),
    "Close"
  );
  assert.equal(
    ns.isIgnoredNoiseUrl("https://gc.kis.v2.scr.kaspersky-labs.com/E3E8934C-235A-4B0E-825A-35A08381A191/abn/main.css?attr=xyz"),
    true
  );
}

// 4. rankMediaList: Master varsa ayni framedeki belirsiz kayitlari ve knownSubstreams'i gizle
{
  const known = new Set(["https://cdn.example.com/720/index.m3u8"]);
  const ranked = ns.rankMediaList([
    {
      id: "sub",
      url: "https://cdn.example.com/720/index.m3u8?tok=1",
      frameId: 5,
      isStream: true,
      timestamp: 100
    },
    {
      id: "bare1",
      url: "https://other.cdn.net/stream.m3u8",
      frameId: 5,
      isStream: true,
      durationSec: null,
      timestamp: 101
    },
    {
      id: "master",
      url: "https://cdn.example.com/master.m3u8",
      frameId: 5,
      isStream: true,
      durationSec: 5400,
      qualities: [{ qualityLabel: "1080p FHD" }, { qualityLabel: "720p HD" }],
      sourceLabel: "Rapidrame",
      timestamp: 102
    }
  ], known);

  assert.equal(ranked.some((r) => r.id === "sub"), false, "known substream must be filtered out");
  const masterRec = ranked.find((r) => r.id === "master");
  const bareRec = ranked.find((r) => r.id === "bare1");
  assert.equal(masterRec.minor, false);
  assert.equal(bareRec.minor, true, "unresolved bare stream in same frame should become minor");
}

// 5. vttToSrt
{
  const vtt = [
    "\uFEFFWEBVTT",
    "X-TIMESTAMP-MAP=MPEGTS:900000,LOCAL:00:00:00.000",
    "",
    "NOTE Bu bir yorumdur",
    "",
    "00:01.250 --> 00:04.500 align:start position:0%",
    "<c.yellow>Merhaba</c> dünya",
    "",
    "00:04.500 --> 00:06.000",
    "Merhaba dünya",
    "",
    "01:02:03.400 --> 01:02:05.800",
    "İkinci satır"
  ].join("\n");

  const srt = ns.vttToSrt(vtt);
  assert.ok(srt.includes("1\n00:00:01,250 --> 00:00:06,000\nMerhaba dünya"), "adjacent duplicate cue merges cleanly");
  assert.ok(srt.includes("2\n01:02:03,400 --> 01:02:05,800\nİkinci satır"));
  assert.equal(srt.includes("WEBVTT"), false);
  assert.equal(srt.includes("<c."), false);
}

console.log("[OK] All extension unit tests passed!");

// Service worker di myMoney: rende l'app installabile e utilizzabile anche senza rete.
// Aumenta VERSION quando cambi l'elenco dei file in CORE.
const VERSION = "mymoney-01.06.007";
const DATA = "mm-data"; // file scaricati dall'app Android (native.js): hanno la precedenza su quelli inclusi
const CORE = ["./", "index.html", "manifest.webmanifest", "icons/icon.svg", "icons/icon-192.png", "icons/icon-512.png", "icons/icon-maskable-512.png", "icons/apple-touch-icon.png", "native.js"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(VERSION).then(c => Promise.all(CORE.map(u => c.add(u).catch(() => {})))).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== VERSION && k !== DATA).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});

// Pagina e prezzi: prima la rete (dati freschi), la copia salvata solo se la rete manca.
// Tutto il resto, compresi i caratteri di Google Fonts: dalla copia salvata, aggiornata in secondo piano.
self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  const fresh = req.mode === "navigate" || (url.origin === location.origin && (/(^|\/)(index\.html|prices\.js|etfdata\.js|catalog\.js|quotes\.js)$/.test(url.pathname) || /\/data\/[pd]\/[^/]+\.js$/.test(url.pathname)));
  if (fresh) {
    const net = () => fetch(req).then(r => { if (r.ok) caches.open(VERSION).then(c => c.put(req, r.clone())); return r; })
      .catch(() => caches.match(req, { ignoreSearch: true }).then(r => r
        || (req.mode === "navigate" ? caches.match("index.html")
          : /(prices|etfdata|catalog|quotes)\.js$/.test(url.pathname) ? new Response(url.pathname.endsWith("prices.js") ? "window.PRICES=null;" : url.pathname.endsWith("catalog.js") ? "window.CATALOG=null;" : url.pathname.endsWith("quotes.js") ? "window.QUOTES=null;" : "window.ETFDATA=null;", { headers: { "Content-Type": "text/javascript" } })
          : new Response("", { status: 504 }))));
    // i file scaricati dall'app Android (cache «mm-data») hanno la precedenza su quelli inclusi o sul sito
    const mine = url.origin === location.origin && /(^|\/)(prices|etfdata|catalog|quotes)\.js$|\/data\/[pd]\/[^/]+\.js$/.test(url.pathname);
    e.respondWith(mine ? caches.match(req, { cacheName: DATA, ignoreSearch: true }).then(r => r || net()) : net());
    return;
  }
  if (url.origin === location.origin || /fonts\.(googleapis|gstatic)\.com$/.test(url.hostname)) {
    e.respondWith(caches.match(req).then(hit => {
      const net = fetch(req).then(r => { if (r.ok || r.type === "opaque") caches.open(VERSION).then(c => c.put(req, r.clone())); return r; }).catch(() => hit);
      return hit || net;
    }));
  }
});

/* myMoney · app Android (Capacitor)
   Porta sul telefono gli stessi download degli script scripts/fetch_*.py: quotazioni, serie di prezzi, 14 ETF principali,
   caratteristiche e composizione (justETF) e catalogo. Il codice nativo (CapacitorHttp) non ha il blocco CORS del browser.
   I file «scritti» sono gli stessi dei workflow (quotes.js, prices.js, catalog.js, data/p/ISIN.js, data/d/ISIN.js) e stanno nella
   cache «mm-data»: la pagina li legge al posto di quelli inclusi nell'app (jsLoad in index.html) e sw.js li serve al caricamento.
   Fuori dall'app questo file non fa nulla. */
(function () {
  const C = window.Capacitor;
  const NATIVE = !!(window.__NATIVE || (C && C.isNativePlatform && C.isNativePlatform()));
  window.NATIVE = NATIVE;
  if (!NATIVE) return;

  const STORE = "mm-data";
  const UA = "Mozilla/5.0 (compatible; myMoney/1.0)";
  const UAB = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36";
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const r4 = x => Math.round(x * 1e4) / 1e4, r2 = x => Math.round(x * 100) / 100;
  const nowIso = () => new Date().toISOString().slice(0, 19) + "+00:00";

  /* ---------- File «scritti» sul telefono ---------- */
  const abs = p => new URL(p, location.href).href;
  const put = async (path, text, type) => { const c = await caches.open(STORE); await c.put(abs(path), new Response(text, { headers: { "Content-Type": type || "text/javascript; charset=utf-8" } })); };
  const read = async path => { try { const m = await caches.match(abs(path), { cacheName: STORE }); return m ? await m.text() : null; } catch { return null; } };
  // una versione nuova dell'app porta dati più recenti di quelli scaricati: si riparte da quelli inclusi
  try {
    const v = (document.getElementById("ver") || {}).textContent || "";
    if (v && localStorage.getItem("mm-native-ver") !== v) { caches.delete(STORE); localStorage.setItem("mm-native-ver", v); }
  } catch {}

  /* ---------- HTTP nativo, con i cookie di sessione che Yahoo e justETF richiedono ---------- */
  const H = () => (window.Capacitor.Plugins && window.Capacitor.Plugins.CapacitorHttp) || window.Capacitor.registerPlugin("CapacitorHttp");
  const jar = {};
  const jarKey = u => new URL(u).hostname.split(".").slice(-2).join(".");
  function eatCookies(u, headers) {
    const k = Object.keys(headers || {}).find(x => x.toLowerCase() === "set-cookie"); if (!k) return;
    const raw = Array.isArray(headers[k]) ? headers[k] : String(headers[k]).split(/,(?=\s*[^;,\s]+=)/);
    const j = (jar[jarKey(u)] = jar[jarKey(u)] || {});
    raw.forEach(c => { const m = /^\s*([^=;\s]+)=([^;]*)/.exec(c); if (m) j[m[1]] = m[2]; });
  }
  async function http(url, o = {}) {
    const headers = { "User-Agent": UA, ...(o.headers || {}) };
    const j = jar[jarKey(url)];
    if (j && Object.keys(j).length && !headers.Cookie) headers.Cookie = Object.entries(j).map(([a, b]) => a + "=" + b).join("; ");
    const r = await H().request({ url, method: o.method || "GET", headers, data: o.data, connectTimeout: 30000, readTimeout: 90000, responseType: "text" });
    eatCookies(url, r.headers);
    if (r.status >= 400 && !o.soft) throw new Error("HTTP " + r.status + " " + new URL(url).hostname);
    return r;
  }
  const body = r => (typeof r.data === "string" ? r.data : JSON.stringify(r.data));
  const getJson = async (url, headers) => JSON.parse(body(await http(url, { headers })));

  /* ---------- Yahoo Finance (come scripts/fetch_prices.py) ---------- */
  const ISINS = { IE00B4L5Y983: "SWDA", IE00BK5BQT80: "VWCE", IE00B5BMR087: "CSPX", IE00BTJRMP35: "XMME", IE00BKM4GZ66: "EIMI", IE00B4K48X80: "IMAE", FR0010010827: "FMI", LU0274209740: "XMJP",
    IE00BYZK4552: "RBOT", IE00B1FZS350: "IWDP", IE00B4WXJJ64: "IEGA", IE00B1FZS798: "IBTM", IE00BDBRDM35: "AGGH", IE00B579F325: "SGLD" };
  const SUFFIXES = [".MI", ".AS", ".PA", ".DE"];
  const EXTRA = { IE00B4L5Y983: ["EUNL.DE"], IE00BKM4GZ66: ["IS3N.DE"], IE00B5BMR087: ["SXR8.DE"], IE00BYZK4552: ["2B76.DE"], IE00B1FZS350: ["IQQ6.DE"], IE00B4WXJJ64: ["EUNH.DE"], IE00B579F325: ["8PSG.DE"], IE00BK5BQT80: ["VWCE.DE"] };
  const Q1 = "https://query1.finance.yahoo.com";

  // errori di Yahoo: ultima chiusura fuori scala (es. barra in yen di LCUJ.DE) → prezzo di mercato; punti isolati che saltano oltre il doppio → eliminati (come clean() in scripts/fetch_prices.py)
  function cleanSeries(t, v, price) {
    t = t.slice(); v = v.slice();
    const n = v.length;
    if (n >= 2 && price > 0 && Math.abs(v[n - 1] / price - 1) > 0.2 && Math.abs(v[n - 2] / price - 1) < 0.2) v[n - 1] = r4(+price);
    for (let i = 1; i < v.length - 1;) { const a = v[i - 1], b = v[i], c = v[i + 1]; if (a > 0 && (b / a > 2 || b / a < 0.5) && c / a >= 0.5 && c / a <= 2) { t.splice(i, 1); v.splice(i, 1); } else i++; }
    const m = v.length; if (m >= 2 && v[m - 2] > 0 && (v[m - 1] / v[m - 2] > 2 || v[m - 1] / v[m - 2] < 0.5)) { t.pop(); v.pop(); }
    return [t, v];
  }

  function parseChart(p) {
    const res = p.chart.result[0], q = res.indicators.quote[0], closes = q.close, vols = q.volume || closes.map(() => null);
    const t = [], v = [], tv = [];
    (res.timestamp || []).forEach((ts, i) => {
      const c = closes[i]; if (c == null) return;
      tv.push(c * (vols[i] || 0) / 1e6);
      const d = new Date(ts * 1000); d.setUTCHours(12, 0, 0, 0);
      t.push(d.getTime()); v.push(r4(+c));
    });
    const m = res.meta, tail = tv.slice(-60), cl = cleanSeries(t, v, m.regularMarketPrice);
    t.length = 0; v.length = 0; t.push(...cl[0]); v.push(...cl[1]);
    return [m.currency || "", t, v, { price: m.regularMarketPrice || v[v.length - 1] || null, time: m.regularMarketTime || null, adv: tail.length ? r2(tail.reduce((a, b) => a + b, 0) / tail.length) : null, name: m.longName || m.shortName || null }];
  }

  let crumb = null;
  async function yahooCrumb() {
    if (crumb) return crumb;
    try { await http("https://fc.yahoo.com", { soft: true }); } catch {} // risponde 404 ma imposta il cookie
    const c = body(await http(Q1 + "/v1/test/getcrumb")).trim();
    if (!c || /[<{\s]/.test(c)) throw new Error("crumb di Yahoo non ottenuto");
    return (crumb = c);
  }
  async function quoteRaw(syms, fields) {
    const out = {}; syms = [...syms];
    for (let i = 0; i < syms.length; i += 40) {
      let j;
      for (let k = 0; k < 2; k++) {
        const c = await yahooCrumb();
        try { j = await getJson(Q1 + "/v7/finance/quote?" + new URLSearchParams({ symbols: syms.slice(i, i + 40).join(","), crumb: c, fields })); break; }
        catch (e) { crumb = null; if (k) throw e; }
      }
      for (const r of j.quoteResponse.result) out[r.symbol] = r;
      await sleep(500);
    }
    return out;
  }
  // bid, ask e orario da Yahoo: in caso di errore, nessun dato
  async function bidAsk(syms) {
    const out = {};
    try {
      const q = await quoteRaw(syms, "bid,ask,bidSize,askSize,regularMarketTime,marketState");
      for (const [s, r] of Object.entries(q)) out[s] = { bid: r.bid && r.bid > 0 ? r.bid : null, ask: r.ask && r.ask > 0 ? r.ask : null, qt: Math.floor(Date.now() / 1000) };
    } catch {}
    return out;
  }
  async function candidates(isin, ticker) {
    const j = await getJson(Q1 + "/v1/finance/search?" + new URLSearchParams({ q: isin, quotesCount: 10, newsCount: 0 }));
    const out = (j.quotes || []).filter(q => ["ETF", "MUTUALFUND", "EQUITY"].includes(q.quoteType) && q.symbol).map(q => q.symbol);
    ticker = ticker || ISINS[isin];
    return [...new Set(out.concat(EXTRA[isin] || [], ticker && /^[A-Za-z0-9]{2,8}$/.test(ticker) ? SUFFIXES.map(s => ticker + s) : []))];
  }
  const chartUrl = (sym, qs) => `${Q1}/v8/finance/chart/${encodeURIComponent(sym)}?${qs}&interval=1d`;
  const maxQs = () => "period1=0&period2=" + Math.floor(Date.now() / 1000);
  async function bestListing(isin, ticker, qs) {
    const found = []; let ref = null;
    for (const sym of await candidates(isin, ticker)) {
      let p; try { p = parseChart(await getJson(chartUrl(sym, qs))); } catch { continue; }
      await sleep(300);
      const key = (p[3].name || "").toLowerCase().split("ucits")[0].trim(); // stesso fondo = stesso nome fino a «UCITS»
      if (ref !== null && key !== ref) continue;
      if (p[1].length >= 50) { if (ref === null) ref = key; found.push([sym, p[0], p[1], p[2], p[3]]); if (p[0] === "EUR") break; }
    }
    return found;
  }

  /* ---------- quotes.js: ultimo prezzo, orario, bid e ask in EUR di tutti gli ETF con simbolo ---------- */
  async function readSymbols() { const s = await read("data/symbols.json"); if (s) return JSON.parse(s); try { return await (await fetch("data/symbols.json")).json(); } catch { return {}; } }
  async function readAdv() { const s = await read("data/adv.json"); return s ? JSON.parse(s) : {}; }
  async function doQuotes() {
    const sy = {};
    const PR = (window.PRICES && window.PRICES.series) || {};
    for (const [i, v] of Object.entries(PR)) sy[i] = v.symbol;
    for (const [i, v] of Object.entries(await readSymbols())) if (v.symbol && !sy[i]) sy[i] = v.symbol;
    const adv = { ...Object.fromEntries(Object.entries((window.QUOTES && window.QUOTES.q) || {}).filter(([, v]) => v.adv).map(([i, v]) => [i, v.adv])), ...(await readAdv()) };
    for (const [i, v] of Object.entries(PR)) if (v.adv) adv[i] = v.adv;
    const q = await quoteRaw(new Set(Object.values(sy)), "bid,ask,currency,regularMarketPrice,regularMarketTime");
    const cur = new Set(Object.values(q).map(r => r.currency).filter(c => c && c !== "EUR"));
    const fxs = cur.size ? await quoteRaw([...cur].map(c => `EUR${c === "GBp" ? "GBP" : c}=X`), "bid,ask,currency,regularMarketPrice,regularMarketTime") : {};
    const out = {};
    for (const [isin, sym] of Object.entries(sy)) {
      const r = q[sym]; if (!r) continue;
      let div = 1;
      if (r.currency && r.currency !== "EUR") {
        const rate = (fxs[`EUR${r.currency === "GBp" ? "GBP" : r.currency}=X`] || {}).regularMarketPrice;
        if (!rate) continue;
        div = rate / (r.currency === "GBp" ? 0.01 : 1);
      }
      const b = r.bid, a = r.ask, p = r.regularMarketPrice; if (!p) continue;
      const e = { sym, p: r4(p / div), pt: r.regularMarketTime || null };
      if (b && a && a > b && Math.abs((a + b) / 2 / p - 1) <= 0.03) { e.bid = r4(b / div); e.ask = r4(a / div); } // bid/ask lontani dal prezzo sono vecchi (mercato chiuso)
      if (adv[isin]) e.adv = adv[isin];
      out[isin] = e;
    }
    if (!Object.keys(out).length) throw new Error("Quotazioni non disponibili");
    await put("quotes.js", "window.QUOTES=" + JSON.stringify({ generated: nowIso(), q: out }) + ";\n");
    return [`prezzi per ${Object.keys(out).length} ETF su ${Object.keys(sy).length}`];
  }

  /* ---------- prices.js: i 14 ETF principali con la cronologia (10 anni) ---------- */
  async function doPrices() {
    const out = {}, PR = (window.PRICES && window.PRICES.series) || {};
    for (const [isin, ticker] of Object.entries(ISINS)) {
      try {
        let pick = null;
        const known = PR[isin] && PR[isin].symbol; // il simbolo già scelto evita la ricerca
        if (known) { try { const p = parseChart(await getJson(chartUrl(known, "range=10y"))); if (p[1].length >= 50) pick = [known, p[0], p[1], p[2], p[3]]; } catch {} await sleep(300); }
        if (!pick) { const f = await bestListing(isin, undefined, "range=10y"); pick = f.find(x => x[1] === "EUR") || f[0]; }
        if (!pick) continue;
        const [sym, cur, t, v, last] = pick;
        out[isin] = { symbol: sym, currency: cur, source: `https://finance.yahoo.com/quote/${encodeURIComponent(sym)}/history`, name: last.name, adv: last.adv, last: { price: last.price, time: last.time }, t, v };
      } catch {}
      await sleep(500);
    }
    if (!Object.keys(out).length) throw new Error("Nessun prezzo scaricato");
    const q = await bidAsk(Object.values(out).map(s => s.symbol));
    for (const s of Object.values(out)) Object.assign(s.last, q[s.symbol] || {});
    await put("prices.js", "window.PRICES=" + JSON.stringify({ generated: nowIso(), series: out }) + ";\n");
    return [`${Object.keys(out).length} ETF su ${Object.keys(ISINS).length}`];
  }

  /* ---------- data/p/ISIN.js: 5 anni di prezzi giornalieri, convertiti in EUR (come scripts/fetch_series.py) ---------- */
  const FX = {};
  async function toEur(cur, t, v) {
    if (cur === "EUR") return [t, v, null];
    const [scale, base] = cur === "GBp" ? [0.01, "GBP"] : [1, cur];
    if (base === "EUR") return [t, v.map(x => r4(x * scale)), null];
    if (!FX[base]) { const p = parseChart(await getJson(chartUrl(`EUR${base}=X`, maxQs()))); FX[base] = [p[1], p[2]]; await sleep(300); }
    const [ft, fv] = FX[base], out = []; let j = 0;
    for (let n = 0; n < t.length; n++) { while (j + 1 < ft.length && ft[j + 1] <= t[n]) j++; out.push(r4(v[n] * scale / fv[j])); }
    return [t, out, base];
  }
  const catInfo = isin => { const C = window.CATALOG; if (!C || !C.rows) return {}; const ix = C.cols.indexOf("isin"), r = C.rows.find(x => x[ix] === isin); return r ? { ticker: r[C.cols.indexOf("ticker")], name: r[C.cols.indexOf("name")] } : {}; };
  async function doSeries(isins) {
    const syms = await readSymbols(), advs = await readAdv(), batch = {}; let ok = 0;
    const flush = async () => {
      const ents = Object.entries(batch); if (!ents.length) return;
      const q = await bidAsk(ents.map(([, b]) => b[0]));
      for (const [i, [sym, c, nm, t, v, last, orig, cur0]] of ents) {
        const qq = { ...(q[sym] || {}) };
        if (orig && Object.keys(qq).length) { const div = FX[orig][1][FX[orig][1].length - 1] / (cur0 === "GBp" ? 0.01 : 1); for (const k of ["bid", "ask"]) qq[k] = qq[k] ? r4(qq[k] / div) : null; }
        else if (cur0 === "GBp" && Object.keys(qq).length) for (const k of ["bid", "ask"]) qq[k] = qq[k] ? r4(qq[k] * 0.01) : null;
        const days = t.map(x => Math.floor(x / 86400000));
        const o = { symbol: sym, currency: c, fx: orig, name: nm, source: `https://finance.yahoo.com/quote/${encodeURIComponent(sym)}/history`, adv: last.adv == null ? null : last.adv, ...(Object.keys(qq).length ? qq : {}), d: days, v };
        await put(`data/p/${i}.js`, `window.PX=window.PX||{};window.PX["${i}"]=` + JSON.stringify(o) + ";\n");
        if (last.adv) advs[i] = last.adv;
      }
      for (const k of Object.keys(batch)) delete batch[k];
      await put("data/symbols.json", JSON.stringify(syms), "application/json"); await put("data/adv.json", JSON.stringify(advs), "application/json");
    };
    const log = [];
    for (const isin of isins.filter(i => !ISINS[i])) {
      try {
        const known = syms[isin]; let sym, cur, t, v, last;
        if (known && known.symbol) {
          [cur, t, v, last] = parseChart(await getJson(chartUrl(known.symbol, maxQs()))); sym = known.symbol;
          if (t.length < 50) throw new Error("pochi dati");
        } else {
          const tk = catInfo(isin).ticker, found = await bestListing(isin, tk === "-" || tk === isin ? undefined : tk, maxQs());
          if (!found.length) { syms[isin] = { symbol: null, failed: Math.floor(Date.now() / 1000) }; log.push(isin + ": nessuna quotazione"); continue; }
          [sym, cur, t, v, last] = found.find(f => f[1] === "EUR") || found[0]; syms[isin] = { symbol: sym };
        }
        const [t2, v2, orig] = await toEur(cur, t, v);
        batch[isin] = [sym, "EUR", last.name, t2, v2, last, orig, cur]; ok++;
        if (Object.keys(batch).length >= 25) await flush();
      } catch (e) { log.push(isin + ": " + (e.message || e)); }
      await sleep(400);
    }
    await flush();
    if (!ok) throw new Error(log[0] || "Nessuna serie scaricata");
    return [`${ok} serie scritte`, ...log];
  }

  /* ---------- data/d/ISIN.js: indice, titoli principali, paesi e settori da justETF (come scripts/fetch_etf_data.py) ---------- */
  const decode = s => { const t = document.createElement("textarea"); t.innerHTML = s; return t.value; };
  const clean = s => decode(String(s).replace(/<[^>]+>/g, " ")).replace(/\s+/g, " ").trim();
  const reEsc = s => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const tid = (h, name) => { const m = new RegExp(`data-testid="${reEsc(name)}"[^>]*>([\\s\\S]*?)</`).exec(h); return m ? clean(m[1]) : null; };
  function num(s, dec) {
    const m = /-?\d[\d.,]*/.exec(s || ""); if (!m) return null;
    const x = parseFloat(dec === "." ? m[0].replace(/,/g, "") : m[0].replace(/\./g, "").replace(",", "."));
    return isNaN(x) ? null : x;
  }
  function rowsOf(h, table, nameId, pctId, dec) {
    const out = [], seen = new Set();
    for (const block of h.match(new RegExp(`data-testid="${reEsc(table)}"[\\s\\S]*?</tr>`, "g")) || []) {
      const n = tid(block, nameId), p = num(tid(block, pctId), dec);
      if (n && p !== null && !seen.has(n)) { seen.add(n); out.push([n, Math.round(p * 100) / 100]); }
    }
    return out;
  }
  function topN(lst, k = 5) { const head = lst.slice(0, k), rest = Math.round((100 - head.reduce((a, x) => a + x[1], 0)) * 10) / 10; return rest >= 0.5 && lst.length > k ? head.concat([["Altri", rest]]) : head; }
  const jePage = async (isin, lang) => { const url = `https://www.justetf.com/${lang}/etf-profile.html?isin=${isin}`; return [body(await http(url, { headers: { "User-Agent": UAB, "Accept-Language": lang } })), url]; };
  async function parseInfo(isin) {
    const out = {}, [h, url] = await jePage(isin, "en");
    const idx = tid(h, "tl_etf-basics_value_index-name"); if (idx) out.index = idx.replace("®", "").trim();
    const n = num(tid(h, "tl_etf-holdings_top-holdings_count")); if (n) out.n = Math.trunc(n);
    const top = rowsOf(h, "etf-holdings_top-holdings_row", "tl_etf-holdings_top-holdings_link_name", "tl_etf-holdings_top-holdings_value_percentage", "."); if (top.length) out.top = top.slice(0, 10);
    const hd = /\d{2}\/\d{2}\/\d{4}/.exec(tid(h, "tl_etf-holdings_reference-date") || ""); if (hd) out.holdingsDate = hd[0];
    out.source = url;
    await sleep(1000);
    const [hi] = await jePage(isin, "it");
    const countries = rowsOf(hi, "etf-holdings_countries_row", "tl_etf-holdings_countries_value_name", "tl_etf-holdings_countries_value_percentage", ",");
    const sectors = rowsOf(hi, "etf-holdings_sectors_row", "tl_etf-holdings_sectors_value_name", "tl_etf-holdings_sectors_value_percentage", ",");
    if (countries.length) out.countries = topN(countries);
    if (sectors.length) out.sectors = topN(sectors);
    return out;
  }
  async function doInfo(isins) {
    const log = []; let ok = 0;
    for (const isin of isins.filter(i => !ISINS[i])) {
      try {
        const d = await parseInfo(isin);
        if (!["index", "top", "countries", "sectors"].some(k => k in d)) { log.push(isin + ": nessun dato"); continue; }
        await put(`data/d/${isin}.js`, `window.DX=window.DX||{};window.DX["${isin}"]=` + JSON.stringify(d) + ";\n"); ok++;
      } catch (e) { log.push(isin + ": " + (e.message || e)); }
      await sleep(1500);
    }
    if (!ok) throw new Error(log[0] || "Nessun dato scaricato");
    return [`${ok} schede`, ...log];
  }

  /* ---------- catalog.js: tutti gli ETF dallo screener di justETF (come scripts/fetch_catalog.py) ---------- */
  const PAGE = "https://www.justetf.com/en/search.html?search=ETFS";
  const CALL = "https://www.justetf.com/en/search.html?0-1.0-container-tabsContentContainer-tabsContentRepeater-1-container-content-etfsTablePanel&search=ETFS&_wicket=1";
  const COLS = [["", "selectCheckbox"], ["name", "name"], ["", "sparkline"], ["fundCurrency", "fundCurrency"], ["fundSize", "fundSize"], ["ter", "ter"], ["", "bullet"], ["weekReturnCUR", "weekReturn"], ["monthReturnCUR", "monthReturn"], ["threeMonthReturnCUR", "threeMonthReturn"], ["sixMonthReturnCUR", "sixMonthReturn"], ["yearReturnCUR", "yearReturn"], ["threeYearReturnCUR", "threeYearReturn"], ["fiveYearReturnCUR", "fiveYearReturn"], ["ytdReturnCUR", "ytdReturn"], ["yearReturn1CUR", "yearReturn1"], ["yearReturn2CUR", "yearReturn2"], ["yearReturn3CUR", "yearReturn3"], ["yearReturn4CUR", "yearReturn4"], ["yearVolatilityCUR", "yearVolatility"], ["threeYearVolatilityCUR", "threeYearVolatility"], ["fiveYearVolatilityCUR", "fiveYearVolatility"], ["yearReturnPerRiskCUR", "yearReturnPerRisk"], ["threeYearReturnPerRiskCUR", "threeYearReturnPerRisk"], ["fiveYearReturnPerRiskCUR", "fiveYearReturnPerRisk"], ["yearMaxDrawdownCUR", "yearMaxDrawdown"], ["threeYearMaxDrawdownCUR", "threeYearMaxDrawdown"], ["fiveYearMaxDrawdownCUR", "fiveYearMaxDrawdown"], ["maxDrawdownCUR", "maxDrawdown"], ["inceptionDate", "inceptionDate"], ["distributionPolicy", "distributionPolicy"], ["sustainable", "sustainable"], ["numberOfHoldings", "numberOfHoldings"], ["currentDividendYield", "currentDividendYield"], ["yearDividendYield", "yearDividendYield"], ["domicileCountry", "domicileCountry"], ["replicationMethod", "replicationMethod"], ["savingsPlanReady", "savingsPlanReady"], ["hasSecuritiesLending", "hasSecuritiesLending"], ["isin", "isin"], ["ticker", "ticker"], ["wkn", "wkn"], ["valorNumber", "valorNumber"], ["", "addButton"]];
  const ASSET = { "class-equity": "Azionario", "class-bonds": "Obbligazionario", "class-commodities": "Materie prime", "class-preciousMetals": "Materie prime", "class-realEstate": "Immobiliare", "class-moneyMarket": "Monetario" };
  const REGION = { World: "Globale", Europe: "Europa", "North America": "Nord America", "Emerging Markets": "Mercati emergenti", "Asia Pacific": "Asia-Pacifico", "Latin America": "America Latina", Africa: "Africa" };
  const COUNTRY = { Ireland: "Irlanda", Luxembourg: "Lussemburgo", France: "Francia", Germany: "Germania", Switzerland: "Svizzera", Netherlands: "Paesi Bassi", "United Kingdom": "Regno Unito", Sweden: "Svezia", Italy: "Italia", Spain: "Spagna", Denmark: "Danimarca", Finland: "Finlandia", Belgium: "Belgio", Norway: "Norvegia", Austria: "Austria", Jersey: "Jersey", Liechtenstein: "Liechtenstein", "Cayman Islands": "Isole Cayman", Canada: "Canada", "United States": "Stati Uniti", Poland: "Polonia", Hungary: "Ungheria", Greece: "Grecia", Portugal: "Portogallo" };
  const PROVIDERS2 = ["Global X", "Legal & General", "State Street", "BNP Paribas", "Goldman Sachs", "First Trust", "Franklin Templeton", "Morgan Stanley", "Bank of America", "Royal London", "Vontobel", "Tabula", "Man", "BlackRock", "SPDR", "Source", "UBS", "Credit Suisse", "Deutsche Bank", "Lyxor", "Amundi", "Xtrackers", "HANetf", "WisdomTree", "VanEck", "Invesco", "iShares", "Vanguard", "HSBC", "JPMorgan", "Fidelity", "Ossiam", "Expat", "Deka", "Comstage", "Leverage Shares", "GraniteShares"];
  const GUESS = [["Stati Uniti", /S&P ?(500|400|600)|nasdaq|\bUSA?\b|U\.S\.|United States|russell|dow jones|treasur|\bTIPS\b|\$/i], ["Giappone", /japan|nikkei|topix|\bJPX\b/i], ["Cina", /china|CSI ?300|hang seng|chinese/i], ["India", /\bindia|nifty/i], ["Regno Unito", /FTSE ?(100|250)\b|\bUK\b|united kingdom|\bgilt|sterling/i], ["Germania", /\bDAX\b|germany|MDAX|bund/i], ["Svizzera", /swiss|switzerland|\bSMI\b|\bSPI\b/i], ["Eurozona", /euro ?stoxx|eurozone|\bEMU\b|euro area|euro (govt|gov|corp|aggregate|inflation|high)|EUR (govt|gov|corp)|€/i], ["Italia", /italy|italian|\bMIB\b|\bBTP\b/i], ["Francia", /france|\bCAC\b|\bOAT\b/i], ["Spagna", /spain|\bIBEX\b/i], ["Corea del Sud", /korea/i], ["Taiwan", /taiwan/i], ["Brasile", /brazil/i], ["Canada", /canad/i], ["Australia", /australia/i], ["Europa", /europe|stoxx|\bEU\b/i], ["Mercati emergenti", /emerging|\bEM\b/i], ["Asia-Pacifico", /asia|pacific|apac/i], ["Globale", /world|global|all[- ]country|\bACWI\b|international|developed/i]];
  const guessRegion = name => { for (const [label, rx] of GUESS) if (rx.test(name)) return label; return null; };
  const fnum = s => { if (s == null) return null; const m = /-?\d[\d,]*\.?\d*/.exec(String(s)); if (!m) return null; const x = parseFloat(m[0].replace(/,/g, "")); return isNaN(x) ? null : x; };
  const jdate = s => { const m = /^(\d{2})\.(\d{2})\.(\d{2,4})$/.exec(String(s || "")); if (!m) return null; let y = +m[3]; if (y < 100) y += y < 70 ? 2000 : 1900; return `${y}-${m[2]}-${m[1]}`; };
  const provider = name => { for (const p of PROVIDERS2) if (name.toLowerCase().startsWith(p.toLowerCase())) return p; return name ? name.split(/\s+/)[0] : null; };
  const replOf = s => { s = (s || "").toLowerCase(); return /swap|synth/.test(s) ? "Sintetica" : s.includes("sampl") ? "Fisica a campione" : s.includes("full") ? "Fisica completa" : s ? "Fisica" : null; };
  async function jePost(start, length, params) {
    const q = { draw: "1" };
    COLS.forEach(([d, n], i) => { q[`columns[${i}][data]`] = d; q[`columns[${i}][name]`] = n; q[`columns[${i}][searchable]`] = "true"; q[`columns[${i}][orderable]`] = d ? "true" : "false"; q[`columns[${i}][search][value]`] = ""; q[`columns[${i}][search][regex]`] = "false"; });
    Object.assign(q, { "order[0][column]": "4", "order[0][dir]": "desc", start: String(start), length: String(length), "search[value]": "", "search[regex]": "false", ajaxsortOrder: "desc", ajaxsortField: "fundSize", lang: "en", country: "XE", defaultCurrency: "EUR", universeType: "private", etfsParams: params });
    for (let k = 0; k < 3; k++) {
      try {
        return JSON.parse(body(await http(CALL, { method: "POST", data: q, headers: { "User-Agent": UAB, "Accept-Language": "en-GB", "X-Requested-With": "XMLHttpRequest", Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", Referer: PAGE, "Wicket-Ajax": "true", "Wicket-Ajax-BaseURL": "en/search.html?search=ETFS" } })));
      } catch (e) { if (k === 2) throw e; await sleep(5000); }
    }
  }
  async function jeAll(params, step = 500) {
    const out = []; let start = 0, total = null;
    while (total === null || start < total) { const j = await jePost(start, step, params); total = j.recordsFiltered; out.push(...j.data); start += step; await sleep(1000); }
    return [out, total];
  }
  async function doCatalog() {
    await http(PAGE, { headers: { "User-Agent": UAB, "Accept-Language": "en-GB" } }); // cookie di sessione
    const [rows, total] = await jeAll("search=ETFS&query=");
    if (rows.length < 1000) throw new Error("Elenco troppo corto: catalogo non aggiornato");
    const asset = {}, region = {};
    for (const [key, label] of Object.entries(ASSET)) { const [r, n] = await jeAll(`search=ETFS&query=&assetClass=${key}`); if (n < total) r.forEach(x => (asset[x.isin] = label)); }
    for (const [key, label] of Object.entries(REGION)) { const [r, n] = await jeAll(`search=ETFS&query=&region=${encodeURIComponent(key)}`); if (n < total) r.forEach(x => { if (!(x.isin in region)) region[x.isin] = label; }); }
    const cols = ["isin", "name", "ticker", "cur", "aum", "ter", "dist", "repl", "dom", "inc", "n", "sust", "div", "rw", "r1m", "r3m", "r6m", "r1", "r3", "r5", "ytd", "vol1", "vol3", "vol5", "dd1", "dd", "sh1", "prov", "asset", "region"];
    const out = [], seen = new Set(), crypto = /bitcoin|crypto|ether|solana|\bXRP\b|blockchain|digital asset/i;
    for (const x of rows) {
      const isin = x.isin; if (!isin || seen.has(isin)) continue; seen.add(isin);
      const name = x.name || "", pol = x.distributionPolicy || "", nh = fnum(x.numberOfHoldings);
      out.push([isin, name, x.ticker || null, x.fundCurrency || null, fnum(x.fundSize), fnum(x.ter), /accum|capital/i.test(pol) ? "Accumulazione" : /distrib/i.test(pol) ? "Distribuzione" : null, replOf(x.replicationMethod), COUNTRY[x.domicileCountry] || x.domicileCountry || null, jdate(x.inceptionDate), nh ? Math.trunc(nh) : null, x.sustainable === "Yes", fnum(x.currentDividendYield),
        fnum(x.weekReturnCUR), fnum(x.monthReturnCUR), fnum(x.threeMonthReturnCUR), fnum(x.sixMonthReturnCUR), fnum(x.yearReturnCUR), fnum(x.threeYearReturnCUR), fnum(x.fiveYearReturnCUR), fnum(x.ytdReturnCUR), fnum(x.yearVolatilityCUR), fnum(x.threeYearVolatilityCUR), fnum(x.fiveYearVolatilityCUR), fnum(x.yearMaxDrawdownCUR), fnum(x.maxDrawdownCUR), fnum(x.yearReturnPerRiskCUR), provider(name),
        asset[isin] || (crypto.test(name) ? "Criptovalute" : "Altro"), region[isin] || guessRegion(name) || (["Materie prime", "Monetario"].includes(asset[isin]) || /bitcoin|crypto|ether|solana|\bXRP\b|digital asset/i.test(name) ? "Globale" : "Altro")]);
    }
    await put("catalog.js", "window.CATALOG=" + JSON.stringify({ generated: nowIso(), source: "justETF", cols, rows: out }) + ";\n");
    return [`${out.length} ETF`];
  }

  /* ---------- Interfaccia usata dalla pagina al posto del server locale (localApi) ---------- */
  const KINDS = { quotes: () => doQuotes(), prices: () => doPrices(), series: i => doSeries(i), info: i => doInfo(i), catalog: () => doCatalog() };
  let chain = Promise.resolve();
  window.nativeApi = (kind, isins) => {
    const run = chain.then(async () => {
      const t0 = Date.now();
      try { if (!KINDS[kind]) throw new Error("tipo sconosciuto"); const log = await KINDS[kind]((isins || []).filter(i => /^[A-Z]{2}[A-Z0-9]{9}\d$/.test(i))); return { ok: true, seconds: Math.round((Date.now() - t0) / 100) / 10, log }; }
      catch (e) { return { ok: false, error: String((e && e.message) || e), seconds: Math.round((Date.now() - t0) / 100) / 10 }; }
    });
    chain = run;
    return run;
  };
})();

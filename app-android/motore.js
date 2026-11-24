/* motore.js — il programma Python (build.py + fonti.py) riscritto per girare dentro l'app Android.
   Fa le stesse cose del server locale: elenco e salvataggio dei portafogli (nella memoria dell'app), scarico da justETF, scheda dei titoli,
   costruzione dei dati della pagina. La pagina continua a chiamare /api/...: qui le richieste vengono intercettate e risolte in locale.
   Le chiamate verso justETF passano da fetch, che in Capacitor (CapacitorHttp) è nativo e quindi senza limiti CORS. */
(function () {
  "use strict";
  const SEED = window.SEED_APP || { portafogli: {}, titoli: {}, tab: {} };
  const T = SEED.tab;
  const LS = window.localStorage;
  const FETCH = window.fetch.bind(window);
  const PROFILO = "https://www.justetf.com/en/etf-profile.html?isin=";
  const GRAFICO = (isin, dal, al) => `https://www.justetf.com/api/etfs/${isin}/performance-chart?locale=en&currency=EUR&valuesType=MARKET_VALUE&reduceData=false&includeDividends=false&features=DIVIDENDS&dateFrom=${dal}&dateTo=${al}`;
  const FONTE = "justETF";
  const CLASSI = ["Azionario", "Obbligazionario", "Materie prime"];
  const NOME_PF = /^[A-Za-z0-9]{1,30}$/, FILE_PF = /^[A-Za-z0-9]{1,30}_V[0-9]{1,3}\.json$/, ISIN_RE = /^[A-Z]{2}[A-Z0-9]{9}[0-9]$/;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const oggi = () => { const d = new Date(); return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"); };
  const sommaGiorni = (iso, n) => { const d = new Date(iso + "T12:00:00Z"); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
  const feriale = (iso) => { const g = new Date(iso + "T12:00:00Z").getUTCDay(); return g >= 1 && g <= 5; };
  const r4 = (x) => Math.round(x * 1e4) / 1e4;
  const sum = (a) => a.reduce((s, x) => s + x, 0);
  const Err = (m) => Object.assign(new Error(m), { utente: true });

  // ---- memoria dell'app (localStorage)
  const leggiLS = (k) => { try { const v = LS.getItem(k); return v ? JSON.parse(v) : null; } catch (e) { return null; } };
  const scriviLS = (k, v) => { try { LS.setItem(k, JSON.stringify(v)); return true; } catch (e) { return false; } };
  if (!LS.getItem("mm:init")) {  // prima apertura: i portafogli e le schede note che vengono con l'app
    Object.entries(SEED.portafogli).forEach(([f, d]) => scriviLS("mm:pf:" + f, d));
    LS.setItem("mm:init", "1");
  }
  const files = () => Object.keys(LS).filter((k) => k.startsWith("mm:pf:")).map((k) => k.slice(6)).filter((f) => FILE_PF.test(f));
  const definizione = (f) => (typeof f === "string" && f.startsWith("bozza:") ? (/^[\w-]{4,32}$/.test(f.slice(6)) ? leggiLS("mm:bozza:" + f.slice(6)) : null) : FILE_PF.test(f || "") ? leggiLS("mm:pf:" + f) : null);  // «bozza:TOKEN»: titoli cambiati, non ancora salvati
  const numVers = (v) => { const m = /^V(\d+)$/.exec(String(v)); return m ? +m[1] : 0; };
  const info = (f) => {
    const d = definizione(f); if (!d || !Array.isArray(d.titoli)) return null;
    const m = /^([A-Za-z0-9]+)_V(\d+)\.json$/.exec(f);
    return { file: f, nome: d.nome || m[1], versione: "V" + String(d.versione || m[2]).replace(/^[Vv]/, ""), descrizione: d.descrizione || "" };
  };
  const elenco = () => files().map(info).filter(Boolean).sort((a, b) => (a.nome.toLowerCase() < b.nome.toLowerCase() ? -1 : a.nome.toLowerCase() > b.nome.toLowerCase() ? 1 : numVers(a.versione) - numVers(b.versione)));
  const ultimo = () => { const u = LS.getItem("mm:ultimo"); if (u && info(u)) return u; const e = elenco(); return e.length ? e[e.length - 1].file : null; };
  const segna = (f) => LS.setItem("mm:ultimo", f);

  // ---- cartella dei portafogli scelta con il selettore di Android (memoria del telefono o Google Drive); la memoria dell'app resta la copia di lavoro
  const plug = (n) => { const C = window.Capacitor; if (!C || !(C.isNativePlatform ? C.isNativePlatform() : true)) return null; try { return (C.Plugins && C.Plugins[n]) || (C.registerPlugin && C.registerPlugin(n)) || null; } catch (e) { return null; } };
  const cartellaAttiva = () => leggiLS("mm:cartella");
  function formatta(d) {  // come formatta_definizione di build.py: un titolo per riga
    const j = (x) => JSON.stringify(x), r = [], tutto = { $schema: "schema.json", ...Object.fromEntries(Object.entries(d).filter(([k]) => k !== "$schema")) };
    Object.entries(tutto).forEach(([k, v]) => {
      if (k === "titoli" || k === "transazioni" || k === "obiettivo") r.push("  " + j(k) + ": [\n" + v.map((x) => "    " + j(x)).join(",\n") + "\n  ]");
      else if (k === "vincoli") r.push('  "vincoli": {\n' + Object.entries(v).map(([kk, vv]) => "    " + j(kk) + ": {" + (Object.keys(vv).length ? "\n" + Object.entries(vv).map(([a, c]) => "      " + j(a) + ": " + j(c)).join(",\n") + "\n    }" : "}")).join(",\n") + "\n  }");
      else r.push("  " + j(k) + ": " + j(v));
    });
    return "{\n" + r.join(",\n") + "\n}\n";
  }
  let ultimoSpecchio = null;
  function rispecchia(op) {  // ciò che cambia nella memoria dell'app si riflette nella cartella scelta
    const F = cartellaAttiva() && plug("MyMoneyFolder"); if (!F) return;
    ultimoSpecchio = F.apply(op).then(() => null, (e) => e || new Error("errore sconosciuto"));
  }
  async function specchioOk() {  // attende la scrittura nella cartella; se non riesce lo dice (il portafoglio resta nell'app e al prossimo avvio viene riportato nella cartella)
    const p = ultimoSpecchio; ultimoSpecchio = null; if (!p) return;
    const e = await p; if (!e) return;
    const c = cartellaAttiva();
    throw Err("Salvato nell'app, ma NON nella cartella" + (c ? " «" + c.label + "»" : "") + ": " + (e.message || e) + ". Resta nell'app: riapri l'app per riprovare a scriverlo nella cartella.");
  }
  const scriviFile = (f) => ({ name: f, text: formatta(definizione(f)) });
  async function sincronizza() {  // all'avvio: i portafogli della cartella diventano quelli dell'app; una cartella vuota riceve quelli dell'app
    const F = plug("MyMoneyFolder"); if (!F) return;
    let i; try { i = await F.info(); } catch (e) { return; }
    if (!i || !i.uri) { LS.removeItem("mm:cartella"); return; }
    scriviLS("mm:cartella", { label: i.label || "cartella" });
    let l; try { l = await F.list(); } catch (e) { return; }  // cartella non raggiungibile: restano i portafogli già nell'app
    const nella = (l.files || []).filter((f) => FILE_PF.test(f.name));
    if (!nella.length) { try { await F.apply({ write: [...files().map(scriviFile), { name: "schema.json", text: SEED.schema || "{}" }] }); } catch (e) {} return; }
    const inCartella = new Set(nella.map((f) => f.name)), soloApp = files().filter((f) => !inCartella.has(f));  // creati nell'app e non ancora arrivati nella cartella: non vanno persi
    files().filter((f) => inCartella.has(f)).forEach((f) => LS.removeItem("mm:pf:" + f));
    nella.forEach((f) => { try { const d = JSON.parse(f.text); if (d && Array.isArray(d.titoli)) { delete d.$schema; scriviLS("mm:pf:" + f.name, d); } } catch (e) {} });
    if (soloApp.length) { try { await F.apply({ write: soloApp.map(scriviFile) }); } catch (e) { console.error("portafogli non scritti nella cartella:", e && e.message); } }
  }
  async function cartellaApi(r) {  // risposta di /api/cartella
    const F = plug("MyMoneyFolder"); if (!F) return null;
    if (r && r.azione) {
      if (r.azione === "reset") { try { await F.forget(); } catch (e) {} LS.removeItem("mm:cartella"); }
      else { let i = {}; try { i = await F.pick({ drive: r.azione === "drive" }); } catch (e) { throw Err("Selezione della cartella non riuscita: " + (e && e.message)); } if (i && i.uri) await sincronizza(); }
    }
    const c = cartellaAttiva();
    return { cartella: c ? c.label : "memoria dell'app", predefinita: "memoria dell'app", personalizzata: !!c, nativo: true, ultimo: ultimo(), lista: elenco() };
  }

  // ---- rete
  async function scarica(url, json) {
    let ultimoErr = null;
    for (let k = 0; k < 4; k++) {
      try {
        const r = await FETCH(url, { headers: { "Accept-Language": "en-GB" } });
        if (r.status === 404) throw Object.assign(new Error("titolo non trovato su justETF"), { fatale: true });
        if (!r.ok) throw new Error("HTTP " + r.status);
        return json ? await r.json() : await r.text();
      } catch (e) { if (e.fatale) throw e; ultimoErr = e; }
      await sleep(1500 * (k + 1));
    }
    throw new Error("justETF non risponde (" + (ultimoErr && ultimoErr.message) + ")");
  }
  function isinValido(s) {
    if (typeof s !== "string" || !ISIN_RE.test(s)) return false;
    const cifre = [...s].map((c) => parseInt(c, 36)).join(""); let tot = 0;
    [...cifre].reverse().forEach((c, i) => { let d = +c; if (i % 2 === 1) { d *= 2; if (d > 9) d -= 9; } tot += d; });
    return tot % 10 === 0;
  }
  async function serie(isin, dal) {
    const j = await scarica(GRAFICO(isin, dal || sommaGiorni(oggi(), -(365 * 10 + 3)), oggi()), true), out = [];
    ((j && j.series) || []).forEach((x) => { const v = x.value && x.value.raw; if (v && feriale(x.date)) out.push([x.date, Math.round(parseFloat(v) * 1e4) / 1e4]); });
    if (!out.length) throw new Error(isin + ": nessun prezzo su justETF");
    return out;
  }

  // ---- pagina del fondo di justETF -> record del fondo (stessa logica di fonti.py)
  const unescapeHtml = (s) => { const t = document.createElement("textarea"); t.innerHTML = s; return t.value; };
  const testo = (s) => unescapeHtml((s || "").replace(/<[^>]+>/g, " ")).replace(/\s+/g, " ").trim();
  const campo = (t, id) => { const m = new RegExp('data-testid="' + id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + '"[^>]*>([\\s\\S]*?)</').exec(t); return m ? testo(m[1]) : ""; };
  const num = (s) => { const m = /-?\d[\d,]*\.?\d*/.exec(s || ""); if (!m) return null; const x = parseFloat(m[0].replace(/,/g, "")); return isNaN(x) ? null : x; };
  const dataIt = (s) => { const m = /^(\d{1,2}) (\w+) (\d{4})/.exec(s || ""); return m && T.MESI[m[2]] ? m[3] + "-" + String(T.MESI[m[2]]).padStart(2, "0") + "-" + String(+m[1]).padStart(2, "0") : null; };
  function righe(t, pref) {
    const out = [], re = new RegExp('<tr data-testid="etf-holdings_' + pref + '_row">([\\s\\S]*?)</tr>', "g"); let b;
    while ((b = re.exec(t))) {
      const blocco = b[1], peso = num(campo(blocco, "tl_etf-holdings_" + pref + "_value_percentage"));
      let nome = campo(blocco, "tl_etf-holdings_" + pref + "_value_name"), isin = null;
      if (!nome) { const m = /href="([^"]*)"[^>]*title="([^"]*)"/.exec(blocco); if (m) { nome = unescapeHtml(m[2]); const mi = /\/([A-Z]{2}[A-Z0-9]{9}\d)(?:[/?]|$)/.exec(m[1]); isin = mi ? mi[1] : null; } }
      if (nome && peso !== null) out.push([nome, peso / 100, isin]);
    }
    return out;
  }
  function parseProfilo(t, isin) {
    let nome = campo(t, "etf-profile-header_etf-name"); if (!nome) { const h = /<h1[^>]*>([\s\S]*?)<\/h1>/.exec(t); nome = h ? testo(h[1]) : ""; }
    if (!nome) throw new Error(isin + ": pagina del fondo non riconosciuta");
    let repl = campo(t, "tl_etf-basics_value_replication-method") || campo(t, "tl_etf-basics_value_replication"); const r = repl.toLowerCase();
    repl = /swap|synth/.test(r) ? "Sintetica" : r.includes("sampl") ? "Fisica a campione" : r.includes("full") ? "Fisica completa" : r.includes("phys") ? "Fisica" : (repl || null);
    return { isin, name: nome, ticker: campo(t, "etf-profile-header_identifier-button-ticker") || null, ter: num(campo(t, "tl_etf-basics_value_ter")), aum: num(campo(t, "etf-profile-header_fund-size-value-wrapper")),
      focus: campo(t, "tl_etf-basics_value_investment-focus"), repl, dom: campo(t, "tl_etf-basics_value_domicile-country") || null, emittente: campo(t, "tl_etf-basics_value_fund-provider") || null,
      lancio: dataIt(campo(t, "tl_etf-basics_value_launch-date")), valuta: campo(t, "tl_etf-basics_value_fund-currency") || null, n: Math.round(num(campo(t, "etf-profile-header_holdings-value")) || 0) || null,
      top: righe(t, "top-holdings"), paesi: righe(t, "countries"), settori: righe(t, "sectors") };
  }
  const classe = (focus) => { const f = (focus || "").split(",")[0].trim().toLowerCase(); return /^(bond|money)/.test(f) ? "Obbligazionario" : /^(commod|precious|crypto)/.test(f) ? "Materie prime" : "Azionario"; };
  const eOro = (nome, focus) => /\bgold\b|\boro\b|precious/i.test(nome + " " + focus);
  function tipoRuolo(cls, focus, nome) {
    const f = (focus || "").toLowerCase(), n = (nome || "").toLowerCase();
    if (cls === "Obbligazionario") return [/corporate|credit|high yield/.test(f + " " + n) ? "Obbligazioni · societarie" : /govern|treasur|sovereign|state/.test(f + " " + n) ? "Obbligazioni · titoli di Stato" : "Obbligazioni", "Obbligazioni"];
    if (cls === "Materie prime") return eOro(nome, focus) ? ["Oro", "Oro"] : ["Materie prime", "Materie prime"];
    const sec = f.includes(",") ? f.split(",").slice(1).join(",").trim() : "";
    if (/\b(emerging|asia|china|india|latin america|africa|brazil|korea|taiwan)\b/.test(sec + " " + n)) return ["Azioni · emergenti", "Emergenti"];
    if (["world", "europe", "north america", "usa", "united states", "developed", "eurozone", "euro area", "global"].includes(sec) || (/\b(world|all[- ]country|global)\b/.test(n) && ["", "world"].includes(sec))) return ["Azioni · mondo ed Europa", "Nucleo"];
    return ["Azioni · settoriali", "Satellite"];
  }
  const chiave = (n) => n.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  function costruisciMix(p, cls) {
    const insEuro = new Set(T.EURO), insNoEuro = new Set(T.EUROPA_NO_EURO), insEm = new Set(T.EMERGENTI), insAltri = new Set(T.ALTRI_SVILUPPATI);
    const paesiEn = p.paesi.map(([n, w]) => [n, w]);
    const paesi = paesiEn.filter(([n]) => n !== "Other" && n !== "Others").slice(0, 8).map(([n, w]) => [T.PAESI[n] || n, r4(w)]);
    if (cls === "Materie prime") { const oro = eOro(p.name, p.focus), k = oro ? "Oro" : "Materie prime"; return { aree: { [k]: 1.0 }, settori: {}, valute: { [k + " (prezzato in USD)"]: 1.0 }, paesi: [], top: [], nt: 0 }; }
    let aree = {}, valute = {};
    paesiEn.forEach(([n, w]) => {
      const a = n === "United States" ? "Stati Uniti" : insEuro.has(n) ? "Area euro" : insNoEuro.has(n) ? "Europa fuori dall'euro" : n === "Japan" ? "Giappone" : insEm.has(n) ? "Mercati emergenti" : insAltri.has(n) ? "Altri sviluppati" : "Altro";
      aree[a] = (aree[a] || 0) + w;
      const v = insEuro.has(n) ? "EUR" : T.VALUTE[n] || "Altre valute"; valute[v] = (valute[v] || 0) + w;
    });
    if (cls === "Obbligazionario") valute = { [p.valuta || "EUR"]: 1.0 };
    [[aree, "Altro"], [valute, "Altre valute"]].forEach(([d, k]) => { const resto = 1 - sum(Object.values(d)); if (resto > 0.0005 && Object.keys(d).length) d[k] = (d[k] || 0) + resto; });
    let settori = {};
    if (cls === "Azionario") { p.settori.forEach(([n, w]) => { const k = T.SETTORI[n] || "Altro"; settori[k] = (settori[k] || 0) + w; }); const resto = 1 - sum(Object.values(settori)); if (Object.keys(settori).length && resto > 0.0005) settori["Altro"] = (settori["Altro"] || 0) + resto; }
    const top = []; if (cls === "Azionario") p.top.forEach(([n, w, isin]) => { const en = T.ISO2[(isin || "").slice(0, 2)]; top.push([n, T.PAESI[en] || en || "", r4(w), chiave(n)]); });
    const rd = (d) => Object.fromEntries(Object.entries(d).map(([k, v]) => [k, r4(v)]));
    return { aree: rd(aree), settori: rd(settori), valute: rd(valute), paesi, top, nt: top.length };
  }
  function costruisciFondo(p, sigla) {
    const cls = classe(p.focus), [tipo, ruolo] = tipoRuolo(cls, p.focus, p.name);
    return { s: sigla, isin: p.isin, name: p.name, cls, ruolo, tipo, w: 0, q0: 0, p0: 0, ter: p.ter, aum: p.aum, adv: null, emittente: p.emittente, repl: p.repl, dom: p.dom, lancio: p.lancio, valuta: p.valuta, n: p.n, mix: costruisciMix(p, cls) };
  }
  function siglaProposta(p) {
    let s = (p.ticker || "").replace(/[^A-Za-z0-9]/g, "").toUpperCase(); if (s) return s.slice(0, 8);
    const ban = new Set(["UCITS", "ETF", "ETC", "ETN", "ACC", "DIST", "EUR", "USD", "ACCUMULATING", "DISTRIBUTING", "C", "D"]);
    const parole = (p.name.match(/[A-Za-z0-9]+/g) || []).filter((w) => !ban.has(w.toUpperCase()));
    return parole.slice(0, 5).map((w) => w[0]).join("").toUpperCase() || p.isin.replace(/[^A-Z0-9]/g, "").slice(-6);
  }

  // ---- definizione del portafoglio
  function intervallo(x, cosa) { if (!(Array.isArray(x) && x.length === 2 && x.every((v) => typeof v === "number") && 0 <= x[0] && x[0] <= x[1] && x[1] <= 100)) throw Err("«vincoli»: " + cosa + " deve essere [minimo, massimo] in percentuale, da 0 a 100."); return [x[0], x[1]]; }
  function validaTransazioni(tr, ammessi) {  // [{isin, data, tipo: acquisto|vendita, quote, prezzo}] come in build.py
    if (tr === undefined || tr === null) return [];
    if (!Array.isArray(tr) || tr.length > 5000) throw Err("«transazioni»: un elenco (al massimo 5000) di {\"isin\", \"data\", \"tipo\", \"quote\", \"prezzo\"}.");
    const out = tr.map((x, k) => {
      if (!x || typeof x !== "object") throw Err("«transazioni» n. " + (k + 1) + ": deve essere un oggetto.");
      const isin = String(x.isin || "").trim().toUpperCase(), n = k + 1;
      if (!ammessi.has(isin)) throw Err("«transazioni» n. " + n + ": l'ISIN «" + isin + "» non è tra i titoli del portafoglio (aggiungilo con peso 0 se l'hai già venduto).");
      if (!/^\d{4}-\d{2}-\d{2}$/.test(String(x.data)) || isNaN(new Date(x.data + "T12:00:00Z"))) throw Err("«transazioni» n. " + n + " (" + isin + "): «data» deve essere AAAA-MM-GG.");
      if (x.tipo !== "acquisto" && x.tipo !== "vendita") throw Err("«transazioni» n. " + n + " (" + isin + "): «tipo» deve essere «acquisto» o «vendita».");
      const quote = parseFloat(x.quote), prezzo = parseFloat(x.prezzo);
      if (!(quote > 0 && prezzo > 0)) throw Err("«transazioni» n. " + n + " (" + isin + "): «quote» e «prezzo» devono essere numeri maggiori di 0 (la vendita ha tipo «vendita», non quote negative).");
      return { isin, data: String(x.data), tipo: x.tipo, quote: Number.isInteger(quote) ? quote : Math.round(quote * 1e6) / 1e6, prezzo: Math.round(prezzo * 1e6) / 1e6 };
    });
    out.sort((a, b) => (a.data < b.data ? -1 : a.data > b.data ? 1 : (a.tipo === "acquisto" ? 0 : 1) - (b.tipo === "acquisto" ? 0 : 1)));
    const pos = {};
    out.forEach((x) => { const q = (pos[x.isin] || 0) + (x.tipo === "acquisto" ? x.quote : -x.quote); if (q < -1e-9) throw Err("Vendita di " + x.isin + " del " + x.data + ": stai vendendo più quote di quelle che avevi."); pos[x.isin] = q; });
    return out;
  }
  function validaObiettivo(ob, ammessi) {  // quote obiettivo del piano proposto: [{isin, quote}]; «da investire» = quote obiettivo − quote che hai davvero
    if (ob === undefined || ob === null) return [];
    if (!Array.isArray(ob) || ob.length > 100) throw Err("«obiettivo»: un elenco di {\"isin\", \"quote\"}.");
    const visti = new Set();
    return ob.map((x, k) => {
      const isin = String((x && x.isin) || "").trim().toUpperCase();
      if (!ammessi.has(isin)) throw Err("«obiettivo» n. " + (k + 1) + ": l'ISIN «" + isin + "» non è tra i titoli del portafoglio.");
      if (visti.has(isin)) throw Err("«obiettivo»: ISIN ripetuto (" + isin + ")."); visti.add(isin);
      const q = parseFloat(x.quote); if (!(q >= 0)) throw Err("«obiettivo» n. " + (k + 1) + " (" + isin + "): «quote» deve essere un numero non negativo.");
      return { isin, quote: Math.round(q * 1e6) / 1e6 };
    });
  }
  function validaDefinizione(d) {
    if (!d || typeof d !== "object" || Array.isArray(d)) throw Err("Il JSON deve essere un oggetto con nome, versione, descrizione e titoli.");
    const nome = d.nome; if (typeof nome !== "string" || !NOME_PF.test(nome)) throw Err("«nome»: solo lettere e cifre, niente spazi né simboli, al massimo 30 caratteri.");
    const v = parseInt(String(d.versione).trim().replace(/^[Vv]/, ""), 10); if (!(v >= 1 && v <= 999)) throw Err("«versione»: V1, V2, V3… (un numero da 1 a 999).");
    const descrizione = String(d.descrizione || "").split(/\s+/).filter(Boolean).join(" ");
    if (!descrizione) throw Err("«descrizione»: scrivi una breve descrizione."); if (descrizione.length > 300) throw Err("«descrizione»: al massimo 300 caratteri.");
    let amount = 10000; if (d.valore !== undefined && d.valore !== null) { amount = Math.round(parseFloat(d.valore) * 100) / 100; if (isNaN(amount)) throw Err("«valore»: un numero in euro (facoltativo)."); if (!(amount >= 100 && amount <= 1e9)) throw Err("«valore»: tra 100 e 1.000.000.000 euro."); }
    const tit = d.titoli; if (!Array.isArray(tit) || tit.length < 1 || tit.length > 30) throw Err("«titoli»: da 1 a 30 elementi {\"isin\": …, \"peso\": …}.");
    const visti = new Set(), rr = [];
    tit.forEach((x) => {
      const isin = x && typeof x === "object" ? String(x.isin || "").trim().toUpperCase() : "";
      if (!isinValido(isin)) throw Err("ISIN non valido: «" + (isin || JSON.stringify(x)) + "».");
      if (visti.has(isin)) throw Err("ISIN ripetuto: " + isin + "."); visti.add(isin);
      const peso = parseFloat(x.peso); if (isNaN(peso)) throw Err(isin + ": «peso» deve essere un numero (percentuale).");
      if (!(peso >= 0 && peso <= 100)) throw Err(isin + ": il peso deve essere tra 0 e 100 (0 per un titolo già venduto, che serve solo alle transazioni).");
      rr.push([isin, peso]);
    });
    const tot = sum(rr.map((x) => x[1])); if (Math.abs(tot - 100) > 0.5) throw Err("I pesi danno " + Math.round(tot * 100) / 100 + "%: devono dare 100%.");
    const transazioni = validaTransazioni(d.transazioni, visti), obiettivo = validaObiettivo(d.obiettivo, visti);
    let vincoli = null;
    if (d.vincoli !== undefined && d.vincoli !== null) {
      const vv = d.vincoli; if (typeof vv !== "object" || Array.isArray(vv)) throw Err("«vincoli»: un oggetto con «fondi» (per ISIN) e «classi».");
      const fondi = {}, classi = {};
      Object.entries(vv.fondi || {}).forEach(([i, x]) => { if (!visti.has(i)) throw Err("«vincoli»: " + i + " non è tra i titoli del portafoglio."); fondi[i] = intervallo(x, i); });
      Object.entries(vv.classi || {}).forEach(([c, x]) => { if (!CLASSI.includes(c)) throw Err("«vincoli»: classe «" + c + "» sconosciuta (ammesse: " + CLASSI.join(", ") + ")."); classi[c] = intervallo(x, c); });
      vincoli = { fondi, classi };
    }
    let frontiera = null;  // come è stata calcolata la frontiera: riaprendo il portafoglio si ritrova la stessa curva
    if (d.frontiera !== undefined && d.frontiera !== null) {
      const fr = d.frontiera; if (!fr || typeof fr !== "object" || ![1, 3, 5].includes(fr.finestra) || typeof fr.prudente !== "boolean") throw Err("«frontiera»: {\"finestra\": 1, 3 o 5 (anni di storico), \"prudente\": true o false}.");
      frontiera = { finestra: fr.finestra, prudente: fr.prudente };
    }
    return { nome, v, descrizione, amount, pesi: rr.map(([i, p]) => [i, r4(p / tot)]), vincoli, transazioni, obiettivo, frontiera };
  }

  // ---- dati dei titoli: schede note (con l'app), memoria dell'app, justETF
  const scheda = (isin) => leggiLS("mm:scheda:" + isin);
  const fondoNoto = (isin) => { const s = SEED.titoli[isin]; if (s && s.fondo) return JSON.parse(JSON.stringify(s.fondo)); const c = scheda(isin); return c && c.fondo ? JSON.parse(JSON.stringify(c.fondo)) : null; };
  const sigleUsate = () => { const u = new Set(Object.values(SEED.titoli).map((s) => s.fondo && s.fondo.s)); Object.keys(LS).filter((k) => k.startsWith("mm:scheda:")).forEach((k) => { const s = leggiLS(k); if (s && s.fondo) u.add(s.fondo.s); }); return u; };
  async function titoloScarica(isin, usate, say) {  // scarica ciò che manca per un ISIN e lo mette nella memoria dell'app
    const sc = scheda(isin); let fondo = fondoNoto(isin);
    if (sc && sc.scaricato === oggi() && sc.serie && fondo) { say({ t: "testo", testo: isin + ": dati scaricati oggi, li riuso (" + sc.serie.length + " prezzi)" }); return; }
    if (fondo) say({ t: "testo", testo: isin + ": profilo già noto (" + fondo.name + "), aggiorno i prezzi" });
    else {
      say({ t: "testo", testo: isin + ": scarico la scheda del fondo da justETF…" });
      const p = parseProfilo(await scarica(PROFILO + isin, false), isin); let sigla = siglaProposta(p), k = 1; const base = sigla;
      while (usate.has(sigla)) { k++; sigla = base.slice(0, 6) + k; } usate.add(sigla);
      fondo = costruisciFondo(p, sigla);
      say({ t: "testo", testo: fondo.name + " · " + fondo.tipo + " · TER " + fondo.ter + "% · patrimonio " + fondo.aum + " mln €", c: "t" });
    }
    say({ t: "testo", testo: isin + ": scarico lo storico dei prezzi in euro da justETF…" });
    const s = await serie(isin);
    if (!scriviLS("mm:scheda:" + isin, { scaricato: oggi(), fondo, serie: s })) throw Err("Memoria dell'app piena: elimina qualche portafoglio.");
  }
  function costruisciDaCache(nomefile, avanza) {  // documento {meta, funds, dates, px}; LookupError se mancano dati di oggi
    const say = avanza || (() => {}), d = definizione(nomefile); if (!d) throw Err("Portafoglio non trovato.");
    const df = validaDefinizione(d), versione = "V" + df.v; say({ t: "inizio", n: df.pesi.length });
    const fondi = [], serieTot = {}, siglaDi = {};
    df.pesi.forEach(([isin, w], k) => {
      say({ t: "titolo", s: isin, isin, k: k + 1, n: df.pesi.length });
      const sc = scheda(isin), f = fondoNoto(isin);
      if (!(sc && sc.scaricato === oggi() && sc.serie && f)) throw Object.assign(new Error(isin + ": dati da scaricare"), { mancano: true });
      if (fondi.some((x) => x.s === f.s)) throw Err(isin + ": sigla " + f.s + " già usata nel portafoglio");
      delete f.sym; f.w = w; fondi.push(f); serieTot[f.s] = sc.serie; siglaDi[isin] = f.s;
      say({ t: "dati", s: f.s, isin, fonte: FONTE, righe: sc.serie.slice(-40) });
    });
    const inizio = Object.values(serieTot).map((x) => x[0][0]).sort().pop();
    const fine = Object.values(serieTot).map((x) => x[x.length - 1][0]).sort()[0];
    const set = new Set(); Object.values(serieTot).forEach((x) => x.forEach(([dd]) => { if (dd >= inizio && dd <= fine) set.add(dd); }));
    const date = [...set].sort(); if (date.length < 60) throw Err("Lo storico in comune è troppo breve (" + date.length + " giorni, dal " + inizio + " al " + fine + "): togli il titolo più recente.");
    const px = {};
    Object.entries(serieTot).forEach(([sigla, x]) => { const xs = x.slice().sort((a, b) => (a[0] < b[0] ? -1 : 1)); let ult = null, j = 0; px[sigla] = date.map((dd) => { while (j < xs.length && xs[j][0] <= dd) { ult = xs[j][1]; j++; } return ult; }); });
    fondi.forEach((f) => { f.p0 = px[f.s][px[f.s].length - 1]; f.q0 = Math.floor(df.amount * f.w / f.p0); });
    const meta = { nome: df.nome, versione, descrizione: df.descrizione, chiave: "pf-" + df.nome + "-" + versione, file: nomefile, base: date[date.length - 1], from: date[0], amount: df.amount, rf: 0.02, origine: "json" };
    if (nomefile.startsWith("bozza:")) { meta.chiave += "-bozza-" + nomefile.slice(6); meta.bozza = true; if (d._da) meta.bozza_da = d._da; }  // acquisti e limiti nel browser distinti da quelli del portafoglio di partenza
    if (df.frontiera) meta.frontiera = df.frontiera;
    if (df.vincoli) meta.vincoli = { fondi: Object.fromEntries(Object.entries(df.vincoli.fondi).map(([i, x]) => [siglaDi[i], x])), classi: df.vincoli.classi };
    if (df.transazioni.length) meta.transazioni = df.transazioni.map((x) => ({ s: siglaDi[x.isin], d: x.data, t: x.tipo === "acquisto" ? "a" : "v", q: x.quote, p: x.prezzo }));
    if (df.obiettivo.length) meta.obiettivo = Object.fromEntries(df.obiettivo.map((x) => [siglaDi[x.isin], x.quote]));  // quote del piano proposto: la pagina ne ricava «da investire»
    say({ t: "salvato", n: fondi.length });
    return { meta, funds: fondi, dates: date, px };
  }
  async function prepara(nomefile, avanza) {
    const say = avanza || (() => {}), df = validaDefinizione(definizione(nomefile)), usate = sigleUsate();
    say({ t: "inizio", n: df.pesi.length });
    for (let k = 0; k < df.pesi.length; k++) { const isin = df.pesi[k][0]; say({ t: "titolo", s: isin, isin, k: k + 1, n: df.pesi.length }); await titoloScarica(isin, usate, say); }
    costruisciDaCache(nomefile, say);
    return info(nomefile);
  }
  const titoliNoti = () => {
    const titoli = {}; let base = "";
    elenco().forEach((i) => { try { validaDefinizione(definizione(i.file)).pesi.forEach(([isin]) => { const f = fondoNoto(isin), sc = scheda(isin); if (f && sc && sc.serie) { titoli[f.s] = titoli[f.s] || { isin, p0: sc.serie[sc.serie.length - 1][1] }; const b = sc.serie[sc.serie.length - 1][0]; if (!base || b < base) base = b; } }); } catch (e) {} });
    return { titoli, base };
  };

  // ---- scrittura dei portafogli
  async function crea(def, avanza) {
    if (def && typeof def === "object" && Object.keys(def).length === 1 && def.file) { if (!info(def.file)) throw Err("Portafoglio non trovato."); return prepara(def.file, avanza); }
    const df = validaDefinizione(def), versione = "V" + df.v, nuovo = df.nome + "_" + versione + ".json";
    if (info(nuovo)) throw Object.assign(Err("Esiste già il portafoglio " + df.nome + " " + versione + " (" + nuovo + "). Cambia la versione nel JSON per crearne uno nuovo."), { esiste: nuovo });
    scriviLS("mm:pf:" + nuovo, { nome: df.nome, versione, descrizione: df.descrizione, valore: df.amount, titoli: df.pesi.map(([i, w]) => ({ isin: i, peso: Math.round(w * 1e4) / 100 })), ...(df.transazioni.length ? { transazioni: df.transazioni } : {}), ...(df.obiettivo.length ? { obiettivo: df.obiettivo } : {}), ...(df.vincoli ? { vincoli: df.vincoli } : {}) });
    let i; try { i = await prepara(nuovo, avanza); } catch (e) { LS.removeItem("mm:pf:" + nuovo); throw e; }
    rispecchia({ write: [scriviFile(nuovo)] }); await specchioOk(); return i;
  }
  async function bozza(da, titoli, avanza, valore, transazioni, obiettivo) {  // portafoglio `da` con i titoli cambiati: [{isin, peso?}] (peso in %, se manca resta quello di prima, 1 per un titolo nuovo); i pesi tornano a 100
    const origine = definizione(da); if (!origine) throw Err("Portafoglio di partenza non trovato.");
    if (!Array.isArray(titoli) || titoli.length < 1 || titoli.length > 30) throw Err("Servono da 1 a 30 titoli.");
    const prima = Object.fromEntries((origine.titoli || []).map((x) => [x.isin, x.peso])), visti = new Set(), nuovi = [];
    titoli.forEach((x) => {
      const isin = String((x && x.isin) || "").trim().toUpperCase(); if (!isin) throw Err("C'è un titolo senza ISIN."); if (visti.has(isin)) throw Err(isin + ": ISIN ripetuto."); visti.add(isin);
      let peso = x.peso, fisso = false; if (peso === undefined || peso === null || peso === "") { if (prima[isin] != null) peso = prima[isin]; else { peso = 1; fisso = true; } } peso = parseFloat(peso);  // titolo nuovo senza peso: entra all'1%
      if (isNaN(peso)) throw Err(isin + ": peso non valido."); if (!(peso >= 0 && peso <= 100)) throw Err(isin + ": il peso deve essere tra 0 e 100.");
      nuovi.push([isin, peso, fisso]);
    });
    const fissi = sum(nuovi.filter((x) => x[2]).map((x) => x[1])), altri = sum(nuovi.filter((x) => !x[2]).map((x) => x[1]));
    if (altri > 0 && fissi < 100) nuovi.forEach((x) => { if (!x[2]) x[1] = x[1] * (100 - fissi) / altri; });  // gli altri si riducono (o crescono, se ne è stato tolto uno) in proporzione fino a fare 100
    const tot = sum(nuovi.map((x) => x[1])); if (!(tot > 0)) throw Err("Almeno un titolo deve avere un peso maggiore di 0.");
    nuovi.forEach((x) => { x[1] = Math.round(x[1] * 100 / tot * 100) / 100; });
    const grande = nuovi.reduce((a, x) => (x[1] > a[1] ? x : a), nuovi[0]); grande[1] = Math.round((grande[1] + (100 - sum(nuovi.map((x) => x[1])))) * 100) / 100;
    let val = origine.valore || 10000; if (valore !== undefined && valore !== null && valore !== "") { val = Math.round(parseFloat(valore) * 100) / 100; if (isNaN(val)) throw Err("Il valore dell'investimento deve essere un numero."); if (!(val >= 100 && val <= 1e9)) throw Err("Il valore dell'investimento deve essere tra 100 e 1.000.000.000 euro."); }
    const d = { nome: origine.nome, versione: origine.versione, descrizione: origine.descrizione || "bozza", valore: val, titoli: nuovi.map(([isin, peso]) => ({ isin, peso })), _da: da.startsWith("bozza:") ? origine._da : da };
    const tr = transazioni !== undefined && transazioni !== null ? validaTransazioni(transazioni, visti) : (origine.transazioni || []).filter((x) => visti.has(x.isin)); const ob = obiettivo !== undefined && obiettivo !== null ? validaObiettivo(obiettivo, visti) : (origine.obiettivo || []).filter((x) => visti.has(x.isin)); if (ob.length) d.obiettivo = ob;
    if (tr.length) d.transazioni = tr;  // con la schermata di modifica gli acquisti e le vendite inseriti sostituiscono quelli di prima
    validaDefinizione(d);
    const token = Math.random().toString(36).slice(2, 8) + Date.now().toString(36);
    if (!scriviLS("mm:bozza:" + token, d)) throw Err("Memoria dell'app piena: elimina qualche portafoglio.");
    try { await prepara("bozza:" + token, avanza); } catch (e) { LS.removeItem("mm:bozza:" + token); throw e; }
    Object.keys(LS).filter((k) => k.startsWith("mm:bozza:") && k !== "mm:bozza:" + token).slice(0, -9).forEach((k) => LS.removeItem(k));  // poche bozze: le più vecchie vengono dimenticate
    return { token };
  }
  async function salvaTitoli(da, titoli, nome, versione, descrizione, avanza, valore, transazioni, obiettivo) {  // salva nome_Vn.json da `da` con i titoli cambiati ([{isin, peso?}]), scaricando i dati dei titoli nuovi
    const token = (await bozza(da, titoli, avanza, valore, transazioni, obiettivo)).token;
    try {
      const doc = costruisciDaCache("bozza:" + token), w = Object.fromEntries(doc.funds.map((f) => [f.s, Math.round(f.w * 1000) / 1000]));
      const grande = Object.keys(w).reduce((a, k) => (w[k] > w[a] ? k : a)); w[grande] = Math.round((w[grande] + (1 - sum(Object.values(w)))) * 1000) / 1000;  // la somma resta 100% dopo l'arrotondamento
      const info = salva("bozza:" + token, nome, versione, descrizione, w);
      await specchioOk();
      return info;
    } finally { LS.removeItem("mm:bozza:" + token); }
  }
  function salva(da, nome, versione, descrizione, pesi, importo, transazioni, vincoli, frontiera, obiettivo) {
    const origine = definizione(da); if (!origine) throw Err("Portafoglio di partenza non trovato.");
    if (typeof nome !== "string" || !NOME_PF.test(nome)) throw Err("Il nome può avere solo lettere e cifre (niente spazi né simboli), al massimo 30 caratteri.");
    const v = parseInt(String(versione).replace(/^[Vv]/, ""), 10); if (!(v >= 1 && v <= 999)) throw Err("La versione deve essere un numero da 1 a 999 (V1, V2, V3…).");
    descrizione = String(descrizione || "").split(/\s+/).filter(Boolean).join(" "); if (!descrizione) throw Err("Scrivi una breve descrizione."); if (descrizione.length > 300) throw Err("La descrizione può avere al massimo 300 caratteri.");
    const doc = costruisciDaCache(da), siglaIsin = Object.fromEntries(doc.funds.map((f) => [f.s, f.isin]));
    if (!pesi || typeof pesi !== "object" || Object.keys(pesi).sort().join() !== Object.keys(siglaIsin).sort().join()) throw Err("I pesi non corrispondono ai fondi del portafoglio.");
    const w = Object.fromEntries(Object.entries(pesi).map(([k, x]) => [k, Math.round(parseFloat(x) * 1000) / 1000]));
    if (Object.values(w).some((x) => isNaN(x) || x < 0) || Math.abs(sum(Object.values(w)) - 1) > 0.0015) throw Err("I pesi devono essere positivi e dare 100%.");
    let amount = origine.valore || doc.meta.amount;
    if (importo !== undefined && importo !== null) { amount = Math.round(parseFloat(importo) * 100) / 100; if (isNaN(amount)) throw Err("Importo non valido."); if (!(amount >= 100 && amount <= 1e9)) throw Err("L'importo deve essere tra 100 e 1.000.000.000 euro."); }
    const versioneT = "V" + v, nuovo = nome + "_" + versioneT + ".json";
    if (info(nuovo)) { const libere = Math.max(...elenco().filter((i) => i.nome === nome).map((i) => numVers(i.versione)), v) + 1; throw Err("Esiste già " + nuovo + ": usa la versione V" + libere + "."); }
    const tr = validaTransazioni(transazioni === undefined || transazioni === null ? origine.transazioni : transazioni, new Set(Object.values(siglaIsin))), conMov = new Set(tr.map((x) => x.isin));  // un titolo già venduto resta con peso 0: serve ai suoi movimenti
    const titoli = Object.entries(w).sort((a, b) => b[1] - a[1]).filter(([s, x]) => x > 0 || conMov.has(siglaIsin[s])).map(([s, x]) => ({ isin: siglaIsin[s], peso: Math.round(x * 1000) / 10 }));
    const nd = { nome, versione: versioneT, descrizione, valore: amount, titoli };
    if (tr.length) nd.transazioni = tr;
    const ob = validaObiettivo(obiettivo === undefined || obiettivo === null ? (da.startsWith("bozza:") ? origine.obiettivo : []) : obiettivo, new Set(titoli.map((t) => t.isin))); if (ob.length) nd.obiettivo = ob;  // un piano nuovo parte senza «da investire» se la pagina non lo indica
    const vv = vincoli && typeof vincoli === "object" && (Object.keys(vincoli.fondi || {}).length || Object.keys(vincoli.classi || {}).length) ? vincoli : origine.vincoli;  // i limiti usati per trovare il punto sulla frontiera
    if (vv) { const amm = new Set(titoli.map((t) => t.isin)); nd.vincoli = { fondi: Object.fromEntries(Object.entries(vv.fondi || {}).filter(([i]) => amm.has(i))), classi: vv.classi || {} }; }
    const fr = frontiera && typeof frontiera === "object" ? frontiera : origine.frontiera; if (fr) nd.frontiera = fr;
    validaDefinizione(nd);  // il file scritto deve restare valido
    scriviLS("mm:pf:" + nuovo, nd);
    rispecchia({ write: [scriviFile(nuovo)] });
    return info(nuovo);
  }
  function modifica(f, nome, versione, descrizione) {  // nome, versione e descrizione: stesso file, o rinominato se cambiano nome o versione
    const d = definizione(f); if (!d) throw Err("Portafoglio non trovato.");
    if (typeof nome !== "string" || !NOME_PF.test(nome)) throw Err("Il nome può avere solo lettere e cifre (niente spazi né simboli), al massimo 30 caratteri.");
    const v = parseInt(String(versione).replace(/^[Vv]/, ""), 10); if (!(v >= 1 && v <= 999)) throw Err("La versione deve essere un numero da 1 a 999 (V1, V2, V3…).");
    descrizione = String(descrizione || "").split(/\s+/).filter(Boolean).join(" "); if (!descrizione) throw Err("Scrivi una breve descrizione."); if (descrizione.length > 300) throw Err("La descrizione può avere al massimo 300 caratteri.");
    const nuovo = nome + "_V" + v + ".json"; if (nuovo !== f && info(nuovo)) throw Err("Esiste già " + nuovo + ": scegli un'altra versione.");
    const nd = { ...d, nome, versione: "V" + v, descrizione }; validaDefinizione(nd);
    scriviLS("mm:pf:" + nuovo, nd);
    if (nuovo !== f) { LS.removeItem("mm:pf:" + f); if (LS.getItem("mm:ultimo") === f) segna(nuovo); rispecchia({ write: [scriviFile(nuovo)], trash: [f] }); } else rispecchia({ write: [scriviFile(nuovo)] });
    return { ...info(nuovo), chiave: "pf-" + nome + "-V" + v };
  }
  function elimina(f) { if (!info(f)) throw Err("Portafoglio non trovato."); LS.removeItem("mm:pf:" + f); rispecchia({ trash: [f] }); return { eliminato: f, ultimo: ultimo() }; }

  // ---- prezzi
  let ultimoTentativo = 0;
  const prezziVuoti = () => ({ at: null, fonte: "", prezzi: {}, storico: {}, avvisi: [], risposte: 0 });
  const leggiPrezzi = () => leggiLS("mm:prezzi") || prezziVuoti();
  // quotazione in tempo reale di gettex: lo stesso canale che usa la pagina di justETF; si sottoscrivono tutti gli ISIN, si legge la prima quotazione di ciascuno e si chiude
  function gettex(isins, attesa) {
    const lista = [...new Set(isins)].filter((i) => ISIN_RE.test(i));
    return new Promise((ok) => {
      const out = {}; if (!lista.length || typeof WebSocket === "undefined") { ok(out); return; }
      let ws = null, chiuso = false;
      const fine = () => { if (chiuso) return; chiuso = true; try { ws && ws.close(); } catch (e) {} ok(out); };
      try {
        ws = new WebSocket("wss://api.mobile.stock-data-subscriptions.justetf.com?subscription=trend&parameters=isins:" + lista.join(",") + "/currency:EUR/language:it");
        ws.onmessage = (m) => { try { const j = JSON.parse(m.data), mid = j && j.mid && j.mid.raw; if (lista.includes(j.isin) && mid > 0 && !out[j.isin]) { const ts = String(j.timestamp || ""); out[j.isin] = { p: Math.round(mid * 1e4) / 1e4, t: ts, d: ts.slice(0, 10) }; if (Object.keys(out).length >= lista.length) fine(); } } catch (e) {} };
        ws.onerror = fine; ws.onclose = fine;
        setTimeout(fine, attesa || 8000);
      } catch (e) { fine(); }
    });
  }
  async function aggiornaPrezzi(say) {
    const { titoli, base } = titoliNoti(), vecchi = leggiPrezzi(), prezzi = { ...vecchi.prezzi }, storico = JSON.parse(JSON.stringify(vecchi.storico || {})), avvisi = []; let risposte = 0;
    const nt = Object.keys(titoli).length; say({ t: "inizio", n: nt });
    let k = 0;
    for (const [sigla, t] of Object.entries(titoli)) {
      k++; say({ t: "titolo", s: sigla, isin: t.isin, k, n: nt });
      let s; try { s = await serie(t.isin, sommaGiorni(oggi(), -12)); } catch (e) { avvisi.push(sigla + ": prezzo non scaricato"); say({ t: "errore", s: sigla, testo: sigla + ": prezzo non scaricato" }); continue; }
      risposte++; say({ t: "dati", s: sigla, isin: t.isin, fonte: FONTE, righe: s });
      let prec = (prezzi[sigla] && prezzi[sigla].p) || t.p0, ok = true;
      for (const [d, p] of s) { if (d <= base) continue; if (!(p / prec > 0.6 && p / prec < 1.6)) { avvisi.push(sigla + ": prezzo anomalo il " + d + " (" + p + "), ignorato"); say({ t: "avviso", testo: avvisi[avvisi.length - 1] }); ok = false; break; } (storico[d] = storico[d] || {})[sigla] = p; prec = p; }
      const ultime = s.filter((x) => x[0] > base); if (ok && ultime.length) prezzi[sigla] = { p: ultime[ultime.length - 1][1], d: ultime[ultime.length - 1][0] };
      await sleep(300);
    }
    const q = await gettex(Object.values(titoli).map((t) => t.isin)), live = {};  // prezzo gettex (come justETF): sostituisce l'ultimo prezzo XETRA del grafico
    for (const [sigla, t] of Object.entries(titoli)) { const x = q[t.isin]; if (!x) continue; const prec = (prezzi[sigla] && prezzi[sigla].p) || t.p0; if (x.p / prec > 0.6 && x.p / prec < 1.6) live[sigla] = x; else avvisi.push(sigla + ": prezzo gettex anomalo (" + x.p + "), ignorato"); }
    if (nt && !Object.keys(live).length) avvisi.push("gettex non raggiunto: restano i prezzi XETRA di justETF");
    say({ t: "testo", testo: "gettex: " + Object.keys(live).length + " prezzi in tempo reale" });
    const nuovo = { at: new Date().toISOString().replace(/\.\d+Z$/, "Z"), fonte: risposte ? FONTE : vecchi.fonte || "", prezzi, storico, avvisi, risposte, live };
    scriviLS("mm:prezzi", nuovo); ultimoTentativo = Date.now(); say({ t: "salvato", n: Object.keys(prezzi).length });
    return nuovo;
  }

  // ---- le risposte alle chiamate /api della pagina
  const json = (corpo, status) => new Response(JSON.stringify(corpo), { status: status || 200, headers: { "Content-Type": "application/json; charset=utf-8" } });
  function flusso(lavoro) {
    const enc = new TextEncoder();
    return new Response(new ReadableStream({ async start(c) { const riga = (ev) => { try { c.enqueue(enc.encode(JSON.stringify(ev) + "\n")); } catch (e) {} }; try { await lavoro(riga); } catch (e) { riga({ t: "fallito", testo: String(e.message || e) }); } try { c.close(); } catch (e) {} } }), { status: 200, headers: { "Content-Type": "application/x-ndjson; charset=utf-8" } });
  }
  async function api(percorso, metodo, corpo) {
    if (metodo === "GET") {
      if (percorso === "/api/prezzi") return json(leggiPrezzi());
      if (percorso === "/api/portafogli") return json({ ultimo: ultimo(), lista: elenco() });
      if (percorso === "/api/cartella") { const c = await cartellaApi(null); return c ? json(c) : json({ errore: "non trovato" }, 404); }
      return json({ errore: "non trovato" }, 404);
    }
    let r = {}; try { r = corpo ? JSON.parse(corpo) : {}; } catch (e) { return json({ errore: "richiesta non valida" }, 400); }
    if (percorso === "/api/cartella") { try { const c = await cartellaApi(r); return c ? json(c) : json({ errore: "non trovato" }, 404); } catch (e) { return json({ errore: e.message }, 400); } }
    if (percorso === "/api/elimina") { try { return json(elimina(r.file)); } catch (e) { return json({ errore: e.message }, 400); } }
    if (percorso === "/api/modifica") { try { const m = modifica(r.file, r.nome, r.versione, r.descrizione); await specchioOk(); return json(m); } catch (e) { return json({ errore: e.message }, 400); } }
    if (percorso === "/api/salva") { try { const x = salva(r.da, r.nome, r.versione, r.descrizione, r.pesi, r.importo, r.transazioni, r.vincoli, r.frontiera, r.obiettivo); await specchioOk(); return json(x); } catch (e) { return json({ errore: e.message }, 400); } }
    if (percorso === "/api/salva-titoli") return flusso(async (riga) => { try { riga({ t: "salvato_pf", ...(await salvaTitoli(r.da, r.titoli, r.nome, r.versione, r.descrizione, riga, r.valore, r.transazioni, r.obiettivo)) }); } catch (e) { riga({ t: "fallito", testo: e.message || "richiesta non valida" }); } });
    if (percorso === "/api/bozza") return flusso(async (riga) => { try { riga({ t: "pronta", ...(await bozza(r.da, r.titoli, riga, r.valore, r.transazioni, r.obiettivo)) }); } catch (e) { riga({ t: "fallito", testo: e.message || "richiesta non valida" }); } });
    if (percorso === "/api/crea") return flusso(async (riga) => { try { riga({ t: "creato", ...(await crea(r, riga)) }); } catch (e) { riga(e.esiste ? { t: "esiste", file: e.esiste, testo: e.message } : { t: "fallito", testo: e.message || "richiesta non valida" }); } });
    if (percorso === "/api/aggiorna") return flusso(async (riga) => {
      let dati;
      if (Date.now() - ultimoTentativo < 15000) { riga({ t: "riuso" }); dati = leggiPrezzi(); }
      else { try { dati = await aggiornaPrezzi(riga); } catch (e) { riga({ t: "errore", testo: "errore nello scarico: " + e.message }); dati = leggiPrezzi(); dati.avvisi = (dati.avvisi || []).concat(["errore nello scarico: " + e.message]); dati.risposte = 0; } }
      riga({ t: "fine", dati });
    });
    return json({ errore: "non trovato" }, 404);
  }
  window.fetch = function (url, opts) {
    const u = typeof url === "string" ? url : url && url.url ? url.url : String(url);
    let p = null; try { const x = new URL(u, location.href); if (x.origin === location.origin && x.pathname.startsWith("/api/")) p = x.pathname; } catch (e) {}
    if (!p) return FETCH(url, opts);
    return api(p, ((opts && opts.method) || "GET").toUpperCase(), opts && opts.body);
  };

  // ---- il documento che la pagina riceve all'apertura (come /portafoglio.html del server)
  const MODELLO = { meta: { nome: "portafoglio", modello: true, descrizione: "Modello vuoto: carica un file JSON con la definizione di un portafoglio.", base: "", amount: 10000, rf: 0.02 }, funds: [], dates: [], px: {} };
  function doc() {
    const modello = () => JSON.parse(JSON.stringify(MODELLO));
    const bz = new URLSearchParams(location.search).get("bozza");
    if (bz) {  // bozza non salvata: nessun portafoglio segnato come ultimo
      try { const d = costruisciDaCache("bozza:" + bz); document.title = d.meta.nome + " · " + d.meta.versione + " (bozza)"; return d; }
      catch (e) { const m = modello(); m.meta.descrizione = e.mancano ? "La bozza non è più valida: riaprila dal portafoglio." : "Errore: " + e.message; return m; }
    }
    let pf = new URLSearchParams(location.search).get("pf") || ultimo();
    if (!pf || !info(pf)) return modello();
    segna(pf);
    try { const d = costruisciDaCache(pf); document.title = d.meta.nome + " · " + d.meta.versione; return d; }
    catch (e) { if (!e.mancano) { const m = modello(); m.meta.descrizione = "Errore: " + e.message; return m; } const m = modello(); m.meta.autocarica = pf; return m; }
  }
  // ---- widget: la pagina passa a Android valore, rendita e andamento; il widget li aggiorna da solo con i prezzi di justETF
  let ultimoWidget = "";
  function pubblicaWidget() {
    const W = plug("MyMoneyWidget"); if (!W || typeof F === "undefined" || typeof DATES === "undefined" || !F.length || (typeof META !== "undefined" && META.bozza)) return;  // una bozza non va sul widget
    try {
      const last = DATES.length - 1, hasPos = VAL > 0, q = (i) => (hasPos ? POS[i].q : F[i].q0);
      const pos = F.map((f, i) => ({ q: q(i), isin: f.isin, p: PX[i][last] })).filter((x) => x.q > 0);
      const val = hasPos ? VAL : sum(pos.map((x) => x.q * x.p));
      let i0 = 0, v = null, iv = null;  // serie del valore: dai tuoi acquisti se ci sono, altrimenti quella del piano su tutto lo storico
      if (hasPos) { const su = serieUtente(); if (su && su.val.length > 1) { v = su.val; iv = su.inv && su.inv.length === su.val.length ? su.inv : null; i0 = DATES.length - v.length; } }
      if (!v) { const s0 = statistiche(pesiPiano(), 0).v; v = s0.map((x) => (x / s0[s0.length - 1]) * val); }  // il piano è una rendita relativa: la serie è scalata in modo che oggi valga quanto il valore attuale
      const n = v.length, giorno = n > 1 ? v[n - 1] / v[n - 2] - 1 : null, ds = [], vs = [], is = [];
      v.forEach((x, k) => { if (k >= n - 400 || k % 5 === 0 || k === n - 1) { ds.push(DATES[i0 + k]); vs.push(Math.round(x * 100) / 100); if (iv) is.push(Math.round(iv[k] * 100) / 100); } });  // ultimi 400 giorni per intero, prima uno ogni cinque
      vs[vs.length - 1] = Math.round(val * 100) / 100;
      const d = { name: NOMEPF + " " + VERS, val: Math.round(val * 100) / 100, cost: hasPos && INV > 0 ? Math.round(INV * 100) / 100 : 0, real: Math.round(REAL * 100) / 100, day: giorno, ds, vs, ...(iv ? { is } : {}), pos, at: Date.now() };
      const files = typeof PF !== "undefined" && PF.lista && PF.lista.length ? PF.lista.map((x) => x.file) : null, s = JSON.stringify(d), firma = s + JSON.stringify(files);
      if (firma === ultimoWidget) return; ultimoWidget = firma;
      W.update({ data: s, file: (META && META.file) || "portafoglio", ...(files ? { files } : {}) }).catch(() => {});  // un portafoglio per volta; l'elenco serve a togliere dal widget quelli eliminati
    } catch (e) {}
  }
  setInterval(pubblicaWidget, 15000); setTimeout(pubblicaWidget, 3000); document.addEventListener("visibilitychange", () => { if (document.hidden) pubblicaWidget(); });
  // quando si torna nell'app (o ogni 5 minuti se resta aperta) i prezzi si riscaricano da justETF: non restano quelli di quando l'hai aperta
  let ultimoAuto = Date.now();
  const rinfresca = () => { if (typeof scaricaAuto === "function" && typeof SC !== "undefined" && !SC.aperta && Date.now() - ultimoAuto > 120000) { ultimoAuto = Date.now(); scaricaAuto(); } };
  document.addEventListener("visibilitychange", () => { if (!document.hidden) rinfresca(); });
  setInterval(() => { if (!document.hidden) rinfresca(); }, 300000);
  window.MOTORE = { doc, app: true, sincronizza };
})();

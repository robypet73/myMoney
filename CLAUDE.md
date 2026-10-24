# myMoney

Web app statica per cercare ETF e gestire portafogli (acquistati e draft). Un solo file, `index.html`, senza build né dipendenze. Si apre direttamente nel browser e gira su GitHub Pages.

## Come lavorare (automatico, senza chiedere)

- **All'inizio di ogni nuova chat** allinea subito la copia locale a `origin/main`: `git fetch origin main`, `git checkout main`, `git merge --ff-only origin/main` (il file `.claude/settings.json` lo fa già all'avvio della sessione). Se ci sono modifiche locali non salvate o la storia è divergente, risolvi tu in modo sicuro e continua: non chiedere conferma.
- Lavora **solo sul branch `main`**. Non creare branch né pull request, salvo richiesta esplicita.
- **Ogni modifica va committata e pushata su `origin main`**, subito e senza chiedere conferma:
  1. verifica (vedi "Verifica");
  2. bump della versione (vedi sotto) e commit con messaggio breve in italiano che inizia con la versione;
  3. `git push origin main` (se il push è rifiutato perché `main` è avanzato, fai `git pull --ff-only` o `git pull --rebase origin main` e riprova);
  4. se hai lo strumento Artifact, ripubblica `index.html` con lo stesso `file_path` per mantenere l'URL.
- **Versione dell'app**, formato `MM.mm.ppp` (major.minor.patch, per esempio `01.00.000`), mostrata in alto nella pagina sotto il logo. **Ogni aggiornamento fa bump patch** (`python3 scripts/bump.py`), salvo diversa indicazione dell'utente: `minor` (`bump.py minor`, azzera la patch) o `major` (`bump.py major`, azzera minor e patch). Il comando aggiorna `index.html` (`id="ver"`) e il nome della cache in `sw.js`. Il commit si intitola `vMM.mm.ppp: messaggio breve` e riceve il tag git `vMM.mm.ppp`, creato in automatico dal workflow `.github/workflows/tag.yml` quando `index.html` cambia versione (da qui `git push` dei tag è rifiutato: non pushare tag a mano). Gli aggiornamenti automatici dei dati (bot di GitHub Actions) non cambiano la versione. Versione di partenza: `01.00.000`.
- Rispondi in italiano, in modo breve: cosa hai cambiato, cosa hai verificato, cosa resta aperto.
- Non cancellare dati o branch senza richiesta.

## Verifica

- Sintassi dello script: estrai il contenuto di `<script>…</script>` in un file temporaneo e lancia `node --check`.
- Prova nel browser con Playwright headless (Chromium già installato in `/opt/pw-browsers`, libreria in `/opt/node-tools`), aprendo `file:///…/index.html` a 1100 px e a 390 px. Controlla che non ci siano errori di pagina e guarda uno screenshot.
- Scrivi i file temporanei nella cartella scratchpad della sessione, non nel repo.

## Regole di interfaccia

- **Tre soli livelli di font**, definiti in `:root`: `--fs-l` (grande, solo valori di sintesi importanti come il totale), `--fs-m` (medio, informazioni), `--fs-s` (piccolo, note, commenti, etichette). Non usare altre dimensioni in px.
- Stile minimale e moderno, **testo ridotto al minimo**. Niente spiegazioni inutili nella pagina.
- Lingua dell'interfaccia: italiano. Numeri in formato italiano (`fmt`, `pct`, `eur`).
- Colori solo da token CSS, con tema chiaro e scuro. Verde (`--up`) sopra il riferimento, rosso (`--down`) sotto, con leggera sfumatura sull'area.
- Layout adatto al telefono (390 px) senza scroll orizzontale della pagina.
- **Numeri**: valori in euro con 2 decimali (`eur`, `eurS`, `aumTxt`); prezzi per quota, bid e ask con 3 decimali; le operazioni si inseriscono con il numero di quote e il prezzo per quota **oppure** il prezzo totale. Nessuno «stato» del portafoglio (draft/acquistato) in vista.
- **Modifiche ai portafogli**: quantità, importo, data, ETF aggiunti/rimossi, titolo e descrizione restano in una copia fino a «Salva» (barra in basso, con «Annulla»); le azioni con un proprio pulsante (aggiungi/modifica/elimina operazione, applica ribilanciamento, registra acquisti) salvano subito. Cambiare portafoglio con modifiche in sospeso chiede conferma.
- **Movimenti**: aggiungendo un ETF (dalla ricerca) o premendo «Movimenti» sulla riga di una posizione si apre l'editor dei movimenti (acquisto/vendita, quote, data, prezzo medio o totale; più righe); l'editor delle posizioni esistenti ha «Salva». Il prezzo vuoto usa il prezzo di mercato del giorno, se i prezzi dell'ETF sono scaricati.
- **Grafici nel tempo**: sempre 1A, 3A e 5A (e Max); si nascondono solo i periodi più lunghi della storia disponibile (tolleranza 10 giorni).
- **Bid, ask e spread** nel dettaglio di ogni ETF: bid/ask dall'ultimo aggiornamento di Yahoo (`fetch_prices.py` ogni 30 minuti per i 14 di `prices.js`, `fetch_series.py` ogni sera per gli altri), spread calcolato in pagina; senza dato si mostra «—».

## Dati e fonti

- **Ogni dato mostrato porta il link alla sua fonte** (justETF per le anagrafiche, Yahoo Finance per i prezzi, articolo di origine per ogni previsione).
- Non inventare dati. Se una fonte non è raggiungibile (la rete dell'ambiente cloud blocca molti domini), segnalalo all'utente. I dati simulati o stimati devono essere sempre dichiarati come tali nella pagina ("simulato", "stime indicative").
- Prezzi: `scripts/fetch_prices.py` scarica da Yahoo Finance e scrive `prices.js` accanto a `index.html`; sceglie la quotazione in **EUR** (prova ticker e suffissi `.MI .AS .PA .DE`, scarta i fondi con nome diverso) e salva il nome del fondo. Il workflow `.github/workflows/prices.yml` lo esegue ogni 30 minuti nei giorni di borsa e a mano (Actions → Aggiorna prezzi → Run workflow), poi committa `prices.js` su `main`: **prima di ogni push fai `git pull --rebase origin main`**, perché il bot scrive su `main`. La pagina rilegge `prices.js` e, se Yahoo lo consente al browser, aggiorna le quotazioni ogni 30 s. Senza `prices.js` la pagina usa un NAV simulato. `--watch N` serve solo in locale.
- **Previsioni degli esperti: solo da fonti ufficiali** (siti e pubblicazioni delle banche: goldmansachs.com, morganstanley.com, jpmorgan.com / am.jpmorgan.com, ubs.com ecc.), mai da aggregatori o siti di cronaca. Oggetto `FC` in `index.html`, una voce per ticker, ognuna con banca, obiettivo o variazione indicata dalla fonte, orizzonte e URL. Si riferiscono all'indice dell'ETF; se non esiste una fonte ufficiale la pagina mostra «Nessuna previsione da fonte ufficiale trovata». Aggiornale con una ricerca web limitata a quei domini (`allowed_domains`) e riporta sempre il link.
- **Ricerca ETF**: si cerca per criteri: senza testo né filtri la lista è vuota (non si elenca tutto il catalogo). Filtri a selezione multipla (`FMULTI`) e a intervallo (`FRANGE`), ordinamento (`SORTS`, di default per patrimonio: con ~5.000 ETF il rendimento a 1 anno porta in cima prodotti a leva e cripto). Borse di quotazione in `EXCH` (da justETF, solo per i 14 dettagliati). Si cerca su `ALL` = `ETFS` (14 dettagliati con prezzi in `prices.js`) + `CAT` (tutto il resto del catalogo).
- **Catalogo completo (~5.000 ETF)**: `scripts/fetch_catalog.py` legge lo screener di justETF (pagine da 500, stesso dato che vede ogni visitatore) e scrive `catalog.js` (ISIN, nome, ticker, valuta, patrimonio, TER, dividendi, replica, domicilio, lancio, titoli, rendimenti 1S…5A in EUR, volatilità, drawdown; categoria e area dai filtri dello screener o dal nome). Workflow `.github/workflows/catalog.yml` ogni lunedì. Gli ETF di `CAT` non hanno serie di prezzi finché non esiste `data/p/ISIN.js`. Un sito statico non può interrogare justETF dal browser (niente CORS), per questo il catalogo è un file unico, aggiornato da GitHub e letto dalla cache del browser.
- **Serie di prezzi on demand**: `scripts/fetch_series.py` (workflow `series.yml`, ogni sera nei giorni di borsa e a ogni modifica di `watchlist.txt`) scarica 5 anni di prezzi giornalieri da Yahoo per i primi 150 ETF per patrimonio e per gli ISIN in `watchlist.txt`, li converte in EUR al cambio giornaliero e scrive `data/p/ISIN.js`; i simboli scelti stanno in `data/symbols.json`. **Monitoraggio**: se in «Portafogli» è salvato un token GitHub (fine-grained, Contents lettura/scrittura, solo in `localStorage` come `mm-gh-token`), ogni ETF di `CAT` aggiunto a un portafoglio viene scritto in `watchlist.txt` via API e il workflow ne scarica i prezzi. La pagina li carica solo quando servono (dettaglio, portafoglio); senza serie l'ETF resta fuori dal calcolo e la pagina rimanda a `watchlist.txt`.
- Liquidità (volume, spread) in `LIQ`: stime indicative finché non ci sono dati reali.
- **Anagrafica e composizione degli ETF: `scripts/fetch_etf_data.py`** legge le schede justETF (inglese per TER, patrimonio, replica, distribuzione, lancio, valuta, indice, numero di titoli e primi 10 titoli; italiana per paesi e settori) e scrive `etfdata.js`. Il workflow `.github/workflows/etf-data.yml` lo esegue ogni lunedì e a mano e committa su `main` (anche qui: `git pull --rebase` prima di ogni push). L'app usa `etfdata.js` quando c'è e ripiega sui valori scritti in `ETFS`. Restano scritti a mano solo le classificazioni (`asset`, `region`, `focus`), le borse (`EXCH`) e la liquidità (`LIQ`).
- **Dati degli ETF da fonti ufficiali con URL di verifica.** TER, patrimonio, replica, data di lancio e domicilio in `ETFS` vengono da justETF (`https://www.justetf.com/en/etf-profile.html?isin=ISIN`), prezzi da Yahoo Finance. Se non puoi aprire le pagine (rete bloccata), usa la ricerca web con `allowed_domains: ["justetf.com"]`, riporta la data della verifica (`VERIFIED`) e distingui sempre ciò che è verificato da ciò che è indicativo (posizioni, ripartizioni, numero di titoli).
- **Le spiegazioni «i»** stanno nell'oggetto `GL` (cos'è, a cosa serve, come si usa, parametri di riferimento, link). Ogni nuova informazione rilevante nella pagina deve avere la sua «i» (`ib("chiave")`) e una voce in `GL`; i link di approfondimento vanno presi da fonti reali e verificate.

## Modello dei portafogli (JSON)

```json
{ "version": 2, "portfolio": {
  "id": "…", "name": "…", "description": "…", "currency": "EUR",
  "amount": 10000, "start": "AAAA-MM-GG",
  "positions": [
    { "isin": "…", "weight": 40 },
    { "isin": "…", "qty": 12 },
    { "isin": "…", "transactions": [ { "date": "AAAA-MM-GG", "price": 100.5, "qty": 10 }, { "date": "AAAA-MM-GG", "price": 110, "qty": -4 } ] }
  ] } }
```

- Ogni portafoglio ha **posizioni**: ISIN + quantità **assoluta** (`qty`, quote) **oppure percentuale** (`weight`, % di `amount`), entrambe opzionali. In più, **operazioni opzionali e multiple** (`transactions`: data, prezzo, quantità; **quantità negativa = vendita**, non può superare le quote possedute).
- La quantità iniziale (`qty`/`weight`) si considera aperta alla data `start` (non prima del lancio dell'ETF) al prezzo di quel giorno; le operazioni si sommano. Senza operazioni il portafoglio è un **draft** (simulazione), con operazioni è **acquistato**.
- Un file JSON per portafoglio (`{version, portfolio}`); più portafogli insieme: `{version, portfolios: [...]}`. L'import accetta anche il formato precedente (`kind: owned` con `lots`, `kind: draft` con `items`).
- I portafogli dell'utente stanno in `localStorage` (`mm-portfolios-v1`), il predefinito in `mm-default`, i portafogli di prova nascosti in `mm-hidden`. I portafogli di prova (`sample: true`) non si modificano: la modifica crea una copia "(mio)"; eliminarli li nasconde (si ripristinano dalla scheda Portafogli). C'è sempre almeno un portafoglio.
- Scheda **Home**: portafoglio selezionato; sezione **Posizioni** (quantità + unità quote/%, aggiunta ETF) e **Dimensionamento**; in fondo lo **Storico** (grafico a aree impilate di valore e composizione nel tempo, modulo e tabella di acquisti e vendite); «Scarica JSON» del portafoglio. Scheda **Portafogli**: elenco con Apri, Ribilancia, Esporta, Elimina; «+ Nuovo portafoglio» crea un portafoglio vuoto con titolo e descrizione; JSON scaricabile (tutti o uno) e importabile. Dalla ricerca e dal dettaglio ETF si aggiunge a un portafoglio esistente o a uno nuovo (quantità o % e, facoltativi, data e prezzo).

## Struttura di `index.html`

CSS in alto (token, poi sezioni), poi markup (`#v-port` Home/portafoglio, `#v-search` ricerca, finestre `#detail` e `#addto`), poi lo script: dati `ETFS`, serie simulate, ricerca e filtri, dettaglio ETF, previsioni `FC`, motore del portafoglio (`pfBuild`, `pfStats`, `frontier`, `renderRb`), rendimenti live, draft, eventi.

## App installabile (PWA)

- File: `manifest.webmanifest`, `sw.js` (service worker, funziona offline), `icons/` (192, 512, maskable, SVG, apple-touch). Il tag `<link rel="manifest">`, le `meta` per tema e viewport e la registrazione del service worker sono in `index.html`.
- Se aggiungi file da tenere offline, mettili in `CORE` in `sw.js` e aumenta `VERSION`. Pagina e `prices.js` si scaricano sempre dalla rete se disponibile (dati freschi), la copia salvata serve solo senza rete.
- `prices.js` nel repo è un segnaposto (`window.PRICES = null`) che evita l'errore 404: `scripts/fetch_prices.py` lo sovrascrive.
- Verifica dell'installabilità: servire la cartella con `python3 -m http.server`, aprire con Playwright e chiamare `Page.getInstallabilityErrors` via CDP (l'unico errore ammesso è `in-incognito`).
- `index.html` inizia con `<!doctype html>`, `charset` e `viewport`: servono su Android/Pages. Non rimuoverli.

## GitHub Pages

Il sito si pubblica da `main`, cartella `/ (root)`: `https://robypet73.github.io/myMoney/`. Non servono passaggi di build.

# myMoney

Web app statica per cercare ETF e gestire portafogli (acquistati e draft). Un solo file, `index.html`, senza build né dipendenze. Si apre direttamente nel browser e gira su GitHub Pages.

## Come lavorare (automatico, senza chiedere)

- **All'inizio di ogni nuova chat** allinea subito la copia locale a `origin/main`: `git fetch origin main`, `git checkout main`, `git merge --ff-only origin/main` (il file `.claude/settings.json` lo fa già all'avvio della sessione). Se ci sono modifiche locali non salvate o la storia è divergente, risolvi tu in modo sicuro e continua: non chiedere conferma.
- Lavora **solo sul branch `main`**. Non creare branch né pull request, salvo richiesta esplicita.
- **Ogni modifica va committata e pushata su `origin main`**, subito e senza chiedere conferma:
  1. verifica (vedi "Verifica");
  2. commit con messaggio breve in italiano;
  3. `git push origin main` (se il push è rifiutato perché `main` è avanzato, fai `git pull --ff-only` o `git pull --rebase origin main` e riprova);
  4. se hai lo strumento Artifact, ripubblica `index.html` con lo stesso `file_path` per mantenere l'URL.
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

## Dati e fonti

- **Ogni dato mostrato porta il link alla sua fonte** (justETF per le anagrafiche, Yahoo Finance per i prezzi, articolo di origine per ogni previsione).
- Non inventare dati. Se una fonte non è raggiungibile (la rete dell'ambiente cloud blocca molti domini), segnalalo all'utente. I dati simulati o stimati devono essere sempre dichiarati come tali nella pagina ("simulato", "stime indicative").
- Prezzi: `scripts/fetch_prices.py` scarica da Yahoo Finance e scrive `prices.js` accanto a `index.html`; sceglie la quotazione in **EUR** (prova ticker e suffissi `.MI .AS .PA .DE`, scarta i fondi con nome diverso) e salva il nome del fondo. Il workflow `.github/workflows/prices.yml` lo esegue ogni 30 minuti nei giorni di borsa e a mano (Actions → Aggiorna prezzi → Run workflow), poi committa `prices.js` su `main`: **prima di ogni push fai `git pull --rebase origin main`**, perché il bot scrive su `main`. La pagina rilegge `prices.js` e, se Yahoo lo consente al browser, aggiorna le quotazioni ogni 30 s. Senza `prices.js` la pagina usa un NAV simulato. `--watch N` serve solo in locale.
- **Previsioni degli esperti: solo da fonti ufficiali** (siti e pubblicazioni delle banche: goldmansachs.com, morganstanley.com, jpmorgan.com / am.jpmorgan.com, ubs.com ecc.), mai da aggregatori o siti di cronaca. Oggetto `FC` in `index.html`, una voce per ticker, ognuna con banca, obiettivo o variazione indicata dalla fonte, orizzonte e URL. Si riferiscono all'indice dell'ETF; se non esiste una fonte ufficiale la pagina mostra «Nessuna previsione da fonte ufficiale trovata». Aggiornale con una ricerca web limitata a quei domini (`allowed_domains`) e riporta sempre il link.
- **Ricerca ETF**: filtri a selezione multipla (`FMULTI`) e a intervallo (`FRANGE`), ordinamento (`SORTS`, di default per rendimento a 1 anno). Borse di quotazione in `EXCH` (da justETF). L'universo è l'elenco `ETFS`: per ampliarlo servono dati da una fonte reale, non inventati.
- Liquidità (volume, spread) in `LIQ`: stime indicative finché non ci sono dati reali.
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

# myMoney

Web app statica per cercare ETF e gestire portafogli (acquistati e draft). Un solo file, `index.html`, senza build né dipendenze. Si apre direttamente nel browser e gira su GitHub Pages.

## Come lavorare (automatico)

- Lavora **solo sul branch `main`**. Non creare branch né pull request, salvo richiesta esplicita.
- Dopo ogni modifica, senza chiedere conferma:
  1. verifica (vedi "Verifica");
  2. commit con messaggio breve in italiano;
  3. `git push origin main`;
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
- Prezzi: `scripts/fetch_prices.py` scarica da Yahoo Finance e scrive `prices.js` accanto a `index.html` (`--watch N` aggiorna le quotazioni ogni N secondi). Senza `prices.js` la pagina usa un NAV simulato.
- Previsioni degli esperti: oggetto `FC` in `index.html`, una voce per ticker, ognuna con banca, obiettivo, orizzonte e URL. Aggiornale con una ricerca web e riporta sempre il link.
- Liquidità (volume, spread) in `LIQ`: stime indicative finché non ci sono dati reali.

## Modello dei portafogli (JSON)

```json
{ "version": 1, "portfolios": [
  { "id": "…", "name": "…", "currency": "EUR", "kind": "owned",
    "lots": [{ "isin": "…", "date": "AAAA-MM-GG", "qty": 10, "price": 100.5 }] },
  { "id": "…", "name": "…", "currency": "EUR", "kind": "draft",
    "amount": 10000, "start": "AAAA-MM-GG", "items": [{ "isin": "…", "weight": 40 }] }
] }
```

- `owned` (acquistato): lista di operazioni; una **quantità negativa è una vendita** e non può superare le quote possedute.
- `draft`: pesi target su un importo, simulati dalla data `start`; si può dimensionare e convertire in acquistato.
- I portafogli dell'utente stanno in `localStorage` (`mm-portfolios-v1`), il predefinito in `mm-default`. I portafogli di prova (`sample: true`) non si modificano: la modifica crea una copia "(mio)".

## Struttura di `index.html`

CSS in alto (token, poi sezioni), poi markup (`#v-port` portafoglio, `#v-search` ricerca, finestre `#detail` e `#addto`), poi lo script: dati `ETFS`, serie simulate, ricerca e filtri, dettaglio ETF, previsioni `FC`, motore del portafoglio (`pfBuild`, `pfStats`, `frontier`, `renderRb`), rendimenti live, draft, eventi.

## GitHub Pages

Il sito si pubblica da `main`, cartella `/ (root)`: `https://robypet73.github.io/myMoney/`. Non servono passaggi di build.

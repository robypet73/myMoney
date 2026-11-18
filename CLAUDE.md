# myMoney

App Python (server locale + pagina web + SQLite) che scarica da Yahoo Finance anagrafica e prezzi di ETF/ETC/ETN e propone portafogli (Sharpe, bilanciato, aggressivo). Il vecchio sito web è stato rimosso (resta nella storia git, fino al commit `e49a0e1`). Vedi `README.md`.

## Come lavorare

- Lavora **solo su `main`**, senza branch né pull request salvo richiesta. Ogni modifica: verifica, commit con messaggio breve in italiano, `git pull --rebase origin main`, `git push origin main`.
- Rispondi in italiano, in modo breve: cosa hai cambiato, cosa hai verificato, cosa resta aperto.
- File temporanei nella cartella scratchpad, non nel repo. Non committare `etf.db`, CSV o `impostazioni.json`.

## Struttura

- `mymoney.py` ingresso (server e pagina nel browser, o riga di comando), `build.py` programma unico con PyInstaller (in `dist/`, il database va accanto all'eseguibile: `BASE`/`sys._MEIPASS`; provato solo su Linux), `server.py` server HTTP su 127.0.0.1 con API JSON e un solo lavoro alla volta (`Job`), `web/index.html` pagina (HTML, CSS e JS senza librerie), `jobs.py` scarichi (Yahoo e justETF), `refdata.py` fonti dirette (registro ESMA, OpenFIGI, cambi BCE), `justetf.py` client justETF (solo lo screener, ~5.000 ETF con ISIN e caratteristiche), `yahoo.py` client Yahoo (solo `urllib`), `db.py` SQLite, `classify.py` classi dal nome, `portfolio.py` selezione e ottimizzazione (numpy + scipy), `selftest.py` prova senza rete.
- Yahoo: cookie da `fc.yahoo.com`, crumb da `getcrumb`, screener `POST /v1/finance/screener` (per borsa, 250 per pagina), `v7/finance/quote`, `v10/finance/quoteSummary`, `v8/finance/chart`. Risponde spesso 429 dall'ambiente cloud: `Yahoo.request` ritenta con attese crescenti e alterna `query1`/`query2`.

## ISIN e justETF

- **L'ISIN deve essere corretto: mai assegnarlo per ipotesi.** `etf.isin` si riempie solo in `Database.link_verified` da `isin_ref` (OpenFIGI `refdata.Figi`: ticker + suffisso Yahoo per borsa `FIGI_SUFFIX`), con `isin_src` = fonte (`figi`, e `+firds` se il registro ESMA `refdata.firds_list`, tabella `firds`, conferma che l'ISIN è attivo su quella borsa: `SUFFIX_MIC`), scartando i simboli contesi e i nomi incoerenti. Le ipotesi dal nome o dal ticker (`guess_by_name`, `guess_by_ticker`) vanno solo in `isin_guess`. Un database di versioni precedenti viene ripulito (gli ISIN senza `isin_src` diventano ipotesi).
- **Preferire fonti che danno i dati direttamente (JSON, CSV, API) a pagine da leggere**: Yahoo (JSON), OpenFIGI, ESMA FIRDS (Solr JSON, MIC in minuscolo: `etfp` = Borsa Italiana ETFplus, `xeta` = Xetra, `xpar`, `xams`; filtri `latest_received_flag:1` e `-status:term`), cambi BCE (SDMX CSV, `refdata.ecb_fx`), screener justETF (chiamata dati interna). Nessuna lettura di pagine HTML: se una fonte offre solo pagine, non si usa.
- Tabella `jetf` (per ISIN) = dati justETF; `apply_jetf` li copia solo nelle righe con `isin` verificato (hanno la precedenza su Yahoo; `class_src='justetf'` impedisce che nome o scheda Yahoo riscrivano la classe). Rendimenti 3 e 5 anni di justETF sono cumulati: si annualizzano (`ann`). `figi_done` evita di rifare le richieste OpenFIGI per 30 giorni.
- OpenFIGI: 25 richieste/minuto senza chiave (10 ISIN l'una), con `OPENFIGI_KEY` 100 ISIN l'una. Lo screener justETF è una chiamata Wicket (POST con colonne): se cambia, `JustETF.catalog` fallisce con «Elenco troppo corto». Se l'interfaccia ESMA cambia, `firds_list` fallisce con «Registro ESMA non raggiungibile».

## Una scheda per fondo, clessidra e avvisi

- `etf` = una riga per quotazione (simbolo Yahoo); la vista `fondo` (`db.VIEW`) è la **scheda unica per fondo** (chiave `COALESCE(isin, 'sym:'||symbol)`, quotazione preferita, `quotazioni`, `fonti`); l'esportazione CSV legge da lì. Se aggiungi colonne a `etf`, aggiungile alla vista.
- Ogni scaricamento mostra la clessidra (`#wait`) e, a fine lavoro, l'avviso (`#notice`) con `warnings` ed `error` di `Job`. **Ogni errore o dato mancante va segnalato con `y.warn(...)`** (raggruppato con `_examples`, non uno per titolo); gli errori che impediscono il lavoro sono eccezioni (`RuntimeError`) e `Streak` ferma dopo 5 errori di fila. Quanto scaricato si salva sempre (`commit`) prima di fallire.

## Verifica

- `python selftest.py` (serve numpy e scipy). La pagina si prova avviando `python mymoney.py --db PROVA.db --no-browser --porta 8799` (database con `selftest.make_db`) e Playwright a 1100 e 390 px: nessun errore di pagina né scroll orizzontale.
- Prova con rete reale: elenco di una borsa (`jobs.download_catalog`), poi `select` → `download_history` → `load_dataset` → `propose` su pochi titoli.

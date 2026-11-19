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

## Schermata Crea portafoglio

- Due schermate (`nav.main`): Archivio e Crea portafoglio. Quest'ultima interroga il database a ogni modifica (`/api/search` → `PF.search_summary`, con attesa di 350 ms) e mostra conteggi, classi e tabella; i criteri applicati dalla ricerca sono quelli di `PF.select`.
- **Ogni criterio ha la «i»** (`TEXTS` in `web/index.html`: cos'è, come si usa, soglie di riferimento). Un nuovo criterio o parametro deve avere il suo testo, e le soglie usate dal codice (`MINW`, `SHRINK`, `DR_GAIN`, `WINDOW_YEARS` di `portfolio.py`) arrivano alla pagina da `/api/info` (`rules`): non scriverle a mano nei testi. Le soglie «di riferimento» generiche (TER, spread, volume…) sono indicative e vanno dichiarate tali.
- Un solo titolo per fondo: chiave = ISIN verificato (le quotazioni senza ISIN dello stesso nome si uniscono solo se il nome ha un solo ISIN); due ISIN con lo stesso nome restano fondi diversi.

## Frontiera e portafogli salvati

- `PF.frontier` calcola la frontiera efficiente (rendimenti storici reali, stessi vincoli) sui fondi delle tre proposte; il risultato di `/api/propose` include `frontier` (fondi, punti con pesi `w`) e `criteria`. La pagina disegna il grafico in SVG (`drawFrontier`), il cursore e il clic selezionano un punto (`SEL`), importi e quote si ricalcolano nel browser (`fundsPort`).
- Portafogli salvati: file JSON `{version, saved_at, portfolio:{name, description, amount, source, data_period, criteria, metrics, classes, cash, positions[]}}` in `portafogli/` accanto al database (`pf_save`, `pf_list`, `pf_path`; nome unico, `id` = slug, nessun percorso arbitrario). Se cambi il formato, alza `version` e leggi anche i vecchi.

## Criteri: tutti vuoti, campi numerici e cursori sincronizzati

- Ogni intervallo (`RS`) ha **campo minimo e massimo numerici** (qualsiasi numero, virgola ammessa, `inFmt`) **sincronizzati con il cursore a gradini** (il campo non si arrotonda al gradino); anche i parametri singoli (`SS`) hanno campo + cursore; le selezioni restano multiple. **Tutto parte vuoto = `null` = nessun limite**: nei parametri di calcolo il valore usato se vuoto (importo 10000, ETF 3–8, peso minimo 3%, peso massimo 35%, tasso 2%, volatilità aggressivo 20%, titoli analizzati 150) si vede come placeholder e lo applica il server (`parse_create`, `dv`). Min > max segna il campo (`.bad`). Stato in localStorage `mm3`. Un nuovo criterio va aggiunto in `RS`/`SS`, in `PF.RANGE_COLS`/`PF.select` e in `TEXTS` (con la «i»).
- **Classi**: per ognuna minimo e massimo (`class_min`, `class_caps`; massimo 0 = esclusa); `PF.solve` ha il vincolo di minimo per classe (se una classe con minimo > 0 non c'è nei fondi, nessuna soluzione; `greedy_dr` parte con un fondo per classe con minimo). **Peso minimo per ETF** (`minw`) sostituisce `MINW` (default) in `prune`/`propose`/`frontier`; `check(p)` in `server.py` segnala combinazioni impossibili (minw·kmin>1, minw>cap, somma dei minimi>100%, minimo>cap).
- Il primo criterio sono `dr_min` (diversificazione minima) e `corr_max` (correlazione media **pesata** massima): vincoli di `PF.solve`, validi per le tre strategie e per la frontiera; se irraggiungibili il server spiega i limiti (`PF.limits`).
- **Numero di ETF**: `PF.prune` toglie i fondi fino a `kmax` e alla fine rifà il calcolo con peso minimo `MINW` per ogni fondo scelto: il numero effettivo è sempre tra `kmin` e `kmax`. La frontiera usa `prune` per ogni punto. Non ripristinare titoli a peso zero nei risultati.
- **Dati**: `load_dataset` corregge gli errori di Yahoo (`clean_series`), esclude i fondi con movimenti giornalieri > 50% (`MAX_MOVE`) e quelli giovani che accorciano la finestra sotto `MIN_WINDOW_YEARS`, e riporta tutto in `ds.notes` (mostrato nella pagina). I rendimenti a monte dei criteri vengono da `etf.ret_*`, `vol_*`, `max_dd` (justETF, Yahoo, `hist_stats`); `/api/returns` scarica lo storico dei fondi che ne sono privi.
- Gli assi del grafico della frontiera seguono la curva e le proposte, mai i singoli fondi.

## Storico dei prezzi: completo la prima volta, poi solo i giorni nuovi

- `jobs.download_history`: 5 anni la prima volta, poi **solo i giorni nuovi** (`Yahoo.history(since=…)`, 10 giorni di sovrapposizione) uniti con `Database.merge_prices`, che riallinea lo storico vecchio sul rapporto mediano nel periodo in comune (i prezzi aggiustati per i dividendi cambiano a ogni dividendo); senza sovrapposizione o con storico più vecchio di 300 giorni si riscarica tutto. `download_history_all` copre i fondi dell'archivio (la quotazione preferita della vista `fondo`, o tutte), dai più grandi; riprendibile (`max_age_days`).
- Dopo ogni scarico `_refresh_stats` ricalcola rendimenti, volatilità e perdita massima dallo storico salvato (`stats_src='hist'`); quelli justETF (`stats_src='justetf'`) hanno la precedenza e si riempiono solo i vuoti; il valore a 52 settimane di Yahoo (`ret_1y`) si scrive solo se non c'è una fonte migliore.

## Archivio: un solo pulsante, esportazione e controllo

- **Un solo pulsante di scaricamento** (`/api/sync` → `jobs.sync_all`): crea l'archivio se manca, altrimenti aggiorna in modo incrementale; quattro passi (elenco, justETF e ISIN, storico, schede), un passo che fallisce dà un avviso e non ferma gli altri (solo l'elenco fallito su archivio vuoto interrompe). Non reintrodurre nella pagina pulsanti o opzioni di scaricamento separati (restano le API e i comandi `storico`, `justetf`, `aggiorna` per la riga di comando).
- **Esporta/importa** (`server.db_export` / `db_import`): zip con `etf.db` (copia coerente con l'API di backup di SQLite) e `portafogli/*.json`; l'importazione controlla il file (`integrity_check`, tabelle `etf` e `prezzi`), tiene `etf.db.prima-dell-importazione`, sostituisce il file e aggiunge i portafogli mancanti. I comandi `backup` e `ripristina` agiscono prima di aprire il database (un file aperto non si sostituisce su Windows).
- **Controllo a campione** (`checks.py`, `/api/check`, comando `controlla`, rapporti in `controlli/`): confronta 15 fondi con Yahoo, justETF, registro ESMA, OpenFIGI e con la coerenza interna. Un confronto non fattibile è `skip`, mai `ok`. Un nuovo dato importante nell'archivio deve avere il suo controllo. `Database._legacy_cleanup` azzera i dati copiati su titoli con ISIN non verificato (archivi di versioni precedenti); `update_group` e `fill_groups` non propagano dati tra ISIN verificati diversi.

## Scheda di un fondo

- Ogni titolo mostrato (proposte, tabella dei candidati, portafogli salvati) si rende con `flink(symbol, testo)` e un clic apre la scheda (`openFund` → `/api/fund` → `server.fund_detail`, statistiche in `PF.fund_stats`): anagrafica, rendimenti dallo storico a confronto con quelli dell'archivio (`stats_src`), grafici con `lineChart` (asse verticale sui dati, mai forzato a 0; area sfumata verde sopra il livello di riferimento e rossa sotto, `ref`: prezzo a inizio periodo, 0 per la perdita), rendimento per anno, composizione, altre quotazioni. Un nuovo elenco di titoli deve usare `flink`. Senza storico la scheda offre `/api/fund/history`.

## Verifica

- `python selftest.py` (serve numpy e scipy). La pagina si prova avviando `python mymoney.py --db PROVA.db --no-browser --porta 8799` (database con `selftest.make_db`) e Playwright a 1100 e 390 px: nessun errore di pagina né scroll orizzontale.
- Prova con rete reale: elenco di una borsa (`jobs.download_catalog`), poi `select` → `download_history` → `load_dataset` → `propose` su pochi titoli.

# myMoney

App Python (server locale + pagina web + SQLite) che scarica da Yahoo Finance anagrafica e prezzi di ETF/ETC/ETN e propone portafogli (Sharpe, bilanciato, aggressivo). Il vecchio sito web è stato rimosso (resta nella storia git, fino al commit `e49a0e1`). Vedi `README.md`.

## Come lavorare

- Lavora **solo su `main`**, senza branch né pull request salvo richiesta. Ogni modifica: verifica, commit con messaggio breve in italiano, `git pull --rebase origin main`, `git push origin main`.
- Rispondi in italiano, in modo breve: cosa hai cambiato, cosa hai verificato, cosa resta aperto.
- File temporanei nella cartella scratchpad, non nel repo. Non committare `etf.db`, CSV o `impostazioni.json`.

## Struttura

- `mymoney.py` ingresso (server e pagina nel browser, o riga di comando), `server.py` server HTTP su 127.0.0.1 con API JSON e un solo lavoro alla volta (`Job`), `web/index.html` pagina (HTML, CSS e JS senza librerie), `jobs.py` scarichi (Yahoo e justETF), `justetf.py` client justETF (screener ~5.000 ETF con ISIN e caratteristiche, scheda del fondo con indice, titoli, paesi, settori), `yahoo.py` client Yahoo (solo `urllib`), `db.py` SQLite, `classify.py` classi dal nome, `portfolio.py` selezione e ottimizzazione (numpy + scipy), `selftest.py` prova senza rete.
- Yahoo: cookie da `fc.yahoo.com`, crumb da `getcrumb`, screener `POST /v1/finance/screener` (per borsa, 250 per pagina), `v7/finance/quote`, `v10/finance/quoteSummary`, `v8/finance/chart`. Risponde spesso 429 dall'ambiente cloud: `Yahoo.request` ritenta con attese crescenti e alterna `query1`/`query2`.

## justETF e ISIN

- Tabella `jetf` (per ISIN) = dati justETF; `Database.apply_jetf` li copia nelle righe `etf` con quell'ISIN (hanno la precedenza su Yahoo; `class_src='justetf'` impedisce che nome o scheda Yahoo riscrivano la classe). L'ISIN si assegna a `etf.isin` con `link_by_name` (group_key univoco), `link_by_ticker` (ticker uguale e nomi simili) e, a richiesta, con la ricerca Yahoo per ISIN (`isin_tried` evita di ripetere per 60 giorni). Rendimenti 3 e 5 anni di justETF sono cumulati: si annualizzano (`ann`).
- Lo screener justETF è una chiamata Wicket (POST con colonne): se cambia, `JustETF.catalog` fallisce con «Elenco troppo corto».

## Verifica

- `python selftest.py` (serve numpy e scipy). La pagina si prova avviando `python mymoney.py --db PROVA.db --no-browser --porta 8799` (database con `selftest.make_db`) e Playwright a 1100 e 390 px: nessun errore di pagina né scroll orizzontale.
- Prova con rete reale: elenco di una borsa (`jobs.download_catalog`), poi `select` → `download_history` → `load_dataset` → `propose` su pochi titoli.

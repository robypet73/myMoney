# myMoney

App Python (server locale + pagina web + SQLite) che scarica da Yahoo Finance anagrafica e prezzi di ETF/ETC/ETN e propone portafogli (Sharpe, bilanciato, aggressivo). Il vecchio sito web è stato rimosso (resta nella storia git, fino al commit `e49a0e1`). Vedi `README.md`.

## Come lavorare

- Lavora **solo su `main`**, senza branch né pull request salvo richiesta. Ogni modifica: verifica, commit con messaggio breve in italiano, `git pull --rebase origin main`, `git push origin main`.
- Rispondi in italiano, in modo breve: cosa hai cambiato, cosa hai verificato, cosa resta aperto.
- File temporanei nella cartella scratchpad, non nel repo. Non committare `etf.db`, CSV o `impostazioni.json`.

## Struttura

- `mymoney.py` ingresso (server e pagina nel browser, o riga di comando), `server.py` server HTTP su 127.0.0.1 con API JSON e un solo lavoro alla volta (`Job`), `web/index.html` pagina (HTML, CSS e JS senza librerie), `jobs.py` scarichi, `yahoo.py` client Yahoo (solo `urllib`), `db.py` SQLite, `classify.py` classi dal nome, `portfolio.py` selezione e ottimizzazione (numpy + scipy), `selftest.py` prova senza rete.
- Yahoo: cookie da `fc.yahoo.com`, crumb da `getcrumb`, screener `POST /v1/finance/screener` (per borsa, 250 per pagina), `v7/finance/quote`, `v10/finance/quoteSummary`, `v8/finance/chart`. Risponde spesso 429 dall'ambiente cloud: `Yahoo.request` ritenta con attese crescenti e alterna `query1`/`query2`.

## Verifica

- `python selftest.py` (serve numpy e scipy). La pagina si prova avviando `python mymoney.py --db PROVA.db --no-browser --porta 8799` (database con `selftest.make_db`) e Playwright a 1100 e 390 px: nessun errore di pagina né scroll orizzontale.
- Prova con rete reale: elenco di una borsa (`jobs.download_catalog`), poi `select` → `download_history` → `load_dataset` → `propose` su pochi titoli.

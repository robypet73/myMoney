# myMoney

App Python (Tkinter + SQLite) che scarica da Yahoo Finance anagrafica e prezzi di ETF/ETC/ETN e propone portafogli (Sharpe, bilanciato, aggressivo). Il vecchio sito web è stato rimosso (resta nella storia git, fino al commit `e49a0e1`). Vedi `README.md`.

## Come lavorare

- Lavora **solo su `main`**, senza branch né pull request salvo richiesta. Ogni modifica: verifica, commit con messaggio breve in italiano, `git pull --rebase origin main`, `git push origin main`.
- Rispondi in italiano, in modo breve: cosa hai cambiato, cosa hai verificato, cosa resta aperto.
- File temporanei nella cartella scratchpad, non nel repo. Non committare `etf.db`, CSV o `impostazioni.json`.

## Struttura

- `mymoney.py` ingresso (finestra o riga di comando), `app.py` finestra, `jobs.py` scarichi, `yahoo.py` client Yahoo (solo `urllib`), `db.py` SQLite, `classify.py` classi dal nome, `portfolio.py` selezione e ottimizzazione (numpy + scipy), `selftest.py` prova senza rete.
- Yahoo: cookie da `fc.yahoo.com`, crumb da `getcrumb`, screener `POST /v1/finance/screener` (per borsa, 250 per pagina), `v7/finance/quote`, `v10/finance/quoteSummary`, `v8/finance/chart`. Risponde spesso 429 dall'ambiente cloud: `Yahoo.request` ritenta con attese crescenti e alterna `query1`/`query2`.

## Verifica

- `python selftest.py` (serve numpy e scipy). La finestra si prova con `xvfb-run` (Tkinter: `apt install python3-tk`) e uno screenshot con `import -window root`.
- Prova con rete reale: elenco di una borsa (`jobs.download_catalog`), poi `select` → `download_history` → `load_dataset` → `propose` su pochi titoli.

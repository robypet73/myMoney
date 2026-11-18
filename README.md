# myMoney

App Python con interfaccia nel browser che scarica da Yahoo Finance l'anagrafica e i prezzi di ETF, ETC ed ETN, li salva in un database SQLite (`etf.db`) e propone tre portafogli: **Sharpe**, **bilanciato** e **aggressivo**.

## Installazione

Serve Python 3.9 o successivo.

```
pip install -r requirements.txt
python mymoney.py
```

Si apre il browser su `http://127.0.0.1:8765`. Il programma Python resta acceso nel terminale (Ctrl+C per chiuderlo): fa da ponte verso Yahoo, che non si può interrogare direttamente da una pagina web, e verso il database. Il server ascolta solo sul tuo computer. Opzioni: `--db FILE`, `--porta N`, `--no-browser`.

## Dove sono i dati

- **`etf.db`** (SQLite) nella cartella del programma: anagrafica dei titoli (tabella `etf`), prezzi giornalieri in EUR (`prezzi`) e cambi (`fx`). Per metterlo altrove: `python mymoney.py --db /percorso/etf.db` o la variabile `MYMONEY_DB`. Per salvarlo su Drive o altro, basta puntare la cartella lì. Per fare una copia, copia il file; per ripartire da zero, cancellalo.
- Le **impostazioni** della pagina (criteri, importo…) stanno nel browser (`localStorage`).
- I **CSV** (archivio e proposte) li scarica il browser nella cartella dei download.

## Uso

1. **Scarica elenco titoli**: tutti gli ETF/ETC/ETN delle borse scelte (Milano, Xetra, Parigi, Amsterdam, Londra, SIX) con nome, tipo, valuta, prezzo, bid, ask, spread, volume medio, TER e patrimonio quando Yahoo li dà, rendimento a 1 anno e data di primo scambio. Circa 2.300 titoli per Milano in meno di un minuto.
   *Facoltativo*: «Scarica anche le schede dei fondi» aggiunge la composizione (azioni, obbligazioni, liquidità) e completa TER e patrimonio. Una richiesta per fondo: può durare ore, ma si può interrompere e riprendere.
2. **Aggiorna prezzi attuali**: ultimo prezzo, bid, ask, volume.
3. **Scarica il CSV**: tutto il database, una riga per titolo (apribile in Excel).
4. **Crea portafoglio**: scegli importo, numero di ETF (minimo e massimo), peso massimo per ETF, massimi per classe (azionario, obbligazionario, materie prime…) e i criteri di ricerca. «Quanti titoli passano?» mostra il risultato dei criteri. «Calcola le proposte» scarica lo storico dei prezzi (5 anni, in EUR) dei soli titoli che passano i criteri e mostra le tre proposte con pesi, importi e quote intere; ognuna si salva in CSV.

Dalla riga di comando (utile per i download lunghi): `python mymoney.py scarica --borse MIL GER --schede`, `aggiorna`, `esporta etf.csv`, `info`.

## Come si calcolano le proposte

- Un solo titolo per fondo (lo stesso fondo quotato su più borse conta una volta: si preferisce EUR, poi la borsa nell'ordine scelto, poi il volume). Al massimo «Titoli analizzati» fondi, i più grandi per patrimonio.
- Prezzi di chiusura aggiustati (dividendi inclusi), convertiti in EUR al cambio del giorno. Rendimenti a 5 giorni sovrapposti, sulla finestra in comune dei titoli (al massimo 3 anni).
- **Sharpe**: massimo (rendimento − tasso privo di rischio) / volatilità, solo posizioni lunghe, con tetto per ETF e massimi per classe.
- **Bilanciato**: titoli scelti per diversificazione (rapporto di diversificazione, Choueifaty–Coignard 2008) e pesi a parità di rischio.
- **Aggressivo**: massimo rendimento con volatilità fino al limite scelto.
- Per scegliere i pesi i rendimenti storici sono portati per metà verso la media dei titoli (sono molto rumorosi); le cifre mostrate sono quelle storiche reali del portafoglio.
- Sono simulazioni sul passato, non previsioni né consulenza.

## Limiti

- Yahoo non ha l'ISIN: i titoli si identificano dal simbolo (es. `SWDA.MI`).
- Classe di attivo, area e distribuzione sono dedotte dal nome (e, con le schede, dalla composizione): possono sbagliare.
- Patrimonio e TER mancano per una parte dei titoli: un criterio su un dato mancante esclude il titolo, salvo la spunta «Includi i titoli senza il dato».
- Yahoo limita le richieste: se risponde 429 il programma aspetta e riprova da solo.

`python selftest.py` prova selezione e proposte con dati inventati, senza rete.

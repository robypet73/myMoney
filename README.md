# myMoney

Una sola pagina, **`portafoglio.html`**, da cui si fa tutto. Ogni portafoglio è un file **JSON** nella cartella **`portafogli/`**. Un piccolo programma Python apre la pagina con l'ultimo portafoglio caricato e scarica da **justETF** i dati dei titoli e i prezzi aggiornati.

| File / cartella | A cosa serve |
|---|---|
| `avvia.cmd` | doppio clic su Windows: lancia `build.py` |
| `build.py` | il programma: server locale (solo su 127.0.0.1), scarico da justETF, lettura e salvataggio dei portafogli |
| `fonti.py` | scarica da justETF i dati di un titolo (scheda del fondo e storico dei prezzi in euro) |
| `portafoglio.html` | **la pagina**: il codice di tutto; i dati del portafoglio scelto vengono inseriti dal programma |
| `portafogli/` | i portafogli: `nome_V1.json`, `nome_V2.json`… e lo schema |
| `portafogli/schema.json` | lo **schema JSON** (JSON Schema) del formato di un portafoglio |
| `portafogli/titoli/` | schede già complete dei titoli noti (caratteristiche e composizione); i prezzi si scaricano sempre |
| `icons/` | l'icona dell'app |

Serve Python 3.9 o più recente, nient'altro.

## Uso

1. `avvia.cmd` (oppure `python build.py`). Si apre `portafoglio.html` con **l'ultimo portafoglio caricato** (`--file nome_V1.json` per forzarne uno). Dal menu «Portafoglio» in alto si passa a qualsiasi altro JSON della cartella.
2. **All'apertura parte da solo il download** dei prezzi da justETF (lo stato compare sotto i pulsanti). Alla prima apertura di un portafoglio, o in un giorno nuovo, il programma scarica anche scheda e storico dei suoi titoli: una finestra mostra l'avanzamento, poi la pagina si apre.
3. **Aggiorna i valori**: rifà lo scarico dei prezzi quando vuoi (finestra con l'avanzamento).
4. **Carica portafoglio (JSON)**: scegli un file nel formato qui sotto. Il programma lo salva in `portafogli/` (nome e versione esistenti non si sovrascrivono: cambia la versione), scarica i dati dei titoli e apre il portafoglio.
5. **Salva**: dalla composizione («Salva il portafoglio…») o dalla frontiera efficiente («Salva come nuovo portafoglio…») si scrive un nuovo `nome_Vn.json` in `portafogli/`, con nome (solo lettere e cifre), versione (1, 2, 3…) e descrizione.
6. **Elimina**: cancella il JSON del portafoglio aperto (chiede conferma).
7. **Scarica JSON**: esporta la definizione del portafoglio aperto (con i vincoli della frontiera).

## Formato di un portafoglio

Lo schema è in [`portafogli/schema.json`](portafogli/schema.json). Esempio (`portafogli/esempio_V1.json`):

```json
{
  "$schema": "schema.json",
  "nome": "mioPortafoglio",
  "versione": "V1",
  "descrizione": "Una frase che spiega il portafoglio",
  "valore": 40000,
  "titoli": [
    {"isin": "IE00B4L5Y983", "peso": 60},
    {"isin": "IE00B1FZS798", "peso": 40}
  ],
  "vincoli": {
    "fondi": { "IE00B4L5Y983": [40, 70] },
    "classi": { "Azionario": [50, 80] }
  }
}
```

| Campo | Regola |
|---|---|
| `nome` | obbligatorio; solo lettere e cifre (niente spazi né simboli), al massimo 30 caratteri; il file si chiama `nome_Vn.json` |
| `versione` | obbligatoria; `V1`, `V2`, `V3`… (anche solo il numero) |
| `descrizione` | obbligatoria; al massimo 300 caratteri |
| `valore` | **facoltativo**; investimento totale in euro da ripartire sui pesi (se manca: 10.000) |
| `titoli` | da 1 a 30 elementi `{ "isin", "peso" }`; ISIN con cifra di controllo valida, non ripetuto; `peso` in percentuale, la somma deve dare 100 (tolleranza 0,5) |
| `vincoli` | **facoltativo**; limiti iniziali della frontiera in percentuale, `[minimo, massimo]`: `fondi` per ISIN e `classi` (`Azionario`, `Obbligazionario`, `Materie prime`). Se manca: peso del piano ±10 punti per fondo |

## Dove stanno i dati

- **`portafogli/`** (nel repository): i JSON dei portafogli, lo schema e le schede note dei titoli (`titoli/<ISIN>.json`).
- **Cartella dell'utente** (`%LOCALAPPDATA%\myMoney`, oppure `~/.myMoney`): `prezzi.json` (ultimo scarico), `ultimo.json` (ultimo portafoglio aperto) e `titoli/<ISIN>.json` (scheda e storico dei prezzi scaricati oggi da justETF).
- Gli acquisti inseriti nella pagina restano nel browser, separati per portafoglio.
- Nessun database.

## Limiti da conoscere

- Tutti i prezzi vengono da justETF, in euro: possono differire di qualche centesimo da Borsa Italiana.
- Per un ISIN non presente in `portafogli/titoli/` la composizione viene dalla pagina di justETF, che elenca solo i primi paesi, settori e titoli: la quota restante finisce in «Altro». Aree geografiche e valute sono stimate dai paesi. «Scambi medi a Milano» non è disponibile per questi titoli («n.d.»).
- Lo storico in comune parte dal titolo con la storia più breve.
- Analisi tecnica sui dati storici, non consulenza.

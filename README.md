# myMoney

Ogni portafoglio è **una pagina HTML** con tutto dentro (prezzi, caratteristiche e composizione dei titoli). Un piccolo programma Python la apre nel browser, scarica i prezzi aggiornati e crea nuovi portafogli.

| File | A cosa serve |
|---|---|
| `avvia.cmd` | doppio clic su Windows: lancia `build.py` |
| `build.py` | il programma: server locale (solo su 127.0.0.1), scarico dei prezzi, creazione e salvataggio dei portafogli |
| `fonti.py` | scarica da justETF i dati di un titolo (scheda del fondo e storico dei prezzi in euro) |
| `portafoglio.html` | **il modello**: il codice di ogni pagina, senza dati |
| `portafoglio.json` | un esempio del **formato di definizione** di un portafoglio |
| `francesca.html`, `nome_V2.html`… | i portafogli (uno per file) |

Serve Python 3.9 o più recente, nient'altro.

## Uso

1. `avvia.cmd` (oppure `python build.py`). Si apre l'**ultimo portafoglio aperto**; dal menu «Portafoglio» in alto si passa a qualsiasi altro HTML della cartella (`--file nome.html` per forzarne uno).
2. **Carica portafoglio (JSON)**: scegli un file nel formato qui sotto. Il programma scarica i dati dei titoli che non ha già (scheda del fondo e storico dei prezzi da justETF), poi crea `nome_Vn.html` e lo apre. Se nome e versione esistono già, non sovrascrive: cambia la versione.
3. **Aggiorna i valori**: scarica i prezzi nuovi (finestra con la clessidra e i dati che scorrono).
4. **Salva**: dalla composizione («Salva il portafoglio…», con l'importo totale ripartito sui pesi) o dalla frontiera efficiente («Salva come nuovo portafoglio…», con i pesi del punto scelto) si crea `nome_Vn.html`: nome (solo lettere e cifre), versione (1, 2, 3…) e descrizione.
5. **Scarica JSON**: esporta la definizione del portafoglio aperto, per ricaricarla o condividerla.

Se cambia il codice del modello, `python build.py --rigenera` riscrive tutti i portafogli con il codice nuovo, senza toccare i loro dati.

## Formato `portafoglio.json`

```json
{
  "nome": "mioPortafoglio",
  "versione": "V1",
  "descrizione": "Una frase che spiega il portafoglio",
  "valore": 40000,
  "titoli": [
    { "isin": "IE00B4L5Y983", "peso": 60 },
    { "isin": "IE00B1FZS798", "peso": 40 }
  ]
}
```

| Campo | Regola |
|---|---|
| `nome` | obbligatorio; solo lettere e cifre (niente spazi né simboli), al massimo 30 caratteri; è il nome del file |
| `versione` | obbligatoria; `V1`, `V2`, `V3`… (anche solo il numero) |
| `descrizione` | obbligatoria; al massimo 300 caratteri |
| `valore` | **facoltativo**; investimento totale in euro da ripartire sui pesi (se manca: 10.000) |
| `titoli` | da 1 a 30 elementi `{ "isin", "peso" }`; ISIN con cifra di controllo valida, non ripetuto; `peso` in percentuale, la somma deve dare 100 (tolleranza 0,5) |

Il file creato si chiama `nome_Vn.html` (per esempio `mioPortafoglio_V1.html`).

## Dove stanno i dati

- Dentro ogni HTML: prezzi storici, caratteristiche e composizione dei suoi titoli.
- Cartella dell'utente (`%LOCALAPPDATA%\myMoney`, oppure `~/.myMoney`): `prezzi.json` (ultimo scarico), `ultimo.json` (ultimo portafoglio aperto) e `titoli/<ISIN>.json` (scheda dei titoli già scaricati da justETF, riusata dai portafogli nuovi).
- Gli acquisti inseriti nella pagina restano nel browser, separati per portafoglio.
- Nessun database.

## Limiti da conoscere

- I titoli già presenti in un portafoglio (per esempio gli otto di `francesca.html`) hanno composizione completa. Per un ISIN nuovo la composizione viene dalla pagina di justETF, che elenca solo i primi paesi, settori e titoli: la quota restante finisce in «Altro». Aree geografiche e valute sono stimate dai paesi.
- I prezzi dei titoli nuovi sono quelli di justETF in euro (possono differire di qualche centesimo da Borsa Italiana); per i titoli senza simbolo di Borsa Italiana l'aggiornamento viene sempre da justETF.
- «Scambi medi a Milano» non è disponibile per i titoli nuovi («n.d.»).
- Analisi tecnica sui dati storici, non consulenza.

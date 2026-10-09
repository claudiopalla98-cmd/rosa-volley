# Comunello Volley Rosà · sito e dati

Sito non ufficiale del campionato FIPAV Vicenza (Seconda divisione maschile) e fonte dati dell'app iPhone.

```
Pagina FIPAV "risultati-classifiche"  ->  scraper.py (GitHub Actions, ogni 5 min)
                                      ->  dati.json + index.html su GitHub Pages
                                      ->  sito e app iPhone (rileggono ogni 5 min)
```

- `scraper.py` legge solo la pagina desktop `risultati-classifiche` (la pagina `/mobile/` non è consentita dal robots.txt).
- Se la lettura fallisce, non pubblica niente: resta online l'ultima versione buona.
- `aggiornato` cambia solo quando cambiano i dati; se non cambia niente il sito non viene ripubblicato.
- `squadre.json`: dati fissi delle squadre (palestra, indirizzo, coordinate). La prima squadra è quella seguita dall'app.

Prova in locale: `pip install -r requirements.txt && python scraper.py dati.json`

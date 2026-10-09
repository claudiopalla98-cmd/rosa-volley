"""
Scraper del campionato FIPAV Vicenza per il sito e l'app del Comunello Volley Rosà.

Legge UNA sola pagina, quella desktop "risultati-classifiche" (consentita dal robots.txt
del sito; la pagina /mobile/risultati.asp invece NON è consentita e non va usata),
e scrive dati.json con squadre, partite (con set e parziali) e classifica ufficiale.

Regole:
- se il sito non risponde o la pagina non si legge bene, lo script si ferma con errore
  e NON scrive niente: online resta l'ultima versione buona di dati.json;
- "aggiornato" cambia solo quando cambiano davvero i dati, così sito e app
  ridisegnano solo se serve.
"""

import html
import json
import os
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------- IMPOSTAZIONI -----------------------------------------------------
STAGIONE_ID = "2388"          # Stagione Sportiva 2026 / 2027
CAMPIONATO_ID = "93505"       # Seconda divisione maschile girone unico
URL = (
    "https://www.fipavvicenza.it/risultati-classifiche"
    f"?ComitatoId=8&StId={STAGIONE_ID}&DataDa=&StatoGara=&CId={CAMPIONATO_ID}&SId=&btFiltro=CERCA"
)
BASE = "https://www.fipavvicenza.it"
FILE_SQUADRE = Path("squadre.json")
USCITA = Path(sys.argv[1] if len(sys.argv) > 1 else "site/dati.json")
ROMA = ZoneInfo("Europe/Rome")
# -----------------------------------------------------------------------------

SESSIONE = requests.Session()
SESSIONE.headers.update({"User-Agent": "Mozilla/5.0 (compatible; RosaVolleyScraper/1.0)"})
SESSIONE.mount("https://", HTTPAdapter(max_retries=Retry(
    total=3, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])))


def pulisci(testo: str) -> str:
    return re.sub(r"\s+", " ", (testo or "").replace("\xa0", " ")).strip()


def chiave(nome: str) -> str:
    """Nome confrontabile: maiuscolo, senza accenti né apostrofi."""
    n = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]", "", n.upper())


def leggi_pagina(sorgente: str | None = None) -> BeautifulSoup:
    if sorgente:                                  # per le prove in locale
        return BeautifulSoup(Path(sorgente).read_bytes(), "html.parser")
    r = SESSIONE.get(URL, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.content, "html.parser")


def leggi_impianto(td) -> dict | None:
    """Il fumetto 'info' contiene: <b>NOME</b><br/>LOCALITÀ<br/>VIA."""
    img = td.find("img", alt="info") if td else None
    titolo = html.unescape(img.get("title", "")) if img else ""
    if not titolo.strip():
        return None
    righe = [pulisci(BeautifulSoup(p, "html.parser").get_text()) for p in re.split(r"<br\s*/?>", titolo)]
    righe = [r for r in righe if r]
    if not righe:
        return None
    return {"nome": righe[0].title(), "indirizzo": ", ".join(r.title() for r in righe[1:])}


def leggi_squadra(td) -> tuple[str, str | None]:
    img = td.find("img")
    logo = BASE + img["src"] if img and img.get("src") else None
    return pulisci(td.get_text()), logo


def leggi_partite(pagina: BeautifulSoup) -> tuple[str, list[dict]]:
    tabella = pagina.select_one("table.tbl-risultati")
    if tabella is None:
        raise SystemExit("Tabella delle partite non trovata: la pagina FIPAV è cambiata?")
    titolo = pulisci(tabella.caption.get_text()) if tabella.caption else ""
    partite = []
    for riga in tabella.find_all("tr"):
        c = riga.find_all("td", recursive=False)
        if len(c) < 8:
            continue
        cella_ris = riga.select_one("td.risultato")
        id_gara = (cella_ris.get("id", "").split("_")[-1]) if cella_ris else ""
        quando = pulisci(c[2].get_text())
        m = re.match(r"(\d{2})/(\d{2})/(\d{2,4})\s+(\d{1,2}):(\d{2})", quando)
        if not m or not id_gara:
            continue                                  # data non ancora fissata
        g, mese, anno, ora, minuti = m.groups()
        anno = int(anno) + (2000 if len(anno) == 2 else 0)
        casa, logo_casa = leggi_squadra(c[3])
        ospite, logo_ospite = leggi_squadra(c[4])

        partita = {
            "id": id_gara,
            "n": int(pulisci(c[0].get_text()) or 0),
            "g": int(pulisci(c[1].get_text()) or 0),
            "d": f"{anno:04d}-{int(mese):02d}-{int(g):02d}T{int(ora):02d}:{minuti}",
            "casa": casa, "ospite": ospite,
            "logo_casa": logo_casa, "logo_ospite": logo_ospite,
        }
        ris = re.match(r"(\d+)\s*-\s*(\d+)", pulisci(cella_ris.get_text()) if cella_ris else "")
        if ris:
            partita["s"] = [int(ris.group(1)), int(ris.group(2))]
            parziali = []
            for span in riga.select("td.risultato-dettagli .parziali"):
                p = re.match(r"(\d+)\s*-\s*(\d+)", pulisci(span.get_text()))
                if p:
                    parziali.append([int(p.group(1)), int(p.group(2))])
            if parziali:
                partita["p"] = parziali
        stato = riga.select_one("span[id^=StatoGara_] img")
        if stato and stato.get("title"):
            partita["stato"] = pulisci(stato["title"])
        imp = leggi_impianto(c[7])
        if imp:
            partita["imp"] = imp
        partite.append(partita)
    if not partite:
        raise SystemExit("Nessuna partita letta: file NON aggiornato.")
    return titolo, partite


def leggi_classifica(pagina: BeautifulSoup) -> list[dict]:
    tabella = pagina.select_one("table.tbl-classifica")
    righe = []
    if tabella is None:
        return righe
    numero = lambda t: float(pulisci(t).replace(",", ".") or 0)
    for r in tabella.find_all("tr"):
        c = r.find_all("td", recursive=False)
        if len(c) < 13:
            continue
        righe.append({
            "nome": pulisci(c[1].get_text()),
            "pt": int(numero(c[2].get_text())), "g": int(numero(c[3].get_text())),
            "v": int(numero(c[4].get_text())), "p": int(numero(c[5].get_text())),
            "sf": int(numero(c[6].get_text())), "ss": int(numero(c[7].get_text())),
            "qs": numero(c[8].get_text()), "pf": int(numero(c[9].get_text())),
            "ps": int(numero(c[10].get_text())), "qp": numero(c[11].get_text()),
            "pen": int(numero(c[12].get_text())),
        })
    return righe


def costruisci(pagina: BeautifulSoup) -> dict:
    config = json.loads(FILE_SQUADRE.read_text(encoding="utf-8"))["squadre"]
    squadre = [dict(s) for s in config]
    indice = {chiave(s["fipav"]): i for i, s in enumerate(squadre)}

    titolo, grezze = leggi_partite(pagina)

    def trova(nome: str, logo: str | None) -> int:
        k = chiave(nome)
        if k not in indice:                            # squadra nuova: la aggiungo in fondo
            indice[k] = len(squadre)
            squadre.append({"fipav": nome, "nome": nome.title(), "impianto": "", "indirizzo": "",
                            "la": None, "lo": None})
            print(f"[!] Squadra non presente in squadre.json: {nome}")
        i = indice[k]
        if logo and not squadre[i].get("logo"):
            squadre[i]["logo"] = logo
        return i

    partite = []
    for p in grezze:
        h = trova(p["casa"], p["logo_casa"])
        a = trova(p["ospite"], p["logo_ospite"])
        voce = {"id": p["id"], "n": p["n"], "g": p["g"], "d": p["d"], "h": h, "a": a, "r": p.get("stato", "")}
        for k in ("s", "p"):
            if k in p:
                voce[k] = p[k]
        # palestra diversa da quella abituale della squadra di casa (es. campo spostato)
        imp = p.get("imp")
        if imp and squadre[h]["impianto"] and chiave(imp["nome"]) not in chiave(squadre[h]["impianto"]):
            voce["imp"] = imp
        partite.append(voce)
    partite.sort(key=lambda x: (x["g"], x["d"]))

    classifica = []
    for r in leggi_classifica(pagina):
        sq = trova(r.pop("nome"), None)
        classifica.append({"sq": sq, **r})

    for s in squadre:
        s.pop("fipav", None)

    return {
        "campionato": titolo.title() if titolo else "",
        "squadre": squadre,
        "partite": partite,
        "classifica": classifica,
    }


def main() -> None:
    sorgente = sys.argv[2] if len(sys.argv) > 2 else None
    dati = costruisci(leggi_pagina(sorgente))

    # "aggiornato" cambia solo se i dati sono cambiati rispetto alla versione online
    precedente = None
    url_precedente = os.environ.get("URL_PRECEDENTE")   # lo passa il workflow di GitHub
    try:
        if url_precedente and sorgente is None:
            r = SESSIONE.get(url_precedente, timeout=15)
            if r.ok:
                precedente = r.json()
    except Exception:
        pass
    cambiato = not (precedente and {k: v for k, v in precedente.items() if k != "aggiornato"} == dati)
    if cambiato:
        dati["aggiornato"] = datetime.now(ROMA).isoformat(timespec="seconds")
    else:
        dati["aggiornato"] = precedente["aggiornato"]
        print("Nessun cambiamento rispetto alla versione online.")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"cambiato={'true' if cambiato else 'false'}\n")

    USCITA.parent.mkdir(parents=True, exist_ok=True)
    USCITA.write_text(json.dumps(dati, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    giocate = sum(1 for p in dati["partite"] if "s" in p)
    print(f"OK: {len(dati['partite'])} partite ({giocate} giocate), "
          f"{len(dati['classifica'])} righe di classifica -> {USCITA}")


if __name__ == "__main__":
    main()

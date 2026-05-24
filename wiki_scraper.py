import asyncio
import aiohttp
import pandas as pd
import json
import logging
import os
import argparse
import random
import re
from datetime import datetime
from typing import Optional, List, Dict
from tqdm.asyncio import tqdm
from colorama import Fore, Style, init

init(autoreset=True)

# ── KONFIGURACJA ───────────────────────────────────────────────────────────
CONFIG = {
    "API_URL":          "https://pl.wikipedia.org/w/api.php",

    # Wydajność – zgodnie z polityką Wikimedia:
    # max 200 tytułów na zapytanie, max ~200 req/s dla anonimowych
    "PAGE_SIZE":         50,       # Artykułów na stronę (max 500 dla allpages)
    "DETAIL_BATCH":      20,       # Ile artykułów pobierać szczegółowo naraz
    "CONCURRENT":        5,        # Równoległe requesty
    "DELAY_MIN":         0.05,     # Minimalne opóźnienie [s]
    "DELAY_MAX":         0.15,     # Maksymalne opóźnienie [s]
    "REQUEST_TIMEOUT":   30,
    "MAX_RETRIES":       5,

    # Zapis
    "SAVE_EVERY":        5_000,    # Checkpoint co N artykułów
    "OUTPUT_DIR":        "wiki_output",
    "PROGRESS_FILE":     "wiki_output/progress.json",
    "LOG_FILE":          "wiki_output/wiki_scraper.log",
    "CHECKPOINT_PREFIX": "wiki_output/checkpoint_",
    "FINAL_FILE":        "wiki_output/WIKIPEDIA_PL_",

    "NAMESPACE":         0,
}

HEADERS = {
    "User-Agent": (
        "WikiScraper/1.0 (https://github.com/zanae; damian@example.com) "
        "aiohttp/3.9 Python/3.11"
    ),
    "Accept":          "application/json",
    "Accept-Encoding": "gzip, deflate",
}


# ── LOGOWANIE ──────────────────────────────────────────────────────────────
def setup_logging(log_file: str) -> logging.Logger:
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    logger = logging.getLogger("WikiScraper")
    logger.setLevel(logging.DEBUG)

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


# ── POSTĘP ─────────────────────────────────────────────────────────────────
class ProgressManager:
    """Zapis/odczyt stanu pobierania – umożliwia wznowienie po przerwie."""

    def __init__(self, path: str):
        self.path = path
        self.data = self._load()

    def _load(self) -> Dict:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "start_time":    datetime.now().isoformat(),
            "apcontinue":    None,   
            "pobrano":       0,
            "bledow":        0,
            "checkpointy":   [],
        }

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)


# ── PARSOWANIE ARTYKUŁU ────────────────────────────────────────────────────
def parsuj_artykul(dane: Dict) -> Dict:
    """
    Zamienia surowy JSON z API Wikimedia na płaski słownik z polami do Excela.
    Pobiera wszystkie dostępne metadane + czysty tekst bez znaczników wiki.
    """
    wynik = {
        "pageid":           None,
        "tytul":            None,
        "url":              None,
        "dlugosc_bajtow":   None,
        "liczba_slow":      None,
        "opis_krotki":      None,    
        "tresc_skrot":      None,    
        "sekcje":           None,    # Lista sekcji (nagłówki)
        "kategorie":        None,    # Lista kategorii
        "linki_wewn":       None,    # Liczba linków wewnętrznych
        "linki_zewn":       None,    # Liczba linków zewnętrznych
        "obrazy":           None,    # Lista obrazów w artykule
        "wspolrzedne_lat":  None,    # Geolokalizacja (jeśli jest)
        "wspolrzedne_lon":  None,
        "data_utworzenia":  None,
        "data_ostatniej_edycji": None,
        "liczba_edycji":    None,
        "liczba_autorow":   None,
        "rozmiar_kb":       None,
        "czy_stub":         None,    # Czy artykuł-zalążek
        "jezyki_wersji":    None,    # Ile wersji językowych
        "data_pobrania":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    try:
        wynik["pageid"]  = dane.get("pageid")
        wynik["tytul"]   = dane.get("title")
        wynik["url"]     = f"https://pl.wikipedia.org/wiki/{dane.get('title', '').replace(' ', '_')}"
        wynik["dlugosc_bajtow"] = dane.get("length")
        wynik["rozmiar_kb"]     = round(dane.get("length", 0) / 1024, 2)

        # Opis krótki (Wikidata)
        terms = dane.get("terms", {})
        opisy = terms.get("description", [])
        wynik["opis_krotki"] = opisy[0] if opisy else None

        # Tekst artykułu – czyścimy ze znaczników wiki
        extract = dane.get("extract", "")
        if extract:
            # Usuwamy nadmiarowe białe znaki
            tekst_czysty = re.sub(r'\n{3,}', '\n\n', extract).strip()
            wynik["tresc_skrot"] = tekst_czysty[:1500]
            wynik["liczba_slow"] = len(tekst_czysty.split())

        # Sekcje (nagłówki)
        sekcje = dane.get("sections", [])
        if sekcje:
            wynik["sekcje"] = " | ".join(
                s.get("line", "") for s in sekcje[:20] if s.get("line")
            )

        # Kategorie
        kategorie = dane.get("categories", [])
        if kategorie:
            nazwy_kat = [
                k.get("title", "").replace("Kategoria:", "")
                for k in kategorie[:30]
            ]
            wynik["kategorie"] = "; ".join(nazwy_kat)

        # Linki wewnętrzne
        linki = dane.get("links", [])
        wynik["linki_wewn"] = len(linki)

        # Linki zewnętrzne
        linki_zewn = dane.get("extlinks", [])
        wynik["linki_zewn"] = len(linki_zewn)

        # Obrazy
        obrazy = dane.get("images", [])
        if obrazy:
            wynik["obrazy"] = "; ".join(
                img.get("title", "").replace("Plik:", "")
                for img in obrazy[:10]
            )

        # Współrzędne geograficzne
        coords = dane.get("coordinates", [])
        if coords:
            wynik["wspolrzedne_lat"] = coords[0].get("lat")
            wynik["wspolrzedne_lon"] = coords[0].get("lon")

        # Daty i statystyki edycji
        revisions = dane.get("revisions", [])
        if revisions:
            wynik["data_ostatniej_edycji"] = revisions[0].get("timestamp", "")[:10]

        # Info o pierwszej rewizji (data utworzenia)
        first_rev = dane.get("first_revision", {})
        if first_rev:
            wynik["data_utworzenia"] = first_rev.get("timestamp", "")[:10]

        wynik["liczba_edycji"]  = dane.get("revcount")
        wynik["liczba_autorow"] = dane.get("authorcount")

        # Wersje językowe
        langlinks = dane.get("langlinks", [])
        wynik["jezyki_wersji"] = len(langlinks) + 1  # +1 za polski

        # Czy zalążek (stub) – po kategorii
        kat_str = wynik.get("kategorie", "") or ""
        wynik["czy_stub"] = "Tak" if "zalążek" in kat_str.lower() else "Nie"

    except Exception as e:
        wynik["_blad"] = str(e)

    return wynik


# ── KLIENT API ─────────────────────────────────────────────────────────────
class WikiApiClient:
    """Asynchroniczny klient Wikimedia API z retry i rate limitingiem."""

    def __init__(self, session: aiohttp.ClientSession, logger: logging.Logger):
        self.session   = session
        self.logger    = logger
        self._sem      = asyncio.Semaphore(CONFIG["CONCURRENT"])

    async def _get(self, params: Dict) -> Optional[Dict]:
        """Wykonuje request z automatycznym retry."""
        params["format"] = "json"

        for attempt in range(CONFIG["MAX_RETRIES"]):
            try:
                async with self._sem:
                    await asyncio.sleep(
                        random.uniform(CONFIG["DELAY_MIN"], CONFIG["DELAY_MAX"])
                    )
                    async with self.session.get(
                        CONFIG["API_URL"],
                        params=params,
                        timeout=aiohttp.ClientTimeout(total=CONFIG["REQUEST_TIMEOUT"]),
                        headers=HEADERS
                    ) as resp:
                        if resp.status == 200:
                            return await resp.json(content_type=None)
                        elif resp.status == 429:
                            wait = 15 * (attempt + 1)
                            self.logger.warning(f"⏳ Rate limit, czekam {wait}s...")
                            await asyncio.sleep(wait)
                        elif resp.status in (500, 502, 503):
                            await asyncio.sleep(5 * (attempt + 1))
                        else:
                            self.logger.debug(f"HTTP {resp.status}")
                            return None
            except asyncio.TimeoutError:
                await asyncio.sleep(3 * (attempt + 1))
            except aiohttp.ClientError as e:
                self.logger.debug(f"Błąd połączenia: {e}")
                await asyncio.sleep(3 * (attempt + 1))

        self.logger.error(f"❌ Wyczerpano retry dla params: {params.get('titles', params.get('apfrom', '?'))}")
        return None

    async def lista_artykulow(self, apcontinue: Optional[str] = None) -> Dict:
        """
        Pobiera listę tytułów artykułów przez API allpages.
        apcontinue – token paginacji (None = od początku).
        Zwraca: {"tytuly": [...], "nastepny": "token lub None"}
        """
        params = {
            "action":      "query",
            "list":        "allpages",
            "apnamespace": CONFIG["NAMESPACE"],
            "aplimit":     CONFIG["PAGE_SIZE"],
            "apfilterredir": "nonredirects",   # Pomijamy przekierowania
        }
        if apcontinue:
            params["apcontinue"] = apcontinue

        dane = await self._get(params)
        if not dane:
            return {"tytuly": [], "nastepny": None}

        strony = dane.get("query", {}).get("allpages", [])
        tytuly = [s["title"] for s in strony if "title" in s]

        # Token do następnej strony
        nastepny = (
            dane.get("continue", {}).get("apcontinue") or
            dane.get("query-continue", {}).get("allpages", {}).get("apcontinue")
        )

        return {"tytuly": tytuly, "nastepny": nastepny}

    async def szczegoly_artykulow(self, tytuly: List[str]) -> List[Dict]:
        """
        Pobiera szczegółowe dane dla listy artykułów w jednym zapytaniu.
        Wikimedia API pozwala na do 50 tytułów naraz w prop queries.
        """
        if not tytuly:
            return []

        params = {
            "action":   "query",
            "titles":   "|".join(tytuly),
            "prop": "|".join([
                "revisions",      # Data ostatniej edycji
                "categories",     # Kategorie
                "links",          # Linki wewnętrzne
                "extlinks",       # Linki zewnętrzne
                "images",         # Obrazy
                "coordinates",    # Współrzędne geo
                "langlinks",      # Wersje językowe
                "pageprops",      # Właściwości (short description itp.)
                "extracts",       # Tekst artykułu (plain text)
                "info",           # Informacje podstawowe (długość, daty)
                "pageterms",      # Opisy Wikidata
            ]),
            # Opcje dla poszczególnych prop
            "rvprop":       "timestamp|ids",
            "rvlimit":      1,
            "rvdir":        "newer",      # pierwsza rewizja = data utworzenia
            "cllimit":      50,
            "pllimit":      500,
            "ellimit":      50,
            "imlimit":      20,
            "lllimit":      500,
            "exintro":      True,         # Tylko intro artykułu (szybciej)
            "explaintext":  True,         # Czysty tekst (bez HTML)
            "exlimit":      "max",
            "inprop":       "url|length|editcount",
            "clshow":       "!hidden",    # Bez ukrytych kategorii
        }

        dane = await self._get(params)
        if not dane:
            return []

        strony = dane.get("query", {}).get("pages", {})
        wyniki = []

        for page_id, page_data in strony.items():
            if int(page_id) < 0:
                # Artykuł nie istnieje (pageid ujemne = brak)
                continue

            # Pierwsza rewizja = data utworzenia
            revs = page_data.get("revisions", [])
            if revs:
                page_data["first_revision"] = revs[-1]
                page_data["revisions"]      = revs[:1]

            wyniki.append(parsuj_artykul(page_data))

        return wyniki


# ── ZAPIS DO EXCELA ────────────────────────────────────────────────────────
class ExcelWriter:
    """Buforuje rekordy i zapisuje checkpointy do Excela."""

    def __init__(self, logger: logging.Logger):
        self.logger    = logger
        self.bufor:    List[Dict] = []
        self.nr        = 0
        self.pliki:    List[str] = []
        os.makedirs(CONFIG["OUTPUT_DIR"], exist_ok=True)

    def dodaj(self, rekordy: List[Dict]):
        self.bufor.extend(rekordy)

    def czy_zapisac(self) -> bool:
        return len(self.bufor) >= CONFIG["SAVE_EVERY"]

    def zapisz_checkpoint(self, wymus: bool = False):
        if not self.bufor or (not wymus and not self.czy_zapisac()):
            return

        self.nr += 1
        ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
        sciezka = f"{CONFIG['CHECKPOINT_PREFIX']}{self.nr:04d}_{ts}.xlsx"

        try:
            df = pd.DataFrame(self.bufor)
            df = self._kolejnosc_kolumn(df)
            df.to_excel(sciezka, index=False, engine="openpyxl")
            self.pliki.append(sciezka)
            self.logger.info(
                f"{Fore.GREEN}💾 Checkpoint {self.nr}: "
                f"{len(self.bufor):,} artykułów → {sciezka}{Style.RESET_ALL}"
            )
            self.bufor.clear()
        except Exception as e:
            self.logger.error(f"❌ Błąd zapisu: {e}")

    def _kolejnosc_kolumn(self, df: pd.DataFrame) -> pd.DataFrame:
        kolejnosc = [
            "pageid", "tytul", "url", "opis_krotki",
            "dlugosc_bajtow", "rozmiar_kb", "liczba_slow",
            "data_utworzenia", "data_ostatniej_edycji",
            "liczba_edycji", "liczba_autorow",
            "kategorie", "sekcje",
            "linki_wewn", "linki_zewn",
            "obrazy", "wspolrzedne_lat", "wspolrzedne_lon",
            "jezyki_wersji", "czy_stub",
            "tresc_skrot", "data_pobrania",
        ]
        ist = [k for k in kolejnosc if k in df.columns]
        poz = [k for k in df.columns if k not in kolejnosc]
        return df[ist + poz]

    def scal_i_zapisz(self, progress: "ProgressManager") -> Optional[str]:
        """Scala wszystkie checkpointy w jeden plik finalny."""
        self.zapisz_checkpoint(wymus=True)

        # Dołącz wcześniejsze checkpointy z progress.json
        wszystkie_pliki = list(dict.fromkeys(
            progress.data.get("checkpointy", []) + self.pliki
        ))

        if not wszystkie_pliki:
            self.logger.warning("⚠️  Brak plików do scalenia")
            return None

        self.logger.info(f"🔄 Scalanie {len(wszystkie_pliki)} plików...")
        dfs = []
        for p in wszystkie_pliki:
            if os.path.exists(p):
                try:
                    dfs.append(pd.read_excel(p, engine="openpyxl"))
                except Exception as e:
                    self.logger.error(f"❌ Błąd odczytu {p}: {e}")

        if not dfs:
            return None

        df = pd.concat(dfs, ignore_index=True)
        przed = len(df)
        df = df.drop_duplicates(subset=["pageid"], keep="last")
        if przed != len(df):
            self.logger.info(f"🧹 Usunięto {przed - len(df):,} duplikatów")

        df = self._kolejnosc_kolumn(df)
        df = df.sort_values("pageid", na_position="last")

        ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
        sciezka = f"{CONFIG['FINAL_FILE']}{ts}.xlsx"
        df.to_excel(sciezka, index=False, engine="openpyxl")

        rozmiar = os.path.getsize(sciezka) / (1024 * 1024)
        self.logger.info(
            f"{Fore.CYAN}✅ Plik finalny: {sciezka} "
            f"({len(df):,} artykułów, {rozmiar:.1f} MB){Style.RESET_ALL}"
        )
        return sciezka


# ── GŁÓWNA LOGIKA ──────────────────────────────────────────────────────────
class WikiScraper:

    def __init__(self, logger: logging.Logger, progress: ProgressManager):
        self.logger   = logger
        self.progress = progress

    def _banner(self):
        total_art = "~1 700 000"  # pl.wikipedia.org ma ~1.7M artykułów
        print(f"\n{Fore.CYAN}{'═'*62}")
        print(f"  WIKIPEDIA MASS DOWNLOADER  │  Damian / zanae")
        print(f"  pl.wikipedia.org  │  ~{total_art} artykułów")
        print(f"  Start: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'═'*62}{Style.RESET_ALL}\n")

    async def uruchom(self, max_artykulow: int = 0):
        """
        Główna pętla pobierania.
        max_artykulow: 0 = bez limitu (wszystkie artykuły)
        """
        self._banner()

        connector = aiohttp.TCPConnector(
            limit=CONFIG["CONCURRENT"] * 2,
            limit_per_host=CONFIG["CONCURRENT"],
            ssl=True,
        )
        writer = ExcelWriter(self.logger)

        # Wczytaj poprzednie checkpointy z progress.json
        writer.pliki = list(self.progress.data.get("checkpointy", []))

        async with aiohttp.ClientSession(connector=connector) as session:
            client = WikiApiClient(session, self.logger)

            apcontinue = self.progress.data.get("apcontinue")
            pobrano    = self.progress.data.get("pobrano", 0)
            bledow     = self.progress.data.get("bledow", 0)

            if apcontinue:
                self.logger.info(
                    f"🔄 Wznawiam od: '{apcontinue}' "
                    f"(poprzednio pobrano: {pobrano:,})"
                )

            pbar = tqdm(
                initial=pobrano,
                total=max_artykulow or None,
                desc="  Artykuły",
                unit="art",
                colour="blue",
                bar_format="{l_bar}{bar}| {n_fmt} [{elapsed}, {rate_fmt}]"
            )

            while True:
                # Pobierz stronę listy artykułów
                lista = await client.lista_artykulow(apcontinue)
                tytuly = lista["tytuly"]

                if not tytuly:
                    self.logger.info("✅ Pobrano wszystkie artykuły!")
                    break

                # Pobierz szczegóły w batchach po DETAIL_BATCH
                batch_size = CONFIG["DETAIL_BATCH"]
                zadania = [
                    client.szczegoly_artykulow(tytuly[i:i + batch_size])
                    for i in range(0, len(tytuly), batch_size)
                ]
                wyniki_batchy = await asyncio.gather(*zadania, return_exceptions=True)

                rekordy = []
                for wynik in wyniki_batchy:
                    if isinstance(wynik, Exception):
                        bledow += 1
                        self.logger.debug(f"⚠️  Błąd batcha: {wynik}")
                    elif wynik:
                        rekordy.extend(wynik)

                # Zapis do bufora i ewentualny checkpoint
                writer.dodaj(rekordy)
                writer.zapisz_checkpoint()

                # Aktualizuj statystyki
                nowe    = len(rekordy)
                pobrano += nowe
                pbar.update(nowe)

                # Zapisz postęp (token paginacji + lista checkpointów)
                apcontinue = lista["nastepny"]
                self.progress.data.update({
                    "apcontinue":  apcontinue,
                    "pobrano":     pobrano,
                    "bledow":      bledow,
                    "checkpointy": writer.pliki,
                })
                self.progress.save()

                self.logger.debug(
                    f"📄 Pobrano łącznie: {pobrano:,} | "
                    f"Następna strona: {apcontinue or 'KONIEC'}"
                )

                # Koniec paginacji
                if not apcontinue:
                    self.logger.info("✅ Koniec listy artykułów (brak tokenu paginacji)")
                    break

                # Limit (tryb testowy)
                if max_artykulow and pobrano >= max_artykulow:
                    self.logger.info(f"🎯 Osiągnięto limit {max_artykulow:,}")
                    break

            pbar.close()

        # Zapisz plik finalny
        plik = writer.scal_i_zapisz(self.progress)
        self._podsumowanie(pobrano, bledow, plik)

    def _podsumowanie(self, pobrano: int, bledow: int, plik: Optional[str]):
        czas = datetime.fromisoformat(self.progress.data["start_time"])
        delta = datetime.now() - czas
        print(f"\n{Fore.CYAN}{'═'*62}")
        print(f"  PODSUMOWANIE")
        print(f"{'═'*62}{Style.RESET_ALL}")
        print(f"  Pobrano artykułów: {pobrano:,}")
        print(f"  Błędów:            {bledow:,}")
        print(f"  Czas:              {str(delta).split('.')[0]}")
        if plik and os.path.exists(plik):
            mb = os.path.getsize(plik) / (1024 * 1024)
            print(f"  Plik finalny:      {plik} ({mb:.1f} MB)")
        print(f"{Fore.CYAN}{'═'*62}{Style.RESET_ALL}\n")


# ── ARGUMENTY ──────────────────────────────────────────────────────────────
def parsuj_args():
    p = argparse.ArgumentParser(
        description="WikiScraper v1.0 – Damian / zanae",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Przykłady:
  python wiki_scraper.py                   # Pobierz WSZYSTKO (1.7M art.)
  python wiki_scraper.py --test            # Testowo: tylko 200 artykułów
  python wiki_scraper.py --limit 50000     # Pierwsze 50 000 artykułów
  python wiki_scraper.py --reset           # Zacznij od nowa (usuń postęp)
        """
    )
    p.add_argument("--test",  action="store_true", help="Tryb testowy (200 artykułów)")
    p.add_argument("--limit", type=int, default=0, help="Maksymalna liczba artykułów (0=wszystkie)")
    p.add_argument("--reset", action="store_true", help="Usuń progress.json i zacznij od nowa")
    return p.parse_args()


# ── MAIN ───────────────────────────────────────────────────────────────────
async def main():
    args   = parsuj_args()
    os.makedirs(CONFIG["OUTPUT_DIR"], exist_ok=True)
    logger = setup_logging(CONFIG["LOG_FILE"])
    logger.info("🚀 WikiScraper uruchomiony – Damian / zanae")

    if args.reset and os.path.exists(CONFIG["PROGRESS_FILE"]):
        os.remove(CONFIG["PROGRESS_FILE"])
        logger.info("🔄 Reset postępu")

    limit = 200 if args.test else args.limit

    progress = ProgressManager(CONFIG["PROGRESS_FILE"])
    scraper  = WikiScraper(logger, progress)

    try:
        await scraper.uruchom(max_artykulow=limit)
    except KeyboardInterrupt:
        logger.info("\n⚠️  Przerwano (Ctrl+C) – postęp zapisany, wznów przez ponowne uruchomienie")


if __name__ == "__main__":
    asyncio.run(main())

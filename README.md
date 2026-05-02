# WikiScraper

**Autor:** Damian / zanae  
**Wersja:** 1.0  
**API:** [Wikimedia REST API](https://www.mediawiki.org/wiki/API:Main_page) – oficjalne, darmowe, bez rejestracji

Masowe pobieranie wszystkich artykułów z **pl.wikipedia.org** do pliku Excel.  
Skrypt pobiera ~1 700 000 artykułów z pełnymi metadanymi: treść, kategorie, daty, statystyki edycji, geolokalizacja i więcej.

---

## Funkcje

- Pobiera wszystkie artykuły encyklopedyczne (namespace 0)
- 22 kolumny danych na artykuł
- Checkpointy co 5 000 artykułów – nie stracisz postępu
- Automatyczne wznowienie po przerwie
- Asynchroniczne requesty (`asyncio` + `aiohttp`) – szybko i wydajnie
- Pasek postępu w terminalu
- Logi do pliku

---

## Instalacja

```bash
pip install aiohttp pandas openpyxl tqdm colorama
```

Wymagany Python 3.8+

---

## Użycie

```bash
# Test – 200 artykułów (~30 sekund)
python wiki_scraper.py --test

# Pełne pobieranie (~1.7M artykułów, 3-5 dni)
python wiki_scraper.py

# Limit – pierwsze N artykułów
python wiki_scraper.py --limit 50000

# Zacznij od nowa (usuń postęp)
python wiki_scraper.py --reset
```

### Wznowienie po przerwie

Wystarczy uruchomić skrypt ponownie bez parametrów – automatycznie wznowi od miejsca przerwania dzięki `progress.json`.

---

## Struktura plików wyjściowych

```
wiki_output/
├── checkpoint_0001_20240501_120000.xlsx   # Plik pośredni (co 5000 art.)
├── checkpoint_0002_20240501_180000.xlsx
├── WIKIPEDIA_PL_20240503_120000.xlsx      # Finalny scalony plik
├── wiki_scraper.log                       # Logi
└── progress.json                          # Stan pobierania
```

---

## Kolumny w Excelu

| Kolumna | Opis |
|---|---|
| `pageid` | Unikalny ID artykułu |
| `tytul` | Tytuł artykułu |
| `url` | Link do artykułu |
| `opis_krotki` | Krótki opis z Wikidata |
| `tresc_skrot` | Pierwsze 1500 znaków tekstu |
| `kategorie` | Lista kategorii |
| `sekcje` | Nagłówki sekcji |
| `data_utworzenia` | Data pierwszej edycji |
| `data_ostatniej_edycji` | Data ostatniej zmiany |
| `liczba_edycji` | Łączna liczba edycji |
| `liczba_autorow` | Liczba unikalnych autorów |
| `linki_wewn` | Liczba linków wewnętrznych |
| `linki_zewn` | Liczba linków zewnętrznych |
| `obrazy` | Lista plików graficznych |
| `wspolrzedne_lat` | Szerokość geograficzna |
| `wspolrzedne_lon` | Długość geograficzna |
| `jezyki_wersji` | Liczba wersji językowych |
| `czy_stub` | Czy artykuł-zalążek (Tak/Nie) |
| `rozmiar_kb` | Rozmiar artykułu w KB |
| `liczba_slow` | Liczba słów |

---

## Szacowany czas

| Zakres | Czas |
|---|---|
| 1 000 artykułów | ~2 minuty |
| 50 000 artykułów | ~2 godziny |
| 500 000 artykułów | ~1 dzień |
| Wszystkie ~1.7M | 3–5 dni |

---

## Licencja

Kod: **MIT** – rób z nim co chcesz.  
Dane Wikipedii: [Creative Commons CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)

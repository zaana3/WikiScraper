# Utwórz folder projektu
mkdir WikiScraper
cd WikiScraper

# Wrzuć skrypt do folderu
# (skopiuj pobrany wiki_scraper.py tutaj)

# Utwórz .gitignore
cat > .gitignore << 'EOF'
wiki_output/
__pycache__/
*.pyc
*.log
progress.json
*.xlsx
.env
EOF

# Utwórz README.md
cat > README.md << 'EOF'
# WikiScraper

**Autor:** Damian / zanae

Masowe pobieranie wszystkich artykułów z pl.wikipedia.org przez oficjalne API Wikimedia.

## Instalacja

\`\`\`bash
pip install aiohttp pandas openpyxl tqdm colorama
\`\`\`

## Użycie

\`\`\`bash
python wiki_scraper.py --test    # test (200 artykułów)
python wiki_scraper.py           # pełne pobieranie (~1.7M artykułów)
python wiki_scraper.py --limit 10000
\`\`\`

## Output

Plik Excel z 22 kolumnami: tytuł, URL, opis, kategorie, daty, statystyki edycji i więcej.
EOF

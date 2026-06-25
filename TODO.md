# TODO / dług techniczny

## Parytet NiceGUI ↔ legacy (2026-06-23, zgłoszenia użytkownika)

Regresje względem Streamlit znalezione przy testach `src/app_ng/`:

1. ✅ **[ZROBIONE] Podgląd PDF/skanu nie działa** — `detail.py` osadzał PDF jako
   `data:application/pdf;base64,…` w `<iframe>`; współczesne przeglądarki
   blokują render PDF z `data:`-URI (pusta ramka). To samo dla skanów
   (`ui.image` z lokalną ścieżką). **Fix:** endpoint HTTP `/file/{id}`
   (`src/app_ng/files.py`, FastAPI/NiceGUI `app`) z `Content-Disposition: inline`;
   iframe/obraz wskazują na ten endpoint (same-origin → wbudowany viewer renderuje).
2. ✅ **[ZROBIONE] Linki MusicXML/MuseScore pobierają zamiast otwierać** —
   `ui.download.file()` wymuszał pobranie. App jest desktop-first/lokalny → główna
   akcja **otwiera plik w skojarzonej aplikacji** po stronie serwera
   (`open_in_app`: `os.startfile`/`xdg-open`/`open`); pobranie zostało jako wtórna ikona.
3. ✅ **[ZROBIONE] Tłumaczenie znikało po zapisie** — `detail.py`/`edit.py` czytały
   `primary_translation_pl` (rekordy `Translation`), a zapis szedł do legacy kolumny
   `lyrics_translation_pl` → dla utworów z rekordem `Translation(pl)` edycja/tłumaczenie
   nie były widoczne po odświeżeniu. **Fix:** `MusicPieceService.set_primary_translation_pl`
   upsertuje prymarny rekord `Translation(pl)` + lustro do kolumny legacy; podpięte w `edit.py`.

Do ewentualnego dalszego audytu parytetu: zakładki Przetwarzanie/Biblioteka
przejrzane — bez regresji podglądu/pobierania.

## Sprzątanie `data/uploads/` po migracji do biblioteki (2026-06-20)

Po `scripts/migrate_to_library.py --apply` pliki realne przeniesiono do
`../church-music-library/`, ale w `data/uploads/` **zostały do uprzątnięcia**:

1. **Wiszące rekordy `MusicFile`** — 3 wiersze w DB wskazują `data\uploads\…`
   pliki, których NIE ma na dysku (`kind=None`, słusznie pominięte przez migrację).
   Decyzja: usunąć te rekordy czy podpiąć właściwe pliki.
2. **Osierocone pliki testowe** w `data/uploads/` bez żadnego rekordu `MusicFile`
   (m.in. `cantate_domino/`, `if_ye_love_me/`, `niescie_chwale/`, luźne
   `AveMaria_Arcadelt_2sys.{pdf,mxl}`, `1/output.mxl`, `4|5|6/AveMaria_*`).
   Decyzja: skasować albo podpiąć do utworów.

**Warunek przed czyszczeniem:** potwierdzić kompletność `../church-music-library/`
(każdy utwór ma swoje pliki) — backup jest w `backups/church_music_*.db` +
`backups/uploads_*`. Narzędzie: `scripts/cleanup_uploads.py` (raport domyślnie,
kasowanie tylko z jawną flagą).
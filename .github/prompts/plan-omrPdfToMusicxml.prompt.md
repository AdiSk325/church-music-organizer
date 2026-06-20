**PRD**
Celem produktu jest zbudowanie systemu, który przyjmuje PDF lub skan drukowanego zapisu nutowego i zwraca poprawny, edytowalny MusicXML możliwie wiernie odwzorowujący materiał wejściowy. Dla V1 rekomenduję twardo zawęzić zakres do drukowanych nut kościelnych i chóralnych, głównie SATB, z dopuszczalnym human-in-the-loop dla przypadków o niskiej pewności. To jest najszybsza droga do realnej jakości, zamiast rozmywania projektu na wszystkie typy notacji.

Najważniejsza decyzja architektoniczna: nie budować od razu jednego modelu end-to-end. Najpierw trzeba zbudować środowisko benchmarkowe, zintegrować 2-3 baseline’y OMR, zebrać własny gold set domenowy i dopiero wtedy trenować własne modele. Obecne repo ma sensowną reprezentację pośrednią i zalążek benchmarków, ale nie ma skutecznego etapu ekstrakcji muzyki ze skanu. Najmocniejsze punkty startowe to [src/omr/score_graph.py](src/omr/score_graph.py), [src/omr/pipeline.py](src/omr/pipeline.py), [src/omr/benchmarking.py](src/omr/benchmarking.py) i [agent/omr_analysis_agent.py](agent/omr_analysis_agent.py). Największa luka jest taka, że [tests/test_omr_accuracy.py](tests/test_omr_accuracy.py) w praktyce testuje głównie parse referencyjnego MusicXML, a nie prawdziwy scenariusz skan/PDF -> MusicXML.

**Zakres i wymagania**
W zakresie V1 powinny być: PDF wielostronicowy i pojedyncze skany, drukowana notacja zachodnia, pieśni i utwory chóralne SATB, podstawowe grand staff jako rozszerzenie drugiego priorytetu, eksport MusicXML 4.x, metadane utworu, wysokości dźwięków, rytm, pauzy, kropki, podstawowe wiązania, akordy, powtórki i tekst pod nutami. Poza zakresem V1 powinny zostać: zapis odręczny, pełna artykulacja i wszystkie ozdobniki, pełna edycja WYSIWYG oraz obietnica stuprocentowej automatyki dla każdego typu partytury.

System powinien działać w trybie CPU-first na Windows/Linux dla inferencji, ale trening modeli może być realizowany poza środowiskiem docelowym z użyciem GPU. Każdy wynik powinien być wersjonowany razem z wejściem, konfiguracją, użytym silnikiem lub modelem, metrykami i finalnym MusicXML. System nie powinien zwracać “pewnego” wyniku za wszelką cenę. W V1 musi istnieć confidence score i ścieżka review dla trudnych przypadków.

**Rekomendowana architektura**
Rekomenduję pipeline hybrydowy:
1. Ingestion dokumentu: rasteryzacja PDF, split stron, deskew, denoise, normalizacja kontrastu, staff/page crop.
2. Warstwa baseline engines: co najmniej Audiveris jako baseline A oraz homr albo oemer jako baseline B.
3. Normalizacja wyników wszystkich engine’ów do wspólnej reprezentacji pośredniej ScoreGraph.
4. Walidacja muzyczna i strukturalna: takty, głosy, zgodność rytmu, tonacja, metrum, repeats, tekst.
5. Confidence scoring i wybór najlepszego kandydata per dokument, strona, staff lub takt.
6. Opcjonalna warstwa AI/LLM tylko do lokalnej naprawy niespójności i metadanych, nigdy jako główny parser obrazu.
7. Eksport finalnego MusicXML plus raport jakości.

To oznacza, że istniejący [src/omr/score_graph.py](src/omr/score_graph.py) powinien zostać canonical IR dla wszystkich źródeł wyniku. [src/omr/pipeline.py](src/omr/pipeline.py) trzeba przebudować z jednego orchestratora w interfejs wieloengine’owy. [src/omr/constraints.py](src/omr/constraints.py) powinien zostać rozszerzony z prostych reguł do warstwy produkcyjnego rerankingu i repair.

**Dane, open source i trening**
Dane open source trzeba potraktować jako bootstrap, nie jako substytut własnego zbioru domenowego. Rekomendowana strategia danych jest następująca:
- DeepScoresV2 jako źródło drukowanych symboli i pretreningu detekcji; plus licencja jest relatywnie wygodna badawczo.
- PrIMuS jako pretrening dla sekwencyjnego dekodowania nut drukowanych.
- Camera-PrIMuS jako źródło odporności na zdjęcia i zniekształcenia.
- MUSCIMA++ tylko jako poboczny tor eksperymentalny, bo dotyczy głównie rękopisu i nie odpowiada bezpośrednio na zakres V1.
- Własny gold set domenowy drukowanych pieśni i utworów SATB jako najwyższy priorytet.
- Generator syntetyczny z MusicXML/MEI do renderowania domenowych partytur z augmentacjami skanowymi.

Najważniejsza zasada: jakość produkcyjna nie przyjdzie z samego modelu, tylko z połączenia własnego gold setu, syntetyki domenowej i powtarzalnego benchmarku. Dlatego etap modelowy powinien być rozłożony:
1. Etap benchmark-first: bez trenowania dużego modelu, tylko baseline’y, benchmarki i klasyfikacja błędów.
2. Etap modeli wspierających: preprocessing, staff detection, quality scoring, confidence estimation.
3. Etap modelu głównego: staff-image -> symbolic sequence, najlepiej transformer/encoder-decoder uczony najpierw na danych drukowanych open source i syntetycznych, potem fine-tuning na gold secie SATB.
4. Etap ensemble: audiveris + homr/oemer + model własny, z rerankingiem na podstawie confidence i constraint violations.

LLM powinien być używany wyłącznie do lokalnych napraw MusicXML, normalizacji metadanych, klasyfikacji błędów i wsparcia eksperymentalnego. Nie rekomenduję ścieżki image/PDF -> vision LLM -> MusicXML jako głównej architektury produktu, bo będzie niestabilna i bardzo trudna do walidacji.

**Środowisko testowe i walidacyjne**
Trzeba zbudować odrębne środowisko benchmarkowe obejmujące rejestr dokumentów, runner benchmarków, zapis artefaktów, porównanie wielu engine’ów i trendowanie wyników eksperymentów. Minimalny zestaw danych walidacyjnych powinien mieć cztery poziomy:
1. Smoke set: około 20 prostych dokumentów.
2. Dev set: około 100 reprezentatywnych stron.
3. Hard set: około 50 trudnych jakościowo przypadków.
4. Blind holdout: około 50 stron niewykorzystywanych w iteracji rozwojowej.

Każdy rekord datasetu powinien przechowywać: identyfikator dokumentu i strony, źródło pliku, typ notacji, poziom trudności, jakość skanu, ground truth MusicXML lub MEI, status QA oraz status licencyjny. Rekomendacja operacyjna jest prosta: pliki surowe i artefakty w storage plikowym, manifest datasetu w SQLite/Postgres albo parquet, metryki eksperymentów w MLflow lub podobnym trackerze. Jeśli chcesz minimalizować złożoność, najpierw wystarczy manifest plus raporty JSON/Markdown, a pełny tracker wdrożyć w drugiej iteracji.

**Metryki sukcesu**
Obowiązkowe metryki techniczne:
- valid MusicXML rate,
- document success rate,
- measure count accuracy,
- note event precision/recall/F1,
- pitch accuracy,
- rhythm accuracy,
- onset alignment accuracy,
- voice assignment accuracy,
- chord recall/precision,
- dotted note recall,
- key signature accuracy,
- time signature accuracy,
- repeat/barline accuracy,
- lyrics recall/precision i syllable alignment,
- staff grouping accuracy,
- confidence calibration error.

Obowiązkowe metryki produktowe:
- średni czas ręcznej korekty na stronę,
- liczba ręcznych poprawek na stronę,
- odsetek dokumentów przechodzących bez korekty,
- regresja względem ostatniego baseline’u.

Dla V1 SATB proponuję takie progi wejścia do releasu: 99% valid MusicXML, co najmniej 95% document processing success, co najmniej 92% pitch accuracy, co najmniej 90% rhythm accuracy, co najmniej 90% accuracy liczby taktów, co najmniej 85% lyrics recall tam, gdzie tekst istnieje, oraz medianowo nie więcej niż 5 krytycznych poprawek ręcznych na stronę na gold secie.

**Plan wdrożenia**
1. Faza 0: zamrozić definicję V1, listę wspieranych symboli, schema benchmark record i oficjalne metryki sukcesu. To blokuje całą resztę.
2. Faza 1: przebudować [src/omr/pipeline.py](src/omr/pipeline.py) pod interfejs wieloengine’owy i zintegrować baseline Audiveris oraz homr/oemer.
3. Faza 1: rozszerzyć [src/omr/benchmarking.py](src/omr/benchmarking.py) z obecnych prostych metryk do pełnego benchmark harness i rozbudować [agent/omr_analysis_agent.py](agent/omr_analysis_agent.py) do raportowania wieloengine’owego.
4. Faza 1: zamienić [tests/test_omr_accuracy.py](tests/test_omr_accuracy.py) z testu “czy dobrze parsujemy referencyjny MusicXML” na prawdziwe testy end-to-end dla skanów i PDF.
5. Faza 2: zbudować manifest datasetów, proces QA i pierwszy gold set domenowy 50-200 stron.
6. Faza 2: uruchomić generator syntetyczny z augmentacjami imitującymi realne skany.
7. Faza 3: dodać preprocessing dokumentu, detektor jakości i confidence scoring, żeby lepiej routować przypadki łatwe, trudne i review.
8. Faza 4: uruchomić pretrening i fine-tuning własnego modelu sekwencyjnego dla drukowanych SATB.
9. Faza 5: zbudować ensemble i reranking kandydatów oraz użyć LLM wyłącznie do lokalnych napraw po walidacji.
10. Faza 5: ustawić quality gates release’owe i porównania z ostatnim baseline’em jako obowiązkowy warunek wdrożenia.

Pełną wersję planu zapisałem też w pamięci sesji, żeby dało się ją dalej iteracyjnie doprecyzować.

Jeśli ten kierunek akceptujesz, mogę w następnym kroku przygotować jedną z trzech rzeczy:
1. Backlog implementacyjny dla Copilota podzielony na epiki i taski.
2. Dokładny projekt środowiska benchmarkowego, manifestu datasetów i schematu bazy.
3. Plan pierwszego sprintu technicznego tylko dla warstwy benchmark + baseline engines.

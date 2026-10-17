# Adolescents’ Digital Nightlife — Nihai Tekrarlanabilir Analiz Paketi

Bu proje, **Adolescents’ Digital Nightlife** açık veri kaydındaki beş kaynak dosyasını kullanarak CHIuXiD 2026 için ikincil, gözlemsel ve davranışsal computational UX analizi yürütür.

## Bilimsel amaç

Çalışma toplam ekran süresini tek başına kullanmak yerine:

1. gündüz, yatma öncesi ve yatma sonrası kullanım örüntülerini,
2. sosyal medya, oyun ve video kullanımını,
3. kişiler-arası ortalama farklarla kişi-içi günlük sapmaları,
4. ertesi sabah uyku kalitesinin katılımcı bazında gruplanmış dış-kat tahminini

birlikte değerlendirir. Nedensellik iddiası kurulmaz.

## Gerekli resmî dosyalar

`data_raw/` klasöründe şu beş dosya bulunmalıdır:

- `phone.csv`
- `game.csv`
- `social.csv`
- `video.csv`
- `timeframes.csv` veya eşdeğer uzantılı resmî dosya

Dosya adlarındaki küçük farklılıklar `analysis_config.json` içindeki `file_aliases` alanıyla yönetilir. Otomatik sütun eşleştirmesi belirsizse işlem durur; tahmin ederek yanlış değişken seçmez. Kesin sütun adları `column_overrides` bölümüne yazılabilir.

## Kurulum

Python 3.11–3.13 desteklenir. Paket herhangi bir `.venv` veya platforma özgü ikili dosya içermez. En kolay kurulum:

```bash
python bootstrap_environment.py
```

Bu komut hedef bilgisayarda yerel `.venv` oluşturur ve `requirements-lock.txt` içindeki doğrudan sabitlenmiş sürümleri kurar. Sanal ortam dağıtım arşivine hiçbir zaman eklenmez. Elle kurulum da mümkündür:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements-lock.txt
python -m pip check
```

## Çalıştırma

Ağ erişimiyle resmî dosyaları indirmeyi deneyip tüm analizi çalıştırmak:

```bash
python run_all.py
```

Dosyalar önceden `data_raw/` içine konmuşsa:

```bash
python run_all.py --offline
```

Kod doğrulaması için azaltılmış tekrarlar:

```bash
python tests/run_smoke_test.py
pytest -q
```

`--quick` ile üretilen çıktılar yayın sonucu değildir. Doğrulama katmanı, `--allow-quick` açıkça verilmedikçe bunları reddeder.

## İş akışı

1. `src/download_data.py`: Figshare metadata/API ve arşiv uç noktaları, yeniden deneme, atomik indirme, MD5/SHA-256 ve güvenli ZIP çıkarma.
2. `src/inspect_and_prepare.py`: şema, kimlik, gün, saat, süre birimi, birleşim, eksiklik ve geçerlilik denetimi.
3. `src/run_analysis.py`: gerçek Gower uzaklığı, PAM/k-medoids, kararlılık, tekrarlı ölçüm modelleri ve katılımcı bazında dış-kat tahmin.
4. `src/generate_report.py`: yalnızca gerçek çıktı dosyalarından sonuç raporu ve makale sonuç taslağı.
5. `src/validate_outputs.py`: yayın öncesi kritik bütünlük ve sızıntı kontrolleri.

## Başlıca çıktılar

- `data_processed/daily_analytic.csv`
- `data_processed/participant_profiles.csv`
- `outputs/tables/source_file_manifest.csv`
- `outputs/tables/data_quality_report.csv`
- `outputs/tables/cluster_selection.csv`
- `outputs/tables/repeated_model_coefficients.csv`
- `outputs/tables/predictive_performance.csv`
- `outputs/tables/predictive_model_comparisons.csv`
- `outputs/tables/validation_report.json`
- `outputs/ANALYSIS_REPORT.md`
- `outputs/tables/RESULTS_SECTION_DRAFT.md`

## Yayın güvenlik kuralları

- Aynı katılımcının günleri eğitim ve test kümelerine bölünmez.
- Eksik katılımcı kimlikleri metin olarak `nan` değerine dönüştürülmez.
- Ortak gözlenen özelliği olmayan katılımcı çiftleri Gower analizinde benzer kabul edilmez.
- Kararlı küme çözümü bulunmazsa persona üretilmez.
- Birincil model kişi-içi ve kişiler-arası bileşenleri ayırır.
- Gecikmeli uyku duyarlılık modeli yalnızca tam olarak bir önceki çalışma günündeki `sleep_quality_lag1_exact` değerini kullanır; gözlem boşluklarını aşmaz.
- Karma model tekil/kararsızsa GEE yedeği açık biçimde raporlanır.
- Tahmin performansı iki estimandla verilir: `participant_day` her katılımcı-günü eşit, birincil `participant_equal` ise her ergenin toplam katkısını eşit ağırlıklandırır. Her ikisi için katılımcı-bootstrap güven aralıkları üretilir.
- Resmî beş dosya, SHA-256 manifesti ve yayın modu doğrulaması geçmeden paket “yayına hazır” sayılmaz.

## Temiz dağıtım biçimleri

Dağıtımlar çalışma klasörünü doğrudan ZIP'lemez; `DISTRIBUTION_ALLOWLIST.json` içindeki açık izin listesiyle oluşturulur.

- **Code-only:** resmî CSV, işlenmiş katılımcı verisi, sonuç, model ve çalışma logu içermez.
- **Data-inclusive:** yalnızca doğrulanmış beş resmî CSV ile `download_manifest.json` dosyasını ekler; işlenmiş veri, sonuç, model ve log içermez.

Her iki arşiv de `.venv`, `__pycache__`, `.pytest_cache`, `.pyc`, çalıştırılabilir dosya ve paylaşılan kütüphane içermemelidir. Denetim:

```bash
python src/audit_portability.py --root . --mode workspace
python src/build_distribution.py --mode code-only
python src/build_distribution.py --mode data-inclusive
```

Ayrıntılar `PORTABILITY_AND_PACKAGING.md` dosyasındadır.

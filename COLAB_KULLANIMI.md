# Google Colab kullanımı

1. Nihai ZIP dosyasını Google Drive’a yükleyip klasöre çıkarın.
2. Colab’da Drive’ı bağlayın:

```python
from google.colab import drive
drive.mount("/content/drive")
```

3. Proje klasörüne geçip ortamı kurun:

```bash
%cd /content/drive/MyDrive/Adolescents_Digital_Nightlife_Analysis_Final
!pip install -r requirements.txt
```

4. Resmî dosyaları otomatik indirmeyi deneyerek tam akışı çalıştırın:

```bash
!python run_all.py
```

Figshare indirmesi engellenirse beş dosyayı `data_raw/` klasörüne manuel yükleyip çevrim dışı çalıştırın:

```bash
!python run_all.py --offline
```

5. Kod testi:

```bash
!pytest -q
!python tests/run_smoke_test.py
```

`--quick` yalnızca kod kontrolü içindir ve makale sonucu olarak kullanılmamalıdır.

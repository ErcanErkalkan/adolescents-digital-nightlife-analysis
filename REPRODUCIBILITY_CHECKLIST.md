# Yeniden Üretilebilirlik Kontrol Listesi

- [ ] Beş resmî kaynak dosyası `data_raw/` içinde.
- [ ] `download_manifest.json` eksik dosya göstermiyor.
- [ ] `source_file_manifest.csv` her dosya için SHA-256 içeriyor.
- [ ] Sütun eşleştirme denetimi incelendi.
- [ ] Süre birimi kararı incelendi.
- [ ] Geçersiz kimlik ve yinelenen katılımcı-gün sayısı sıfır.
- [ ] Uyku kalitesi ve süre sınırları doğrulandı.
- [ ] Profil kararı eşiklere dayanıyor; zorla persona üretilmedi.
- [ ] Tekrarlı ölçüm model türü ve yedekleme nedeni raporlandı.
- [ ] Dış katlarda katılımcı sızıntısı yok.
- [ ] Her model için hem `participant_day` hem `participant_equal` MAE, RMSE ve R² üretildi.
- [ ] `participant_equal` ağırlıklarında her katılımcının toplam ağırlığı eşit ve katılımcı-bootstrap güven aralıkları üretildi.
- [ ] Çalıştırma `--quick` olmadan tamamlandı.
- [ ] `validation_report.json` durumu `passed`.
- [ ] Makale nedensel dil kullanmıyor.

- [ ] The lagged sleep-quality sensitivity variable is nonmissing only when the prior observation is exactly one study day earlier; gaps are never bridged.
- [ ] The ambiguous `sleep_quality_lag1` column is absent from processed data and model specifications.

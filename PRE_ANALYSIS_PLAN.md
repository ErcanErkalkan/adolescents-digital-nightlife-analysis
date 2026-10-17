# Ön Analiz Planı

## Başlık

**Beyond Screen Time: Explainable Temporal UX Profiles of Adolescents’ Smartphone Use and Sleep Quality**

## Tasarım ve analiz birimi

İkincil gözlemsel yoğun boylamsal analiz. Birincil satır düzeyi `katılımcı × gün`; hiyerarşi `katılımcı → gün → zaman dilimi → uygulama kategorisi`.

## Birincil sonuç

Ertesi sabah özbildirim uyku kalitesi, özgün 1–7 ölçeğinde sürekli değişken olarak ele alınır. Ölçek dışı değerler ana analize alınmaz.

## Araştırma soruları

- **RQ1:** Gündüz, yatma öncesi, yatma sonrası ve uygulama bileşimi özelliklerinden kararlı zamansal kullanım profilleri çıkarılabilir mi?
- **RQ2:** Kabul edilen profiller uyku kalitesi ve günlük değişkenlik bakımından farklılaşır mı?
- **RQ3:** Zamanlama ve uygulama kategorileri yalnızca toplam kullanıma göre dış-kat tahminini iyileştirir mi?
- **RQ4:** Sosyal medya, oyun ve video zamanlamalarının uyku kalitesiyle ilişkileri hangi belirsizlik altında gözlenir?

## Önceden belirlenmiş özellikler

Çekirdek: gündüz, yatma öncesi, yatma sonrası ve toplam kullanım; nighttime exposure ratio; post-bedtime intrusion ratio. Genişletilmiş: sosyal medya, oyun ve video kullanımının zaman dilimi bileşenleri; güvenilir şekilde ayrıştırılabilirse uyku penceresi ve döngüsel yatma saati.

## Kişi-içi / kişiler-arası ayrım

Her zamanla değişen `X_it` için:

- kişiler-arası: katılımcı ortalaması `X̄_i`
- kişi-içi: günlük sapma `X_it − X̄_i`

Birincil tekrarlı ölçüm modeli her iki bileşeni aynı anda içerir.

## Profil analizi

Katılımcı düzeyindeki ortalama ve değişkenlik özetleri kullanılır. En az 5 geçerli gün ve özellik başına en çok %30 eksiklik aranır. Yüksek korelasyonlu özellikler aynı yapı içinde `|Spearman ρ| ≥ .92` kuralıyla azaltılır. Yapılar eşit toplam ağırlık alır.

- uzaklık: eksikliği çift bazında normalleştiren sayısal Gower
- kümeleme: PAM/k-medoids
- aday `k`: 2–6
- minimum profil: %10
- minimum silhouette: .25
- minimum median subsample ARI: .75

Tüm koşulları karşılayan çözüm yoksa “kararlı profil bulunamadı” raporlanır.

## Birincil açıklayıcı model

Katılımcı rassal kesişimli doğrusal karma model. Sabit etkiler, standartlaştırılmış gündüz/yatma öncesi/yatma sonrası kişi-içi ve kişiler-arası bileşenlerdir. Yakınsamayan, sonlu olmayan veya ihmal edilebilir rassal varyanslı çözüm reddedilir; aynı formül exchangeable korelasyonlu Gaussian GEE ile yedeklenir.

## Duyarlılık ve keşifsel modeller

- önceki gün uyku kalitesini içeren ayrı duyarlılık modeli
- yeterli kapsama sahip sosyal/oyun/video zamanlamalarını içeren keşifsel uygulama-kategorisi modeli
- ana modelden ayrı raporlama

## Tahmin

Dış değerlendirme katılımcı bazında dengelenmiş 5-fold; iç tuning yine katılımcı bazında 4-fold yapılır.

1. eğitim ortalaması
2. toplam kullanım Elastic Net
3. zamanlama Elastic Net
4. genişletilmiş Elastic Net
5. yalnızca genişletilmiş özelliklerde önceden sabitlenmiş Random Forest karşılaştırması

Ölçütler: MAE, RMSE ve R². Her model için iki ayrı tahmin estimandı raporlanır: (i) her katılımcı-günün eşit ağırlık aldığı `participant_day` performansı ve (ii) her ergenin toplam ağırlığının eşit olduğu `participant_equal` performansı. Katılımcı-eşit MAE, önce mutlak kaybın her katılımcı içinde ortalanması ve sonra katılımcılar arasında eşit ortalama alınmasıyla; katılımcı-eşit RMSE, katılımcı-içi ortalama karesel kayıpların katılımcılar arasında eşit ortalamasının kareköküyle hesaplanır. R² aynı ters-gün-sayısı ağırlıklarıyla hesaplanır. `participant_equal` birincil tahmin estimandı, `participant_day` tamamlayıcı gözlem-düzeyi estimandıdır. Her iki estimand için katılımcı bootstrap %95 güven aralıkları ve eşleştirilmiş model farkları raporlanır; kalibrasyon eğimi ve kesişimi ayrıca sunulur.

## Eksik veri

Model içinde yalnızca eğitim katında medyan imputasyon ve eksiklik göstergeleri uygulanır. Yapısal olarak bulunmayan platform değişkeni sıfır değildir. Kapsaması %30’un altında olan değişken tahmin setine girmez.

## Çoklu analiz ve yorum

Birincil tekrarlı ölçüm modeli ile genişletilmiş-vs-toplam tahmin karşılaştırması ana analizdir. Uygulama kategorisi ve profil moderasyonu keşifseldir. P-değerleri tek başına kanıt kabul edilmez; güven aralıkları, yön, büyüklük ve kararlılık birlikte yorumlanır. Gözlemsel veri nedeniyle nedensellik iddiası kurulmaz.


## Exact lag policy

The lagged-outcome sensitivity analysis uses `sleep_quality_lag1_exact`. The value is populated only when the immediately preceding observed record for the same participant is exactly one numeric study day earlier. Observation gaps are never bridged, and the ambiguous previous-observed-record variable `sleep_quality_lag1` is prohibited.

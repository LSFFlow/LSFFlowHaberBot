# DXY & XAUUSD Telegram Haber Botu

Turkce finans kaynaklarindan DXY (Dolar Endeksi) ve XAUUSD (Altin) ile ilgili
haber/analizleri, ayrica ForexFactory'nin ucretsiz ekonomik takviminden
yuksek etkili (kirmizi) USD verilerini Telegram kanalina otomatik gonderen
bir bot.

## Neler gonderiliyor?
1. **Haber/Analiz**: Investing.com Turkiye'nin Doviz ve Emtia haber/analiz
   bolumlerinden "dolar endeksi", "altin", "ons altin" gibi kelimeler gecen
   icerikler (link olmadan, sadece baslik + kisa ozet + kaynak adi).
2. **Ekonomik Takvim**: ForexFactory'nin haftalik ucretsiz takviminden sadece
   **USD** para birimine ait ve **Yuksek (kirmizi)** etkili veriler - saati,
   beklenti ve onceki degeriyle birlikte (Turkiye saatine cevrilmis olarak).

## 1) Telegram Bot Olustur
1. Telegram'da **@BotFather**'i ac, `/newbot` yaz, adim adim ilerle.
2. Sana verdigi **token**'i kaydet (ornek: `123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxx`).
3. Botu kanalina **yonetici** olarak ekle (mesaj gonderme yetkisiyle).
4. Kanal ID'sini bul:
   - Kanalin kullanici adi varsa: `@kanaliniz` direkt kullanilabilir.
   - Yoksa, kanaldan bir mesaji `@userinfobot`'a yonlendirip chat id'yi ogren.

## 2) GitHub'da Otomatik Calistirma (Onerilen - Ucretsiz)

1. GitHub'da yeni bir **private repo** olustur (ornek: `dxy-gold-bot`).
2. Bu klasordeki `bot.py` ve `requirements.txt` dosyalarini repo'ya yukle.
3. `.github_workflows_dxy-gold-bot.yml` dosyasini `.github/workflows/dxy-gold-bot.yml`
   yoluna (klasor yapisini olusturarak) kopyala.
4. Repo icinde bos bir `sent_links.json` dosyasi olustur, icine `[]` yaz
   (bot bunu kendi guncelleyecek).
5. Repo **Settings > Secrets and variables > Actions** kismina git, ucuncu bir
   secret daha ekle:
   - `TELEGRAM_BOT_TOKEN` -> BotFather'dan aldigin token
   - `TELEGRAM_CHAT_ID` -> kanal/grup kullanici adi ya da chat id (senin
     durumunda: `@lsfflowtrading`)
   - `TELEGRAM_MESSAGE_THREAD_ID` -> belirli bir konuya (topic) atacaksan
     o konunun ID'si (senin durumunda: `23601`, "Haberler" konusu icin)
6. **Actions** sekmesine git, workflow'u gor, "Run workflow" ile bir kere elle
   test et. Sorun yoksa artik her 15 dakikada bir otomatik calisacak.

> Not: GitHub Actions'in ucretsiz plani private repolarda ayda 2000 dakika
> calisma suresi verir; bu bot her calistiginda birkaç saniye surdugu icin
> bu limit rahatlikla yeter.

## 3) Kendi Bilgisayarinda / Sunucuda Calistirma (Alternatif)

```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="senin_token"
export TELEGRAM_CHAT_ID="@kanalin_veya_id"
python bot.py
```

Belirli araliklarla calismasi icin:
- Linux/Mac: `crontab -e` ile `*/15 * * * * cd /path/to/dxy-gold-bot && python bot.py` ekle.
- Windows: Gorev Zamanlayici (Task Scheduler) kullan.

## Ozellestirme

- `bot.py` icindeki `RSS_FEEDS` listesine istedigin kadar RSS kaynagi ekleyebilirsin.
- `KEYWORDS` listesine baska anahtar kelimeler (ornegin "fed faiz karari",
  "nfp" gibi) ekleyerek filtreyi genisletebilirsin.
- `MAX_MESSAGES_PER_RUN` ile bir calistirmada en fazla kac mesaj atilacagini
  ayarlayabilirsin (Telegram spam/rate-limit onlemi icin).

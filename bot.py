#!/usr/bin/env python3
"""
DXY & XAUUSD Haber Botu
-------------------------------
Belirli RSS kaynaklarindan DXY (Dolar Endeksi) ve XAUUSD (Altin) ile
ilgili haberleri tarar, daha once gonderilmemis olanlari Telegram
kanalina gonderir.

Kurulum:
1. requirements.txt icindeki paketleri yukle: pip install -r requirements.txt
2. Asagidaki ortam degiskenlerini ayarla:
   - TELEGRAM_BOT_TOKEN  -> BotFather'dan aldigin token
   - TELEGRAM_CHAT_ID    -> @kanalkullaniciadi ya da sayisal chat id
3. Calistir: python bot.py

GitHub Actions ile otomatik calistirmak icin repo README'sine bak.
"""

import os
import json
import re
import time
import urllib.parse
import feedparser
import requests
from datetime import datetime, timezone, timedelta
from dateutil import parser as date_parser
from deep_translator import GoogleTranslator

# ---------------------------------------------------------------------------
# AYARLAR
# ---------------------------------------------------------------------------

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Eger grubun icinde belirli bir konuya (topic) mesaj atmak istiyorsan
# (ornegin "Haberler" konusu), o konunun ID'sini buraya ortam degiskeni
# olarak ver. Normal kanal/grup icin bos birak.
MESSAGE_THREAD_ID = os.environ.get("TELEGRAM_MESSAGE_THREAD_ID", "")

# Taranacak RSS kaynaklari (Turkce + Ingilizce finans haberleri - Ingilizce
# olanlar otomatik Turkce'ye cevrilip gonderilir)
RSS_FEEDS = [
    "https://tr.investing.com/rss/news_1.rss",       # Investing.com TR - Doviz Haberleri
    "https://tr.investing.com/rss/news_11.rss",      # Investing.com TR - Emtia & Vadeli Islem Haberleri
    "https://tr.investing.com/rss/forex.rss",        # Investing.com TR - Doviz Analiz ve Gorusleri
    "https://tr.investing.com/rss/commodities.rss",  # Investing.com TR - Emtia Analiz ve Gorusleri
    "https://www.investing.com/rss/news_285.rss",    # Investing.com - Forex News (EN)
    "https://www.investing.com/rss/news_25.rss",     # Investing.com - Commodities News (EN)
    "https://www.fxstreet.com/rss/news",             # FXStreet genel haber akisi (EN)
    "https://www.forexlive.com/feed/news",           # ForexLive (EN)
]

# Reuters resmi ucretsiz RSS sunmuyor, bu yuzden Google News'in Reuters'a
# ozel arama sonuclarini RSS olarak kullaniyoruz. Sadece belirlenen
# jeopolitik/makro konularla ilgili Reuters haberlerini getirir.
REUTERS_TOPICS = [
    "Trump", "Powell", "Federal Reserve", "FOMC", "Treasury",
    "bond yield", "US10Y", "US02Y", "CPI", "Core CPI", "PPI", "NFP",
    "inflation", "tariff", "trade war", "Iran", "Israel",
    "Strait of Hormuz", "Hormuz", "oil supply", "OPEC", "Saudi Arabia",
    "Houthi", "gold", "dollar index",
]
_reuters_query = "site:reuters.com (" + " OR ".join(
    f'"{t}"' if " " in t else t for t in REUTERS_TOPICS
) + ")"
REUTERS_GOOGLE_NEWS_URL = (
    "https://news.google.com/rss/search?q="
    + urllib.parse.quote(_reuters_query)
    + "&hl=en-US&gl=US&ceid=US:en"
)
RSS_FEEDS.append(REUTERS_GOOGLE_NEWS_URL)

# Finansal anahtar kelimeler - genel kaynaklarda (Investing, FXStreet,
# ForexLive) bunlardan biri gecmeyen haberler alakasiz sayilir ve atlanir.
FINANCIAL_KEYWORDS = [
    # Turkce
    "dolar endeksi", "dolar endeks", "amerikan dolar endeksi",
    "altin", "altın", "ons altin", "ons altın", "gram altin", "gram altın",
    "spot altin", "spot altın",
    # Ingilizce
    "dxy", "dollar index", "us dollar index",
    "xauusd", "gold", "gold price", "spot gold",
]

# Jeopolitik / makro anahtar kelimeler - sadece ozel filtrelenmis Reuters
# kaynagindan gelen haberler icin gecerli (o kaynak zaten sorgu ile
# daraltilmis oldugu icin ekstra kelime kontrolune gerek yok, ama yine de
# guvenlik amacli tutulur).
GEOPOLITICAL_KEYWORDS = [
    "trump", "powell", "federal reserve", "fomc", "fed ", "treasury",
    "bond yield", "us10y", "us02y", "cpi", "core cpi", "ppi", "nfp",
    "inflation", "tariff", "trade war", "iran", "israel",
    "strait of hormuz", "hormuz", "oil supply", "opec", "saudi arabia",
    "houthi", "gold", "dollar",
]

# Geriye donuk uyumluluk icin (gerekirse baska yerde kullanilabilir)
KEYWORDS = FINANCIAL_KEYWORDS + GEOPOLITICAL_KEYWORDS

# Zaten gonderilen haberlerin linklerini tuttugumuz dosya (tekrar gondermemek icin)
STATE_FILE = os.path.join(os.path.dirname(__file__), "sent_links.json")

# Tek seferde en fazla kac haber gonderilsin (spam onlemek icin)
MAX_MESSAGES_PER_RUN = 8

# Bir haberin "guncel" sayilmasi icin en fazla kac saat once yayinlanmis
# olmasi gerektigi. Bundan eski haberler otomatik elenir.
MAX_NEWS_AGE_HOURS = 6

# Botun ilk kez calisip calismadigini anlamak icin kullanilan ozel anahtar.
# Ilk calistirmada, o ana kadar birikmis eski haberler/veriler GONDERILMEZ,
# sadece "goruldu" olarak isaretlenir. Boylece kurulum sirasinda haber
# seline (spam) yol acilmaz.
FIRST_RUN_MARKER = "__initialized__"

# --- Ekonomik Takvim (ForexFactory ucretsiz veri kaynagi) ---
CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
# Sadece bu para birimine ait olaylari takip et (DXY ve altin en cok USD verilerinden etkilenir)
CALENDAR_COUNTRY = "USD"
# Sadece bu etki seviyesindeki (kirmizi=High) olaylari gonder
CALENDAR_IMPACT = "High"
# Turkiye saat dilimi (UTC+3)
TURKEY_TZ = timezone(timedelta(hours=3))


# ---------------------------------------------------------------------------
# YARDIMCI FONKSIYONLAR
# ---------------------------------------------------------------------------

def load_sent_links():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, IOError):
            return set()
    return set()


def save_sent_links(links):
    # Dosyanin cok buyumesini engellemek icin en son 500 linki tut
    trimmed = list(links)[-500:]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, ensure_ascii=False, indent=2)


def matches_keywords(text, keyword_list):
    text_lower = text.lower()
    return any(kw in text_lower for kw in keyword_list)


def trim_to_sentence(text, max_length):
    """Metni max_length karakterde keser, ama mumkunse yarim cumlede
    kesmemek icin en yakin cumle sonuna (. ! ?) kadar geri gider."""
    if not text or len(text) <= max_length:
        return text
    cut = text[:max_length]
    last_stop = max(cut.rfind("."), cut.rfind("!"), cut.rfind("?"))
    if last_stop > max_length * 0.4:  # cok kisa kalmasin diye makul bir esik
        return cut[: last_stop + 1]
    return cut.rstrip() + "…"


def clean_html(raw_html):
    """Basit bir HTML etiketi temizleyici (ozet metinlerinde gecebiliyor)."""
    return re.sub(r"<[^>]+>", "", raw_html or "").strip()


def is_entry_recent(entry):
    """Haberin yayinlanma tarihine bakar, MAX_NEWS_AGE_HOURS'tan daha eski
    ise False doner. Tarih bilgisi yoksa guvenli tarafta kalip True doner
    (elenmez), boylece tarih eksikligi yuzunden gecerli haber kacmaz."""
    published_struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if not published_struct:
        return True
    try:
        published_dt = datetime(*published_struct[:6], tzinfo=timezone.utc)
    except Exception:
        return True
    age = datetime.now(timezone.utc) - published_dt
    return age <= timedelta(hours=MAX_NEWS_AGE_HOURS)


def fetch_matching_entries():
    matched = []
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
        except Exception as e:
            print(f"[UYARI] {feed_url} okunamadi: {e}")
            continue

        # Reuters (Google News) kaynagi zaten sorguda daraltildigi icin
        # jeopolitik kelimeleri de kabul ediyoruz. Diger genel kaynaklarda
        # sadece dogrudan DXY/Altin ile ilgili haberleri kabul ediyoruz,
        # boylece alakasiz haberler (spam) elenmis olur.
        is_reuters_feed = feed_url == REUTERS_GOOGLE_NEWS_URL
        allowed_keywords = KEYWORDS if is_reuters_feed else FINANCIAL_KEYWORDS

        for entry in feed.entries:
            if not is_entry_recent(entry):
                continue

            title = entry.get("title", "")
            summary = clean_html(entry.get("summary", ""))
            link = entry.get("link", "")

            combined_text = f"{title} {summary}"
            if matches_keywords(combined_text, allowed_keywords):
                matched.append({
                    "title": title,
                    "summary": trim_to_sentence(summary, 380),
                    "link": link,
                    "source": feed.feed.get("title", feed_url),
                })
    return matched


def fetch_high_impact_calendar_events():
    """ForexFactory'nin ucretsiz haftalik takviminden yuksek etkili (kirmizi)
    USD olaylarini ceker."""
    try:
        response = requests.get(CALENDAR_URL, timeout=15)
        response.raise_for_status()
        events = response.json()
    except Exception as e:
        print(f"[UYARI] Ekonomik takvim alinamadi: {e}")
        return []

    important = []
    for event in events:
        if event.get("country") != CALENDAR_COUNTRY:
            continue
        if event.get("impact") != CALENDAR_IMPACT:
            continue
        important.append(event)
    return important


def calendar_event_base_key(event):
    # Ayni olayi tekrar gondermemek icin benzersiz bir anahtar olusturuyoruz
    return f"calendar:{event.get('country')}:{event.get('title')}:{event.get('date')}"


def format_time_tr(raw_date):
    try:
        dt = date_parser.parse(raw_date)
        dt_tr = dt.astimezone(TURKEY_TZ)
        return dt_tr.strftime("%d %B %Y, %H:%M") + " (TR saati)"
    except Exception:
        return raw_date


def format_calendar_reminder_message(event, reminder_label):
    title = event.get("title", "Bilinmeyen veri")
    country = event.get("country", "")
    forecast = event.get("forecast") or "—"
    previous = event.get("previous") or "—"
    time_display = format_time_tr(event.get("date", ""))

    text = (
        f"🔴 <b>Yüksek Etkili Ekonomik Veri - {reminder_label}</b>\n\n"
        f"📌 {title} ({country})\n"
        f"🕒 {time_display}\n"
        f"📈 Beklenti: {forecast}\n"
        f"📉 Önceki: {previous}"
    )
    return text


def format_calendar_release_message(event):
    title = event.get("title", "Bilinmeyen veri")
    country = event.get("country", "")
    actual = event.get("actual") or "—"
    forecast = event.get("forecast") or "—"
    previous = event.get("previous") or "—"
    time_display = format_time_tr(event.get("date", ""))

    text = (
        f"🚨 <b>VERİ AÇIKLANDI</b>\n\n"
        f"📌 {title} ({country})\n"
        f"🕒 {time_display}\n"
        f"✅ Açıklanan: <b>{actual}</b>\n"
        f"📈 Beklenti: {forecast}\n"
        f"📉 Önceki: {previous}"
    )
    return text


def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    if MESSAGE_THREAD_ID:
        payload["message_thread_id"] = MESSAGE_THREAD_ID
    response = requests.post(url, data=payload, timeout=15)
    if not response.ok:
        print(f"[HATA] Telegram gonderim hatasi: {response.status_code} {response.text}")
    return response.ok


def translate_to_turkish(text):
    """Metni otomatik olarak Turkce'ye cevirir. Zaten Turkce ise ya da
    ceviri servisi basarisiz olursa orijinal metni dondurur."""
    if not text:
        return text
    try:
        translated = GoogleTranslator(source="auto", target="tr").translate(text)
        return translated or text
    except Exception as e:
        print(f"[UYARI] Ceviri basarisiz, orijinal metin kullanilacak: {e}")
        return text


def format_message(entry):
    title = translate_to_turkish(entry["title"])
    summary = translate_to_turkish(entry["summary"])
    source = entry["source"]
    # Sadece basligi ve ozetin en onemli kismini duz metin olarak gonder,
    # link/URL eklemiyoruz. Ingilizce kaynaklardan gelen metin otomatik
    # olarak Turkce'ye cevrilir.
    text = f"📊 <b>{title}</b>\n\n{summary}\n\n📰 {source}"
    return text


# ---------------------------------------------------------------------------
# ANA AKIS
# ---------------------------------------------------------------------------

def main():
    if not BOT_TOKEN or not CHAT_ID:
        raise SystemExit(
            "HATA: TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID ortam degiskenlerini "
            "ayarlaman lazim."
        )

    sent_links = load_sent_links()
    is_first_run = FIRST_RUN_MARKER not in sent_links

    matched_entries = fetch_matching_entries()
    calendar_events = fetch_high_impact_calendar_events()

    new_entries = [e for e in matched_entries if e["link"] and e["link"] not in sent_links]

    # --- Ekonomik takvim icin 3 asamali bildirim mantigi ---
    calendar_messages_to_send = []  # (unique_key, mesaj_metni)
    now_utc = datetime.now(timezone.utc)

    for event in calendar_events:
        base_key = calendar_event_base_key(event)
        raw_date = event.get("date", "")
        try:
            event_time = date_parser.parse(raw_date)
            if event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=timezone.utc)
        except Exception:
            continue

        time_until_event = event_time - now_utc
        actual_value = event.get("actual")

        # 1) Veri aciklandiysa (actual dolmussa) ve daha once gonderilmediyse
        release_key = f"{base_key}:actual"
        if actual_value not in (None, "", "N/A") and release_key not in sent_links:
            calendar_messages_to_send.append(
                (release_key, format_calendar_release_message(event))
            )
            continue  # Bu olay icin baska hatirlatma kontrolune gerek yok

        # 2) 24 saat once hatirlatma (23-25 saat penceresi icinde yakala)
        reminder_24h_key = f"{base_key}:24h"
        if (
            timedelta(hours=23) <= time_until_event <= timedelta(hours=25)
            and reminder_24h_key not in sent_links
        ):
            calendar_messages_to_send.append(
                (reminder_24h_key, format_calendar_reminder_message(event, "24 Saat Kaldı"))
            )

        # 3) 1 saat once hatirlatma (50-70 dakika penceresi icinde yakala)
        reminder_1h_key = f"{base_key}:1h"
        if (
            timedelta(minutes=50) <= time_until_event <= timedelta(minutes=70)
            and reminder_1h_key not in sent_links
        ):
            calendar_messages_to_send.append(
                (reminder_1h_key, format_calendar_reminder_message(event, "1 Saat Kaldı"))
            )

    # --- Ilk calistirma korumasi ---
    # Bot ilk kez calisiyorsa, o ana kadar birikmis her seyi SESSIZCE
    # "gorulmus" olarak isaretle ve hicbir mesaj gonderme. Boylece kurulum
    # sirasinda eski haber/veri seli olusmaz, sadece bundan sonraki YENI
    # seyler gonderilir.
    if is_first_run:
        for entry in new_entries:
            if entry["link"]:
                sent_links.add(entry["link"])
        for unique_key, _ in calendar_messages_to_send:
            sent_links.add(unique_key)
        sent_links.add(FIRST_RUN_MARKER)
        save_sent_links(sent_links)
        print("Ilk calistirma: mevcut haber/veriler isaretlendi, mesaj gonderilmedi.")
        return

    if not new_entries and not calendar_messages_to_send:
        print("Yeni haber/veri yok.")
        return

    sent_count = 0

    for unique_key, message in calendar_messages_to_send:
        if sent_count >= MAX_MESSAGES_PER_RUN:
            break
        ok = send_telegram_message(message)
        if ok:
            sent_links.add(unique_key)
            sent_count += 1
            time.sleep(1.5)

    for entry in new_entries:
        if sent_count >= MAX_MESSAGES_PER_RUN:
            break
        message = format_message(entry)
        ok = send_telegram_message(message)
        if ok:
            sent_links.add(entry["link"])
            sent_count += 1
            time.sleep(1.5)  # Telegram rate-limit'e takilmamak icin kucuk bekleme

    save_sent_links(sent_links)
    print(f"{sent_count} yeni haber/veri gonderildi.")


if __name__ == "__main__":
    main()

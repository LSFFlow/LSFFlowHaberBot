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
import feedparser
import requests
from datetime import timezone, timedelta
from dateutil import parser as date_parser

# ---------------------------------------------------------------------------
# AYARLAR
# ---------------------------------------------------------------------------

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Eger grubun icinde belirli bir konuya (topic) mesaj atmak istiyorsan
# (ornegin "Haberler" konusu), o konunun ID'sini buraya ortam degiskeni
# olarak ver. Normal kanal/grup icin bos birak.
MESSAGE_THREAD_ID = os.environ.get("TELEGRAM_MESSAGE_THREAD_ID", "")

# Taranacak RSS kaynaklari (Turkce finans haberleri)
RSS_FEEDS = [
    "https://tr.investing.com/rss/news_1.rss",       # Investing.com TR - Doviz Haberleri
    "https://tr.investing.com/rss/news_11.rss",      # Investing.com TR - Emtia & Vadeli Islem Haberleri
    "https://tr.investing.com/rss/forex.rss",        # Investing.com TR - Doviz Analiz ve Gorusleri
    "https://tr.investing.com/rss/commodities.rss",  # Investing.com TR - Emtia Analiz ve Gorusleri
]

# Haber basligi/ozetinde aranacak anahtar kelimeler (kucuk harfe cevrilip kontrol edilir)
KEYWORDS = [
    "dxy", "dolar endeksi", "dolar endeks", "amerikan dolar endeksi",
    "xauusd", "altin", "altın", "ons altin", "ons altın", "gram altin", "gram altın",
    "spot altin", "spot altın",
]

# Zaten gonderilen haberlerin linklerini tuttugumuz dosya (tekrar gondermemek icin)
STATE_FILE = os.path.join(os.path.dirname(__file__), "sent_links.json")

# Tek seferde en fazla kac haber gonderilsin (spam onlemek icin)
MAX_MESSAGES_PER_RUN = 8

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


def matches_keywords(text):
    text_lower = text.lower()
    return any(kw in text_lower for kw in KEYWORDS)


def clean_html(raw_html):
    """Basit bir HTML etiketi temizleyici (ozet metinlerinde gecebiliyor)."""
    return re.sub(r"<[^>]+>", "", raw_html or "").strip()


def fetch_matching_entries():
    matched = []
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
        except Exception as e:
            print(f"[UYARI] {feed_url} okunamadi: {e}")
            continue

        for entry in feed.entries:
            title = entry.get("title", "")
            summary = clean_html(entry.get("summary", ""))
            link = entry.get("link", "")

            combined_text = f"{title} {summary}"
            if matches_keywords(combined_text):
                matched.append({
                    "title": title,
                    "summary": summary[:280],
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


def calendar_event_key(event):
    # Ayni olayi tekrar gondermemek icin benzersiz bir anahtar olusturuyoruz
    return f"calendar:{event.get('country')}:{event.get('title')}:{event.get('date')}"


def format_calendar_message(event):
    title = event.get("title", "Bilinmeyen veri")
    country = event.get("country", "")
    forecast = event.get("forecast") or "—"
    previous = event.get("previous") or "—"
    raw_date = event.get("date", "")

    try:
        dt = date_parser.parse(raw_date)
        dt_tr = dt.astimezone(TURKEY_TZ)
        time_display = dt_tr.strftime("%d %B %Y, %H:%M") + " (TR saati)"
    except Exception:
        time_display = raw_date

    text = (
        f"🔴 <b>Yüksek Etkili Ekonomik Veri</b>\n\n"
        f"📌 {title} ({country})\n"
        f"🕒 {time_display}\n"
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


def format_message(entry):
    title = entry["title"]
    summary = entry["summary"]
    source = entry["source"]
    # Sadece basligi ve ozetin en onemli kismini duz metin olarak gonder,
    # link/URL eklemiyoruz.
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
    matched_entries = fetch_matching_entries()
    calendar_events = fetch_high_impact_calendar_events()

    new_entries = [e for e in matched_entries if e["link"] and e["link"] not in sent_links]
    new_calendar_events = [
        e for e in calendar_events if calendar_event_key(e) not in sent_links
    ]

    if not new_entries and not new_calendar_events:
        print("Yeni haber/veri yok.")
        return

    sent_count = 0

    for event in new_calendar_events:
        if sent_count >= MAX_MESSAGES_PER_RUN:
            break
        message = format_calendar_message(event)
        ok = send_telegram_message(message)
        if ok:
            sent_links.add(calendar_event_key(event))
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

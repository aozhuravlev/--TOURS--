#!/usr/bin/env python3
"""Exchange short-lived token for long-lived token."""
import os
from pathlib import Path
from dotenv import load_dotenv
import httpx

# Load .env
load_dotenv(Path(__file__).parent / ".env")

APP_ID = "736675292833129"  # Your App ID


def exchange_token(short_token: str, app_secret: str) -> str:
    """Exchange short-lived token for long-lived token."""
    url = "https://graph.facebook.com/v18.0/oauth/access_token"

    params = {
        "grant_type": "fb_exchange_token",
        "client_id": APP_ID,
        "client_secret": app_secret,
        "fb_exchange_token": short_token,
    }

    print("Exchanging token...")

    with httpx.Client(timeout=30) as client:
        response = client.get(url, params=params)

        if response.status_code == 200:
            data = response.json()
            new_token = data.get("access_token")
            expires_in = data.get("expires_in", 0)
            days = expires_in // 86400

            print(f"\nУспех!")
            print(f"Новый токен живёт {days} дней")
            print(f"\n--- НОВЫЙ ТОКЕН (скопируй в .env) ---")
            print(new_token)
            print("--- КОНЕЦ ТОКЕНА ---")

            return new_token
        else:
            print(f"\nОшибка: {response.status_code}")
            print(response.json())
            return None


if __name__ == "__main__":
    print("=" * 50)
    print("Обмен Short-lived → Long-lived токен")
    print("=" * 50)
    print(f"\nApp ID: {APP_ID}")

    short_token = input("\nВведи новый short-lived токен из Graph API Explorer: ").strip()
    if not short_token:
        print("Токен не введён!")
        exit(1)

    app_secret = input("Введи App Secret: ").strip()
    if not app_secret:
        print("App Secret не введён!")
        exit(1)

    exchange_token(short_token, app_secret)

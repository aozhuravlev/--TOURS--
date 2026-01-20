#!/usr/bin/env python3
"""
Exchange short-lived Facebook token for long-lived token (60 days).

How to get a short-lived token:
1. Go to https://developers.facebook.com/tools/explorer/
2. Select your App
3. Click "Generate Access Token"
4. Grant permissions: instagram_basic, instagram_content_publish, pages_read_engagement
5. Copy the token

Usage:
    python scripts/get_long_token.py <SHORT_TOKEN>
    python scripts/get_long_token.py --check          # Check current token expiry
"""

import sys
import os
import argparse
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

import httpx


def get_long_lived_token(short_token: str, app_id: str, app_secret: str) -> dict:
    """Exchange short-lived token for long-lived token."""
    url = "https://graph.facebook.com/v18.0/oauth/access_token"
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": short_token,
    }

    response = httpx.get(url, params=params)
    return response.json()


def check_token(token: str) -> dict:
    """Check token validity and expiration."""
    url = "https://graph.facebook.com/v18.0/debug_token"
    params = {
        "input_token": token,
        "access_token": token,
    }

    response = httpx.get(url, params=params)
    return response.json()


def get_instagram_account_id(token: str, page_id: str) -> str:
    """Get Instagram Business Account ID from Facebook Page."""
    url = f"https://graph.facebook.com/v18.0/{page_id}"
    params = {
        "fields": "instagram_business_account",
        "access_token": token,
    }

    response = httpx.get(url, params=params)
    data = response.json()

    if "instagram_business_account" in data:
        return data["instagram_business_account"]["id"]
    return None


def main():
    parser = argparse.ArgumentParser(description="Facebook token helper")
    parser.add_argument("token", nargs="?", help="Short-lived token to exchange")
    parser.add_argument("--check", action="store_true", help="Check current token from .env")
    parser.add_argument("--app-id", help="Facebook App ID")
    parser.add_argument("--app-secret", help="Facebook App Secret")
    args = parser.parse_args()

    if args.check:
        # Check current token
        current_token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
        if not current_token:
            print("No INSTAGRAM_ACCESS_TOKEN in .env")
            sys.exit(1)

        print("Checking current token...")
        result = check_token(current_token)

        if "data" in result:
            data = result["data"]
            is_valid = data.get("is_valid", False)
            expires_at = data.get("expires_at", 0)
            app_id = data.get("app_id", "unknown")

            print(f"Valid: {is_valid}")
            print(f"App ID: {app_id}")

            if expires_at:
                import datetime
                exp_date = datetime.datetime.fromtimestamp(expires_at)
                print(f"Expires: {exp_date}")
                days_left = (exp_date - datetime.datetime.now()).days
                print(f"Days left: {days_left}")
            else:
                print("Expires: Never (or already expired)")
        else:
            print(f"Error: {result}")
        sys.exit(0)

    if not args.token:
        print("Usage: python scripts/get_long_token.py <SHORT_TOKEN>")
        print("       python scripts/get_long_token.py --check")
        print()
        print("To get a short-lived token:")
        print("1. Go to https://developers.facebook.com/tools/explorer/")
        print("2. Select your App")
        print("3. Add permissions: instagram_basic, instagram_content_publish, pages_read_engagement")
        print("4. Generate Access Token")
        print("5. Run this script with the token")
        sys.exit(1)

    app_id = args.app_id or os.getenv("FACEBOOK_APP_ID")
    app_secret = args.app_secret or os.getenv("FACEBOOK_APP_SECRET")

    if not app_id or not app_secret:
        print("ERROR: Need FACEBOOK_APP_ID and FACEBOOK_APP_SECRET")
        print("Add them to .env or pass via --app-id and --app-secret")
        print()
        print("Find them at: https://developers.facebook.com/apps/<your-app>/settings/basic/")
        sys.exit(1)

    print("Exchanging token...")
    result = get_long_lived_token(args.token, app_id, app_secret)

    if "access_token" in result:
        long_token = result["access_token"]
        expires_in = result.get("expires_in", 0)
        days = expires_in // 86400

        print()
        print("=" * 60)
        print("SUCCESS! Long-lived token obtained.")
        print(f"Expires in: {days} days")
        print("=" * 60)
        # Update .env file automatically
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            with open(env_path, "r") as f:
                env_content = f.read()

            import re
            new_content = re.sub(
                r'INSTAGRAM_ACCESS_TOKEN=.*',
                f'INSTAGRAM_ACCESS_TOKEN={long_token}',
                env_content
            )

            with open(env_path, "w") as f:
                f.write(new_content)

            print()
            print("=" * 60)
            print("SUCCESS! Long-lived token obtained and saved to .env")
            print(f"Expires in: {days} days")
            print("=" * 60)
        else:
            print()
            print("=" * 60)
            print("SUCCESS! Long-lived token obtained.")
            print(f"Expires in: {days} days")
            print("=" * 60)
            print()
            print("Add this to your .env file:")
            print()
            print(f"INSTAGRAM_ACCESS_TOKEN={long_token}")

        # Also check Instagram account
        page_id = os.getenv("FACEBOOK_PAGE_ID")
        if page_id:
            ig_id = get_instagram_account_id(long_token, page_id)
            if ig_id:
                print(f"\nInstagram Business Account ID: {ig_id}")
    else:
        print(f"ERROR: {result}")
        sys.exit(1)


if __name__ == "__main__":
    main()

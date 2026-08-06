#!/usr/bin/env python
"""Diagnose DATABASE_URL without revealing the password.

The usual failure is a password containing characters that are reserved in a URI
(@ : / ? # etc). Those must be percent-encoded or psycopg will parse the string
into the wrong pieces.
"""

from __future__ import annotations

import os
import string
import sys
from urllib.parse import quote, urlsplit

from dotenv import load_dotenv

RESERVED = set("@:/?#[]%!$&'()*+,;= \"<>{}|^~`\\")


def main() -> int:
    load_dotenv(".env")
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("DATABASE_URL is empty")
        return 1

    print(f"placeholder text left in string: {any(k in url for k in ('PASTE_YOUR', 'YOUR-PASSWORD', '[', ']'))}")
    print(f"'@' count in whole string: {url.count('@')}  (should be 1)")

    try:
        authority = url.split("://", 1)[1].split("@")[0]
    except IndexError:
        print("string does not look like a URI")
        return 1

    user, _, password = authority.partition(":")
    parts = urlsplit(url)

    print(f"scheme:   {parts.scheme}")
    print(f"username: {user}")
    print(f"host:     {parts.hostname}")
    print(f"port:     {parts.port}")
    print(f"database: {parts.path}")
    print(f"password length: {len(password)}")

    shape = "".join(
        "A" if c in string.ascii_uppercase
        else "a" if c in string.ascii_lowercase
        else "9" if c.isdigit()
        else c
        for c in password
    )
    print(f"password shape:  {shape}")

    found = sorted(set(password) & RESERVED)
    if found:
        print(f"\nRESERVED CHARACTERS IN PASSWORD: {found}")
        print("These break URI parsing. Percent-encoded form of your password:")
        print(f"  {quote(password, safe='')}")
        print("\nSwap the password portion of DATABASE_URL for the line above.")
    else:
        print("\nNo reserved characters — the password is safe to use unencoded,")
        print("so authentication failing means the password itself is wrong.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

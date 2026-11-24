"""
Wati API client used by batch imports and tests.

Design notes:
- Single class, works per-tenant (tenant_id becomes part of the base URL).
- Sliding-window rate limiter (per-minute) shared by API calls that opt into it.
- Retry loop with 429 Retry-After handling and exponential backoff for transient
  errors. Non-429 errors also sleep between retries (a bug-fix over filippa's
  equivalent — see .molds/mold-4.md).

Notes on deliberately-missing features:
- get_messages_per_contact does NOT accept a from_date / since argument. The
  Wati /getMessages API does not support reliable date filtering. Filippa
  tried and explicitly abandoned that path in commit 65d9613. Idempotency is
  handled at the bronze layer via ON CONFLICT (tenant_id, wati_message_id).
"""

import os
import time
import requests
import dotenv

dotenv.load_dotenv()


class WatiAPIClient:
    def __init__(self, tenant_id, tenant_access_token):
        print(" - Creating a Wati client...\n")
        self.api_token = tenant_access_token
        self.base_url = 'https://live-mt-server.wati.io/' + str(tenant_id)
        self.header = {'Authorization': self.api_token, 'Content-Type': 'application/json'}

        # Reused session for connection pooling / keep-alive.
        # Shared across all _request_with_retries calls so a full backfill
        # doesn't pay the TCP + TLS handshake cost per message. Filippa does
        # the same in filippa/wati/shared/wati_client.py:52-56.
        self._session = requests.Session()
        self._session.headers.update(self.header)

        # Legacy: used as fixed sleep between pages in get_contacts().
        # Left alone per mold-4 ("do not touch get_contacts, it works").
        self.rate_limit = 2

        # Sliding-window rate limiter for /getMessages calls.
        # Default 60 req/min is well under Wati's documented 10 req per 10 sec cap
        # (see filippa/resources/wati/api_errors_rate_limits.json). Override
        # with WATI_RATE_LIMIT env var if you hit real 429s.
        self.requests_per_minute = int(os.getenv('WATI_RATE_LIMIT', '60'))
        self.request_times = []

        # Retry config (applies to _request_with_retries only)
        self.retry_max_attempts = 5
        self.retry_base_delay = 5  # seconds; doubles each attempt

    # -----------------------------------------------------------------
    # Rate limiter + retry helpers (used by get_messages_per_contact)
    # -----------------------------------------------------------------

    def _rate_limit(self):
        """
        Sliding-window per-minute limiter.

        Modeled on filippa/wati/shared/wati_client.py:_rate_limit (lines 64-80).
        """
        now = time.time()
        minute_ago = now - 60

        # Evict old timestamps
        self.request_times = [t for t in self.request_times if t > minute_ago]

        if len(self.request_times) >= self.requests_per_minute:
            sleep_time = 60 - (now - self.request_times[0]) + 1
            if sleep_time > 0:
                print(f"   [rate-limit] {self.requests_per_minute}/min reached, sleeping {sleep_time:.1f}s")
                time.sleep(sleep_time)
                self.request_times = []

        self.request_times.append(now)

    def _request_with_retries(self, method, endpoint):
        """
        GET/POST against the Wati API with rate limiting, 429 Retry-After
        handling, and exponential backoff on transient errors.

        Returns the parsed JSON body on success, or None after exhausting retries.

        Modeled on filippa/wati/shared/wati_client.py:_make_request (lines 82-137),
        with one bug-fix: the non-429 HTTPError branch also sleeps between
        retries, so flapping servers don't produce a tight retry loop.
        """
        url = self.base_url.rstrip('/') + endpoint

        for attempt in range(self.retry_max_attempts):
            self._rate_limit()

            try:
                response = self._session.request(method, url, timeout=30)

                # 429 → honor Retry-After header, then retry
                if response.status_code == 429:
                    retry_after = response.headers.get('Retry-After')
                    if retry_after is None:
                        retry_after = self.retry_base_delay * (2 ** attempt)
                    try:
                        retry_after = float(retry_after)
                    except (TypeError, ValueError):
                        retry_after = self.retry_base_delay * (2 ** attempt)
                    print(
                        f"   [429] rate limited, sleeping {retry_after}s "
                        f"(attempt {attempt + 1}/{self.retry_max_attempts})"
                    )
                    time.sleep(retry_after)
                    continue

                # Non-200 other than 429 → log, backoff, retry
                if response.status_code != 200:
                    print(f"   [HTTP {response.status_code}] {endpoint}")
                    if attempt < self.retry_max_attempts - 1:
                        backoff = self.retry_base_delay * (2 ** attempt)
                        print(f"   Retrying in {backoff}s...")
                        time.sleep(backoff)
                        continue
                    return None

                return response.json()

            except requests.exceptions.RequestException as e:
                print(f"   [net-error] {e}")
                if attempt < self.retry_max_attempts - 1:
                    backoff = self.retry_base_delay * (2 ** attempt)
                    time.sleep(backoff)
                    continue
                return None
            except ValueError as e:  # JSON decode
                print(f"   [json-error] {e}")
                if attempt < self.retry_max_attempts - 1:
                    time.sleep(self.retry_base_delay)
                    continue
                return None

        return None

    # -----------------------------------------------------------------
    # Public API methods
    # -----------------------------------------------------------------

    def _build_messages_url(self, phone_number, page_number=1, page_size=1000):
        """
        Build the /getMessages URL for a given phone, page, and size.

        Kept as a method so V1 (static URL well-formedness check) can call it
        without hitting the API.
        """
        return (
            self.base_url.rstrip('/')
            + f"/api/v1/getMessages/{phone_number}"
            + f"?pageSize={page_size}&pageNumber={page_number}"
        )

    def get_contact_count(self):
        """Return the total contact count from Wati with a single lightweight API call."""
        url = self.base_url + "/api/v1/getContacts?pageSize=1"
        try:
            response = self._session.get(url, timeout=15)
            if response.status_code != 200:
                return None
            data = response.json()
            return data.get("link", {}).get("total")
        except Exception:
            return None

    def get_contacts(self):
        """
        Fetch all contacts for the tenant via link-based pagination.

        Intentionally untouched by mold-4 — this method works, has been
        verified pulling 9224 contacts in 2 minutes, and the mold explicitly
        scopes the fix to get_messages_per_contact only.
        """
        print("Getting Wati contacts...")

        url = self.base_url + "/api/v1/getContacts?pageSize=200"
        all_contacts = []

        with requests.Session() as session:
            session.headers.update(self.header)

            while url is not None:
                print(url)
                response = session.get(url)
                if response.status_code != 200:
                    print(f"Error: {response.status_code}")
                    return None
                data = response.json()
                all_contacts.extend(data['contact_list'])
                url = (data.get('link', {})).get('nextPage')
                if url is not None:
                    time.sleep(self.rate_limit)
        return all_contacts

    def get_messages_per_contact(self, phone_number, page_size=1000):
        """
        Fetch ALL messages for a single contact, paginating until exhausted.

        Returns a (messages, success) tuple:
          - success=True:  messages is a list (possibly empty) of message dicts
          - success=False: messages is [] and an error was already logged

        Uses the retry-aware _request_with_retries helper, which handles 429
        with Retry-After and exponential backoff for transient errors.

        Pagination: stops when Wati returns fewer items than requested OR the
        accumulated total reaches the server-reported total. Wati's reported
        link.total is trusted but optional.

        DOES NOT accept a from_date / since parameter. See module docstring.
        """
        print(f"   * Getting messages from contact {phone_number}")

        all_messages = []
        page_number = 1

        while True:
            # Build the same URL that V1b tests, so the test path and the real
            # path cannot drift. _build_messages_url returns an absolute URL,
            # so strip base_url to pass a relative endpoint to the retry helper.
            full_url = self._build_messages_url(phone_number, page_number=page_number, page_size=page_size)
            endpoint = full_url[len(self.base_url.rstrip('/')):]
            data = self._request_with_retries("GET", endpoint)
            if data is None:
                # Retries exhausted — tell the caller this contact failed
                return [], False

            # Wati sometimes returns {'result': False, 'info': '...'} on 200
            if data.get('result') is False:
                print(f"   [wati-error] {data.get('info', 'unknown')}")
                return [], False

            msg_block = data.get('messages') or {}
            if isinstance(msg_block, list):
                items = msg_block
                reported_total = None
            elif isinstance(msg_block, dict):
                items = msg_block.get('items', []) or []
                reported_total = msg_block.get('total')
            else:
                items = []
                reported_total = None

            if not items:
                break

            all_messages.extend(items)

            # Stop conditions
            if reported_total is not None and len(all_messages) >= reported_total:
                break
            if len(items) < page_size:
                break

            page_number += 1

        return all_messages, True


def main():
    """Manual test harness — not part of the batch import flow."""
    print("Welcome to the Wati client — manual test mode")
    client = WatiAPIClient(
        os.getenv("WATI_TENANT_ID"),
        os.getenv("WATI_TENANT_ACCESS_TOKEN") or os.getenv("WATI_AUTH_TOKEN"),
    )
    contacts = client.get_contacts()
    print(f"Fetched {len(contacts) if contacts else 0} contacts")


if __name__ == "__main__":
    main()

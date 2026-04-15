import base64
import json
import sys

import httpx

PRODUCTION_BASE_URL = "https://axis360api.baker-taylor.com/Services/VendorAPI/"
QA_BASE_URL = "https://axis360apiqa.baker-taylor.com/Services/VendorAPI/"

access_token_endpoint = "accesstoken"
availability_endpoint = "availability/v2"


def get_headers(
    base_url: str, username: str, password: str, library_id: str
) -> dict[str, str]:
    authorization_str = ":".join([username, password, library_id])
    authorization_bytes = authorization_str.encode("utf_16_le")
    authorization_b64 = base64.standard_b64encode(authorization_bytes)
    resp = httpx.post(
        base_url + access_token_endpoint,
        headers={"Authorization": f"Basic {authorization_b64.decode('utf-8')}"},
    )
    if resp.status_code != 200:
        print(f"Error: {resp.status_code}")
        print(f"Headers: {json.dumps(dict(resp.headers), indent=4)}")
        print(resp.text)
        sys.exit(-1)
    return {
        "Authorization": "Bearer " + resp.json()["access_token"],
        "Library": library_id,
    }


def availability(base_url: str, username: str, password: str, library_id: str) -> str:
    headers = get_headers(base_url, username, password, library_id)
    resp = httpx.get(
        base_url + availability_endpoint,
        headers=headers,
        params={"updatedDate": "1970-01-01 00:00:00"},
        timeout=30.0,
    )
    return resp.text

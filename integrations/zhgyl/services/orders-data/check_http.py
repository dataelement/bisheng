"""Run inside the orders-data container; never emit the local service credential."""

import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def request(key=None, post=False, expected=200):
    headers = {} if key is None else {"X-Zhgyl-Data-Key": key}
    req = Request(
        "http://127.0.0.1:8080/api/zhgyl/orders", b"{}" if post else None, headers
    )
    try:
        with urlopen(req, timeout=3) as response:
            code, body = response.status, json.load(response)
    except HTTPError as error:
        code, body = error.code, json.load(error)
    assert code == expected
    return body


if __name__ == "__main__":
    request(expected=403)
    actual = request(os.environ["ZHGYL_ORDERS_DATA_KEY"])
    expected = json.loads(Path("/data/orders.json").read_text())
    assert actual == expected
    assert len(actual["orders"]) == len(expected["orders"]) > 0 and all(
        order["mock"] is True for order in actual["orders"]
    )
    request(os.environ["ZHGYL_ORDERS_DATA_KEY"], post=True, expected=405)
    print(
        json.dumps(
            {
                "real_http": True,
                "unauthorized_status": 403,
                "readonly_post_status": 405,
                "orders": len(actual["orders"]),
                "same_dataset_as_order_skill": True,
            }
        )
    )

"""Exercise the easy HE analytics API through the deployed gateway."""

from __future__ import annotations

import argparse
import json

from he_client import HEClient, PublicScalar, PublicVector


TOLERANCE = 1e-3


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=None,
        help=(
            "HE gateway URL; defaults to HE_GATEWAY_URL or "
            "http://127.0.0.1:18082"
        ),
    )
    args = parser.parse_args()

    x_values = [2.0, 4.0, 6.0, 8.0]
    y_values = [1.0, 3.0, 5.0, 7.0]
    weights = PublicVector([0.1, 0.2, 0.3, 0.4])
    bias = PublicScalar(1.5)

    with HEClient(args.url, multiplicative_depth=4) as he:
        x = he.encrypt(x_values)
        y = he.encrypt(y_values)

        public_add = (x + PublicVector([10, 20, 30, 40])).decrypt()
        public_subtract = (x - PublicScalar(1)).decrypt()
        public_multiply = (x * weights).decrypt()
        square = x.square().decrypt()

        variance = he.variance_components(x)
        covariance = he.covariance_components(x, y)
        correlation = he.correlation_components(x, y)
        weighted_sum = he.weighted_sum(x, weights).decrypt()[0]
        risk_score = he.risk_score(x, weights, bias).decrypt()[0]

        actual = {
            "public_add": public_add,
            "public_subtract": public_subtract,
            "public_multiply": public_multiply,
            "square": square,
            "variance_components": {
                "sum_x": variance.sum_x.decrypt()[0],
                "sum_x_square": variance.sum_x_square.decrypt()[0],
                "count": variance.count,
            },
            "covariance_components": {
                "sum_x": covariance.sum_x.decrypt()[0],
                "sum_y": covariance.sum_y.decrypt()[0],
                "sum_xy": covariance.sum_xy.decrypt()[0],
                "count": covariance.count,
            },
            "correlation_components": {
                "sum_x": correlation.sum_x.decrypt()[0],
                "sum_y": correlation.sum_y.decrypt()[0],
                "sum_x_square": correlation.sum_x_square.decrypt()[0],
                "sum_y_square": correlation.sum_y_square.decrypt()[0],
                "sum_xy": correlation.sum_xy.decrypt()[0],
                "count": correlation.count,
            },
            "weighted_sum": weighted_sum,
            "risk_score": risk_score,
        }

    expected = {
        "public_add": [12.0, 24.0, 36.0, 48.0],
        "public_subtract": [1.0, 3.0, 5.0, 7.0],
        "public_multiply": [0.2, 0.8, 1.8, 3.2],
        "square": [4.0, 16.0, 36.0, 64.0],
        "variance_components": {
            "sum_x": 20.0,
            "sum_x_square": 120.0,
            "count": 4,
        },
        "covariance_components": {
            "sum_x": 20.0,
            "sum_y": 16.0,
            "sum_xy": 100.0,
            "count": 4,
        },
        "correlation_components": {
            "sum_x": 20.0,
            "sum_y": 16.0,
            "sum_x_square": 120.0,
            "sum_y_square": 84.0,
            "sum_xy": 100.0,
            "count": 4,
        },
        "weighted_sum": 6.0,
        "risk_score": 7.5,
    }

    errors: list[float] = []

    def compare(got: object, wanted: object) -> None:
        if isinstance(wanted, dict):
            assert isinstance(got, dict)
            for key, value in wanted.items():
                compare(got[key], value)
        elif isinstance(wanted, list):
            assert isinstance(got, list)
            for got_value, wanted_value in zip(got, wanted, strict=True):
                compare(got_value, wanted_value)
        else:
            assert isinstance(got, (int, float))
            assert isinstance(wanted, (int, float))
            errors.append(abs(float(got) - float(wanted)))

    compare(actual, expected)
    maximum_error = max(errors)
    status = "PASS" if maximum_error <= TOLERANCE else "FAIL"
    print(
        json.dumps(
            {
                "status": status,
                "scheme": "CKKS",
                "openfhe_required_on_caller": False,
                "maximum_absolute_error": maximum_error,
                "results": actual,
            },
            indent=2,
        )
    )
    if status != "PASS":
        raise RuntimeError(
            f"maximum error {maximum_error} exceeds tolerance {TOLERANCE}"
        )


if __name__ == "__main__":
    main()

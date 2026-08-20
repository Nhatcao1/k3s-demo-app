"""CLI entrypoint for CPU and GPU Kubernetes HE Jobs."""

from __future__ import annotations

import argparse
import json
import os
import sys

from he_worker.request import EXECUTION_BACKENDS, OPERATIONS, WorkerRequest
from he_worker.runner import execute


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute one encrypted operation in an HE SDK workspace."
    )
    parser.add_argument("--workspace", default=os.getenv("HE_WORKSPACE"))
    parser.add_argument(
        "--run-id",
        type=int,
        default=os.getenv("HE_RUN_ID"),
        help="PostgreSQL-backed run id; mutually exclusive with --workspace",
    )
    parser.add_argument(
        "--operation", choices=OPERATIONS, default=os.getenv("HE_OPERATION")
    )
    parser.add_argument("--left", default=os.getenv("HE_LEFT"))
    parser.add_argument("--right", default=os.getenv("HE_RIGHT"))
    parser.add_argument("--output", default=os.getenv("HE_OUTPUT"))
    parser.add_argument(
        "--execution-backend",
        choices=EXECUTION_BACKENDS,
        default=os.getenv("HE_EXECUTION_BACKEND"),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        default=os.getenv("HE_OVERWRITE", "false").lower()
        in ("1", "true", "yes"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if bool(arguments.workspace) == (arguments.run_id is not None):
            raise ValueError("select exactly one of workspace or run-id")
        request = WorkerRequest(
            workspace=arguments.workspace or "",
            operation=arguments.operation or "",
            left=arguments.left or "",
            right=arguments.right or None,
            output=arguments.output or "",
            execution_backend=arguments.execution_backend,
            overwrite=arguments.overwrite,
        )
        if arguments.run_id is not None:
            from he_worker.postgres import execute_postgres

            result = execute_postgres(request, arguments.run_id)
        else:
            result = execute(request.validate())
    except Exception as error:
        failure = {
            "status": "failed",
            "error_type": type(error).__name__,
            "message": str(error),
        }
        print(json.dumps(failure, sort_keys=True), file=sys.stderr)
        return 1

    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

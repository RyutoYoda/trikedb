"""Optional S3 API integration smoke using an isolated in-memory test server.

Run with ``uv run --extra remote --with 'moto[server]' python benchmarks/s3_conflict_smoke.py``.
No cloud credentials or external bucket are required.
"""

import os

import boto3
import fsspec
from moto.server import ThreadedMotoServer

from trikedb import TrikeDB
from trikedb.storage import ConcurrentWriteError


def main():
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=0)
    server.start()
    try:
        host, port = server.get_host_and_port()
        endpoint = f"http://{host}:{port}"
        os.environ["AWS_ACCESS_KEY_ID"] = "testing"
        os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
        os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
        fsspec.config.conf["s3"] = {"client_kwargs": {"endpoint_url": endpoint}}
        boto3.client("s3", endpoint_url=endpoint).create_bucket(Bucket="example-bucket")
        path = "s3://example-bucket/graph.yaml"

        first = TrikeDB(path)
        first.add("alice", "KNOWS", "bob")
        second = TrikeDB(path)
        first.add("alice", "KNOWS", "carol")
        try:
            second.add("alice", "KNOWS", "dave")
        except ConcurrentWriteError:
            pass
        else:
            raise AssertionError("stale writer silently overwrote newer data")
        loaded = TrikeDB(path)
        assert list(loaded.triples(s="alice", p="KNOWS", o="carol"))
        assert not list(loaded.triples(s="alice", p="KNOWS", o="dave"))
        print("S3-compatible write, reload and stale-writer rejection passed")
    finally:
        server.stop()


if __name__ == "__main__":
    main()

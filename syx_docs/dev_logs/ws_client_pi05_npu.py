"""Minimal OpenPI-wire websocket client: smoke the npu-torch serve path.

Connects, reads connect-time metadata, sends one wire observation, prints the
returned actions. Uses the same codec module the server uses.
"""
import asyncio

import numpy as np
import websockets

from apxinf.serving.msgpack_numpy import packer, unpackb

URI = "ws://127.0.0.1:8199"


async def main():
    rng = np.random.default_rng(0)
    # ping off: the first request triggers server-side TorchAir compile
    # (~2 min) during which the single-threaded server cannot answer pings
    async with websockets.connect(URI, max_size=64 * 1024 * 1024, ping_interval=None) as ws:
        metadata = unpackb(await ws.recv())
        print("server metadata:")
        for k in ("engine", "robot", "precision", "image_keys", "state_key",
                  "action_horizon", "action_dim", "discrete_state"):
            print(f"  {k}: {metadata.get(k)}")

        obs = {
            "observation/image": rng.integers(0, 255, (256, 256, 3), dtype=np.uint8),
            "observation/wrist_image": rng.integers(0, 255, (256, 256, 3), dtype=np.uint8),
            "observation/state": rng.uniform(-1, 1, 8).astype(np.float32),
            "prompt": "put the black bowl on the stove",
        }
        pack = packer()
        await ws.send(pack.pack(obs))
        reply = unpackb(await asyncio.wait_for(ws.recv(), timeout=300))
        actions = reply.get("actions")
        print("reply keys:", list(reply.keys()))
        print("actions:", getattr(actions, "shape", type(actions)),
              getattr(actions, "dtype", ""))
        print("policy_timing:", reply.get("policy_timing"))
        print("actions[0]:", np.asarray(actions)[0].tolist())
        print("WS_CLIENT_DONE")


asyncio.run(main())

# Optional private splash pool

The default build retains the upstream splash. A private build can stage numbered
`logo_1.rgba` through `logo_N.rgba` files (up to 64), using the existing AL111LG1
header and RGBA8888 payload. Put personal assets in ignored `local_assets/`, not in
the tracked `altscreen/` source tree.

The build-time helper validates the header and payload length, copies the original
bytes, and records their hashes:

```sh
python3 tools/stage_private_logos.py \
  --source local_assets/mixed16 \
  --release build/sd/Toolbox/carplay_alt_screen/mirror_display/release
```

The complete SD builder can call this with `PRIVATE_LOGO_DIR` after staging the
upstream release; its SD checksum manifest must include the resulting numbered
assets, `logo_pool.count`, and `logo_pool.sha256`.

The launcher draws once for each private111 session, using the QNX-tested
`dd if=/dev/urandom bs=16 count=1` and POSIX `cksum` path. A real
`DIRECT111_TAP_STOP` triggers the upstream session restart and a new draw. An
abnormal sidecar recovery retains the selected image. A redundant START does not
draw, and an explicit `ALT111_LOGO_ASSET` override stays fixed. Genuine random
draws can repeat; there is no persistent boot counter or fixed lyric image.

Missing optional assets or unavailable entropy fall back to upstream `logo.rgba`
and emit `STARTUP_LOGO_RANDOM_DETAIL` in the mirror log. Runtime selection does
not hash/decode the complete image on each launch. It does not change upstream
RGI, layout, map geometry, frame rate, or the transparent watermark asset.

Host regression coverage (fake mirror process, no QNX binaries executed):

```sh
python3 tests/test_private_splash.py -v
```

After installation on a vehicle, verify a real disconnect/reconnect changes the
selection over several sessions, and that `STARTUP_LOGO_ASSET` names a numbered
asset. This host coverage does not replace an on-vehicle integration test.

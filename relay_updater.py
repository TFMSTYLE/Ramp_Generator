# SPDX-FileCopyrightText: 2025-2026 The French Monkey
# SPDX-License-Identifier: GPL-3.0-or-later

"""Keeps this addon up to date from Relay.

The same file ships in every TFMSTYLE addon. Change it in templates/relay_updater.py
in the tools repo and run tools/add_updater.py, never in one addon on its own.

When Blender starts it asks Relay whether this addon has a newer published version,
and shows an Update button in the panel if so. It does nothing when the user has
turned off Allow Online Access, inside the Addon Collection (which has its own
updates), or when installed from the Blender store or any other remote repository,
such as the TFMSTYLE one on Relay (Blender updates those itself).
Nothing is installed until Relay's signature over it has been checked.
"""

import base64
import hashlib
import json
import pathlib
import threading
import tomllib
import urllib.error
import urllib.request

import bpy

BASE = "https://relay.tfmstyle.com/update"
PUBLIC_KEY = "B0ZZ6buE3it5mjbajNhQa2+8fOaDJwUPL++tIC7zGEA="
TIMEOUT = 15

STATE = {"item": None, "busy": False, "zip": None, "done": False, "error": ""}
_slug = ""
_operator = None

# Ed25519 signature check (RFC 8032). Blender ships no crypto library.
P = 2**255 - 19
Q = 2**252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)


def _add(a, b):
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    e = (y1 - x1) * (y2 - x2) % P
    f = (y1 + x1) * (y2 + x2) % P
    g = 2 * t1 * t2 * D % P
    h = 2 * z1 * z2 % P
    i, j, k, l = f - e, h - g, h + g, f + e
    return (i * j % P, k * l % P, j * k % P, i * l % P)


def _multiply(point, scalar):
    result = (0, 1, 1, 0)
    while scalar:
        if scalar & 1:
            result = _add(result, point)
        point = _add(point, point)
        scalar >>= 1
    return result


def _decode_point(data):
    if len(data) != 32:
        return None
    number = int.from_bytes(data, "little")
    sign = number >> 255
    y = number & ((1 << 255) - 1)
    if y >= P:
        return None
    u = (y * y - 1) % P
    v = (D * y * y + 1) % P
    x = u * pow(v, 3, P) * pow(u * pow(v, 7, P), (P - 5) // 8, P) % P
    if (v * x * x - u) % P != 0:
        x = x * SQRT_M1 % P
    if (v * x * x - u) % P != 0:
        return None
    if x == 0 and sign:
        return None
    if x & 1 != sign:
        x = P - x
    return (x, y, 1, x * y % P)


_BASE_POINT = _decode_point((4 * pow(5, P - 2, P) % P).to_bytes(32, "little"))


def _verify(public_key, signature, message):
    if len(public_key) != 32 or len(signature) != 64:
        return False
    a = _decode_point(public_key)
    r = _decode_point(signature[:32])
    s = int.from_bytes(signature[32:], "little")
    if a is None or r is None or s >= Q:
        return False
    h = int.from_bytes(hashlib.sha512(signature[:32] + public_key + message).digest(), "little") % Q
    left, right = _multiply(_BASE_POINT, s), _add(r, _multiply(a, h))
    return (left[0] * right[2] - right[0] * left[2]) % P == 0 and (left[1] * right[2] - right[1] * left[2]) % P == 0


def _version_tuple(text):
    return tuple(int(p) for p in str(text).split(".")[:3])


def _manifest():
    path = pathlib.Path(__file__).parent / "blender_manifest.toml"
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _repo():
    parts = __package__.split(".")
    return parts[1] if len(parts) >= 3 and parts[0] == "bl_ext" else None


def _remote(repo):
    """Does Blender keep this repository up to date itself, as it does the store
    and the TFMSTYLE repository on Relay? Then an update here would be a second one."""
    try:
        return any(r.module == repo and r.use_remote_url for r in bpy.context.preferences.extensions.repos)
    except AttributeError:
        return False


def active():
    """Only an extension installed by hand updates itself. One from the Blender store
    or any other remote repository gets its updates from Blender, so this stays out."""
    repo = _repo()
    return repo not in (None, "blender_org") and not _remote(repo)


def _request(url):
    req = urllib.request.Request(url, headers={"User-Agent": "TFMSTYLE-Addon"})
    return urllib.request.urlopen(req, timeout=TIMEOUT)


def _signed_ok(manifest):
    try:
        key = base64.b64decode(PUBLIC_KEY)
        body = {k: v for k, v in manifest.items() if k != "manifest_signature"}
        text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        artifact = manifest["artifact"]
        return _verify(key, base64.b64decode(manifest["manifest_signature"]), text.encode("utf-8")) and _verify(
            key, base64.b64decode(artifact["signature"]), artifact["sha256"].encode("utf-8")
        )
    except (KeyError, TypeError, ValueError):
        return False


def _check(current):
    try:
        with _request(f"{BASE}/{_slug}/manifest.json?channel=stable") as r:
            manifest = json.loads(r.read().decode("utf-8"))
        if _signed_ok(manifest) and _version_tuple(manifest["latest"]) > _version_tuple(current):
            STATE["item"] = manifest
    except urllib.error.HTTPError as e:
        if e.code != 404:  # 404 only means nothing is published
            STATE["error"] = f"Could not check for updates: {e.code}"
    except (OSError, ValueError, KeyError):
        pass  # offline is normal, and not worth a message in somebody's panel
    STATE["busy"] = False


def _download(folder):
    try:
        artifact = STATE["item"]["artifact"]
        if not artifact["url"].startswith(BASE + "/"):
            raise ValueError("the download is not on Relay")
        with _request(artifact["url"]) as r:
            data = r.read(artifact["size_bytes"] + 1)
        if len(data) != artifact["size_bytes"] or hashlib.sha256(data).hexdigest() != artifact["sha256"]:
            raise ValueError("the download does not match its signature")
        path = folder / f"{_slug}.zip"
        path.write_bytes(data)
        STATE["zip"] = path
    except (OSError, ValueError, KeyError) as e:
        STATE["error"] = f"Update refused: {e}"[:80]
    STATE["busy"] = False


def _redraw():
    wm = getattr(bpy.context, "window_manager", None)
    for window in getattr(wm, "windows", []):
        for area in window.screen.areas:
            area.tag_redraw()


def _tick():
    if STATE["busy"]:
        return 0.5
    path, STATE["zip"] = STATE["zip"], None
    _redraw()
    if path:
        # This replaces the file that is running, so nothing may follow it.
        STATE.update(item=None, done=True)
        bpy.ops.extensions.package_install_files(filepath=str(path), repo=_repo(), enable_on_install=True)
    return None


def _start(target, *args):
    if STATE["busy"]:
        return
    STATE["busy"] = True
    threading.Thread(target=target, args=args, daemon=True).start()
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=0.5)


def _on_start():
    if bpy.app.online_access:
        _start(_check, _manifest()["version"])


def draw(layout):
    """One line in the addon's panel, and only when there is something to say."""
    if not _operator:
        return
    item = STATE["item"]
    if STATE["done"]:
        layout.label(text="Updated. Restart Blender to finish", icon="INFO")
    elif item:
        box = layout.box()
        row = box.row()
        row.label(text=f"Version {item['latest']} available", icon="FILE_REFRESH")
        row.operator(_operator.bl_idname, text="Update")
    if STATE["busy"] and item:
        layout.label(text="Downloading", icon="TIME")
    if STATE["error"]:
        layout.label(text=STATE["error"], icon="ERROR")


def _update(self, context):
    folder = pathlib.Path(bpy.utils.extension_path_user(__package__, path="updates", create=True))
    _start(_download, folder)
    return {"FINISHED"}


def register(slug):
    global _slug, _operator
    if not active():
        return
    _slug = slug
    # A class per addon, because they share this file and can be installed together.
    key = slug.replace("-", "_")
    _operator = type(
        f"TFMSTYLE_OT_update_{key}",
        (bpy.types.Operator,),
        {"bl_idname": f"tfmstyle_update.{key}", "bl_label": "Update", "bl_description": "Install the new version from Relay", "execute": _update},
    )
    bpy.utils.register_class(_operator)
    if not bpy.app.background:
        bpy.app.timers.register(_on_start, first_interval=3.0)


def unregister():
    global _operator
    for timer in (_on_start, _tick):
        if bpy.app.timers.is_registered(timer):
            bpy.app.timers.unregister(timer)
    if _operator:
        bpy.utils.unregister_class(_operator)
        _operator = None

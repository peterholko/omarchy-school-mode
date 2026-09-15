"""Owned Chrome/Chromium integration and a locally signed browser companion.

No remote code is fetched. The private signing key survives upgrades. Only the
two named policy files and two native-host manifests belong to this installer.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import tempfile
import zipfile
from omarchy_kids.core.paths import write_private, write_public

HOST = "io.github.peterholko.school_mode"
PORT = 47651
BASE_URL = f"http://127.0.0.1:{PORT}"
POLICY_NAME = "90-omarchy-school-mode.json"
POLICY_KEYS = {"URLBlocklist", "URLAllowlist", "ExtensionSettings", "ExtensionInstallForcelist"}
BROWSERS = ("chromium", "opt/chrome")
WRAPPER = "/usr/bin/omarchy-kids-controls-school-websites"
CONFIG = Path("/etc/omarchy-kids-controls")
STATE = Path("/var/lib/omarchy-kids-controls")
ETC = Path("/etc")
SOURCE = Path(__file__).resolve().parents[2] / "browser-extension"


def read_json(path):
    return json.loads(path.read_text())


def owned(path, owner=None):
    owner = os.geteuid() if owner is None else owner
    info = path.lstat()
    if path.is_symlink() or info.st_uid != owner or info.st_mode & 0o022:
        raise ValueError(f"Not an administrator-owned path: {path}")
    if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
        raise ValueError(f"Not a regular file or directory: {path}")


def policy_paths(etc=ETC):
    return [etc / browser / "policies/managed" / POLICY_NAME for browser in BROWSERS]


def host_paths(etc=ETC):
    return [etc / browser / "native-messaging-hosts" / f"{HOST}.json" for browser in BROWSERS]


def conflicts(etc=ETC, extension_id=""):
    problems = []
    for own in policy_paths(etc):
        for directory in (own.parent, own.parent.with_name("recommended")):
            for path in sorted(directory.glob("*.json")):
                if path == own:
                    continue
                try:
                    policy = read_json(path)
                except (OSError, ValueError):
                    problems.append(f"Cannot inspect {path}")
                    continue
                if not isinstance(policy, dict):
                    problems.append(f"Invalid policy in {path}")
                    continue
                keys = POLICY_KEYS.intersection(policy)
                extensions = policy.get("3rdparty", {}).get("extensions", {}) if isinstance(policy.get("3rdparty", {}), dict) else {}
                if keys or (extension_id and extension_id in extensions):
                    problems.append(f"Browser policy conflict in {path}: {', '.join(sorted(keys)) or 'companion settings'}")
    return problems


def plan(config=CONFIG, state=STATE, etc=ETC, owner=None):
    receipt_path = config / "school-websites.json"
    previous = {}
    if receipt_path.exists() or receipt_path.is_symlink():
        owned(receipt_path, owner)
        previous = read_json(receipt_path)
        if previous.get("identity") != HOST:
            raise ValueError("Unknown website integration receipt")
    for path in policy_paths(etc) + host_paths(etc):
        # Reject symlinked ancestors as well as files (browser paths are root
        # controlled, but an unrelated installation must not be adopted).
        for parent in path.parents:
            if parent == etc.parent:
                break
            if parent.exists() or parent.is_symlink():
                owned(parent, owner)
                if parent.stat().st_mode & 0o005 != 0o005:
                    raise ValueError(f"The browser cannot read {parent}; review its directory permissions before setup.")
        if path.exists() or path.is_symlink():
            owned(path, owner)
            if str(path) not in previous.get("files", {}):
                raise ValueError(f"Website integration collision at {path}")
            expected = previous["files"][str(path)]
            if expected != "policy" and path.read_text() != expected:
                raise ValueError(f"Website integration was edited: {path}")
            if expected == "policy":
                validate_policy(read_json(path), previous["extension_id"])
    directory = state / "school-websites"
    for path in (directory, config / "school-websites-key.pem"):
        if path.exists() or path.is_symlink():
            owned(path, owner)
    return previous


def validate_policy(policy, extension_id):
    if not isinstance(policy, dict) or set(policy) - {"URLBlocklist", "ExtensionSettings", "3rdparty"}:
        raise ValueError("The School Mode browser policy contains unrelated settings; preserve it before setup/removal.")
    if policy.get("ExtensionSettings", {}) != ({extension_id: extension_settings()} if "ExtensionSettings" in policy else {}):
        raise ValueError("The School Mode extension policy was edited.")
    if "3rdparty" in policy and policy["3rdparty"] != managed_flag(extension_id):
        raise ValueError("The School Mode companion policy was edited.")
    from .domains import normalize_domains
    if "URLBlocklist" in policy and normalize_domains(policy["URLBlocklist"]) != policy["URLBlocklist"]:
        raise ValueError("The School Mode block list was edited.")


def extension_settings():
    return {"installation_mode": "force_installed", "update_url": BASE_URL + "/update.xml", "override_update_url": True}


def managed_flag(extension_id):
    return {"extensions": {extension_id: {"policy": {"SchoolModeInstalled": True}}}}


def varint(value):
    out = bytearray()
    while value >= 128:
        out.append((value & 127) | 128)
        value >>= 7
    return bytes(out + bytes([value]))


def field(number, data):
    return varint((number << 3) | 2) + varint(len(data)) + data


def openssl(*args, data=None):
    return subprocess.run(["/usr/bin/openssl", *args], input=data, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=True, timeout=30).stdout


def package(source, key):
    public = openssl("pkey", "-in", str(key), "-pubout", "-outform", "DER")
    digest = hashlib.sha256(public).digest()[:16]
    extension_id = "".join(chr(ord("a") + int(n, 16)) for n in digest.hex())
    archive = io.BytesIO()
    manifest = read_json(source / "manifest.json")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
        for path in sorted(source.iterdir()):
            if path.is_file():
                output.writestr(zipfile.ZipInfo(path.name, (2026, 1, 1, 0, 0, 0)), path.read_bytes())
    data = archive.getvalue()
    signed = field(1, digest)
    # Chromium CRX3 uses RSA PKCS#1 v1.5 / SHA256 (crx_creator.cc), not PSS.
    signature = openssl("dgst", "-sha256", "-sign", str(key),
                        data=b"CRX3 SignedData\x00" + struct.pack("<I", len(signed)) + signed + data)
    header = field(2, field(1, public) + field(2, signature)) + field(10000, signed)
    crx = b"Cr24" + struct.pack("<II", 3, len(header)) + header + data
    return extension_id, manifest["version"], crx


def write_bytes(path, data):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".website-")
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fchmod(output.fileno(), 0o644)
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def install(previous, config=CONFIG, state=STATE, etc=ETC, source=SOURCE):
    directory = state / "school-websites"
    directory.mkdir(mode=0o755, parents=True, exist_ok=True)
    directory.chmod(0o755)
    key = config / "school-websites-key.pem"
    if not key.exists():
        write_private(key, openssl("genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048").decode())
    owned(key)
    key.chmod(0o600)
    extension_id, version, crx = package(source, key)
    if previous and previous.get("extension_id") != extension_id:
        raise ValueError("Website signing key changed; preserve the old integration before replacing its identity.")
    write_bytes(directory / "school.crx", crx)
    xml = f'<?xml version="1.0"?><gupdate xmlns="http://www.google.com/update2/response" protocol="2.0"><app appid="{extension_id}"><updatecheck codebase="{BASE_URL}/school.crx" version="{version}"/></app></gupdate>\n'
    write_public(directory / "update.xml", xml)
    host = json.dumps({"name": HOST, "description": "Local School Mode website rules", "path": WRAPPER,
                       "type": "stdio", "allowed_origins": [f"chrome-extension://{extension_id}/"]}, indent=2) + "\n"
    files = {**{str(p): "policy" for p in policy_paths(etc)}, **{str(p): host for p in host_paths(etc)}}
    # Ownership is recorded before creating files so an interrupted setup is retryable.
    receipt = {"identity": HOST, "extension_id": extension_id, "version": version, "files": files}
    write_private(config / "school-websites.json", json.dumps(receipt, indent=2) + "\n")
    for path in policy_paths(etc) + host_paths(etc):
        # Setup inherits 0077 on some systems; the browser must traverse newly
        # created paths. Existing directory permissions are preserved.
        missing = []
        parent = path.parent
        while not parent.exists():
            missing.append(parent)
            parent = parent.parent
        for parent in reversed(missing):
            parent.mkdir(mode=0o755)
            parent.chmod(0o755)
        if path in host_paths(etc):
            write_public(path, host)
        elif not path.exists():
            write_public(path, "{}\n")
    write_public(directory / "installation.json", json.dumps({"extension_id": extension_id, "version": version}) + "\n")
    return receipt


def remove(config=CONFIG, state=STATE, etc=ETC):
    previous = plan(config, state, etc)
    if not previous:
        return
    for path in policy_paths(etc) + host_paths(etc):
        path.unlink(missing_ok=True)
    (state / "school-websites/installation.json").unlink(missing_ok=True)
    (config / "school-websites.json").unlink()
    # Retain the key and signed package, like other parent settings. There is
    # no installed policy or native host left using them after removal.

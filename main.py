import os
import sys
import time
import subprocess
import argparse
import threading
import queue
import boto3

# ──────────────────────────── CONFIG ────────────────────────────
# AWS CLI profile name — use "default" or a named profile from ~/.aws/config
# If you use AWS SSO, run `aws sso login --profile <name>` before using this tool.
AWS_PROFILE = "default"

# AWS region where your IoT things and tunnels are registered
AWS_REGION = "eu-central-1"

LOCAL_PROXY_PORT = 5555

# SSH username on the remote device (e.g. "root", "ubuntu", "pi", "ec2-user")
SSH_USER = "root"

LOCAL_PROXY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "localproxy")
LOCAL_PROXY_PATH = os.path.join(LOCAL_PROXY_DIR, "localproxy.exe")
CA_CERT_PATH = os.path.join(LOCAL_PROXY_DIR, "cacert.pem")

# V1 = Greengrass Secure Tunneling Component / AWS IoT Device Client
# V2 = Local proxy v2
# Omit --destination-client-type for v3-to-v3 connections
DESTINATION_CLIENT_TYPE = "V1"
# ────────────────────────────────────────────────────────────────


def check_local_proxy():
    if not os.path.isfile(LOCAL_PROXY_PATH):
        print(f"[ERROR] Local proxy not found at: {LOCAL_PROXY_PATH}")
        print()
        print("Download the binary for your platform from:")
        print("  https://github.com/aws-samples/aws-iot-securetunneling-localproxy/releases")
        print()
        print(f"Place the binary in: {LOCAL_PROXY_DIR}")
        sys.exit(1)

    if not os.path.isfile(CA_CERT_PATH):
        print(f"[ERROR] CA certificate bundle not found at: {CA_CERT_PATH}")
        print()
        print("Download it from: https://curl.se/ca/cacert.pem")
        print(f"Place it in:      {LOCAL_PROXY_DIR}")
        sys.exit(1)


def open_tunnel(thing_name):
    print(f"[1/4] Opening secure tunnel to '{thing_name}' ...")

    session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
    client = session.client("iotsecuretunneling")

    response = client.open_tunnel(
        description=f"CLI tunnel to {thing_name}",
        destinationConfig={
            "thingName": thing_name,
            "services": ["SSH"],
        },
        timeoutConfig={
            "maxLifetimeTimeoutMinutes": 720,
        },
    )

    tunnel_id = response["tunnelId"]
    source_token = response["sourceAccessToken"]

    print(f"       Tunnel ID : {tunnel_id}")
    print(f"       Region    : {AWS_REGION}")
    print(f"       Timeout   : 720 min")
    return tunnel_id, source_token


def _reader_thread(pipe, output_queue):
    try:
        for raw_line in iter(pipe.readline, b""):
            line = raw_line.decode(errors="replace").rstrip()
            output_queue.put(line)
    except Exception:
        pass
    finally:
        output_queue.put(None)


def start_local_proxy(source_token):
    print(f"[2/4] Starting local proxy on localhost:{LOCAL_PROXY_PORT} ...")

    env = os.environ.copy()
    env["AWSIOT_TUNNEL_ACCESS_TOKEN"] = source_token
    env["SSL_CERT_FILE"] = CA_CERT_PATH

    cmd = [
        LOCAL_PROXY_PATH,
        "-r", AWS_REGION,
        "-s", str(LOCAL_PROXY_PORT),
        "-b", "127.0.0.1",
        "--destination-client-type", DESTINATION_CLIENT_TYPE,
        "-c", LOCAL_PROXY_DIR,
    ]

    proxy_proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    output_q = queue.Queue()
    t = threading.Thread(target=_reader_thread, args=(proxy_proc.stdout, output_q), daemon=True)
    t.start()

    return proxy_proc, output_q


def wait_for_proxy(proxy_proc, output_q, timeout=60):
    print("[3/4] Waiting for local proxy connection ...")
    collected = []
    start = time.time()

    while time.time() - start < timeout:
        try:
            line = output_q.get(timeout=1)
        except queue.Empty:
            if proxy_proc.poll() is not None:
                break
            continue

        if line is None:
            break

        collected.append(line)
        print(f"       [proxy] {line}")

        if "Listening for new connection on port" in line:
            print(f"       Proxy READY (took {int(time.time() - start)}s)")
            return True

        if "[fatal]" in line or "[error]" in line.lower():
            print(f"\n[ERROR] Local proxy reported a fatal/error condition (see above).")
            return False

    if proxy_proc.poll() is not None:
        print(f"\n[ERROR] Local proxy exited with code {proxy_proc.returncode}")
    else:
        print(f"\n[ERROR] Timed out after {timeout}s waiting for proxy to be ready.")

    if not collected:
        print("       (no output captured from local proxy)")
    return False


def check_tunnel_status(tunnel_id):
    session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
    client = session.client("iotsecuretunneling")
    resp = client.describe_tunnel(tunnelId=tunnel_id)
    tunnel = resp.get("tunnel", {})

    src = tunnel.get("sourceConnectionState", {})
    dst = tunnel.get("destinationConnectionState", {})
    return src.get("status", "UNKNOWN"), dst.get("status", "UNKNOWN")


def drain_proxy_output(output_q):
    while True:
        try:
            line = output_q.get_nowait()
            if line is None:
                return False
            print(f"       [proxy] {line}")
        except queue.Empty:
            return True


def start_ssh(tunnel_id, proxy_proc, output_q, max_retries=12, retry_delay=5):
    print(f"[4/4] Connecting SSH ({SSH_USER}@127.0.0.1:{LOCAL_PROXY_PORT}) ...")
    print(f"       Waiting for device to join the tunnel ...")

    ssh_cmd = (
        f'ssh -tt -4 -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL '
        f'-o ServerAliveInterval=15 '
        f'{SSH_USER}@127.0.0.1 -p {LOCAL_PROXY_PORT}'
    )

    destination_connected = False
    for attempt in range(1, max_retries + 1):
        drain_proxy_output(output_q)

        if proxy_proc.poll() is not None:
            print(f"\n[ERROR] Local proxy exited (code {proxy_proc.returncode})")
            drain_proxy_output(output_q)
            return 1

        src_status, dst_status = check_tunnel_status(tunnel_id)
        print(f"       Attempt {attempt}/{max_retries} -- source: {src_status}, destination: {dst_status}")

        if dst_status == "CONNECTED":
            destination_connected = True
            print("       Destination connected! Waiting 3s for tunnel to stabilize ...")
            time.sleep(3)
            drain_proxy_output(output_q)
            break

        time.sleep(retry_delay)

    if not destination_connected:
        print()
        print(f"[WARNING] Destination never connected after {max_retries * retry_delay}s.")
        print(f"          The device may not have the Secure Tunneling agent running,")
        print(f"          or the component is not picking up the MQTT token.")
        return 1

    if proxy_proc.poll() is not None:
        print(f"\n[ERROR] Local proxy died after destination connected (code {proxy_proc.returncode})")
        drain_proxy_output(output_q)
        return 1

    print()
    print("=" * 60)
    print(f"  User: {SSH_USER}")
    print(f"  Type your password and press Enter.")
    print(f"  (characters won't appear on screen, that's normal)")
    print(f"  Type 'exit' when done to close the session.")
    print("=" * 60)
    print()

    return os.system(ssh_cmd)


def close_tunnel(tunnel_id):
    try:
        session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
        client = session.client("iotsecuretunneling")
        client.close_tunnel(tunnelId=tunnel_id)
        print(f"\n[CLEANUP] Tunnel {tunnel_id} closed.")
    except Exception as e:
        print(f"\n[CLEANUP] Could not close tunnel: {e}")


def list_things():
    session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
    iot = session.client("iot")

    print(f"Listing IoT things (profile={AWS_PROFILE}, region={AWS_REGION}):\n")
    paginator = iot.get_paginator("list_things")
    things = []
    for page in paginator.paginate():
        for t in page.get("things", []):
            things.append(t["thingName"])

    things.sort()
    for name in things:
        print(f"  {name}")
    print(f"\nTotal: {len(things)} things")


def main():
    global AWS_PROFILE, AWS_REGION, LOCAL_PROXY_PORT, SSH_USER

    parser = argparse.ArgumentParser(
        description="Open an AWS IoT Secure Tunnel and SSH into a device.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "thing_name",
        nargs="?",
        help="IoT Core Thing name to connect to",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List all IoT things in the account and exit",
    )
    parser.add_argument(
        "--user", default=SSH_USER,
        help=f"SSH username on the remote device (default: {SSH_USER})",
    )
    parser.add_argument(
        "--port", type=int, default=LOCAL_PROXY_PORT,
        help=f"Local port for the proxy (default: {LOCAL_PROXY_PORT})",
    )
    parser.add_argument(
        "--profile", default=AWS_PROFILE,
        help=f"AWS CLI profile to use (default: {AWS_PROFILE})",
    )
    parser.add_argument(
        "--region", default=AWS_REGION,
        help=f"AWS region (default: {AWS_REGION})",
    )
    parser.add_argument(
        "--dest-client-type", default=DESTINATION_CLIENT_TYPE,
        choices=["V1", "V2"],
        help=f"Destination client protocol version (default: {DESTINATION_CLIENT_TYPE})",
    )

    args = parser.parse_args()

    AWS_PROFILE = args.profile
    AWS_REGION = args.region
    LOCAL_PROXY_PORT = args.port
    SSH_USER = args.user

    if args.list:
        list_things()
        return

    if not args.thing_name:
        thing_name = input("Enter the IoT Thing name: ").strip()
        if not thing_name:
            print("No thing name provided. Exiting.")
            return
    else:
        thing_name = args.thing_name

    check_local_proxy()

    tunnel_id = None
    proxy_proc = None

    try:
        tunnel_id, source_token = open_tunnel(thing_name)
        proxy_proc, output_q = start_local_proxy(source_token)

        if not wait_for_proxy(proxy_proc, output_q):
            sys.exit(1)

        start_ssh(tunnel_id, proxy_proc, output_q)

    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
    except Exception as e:
        print(f"\n[ERROR] {e}")
    finally:
        if proxy_proc and proxy_proc.poll() is None:
            print("[CLEANUP] Stopping local proxy ...")
            proxy_proc.terminate()
            try:
                proxy_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proxy_proc.kill()

        if tunnel_id:
            close_tunnel(tunnel_id)

    print("Done.")


if __name__ == "__main__":
    main()

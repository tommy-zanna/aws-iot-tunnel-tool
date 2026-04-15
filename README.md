# iot-secure-tunnel-cli

**SSH into your AWS IoT devices from the terminal — no AWS Console needed.**

A single Python script that opens an [AWS IoT Secure Tunnel](https://docs.aws.amazon.com/iot/latest/developerguide/secure-tunneling.html), waits for the device to connect, and drops you into a live interactive shell. All from your local command line.

## Why?

AWS IoT Secure Tunneling is powerful — it lets you reach devices behind firewalls, NATs, and private networks without exposing any inbound ports. But the default workflow means clicking through the AWS Console, copying tokens, downloading files, and juggling browser tabs.

**This tool reduces it to one command:**

```bash
python iot_secure_tunnel.py my-device-thing-name
```

That's it. Tunnel opens, device connects, SSH session starts. When you type `exit`, everything cleans up automatically.

### What it does under the hood

1. Opens a secure tunnel via the AWS IoT API using your configured AWS profile
2. Starts the [local proxy](https://github.com/aws-samples/aws-iot-securetunneling-localproxy) on your machine
3. Monitors the tunnel status — waits until the device picks up the token and joins
4. Launches an interactive SSH session through the tunnel
5. On exit, kills the proxy and closes the tunnel — no leftover resources

### Who is this for?

- **IoT engineers** who SSH into devices daily and are tired of the Console workflow
- **Fleet operators** debugging devices in the field behind restrictive networks
- **Anyone using AWS Greengrass** with the Secure Tunneling component who wants faster access

## Prerequisites

- **Python 3.7+** with `boto3` installed (`pip install boto3`)
- **AWS CLI** configured with a profile that has IoT Secure Tunneling permissions
- **Local proxy binary** — download from [GitHub releases](https://github.com/aws-samples/aws-iot-securetunneling-localproxy/releases) and place in a `localproxy/` folder next to the script
- **CA certificate bundle** — download [cacert.pem](https://curl.se/ca/cacert.pem) and place it in the same `localproxy/` folder
- **OpenSSH** available on your machine (built into Windows 10+, macOS, and Linux)

Your IoT devices must have a secure tunneling agent running (e.g. the `aws.greengrass.SecureTunneling` Greengrass component or the AWS IoT Device Client).

## Setup

```
iot-secure-tunnel-cli/
├── iot_secure_tunnel.py          # the script
├── localproxy/
│   ├── localproxy.exe            # local proxy binary (download for your OS)
│   └── cacert.pem                # CA certificate bundle
└── README.md
```

1. Clone this repo
2. Download the local proxy binary for your platform from [releases](https://github.com/aws-samples/aws-iot-securetunneling-localproxy/releases) and place it in `localproxy/`
3. Download [cacert.pem](https://curl.se/ca/cacert.pem) into `localproxy/`
4. Edit the config at the top of the script (profile, region, SSH user) or pass them as flags
5. If using AWS SSO, run `aws sso login --profile your-profile` first

## Usage

**Connect to a device:**

```bash
python iot_secure_tunnel.py my-thing-name
```

**Interactive mode (prompts for the thing name):**

```bash
python iot_secure_tunnel.py
```

**List all things in your account:**

```bash
python iot_secure_tunnel.py --list
```

**Override defaults via flags:**

```bash
python iot_secure_tunnel.py my-thing-name \
    --user ubuntu \
    --profile my-aws-profile \
    --region us-west-2 \
    --port 6666 \
    --dest-client-type V2
```

| Flag | Default | Description |
|------|---------|-------------|
| `--user` | `root` | SSH username on the device |
| `--profile` | `default` | AWS CLI profile |
| `--region` | `eu-central-1` | AWS region |
| `--port` | `5555` | Local proxy listen port |
| `--dest-client-type` | `V1` | `V1` for Greengrass/Device Client, `V2` for local proxy v2 |

## How it works

```
┌──────────────┐       ┌──────────────────────┐       ┌──────────────┐
│  Your laptop │──443──│  AWS IoT Secure       │──443──│  IoT Device  │
│              │       │  Tunneling Service    │       │              │
│  local proxy │       │  (WebSocket broker)   │       │  dest proxy  │
│  ↕ SSH       │       └──────────────────────┘       │  ↕ sshd      │
│  localhost:  │                                       │  localhost:22│
│  5555        │                                       │              │
└──────────────┘                                       └──────────────┘
```

Both sides connect **outbound on port 443** — no inbound firewall rules needed on either end. The tunnel is brokered by AWS over TLS-encrypted WebSocket connections.

## Required AWS Permissions

The IAM identity behind your AWS profile needs:

```json
{
    "Effect": "Allow",
    "Action": [
        "iot:OpenTunnel",
        "iot:DescribeTunnel",
        "iot:CloseTunnel",
        "iot:ListTunnels",
        "iot:ListThings"
    ],
    "Resource": "*"
}
```

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `destination: DISCONNECTED` after all retries | Device's tunneling agent isn't running | Check Greengrass component status on the device |
| `SSL handshake: certificate verify failed` | Missing CA bundle | Download [cacert.pem](https://curl.se/ca/cacert.pem) into `localproxy/` |
| `Connection refused` on SSH | Proxy not binding to 127.0.0.1 | Already handled by the script's `-b 127.0.0.1` flag |
| `Pseudo-terminal will not be allocated` | Running from a non-interactive shell | Run from a real terminal (CMD, PowerShell, or a terminal emulator) |

## License

MIT

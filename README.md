# iot-secure-tunnel-cli

**SSH into your AWS IoT devices from the terminal — no AWS Console needed.**

A single Python script that opens an [AWS IoT Secure Tunnel](https://docs.aws.amazon.com/iot/latest/developerguide/secure-tunneling.html), waits for the device to connect, and drops you into a live interactive shell. All from your local command line.

## Why?

AWS IoT Secure Tunneling is powerful — it lets you reach devices behind firewalls, NATs, and private networks without exposing any inbound ports. But the default workflow means clicking through the AWS Console, copying tokens, downloading files, and juggling browser tabs.

**This tool reduces it to one command:**

```bash
python iot_secure_tunnel.py my-device-thing-name

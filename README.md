# Adlos / Chad App for Home Assistant (E2EE)

A custom component (HACS extension) to integrate your Adlos / Chad App / PocketBase backend into Home Assistant with full **End-to-End Encryption (AES-256-CBC)**.

## Features
- **End-to-End Encrypted Messages & Images**: Text and image files are encrypted locally with AES-256-CBC and PKCS7 padding before being uploaded to PocketBase.
- **Multi-User Support**: Send notifications to multiple user contacts simultaneously. For each user, a separate encrypted PocketBase record is created in their respective derived room.
- **Automatic Room & Key Derivation**: Rooms are derived using `derive_room_id("homeassistant_bot", user_contact_id)` and keys via `sha256('adlos_e2ee_secret_v1_' + room_id)`.
- **Auto-Burn / Ephemeral Relay**: Each user retrieves and burns their own record without affecting other users.
- **Config & Options Flow**: Configure target contacts initially and update them anytime via Home Assistant's *Configure* menu.
- **Service Aliases**: Supports `adlos.send_message`, `adloshacs.send_message`, `chad_app.send_message`, `notify.adlos`, and `send_photo`.

## Installation via HACS

1. Go to HACS -> Integrations.
2. Click the 3 dots in the top right corner and select "Custom repositories".
3. Add the URL of this repository and select category "Integration".
4. Click "Download" and restart Home Assistant.

## Manual Installation

1. Copy the `custom_components/chad_app` directory to your Home Assistant `custom_components` directory.
2. Restart Home Assistant.

## Configuration

1. In Home Assistant, go to Settings -> Devices & Services.
2. Click "Add Integration" and select "Adlos" / "Chad App".
3. Enter:
   - **PocketBase API URL** (e.g. `https://pocket.nextbee.org/api/collections/messages/records`)
   - **Bot ID** (default: `homeassistant_bot`)
   - **Target Contact IDs** (comma-separated, e.g. `user_contact_id_1, user_contact_id_2`)
4. To modify targets later, go to Settings -> Devices & Services -> Adlos -> Configure.

## Services

### `adlos.send_message` / `chad_app.send_message`
Sends an end-to-end encrypted text message or image to all configured users (or specified targets).

```yaml
service: adlos.send_message
data:
  title: "Waschmaschine"
  message: "Die Wäsche ist fertig!"
  # Optional: specify single or multiple recipients (overrides default targets)
  target:
    - "user_contact_id_1"
    - "user_contact_id_2"
```

### `adlos.send_photo` / `chad_app.send_photo`
Sends an end-to-end encrypted photo to all configured users (or specified targets).

```yaml
service: adlos.send_photo
data:
  message: "Bewegung erkannt!"
  path: "/config/www/snapshot.jpg"
```

### Modern Notify Entity
```yaml
service: notify.adlos
data:
  title: "Garten"
  message: "Bewegung im Garten erkannt"
  data:
    image: "/config/www/garden.jpg"
    target: "user_contact_id_1"
```



# Chad App for Home Assistant

A custom component (HACS extension) to integrate your Chad App / PocketBase backend into Home Assistant.
This allows you to easily send text messages and images to a Chad App room without needing complex YAML configurations.

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
2. Click "Add Integration" in the bottom right corner.
3. Search for "Chad App".
4. Enter your Chad App URL, Room ID, and (optional) PocketBase token.

## Services

This integration provides two services:

### `chad_app.send_message`

Sends a simple text message.

**Example YAML:**
```yaml
service: chad_app.send_message
data:
  text: "Hello from Home Assistant!"
```

### `chad_app.send_photo`

Sends an image file.

**Example YAML:**
```yaml
service: chad_app.send_photo
data:
  text: "Optional text"
  path: "/config/www/my_image.jpg"
```
**Note:** Ensure the path you specify is permitted in your Home Assistant configuration under `allowlist_external_dirs` if the file is outside standard locations.

# Adlos Integration für Home Assistant (HACS) 🎯

Die native **Adlos** Integration für Home Assistant verbindet dein Smart Home direkt und Ende-zu-Ende verschlüsselt (E2EE) mit deiner **Adlos App**.

Home Assistant verhält sich dabei für dich exakt wie ein normaler menschlicher Adlos-Kontakt:
- 📱 **QR-Code Pairing in 3 Sekunden**: In Home Assistant wird ein QR-Code angezeigt. In der Adlos-App einfach auf *Kontakt hinzufügen -> QR-Code scannen* tippen.
- 🤝 **Automatischer Handshake**: Die App und Home Assistant tauschen automatisch über die zentrale PocketBase-Relay-Instanz den symmetrischen E2EE-Schlüssel aus.
- ⚡ **Sofortiger FCM-Push**: Nachrichten und Schnappschüsse wecken dein Smartphone auch im tiefsten Schlaf innerhalb von 1–2 Sekunden zuverlässig auf.
- 💬 **Bidirektionaler Chat (Home Assistant Assist)**: Schreibe Home Assistant im Adlos-Chat Befehle (*"Schalte das Wohnzimmerlicht aus"* oder *"Wie warm ist es draußen?"*). Home Assistant antwortet dir direkt im Chat!
- 🧹 **Ephemeral Relay**: Nachrichten und Handshake-Datensätze werden sofort nach Empfang gelöscht – keine dauerhafte Speicherung auf dem Relay-Server.
- 🔒 **Ende-zu-Ende-Verschlüsselung**: Nachrichten und Medien werden vor der Übertragung lokal mit AES-256-CBC verschlüsselt.

---

## 🚀 Installation

### Über HACS (Empfohlen)
1. Öffne **HACS** in deiner Home Assistant Instanz.
2. Klicke oben rechts auf die 3 Punkte -> **Benutzerdefinierte Repositories**.
3. Füge die URL dieses Repositories hinzu (Kategorie: **Integration**).
4. Suche nach **Adlos** und klicke auf **Herunterladen**.
5. Starte Home Assistant neu.

### Manuelle Installation
Kopiere den Ordner `custom_components/chad_app` in dein Home Assistant Verzeichnis `/config/custom_components/chad_app` und starte Home Assistant neu.

---

## ⚡ Einrichtung & QR-Code Kopplung

1. Gehe in Home Assistant zu **Einstellungen -> Geräte & Dienste -> Integration hinzufügen**.
2. Wähle **Adlos** aus.
3. Bestätige den Server (Standard: `https://pocket.nextbee.org`) und den Bot-Namen (`Home Assistant`).
4. Es erscheint der **QR-Code**:
   - Öffne die **Adlos App** auf deinem Smartphone.
   - Tippe auf **Kontakt hinzufügen -> QR-Code scannen**.
   - Scanne den QR-Code vom Bildschirm.
5. Fertig! Der Kontakt **Home Assistant** ist sofort in deiner Chat-Liste gekoppelt und startklar. 🎉

> [!TIP]
> Du kannst den QR-Code jederzeit erneut in Home Assistant unter **Einstellungen -> Geräte & Dienste -> Adlos -> Konfigurieren** oder über die Entität `image.adlos_kopplungs_qr_code` abrufen, um weitere Familienmitglieder oder Smartphones zu koppeln.

---

## 🛠️ Verwendung in Automatisierungen (`notify.adlos`)

Im visuellen Automatisierungs-Editor wählst du einfach die Aktion **Benachrichtigung senden über adlos** (`notify.adlos`):

### 1. Einfache Benachrichtigung
```yaml
action: notify.adlos
data:
  title: "Haushalt"
  message: "Die Waschmaschine ist fertig! 🧺"
```

### 2. Automatischer Kamera-Schnappschuss
Erstellt beim Auslösen der Automation automatisch einen Schnappschuss der angegebenen Kamera und sendet ihn verschlüsselt an Adlos:
```yaml
action: notify.adlos
data:
  title: "Bewegung erkannt!"
  message: "Jemand steht an der Haustür."
  data:
    camera: camera.haustuer
```

### 3. Bild aus lokalem Pfad oder URL
```yaml
action: notify.adlos
data:
  title: "Garten"
  message: "Aktuelles Bild der Gartenkamera"
  data:
    image: "/config/www/garten.jpg"
```

### 4. Gezielt an bestimmte Personen senden
Wenn mehrere Familienmitglieder gekoppelt sind, kannst du Benachrichtigungen gezielt an einzelne Kontakte senden (oder weglassen, um an alle zu senden):
```yaml
action: notify.adlos
data:
  message: "Mülltonne bitte rausstellen!"
  target: "Kai"
```
*(Alternativ steht für jeden Nutzer auch eine eigene Entität wie `notify.adlos_kai` zur Verfügung!)*

---

## 💬 Chatten mit Home Assistant (Assist)

Du kannst Home Assistant jederzeit im Adlos-Chat Nachrichten schreiben. Eingehende Nachrichten werden über Home Assistants Sprachassistenten (**Home Assistant Assist**) verarbeitet und beantwortet.

Zusätzlich feuert die Integration bei jeder eingehenden Nachricht das Event:
- **Event-Typ:** `adlos_message_received`
- **Event-Daten:**
  ```json
  {
    "user_id": "<ADLOS_KONTAKT_ID>",
    "user_name": "<NUTZERNAME>",
    "room": "<RAUM_ID>",
    "text": "<NACHRICHTENTEXT>"
  }
  ```

---

## 📄 Lizenz
MIT License

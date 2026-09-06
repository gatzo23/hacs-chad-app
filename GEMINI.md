# HACS Release- und Versionierungs-Workflow

Bei Versionserhöhungen oder Änderungen an der Home Assistant Integration (`custom_components`) MUSS immer der folgende vollständige Ablauf eingehalten werden:

1. **Version synchronisieren**:
   - `custom_components/chad_app/manifest.json`: Feld `"version"` auf die neue Versionsnummer setzen (z. B. `"2.0.1"`).
   - Sicherstellen, dass ggf. zugehörige Tests aktualisiert werden und grün durchlaufen.

2. **Git Commit**:
   - Geänderte Dateien stagen (`git add ...`)
   - Commit mit aussagekräftiger Nachricht erstellen (z. B. `git commit -m "feat/fix: ... and bump version to X.Y.Z"`).

3. **Git Tag & Push**:
   - Git-Tag erstellen: `git tag -a vX.Y.Z -m "Release vX.Y.Z: ..."`
   - Branch und Tag zu GitHub pushen: `git push origin <branch> && git push origin vX.Y.Z`

4. **GitHub Release veröffentlichen (KRITISCH FÜR HACS)**:
   - Zwingend ein GitHub Release über die CLI anlegen:
     ```bash
     gh release create vX.Y.Z --title "Release vX.Y.Z" --notes "<Release Notes>"
     ```
   - *Hintergrund:* HACS erkennt neue Versionen nur über die GitHub Releases API. Ohne diesen Schritt sieht der Nutzer in Home Assistant keine Aktualisierung!

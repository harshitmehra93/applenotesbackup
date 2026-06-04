# Apple Notes Backup

One-way Apple Notes backup for macOS. It reads notes from the local Notes app and writes Markdown files while preserving account and folder structure.

The tool does not write back to Apple Notes, install background jobs, call network services, or delete old backups.

## Output Structure

Backups are written to a timestamped folder in `~/Downloads` by default:

```text
AppleNotesMarkdownBackup-YYYYMMDD-HHMMSS/
  markdown/
    iCloud/
      Journal/
        My Note-1.md
  raw_html/
    iCloud/
      Journal/
        My Note-1.html
  text/
    iCloud/
      Journal/
        My Note-1.txt
  manifest.tsv
```

Each Markdown file includes front matter with the original title, account, folder, created date, and modified date.

## Install

From this project directory:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Or use Make:

```bash
make setup
```

## Run

Back up all Notes accounts with Make:

```bash
make backup
```

Back up all iCloud notes:

```bash
.venv/bin/python apple_notes_backup.py --account iCloud
```

Back up all Notes accounts:

```bash
.venv/bin/python apple_notes_backup.py
```

Back up only iCloud with Make:

```bash
make backup-icloud
```

Test with a few notes first:

```bash
.venv/bin/python apple_notes_backup.py --account iCloud --limit 5
```

Or:

```bash
make test
```

Write to a specific folder:

```bash
.venv/bin/python apple_notes_backup.py --account iCloud --output ~/Downloads/MyNotesBackup
```

Export a single folder:

```bash
.venv/bin/python apple_notes_backup.py --account iCloud --folder Journal
```

macOS may prompt for permission to let Terminal control Notes. Allow it so the script can read your notes.

## Options

```text
-o, --output PATH              Backup output directory
-a, --account NAME             Export only this Notes account, for example iCloud
-f, --folder NAME              Export only this folder name
-n, --limit NUMBER             Export at most this many notes
--include-recently-deleted     Include the Recently Deleted folder
```

## Safety Notes

- This is a read-only Apple Notes exporter.
- It does not use `--sync` behavior or write content back to Notes.
- It does not call remote APIs.
- It keeps raw HTML and plain text alongside Markdown for recovery/debugging.

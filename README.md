# Apple Notes Backup

One-way Apple Notes backup for macOS. It reads notes from the local Notes app and writes Markdown files while preserving account and nested folder structure.

The tool does not write back to Apple Notes, install background jobs, call network services, or delete old backups.
It uses only the Python standard library.
It also copies Apple Notes file attachments, including PDFs and other documents, into each note's Markdown and browsable HTML folders.

## Output Structure

Backups are written to a timestamped folder in `~/Downloads` by default:

```text
AppleNotesMarkdownBackup-YYYYMMDD-HHMMSS/
  markdown/
    iCloud/
      orcl/
        postgres/
          PITR/
            My Note-1.md
            attachments/
              My Note-1/
                1-Document.pdf
            index.html
          index.html
        index.html
      index.html
  html/
    iCloud/
      orcl/
        postgres/
          PITR/
            My Note-1.html
            attachments/
              My Note-1/
                1-Document.pdf
            index.html
  raw_html/
    iCloud/
      orcl/
        postgres/
          PITR/
            My Note-1.html
  text/
    iCloud/
      orcl/
        postgres/
          PITR/
            My Note-1.txt
  manifest.tsv
  index.html
```

Each Markdown file includes front matter with the original title, account, folder, created date, and modified date.
Markdown and processed HTML place copied attachment links at Apple Notes' attachment markers when macOS exposes those markers.
Any extra attachment files that cannot be matched to a marker are listed in a `Files` section.
The `raw_html` folder keeps Apple's original HTML export for recovery/debugging.
Every backup folder also gets an `index.html` file with links to its child folders and files.

## Install

From this project directory:

```bash
python3 -m venv .venv
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

## Progress Output

Every run prints a planned summary before it starts reading Notes, then shows progress through the backup phases:

```text
Apple Notes Backup

Output: /Users/harshitmehra/Downloads/AppleNotesMarkdownBackup-YYYYMMDD-HHMMSS
Account: iCloud
Folder: All folders
Title filter: None
Limit: None

Planned Phases:
  1. Count matching notes
  2. Export raw Notes data and attachments
  3. Convert to Markdown and HTML
  4. Create folder indexes

macOS may ask for permission to let Terminal control Notes.

Phase 1/4: Counting matching notes...
Found 876 matching notes.

Phase 2/4: Exporting Apple Notes...
[42/876] Exporting: Personal Financial plan - short term

Phase 3/4: Converting to Markdown and HTML...
[42/876] Converting: Personal Financial plan - short term

Phase 4/4: Creating folder indexes...
Created 117 index.html files.
```

## Options

```text
-o, --output PATH              Backup output directory
-a, --account NAME             Export only this Notes account, for example iCloud
-f, --folder NAME              Export only this folder name
-t, --title TITLE              Export only notes with this exact title
-n, --limit NUMBER             Export at most this many notes
--include-recently-deleted     Include the Recently Deleted folder
```

## Safety Notes

- This is a read-only Apple Notes exporter.
- It does not use `--sync` behavior or write content back to Notes.
- It does not call remote APIs.
- It keeps raw HTML and plain text alongside Markdown for recovery/debugging.
- It copies local Apple Notes attachments when macOS exposes them to automation.

#!/usr/bin/env python3
"""One-way Apple Notes backup to Markdown.

This script intentionally does only one thing:
read notes from the local macOS Notes app and write Markdown files.

It does not write back to Notes, install launchd jobs, call network services,
or delete existing backups.
"""

from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import html
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote


APPLESCRIPT = r'''
property exportedCount : 0

on run argv
    set rootDir to item 1 of argv
    set accountFilter to item 2 of argv
    set includeRecentlyDeleted to item 3 of argv
    set folderFilter to item 4 of argv
    set maxNotes to item 5 of argv as integer

    set rawRoot to rootDir & "/raw_html"
    set textRoot to rootDir & "/text"
    set manifestPath to rootDir & "/manifest.tsv"

    do shell script "mkdir -p " & quoted form of rawRoot
    do shell script "mkdir -p " & quoted form of textRoot
    my writeFile(manifestPath, "raw_rel	text_rel	title	account	folder	created	modified" & linefeed)

    set my exportedCount to 0

    tell application "Notes"
        repeat with anAccount in accounts
            set accountName to name of anAccount
            if accountFilter is "" or accountName is accountFilter then
                set accountRel to my safeName(accountName)
                repeat with aFolder in folders of anAccount
                    set parentObject to container of aFolder
                    if class of parentObject is account then
                        my exportFolder(aFolder, accountName, accountRel, "", "", rootDir, rawRoot, textRoot, manifestPath, includeRecentlyDeleted, folderFilter, maxNotes)
                    end if
                end repeat
            end if
        end repeat
    end tell

    return my exportedCount as string
end run

on exportFolder(aFolder, accountName, accountRel, parentRel, parentDisplayPath, rootDir, rawRoot, textRoot, manifestPath, includeRecentlyDeleted, folderFilter, maxNotes)
    if maxNotes is not 0 and (my exportedCount) ≥ maxNotes then return

    set folderName to name of aFolder
    if includeRecentlyDeleted is not "true" and folderName is "Recently Deleted" then return

    set safeFolderDir to my safeName(folderName)
    if parentRel is "" then
        set folderRel to safeFolderDir
        set folderDisplayPath to folderName
    else
        set folderRel to parentRel & "/" & safeFolderDir
        set folderDisplayPath to parentDisplayPath & "/" & folderName
    end if

    set noteDirRel to accountRel & "/" & folderRel
    set rawDir to rawRoot & "/" & noteDirRel
    set textDir to textRoot & "/" & noteDirRel
    do shell script "mkdir -p " & quoted form of rawDir
    do shell script "mkdir -p " & quoted form of textDir

    set shouldExportFolderNotes to folderFilter is "" or folderName is folderFilter or folderDisplayPath is folderFilter
    if shouldExportFolderNotes then
        set folderIndex to 0
        set folderNotes to {}
        try
            tell application "Notes" to set folderNotes to notes of aFolder
        end try
        repeat with aNote in folderNotes
            if maxNotes is not 0 and (my exportedCount) ≥ maxNotes then exit repeat
            set folderIndex to folderIndex + 1
            set my exportedCount to (my exportedCount) + 1

            tell application "Notes"
                set noteTitle to name of aNote
                set noteBody to body of aNote
                set noteText to plaintext of aNote
                set createdValue to (creation date of aNote) as string
                set modifiedValue to (modification date of aNote) as string
            end tell
            set safeTitle to my safeName(noteTitle)
            set baseName to safeTitle & "-" & (folderIndex as string)

            set rawRel to "raw_html/" & noteDirRel & "/" & baseName & ".html"
            set textRel to "text/" & noteDirRel & "/" & baseName & ".txt"
            set rawPath to rootDir & "/" & rawRel
            set textPath to rootDir & "/" & textRel

            my writeFile(rawPath, noteBody)
            my writeFile(textPath, noteText)

            set manifestLine to my tsv(rawRel) & tab & my tsv(textRel) & tab & my tsv(noteTitle) & tab & my tsv(accountName) & tab & my tsv(folderDisplayPath) & tab & my tsv(createdValue) & tab & my tsv(modifiedValue) & linefeed
            my appendFile(manifestPath, manifestLine)
        end repeat
    end if

    set childFolders to {}
    try
        tell application "Notes" to set childFolders to folders of aFolder
    end try
    repeat with childFolder in childFolders
        if maxNotes is not 0 and (my exportedCount) ≥ maxNotes then exit repeat
        my exportFolder(childFolder, accountName, accountRel, folderRel, folderDisplayPath, rootDir, rawRoot, textRoot, manifestPath, includeRecentlyDeleted, folderFilter, maxNotes)
    end repeat
end exportFolder

on writeFile(filePath, content)
    set fileRef to missing value
    try
        set fileRef to open for access (POSIX file filePath) with write permission
        set eof of fileRef to 0
        write content to fileRef as «class utf8»
        close access fileRef
    on error errMsg
        try
            if fileRef is not missing value then close access fileRef
        end try
        error errMsg
    end try
end writeFile

on appendFile(filePath, content)
    set fileRef to missing value
    try
        set fileRef to open for access (POSIX file filePath) with write permission
        write content to fileRef starting at eof as «class utf8»
        close access fileRef
    on error errMsg
        try
            if fileRef is not missing value then close access fileRef
        end try
        error errMsg
    end try
end appendFile

on safeName(inputText)
    set cleaned to inputText as string
    set badChars to {"/", ":", "\\", "|", "<", ">", "\"", "'", "?", "*", tab, return, linefeed}
    repeat with badChar in badChars
        set cleaned to my replaceText(badChar, "-", cleaned)
    end repeat
    repeat while cleaned contains "--"
        set cleaned to my replaceText("--", "-", cleaned)
    end repeat
    if cleaned is "" or cleaned is "-" then set cleaned to "untitled"
    if length of cleaned > 120 then set cleaned to text 1 through 120 of cleaned
    return cleaned
end safeName

on tsv(inputText)
    set cleaned to inputText as string
    set cleaned to my replaceText(tab, " ", cleaned)
    set cleaned to my replaceText(return, " ", cleaned)
    set cleaned to my replaceText(linefeed, " ", cleaned)
    return cleaned
end tsv

on replaceText(findText, replaceText, sourceText)
    set AppleScript's text item delimiters to findText
    set textItems to text items of sourceText
    set AppleScript's text item delimiters to replaceText
    set newText to textItems as string
    set AppleScript's text item delimiters to ""
    return newText
end replaceText
'''


def slugify(value: str, fallback: str = "untitled") -> str:
    value = re.sub(r"[^\w\s.-]+", "", value, flags=re.UNICODE)
    value = re.sub(r"[\s/\\:]+", "-", value).strip(".-")
    return (value or fallback)[:120]


def data_url_to_file(src: str, attachments_dir: Path, stem: str, index: int) -> str | None:
    match = re.match(r"^data:(image/[^;]+);base64,(.*)$", src, flags=re.DOTALL)
    if not match:
        return None

    mime_type, encoded = match.groups()
    extension = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/tiff": ".tiff",
    }.get(mime_type.lower(), ".img")

    attachments_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{stem}-image-{index}{extension}"
    image_path = attachments_dir / filename
    image_path.write_bytes(base64.b64decode(encoded))
    return f"attachments/{filename}"


def extract_image_links(html_text: str, md_path: Path) -> list[str]:
    attachments_dir = md_path.parent / "attachments"
    links = []
    img_sources = re.findall(
        r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"'][^>]*>",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    for index, src in enumerate(img_sources, start=1):
        if not src.startswith("data:"):
            continue
        replacement = data_url_to_file(src, attachments_dir, md_path.stem, index)
        if replacement:
            links.append(f"![Attachment {index}]({replacement})")

    return links


def text_to_markdown(text: str, html_text: str, md_path: Path) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    image_links = extract_image_links(html_text, md_path)
    sections = [text] if text else []
    if image_links:
        sections.extend(["## Attachments", "\n".join(image_links)])
    return "\n\n".join(sections).strip() + "\n"


def yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def convert_manifest(output_dir: Path) -> int:
    manifest = output_dir / "manifest.tsv"
    md_root = output_dir / "markdown"
    count = 0

    with manifest.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            raw_path = output_dir / row["raw_rel"]
            text_path = output_dir / row["text_rel"]
            raw_rel = Path(row["raw_rel"])
            note_dir = raw_rel.parent.relative_to("raw_html")
            md_dir = md_root / note_dir
            md_dir.mkdir(parents=True, exist_ok=True)

            md_name = raw_rel.with_suffix(".md").name
            md_path = md_dir / md_name
            html_text = raw_path.read_text(encoding="utf-8", errors="replace")
            plain_text = text_path.read_text(encoding="utf-8", errors="replace")
            body = text_to_markdown(plain_text, html_text, md_path)

            frontmatter = [
                "---",
                f"title: {yaml_string(row['title'])}",
                f"account: {yaml_string(row['account'])}",
                f"folder: {yaml_string(row['folder'])}",
                f"created: {yaml_string(row['created'])}",
                f"modified: {yaml_string(row['modified'])}",
                "---",
                "",
            ]
            md_path.write_text("\n".join(frontmatter) + body, encoding="utf-8")
            count += 1

    return count


def display_name(path: Path) -> str:
    return path.name or str(path)


def write_index(directory: Path, root: Path) -> None:
    dirs = sorted([p for p in directory.iterdir() if p.is_dir()], key=lambda p: p.name.lower())
    files = sorted(
        [p for p in directory.iterdir() if p.is_file() and p.name != "index.html"],
        key=lambda p: p.name.lower(),
    )
    rel = directory.relative_to(root) if directory != root else Path(".")
    title = "Apple Notes Backup" if rel == Path(".") else str(rel)
    parent_link = ""
    if directory != root:
        parent_link = '<p class="parent"><a href="../index.html">../</a></p>'

    rows = []
    for child in dirs:
        rows.append(
            f'<li class="dir"><a href="{quote(child.name)}/index.html">{html.escape(child.name)}/</a></li>'
        )
    for child in files:
        rows.append(f'<li class="file"><a href="{quote(child.name)}">{html.escape(child.name)}</a></li>')

    body = "\n".join(rows) if rows else '<li class="empty">No files in this folder</li>'
    content = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 2rem; line-height: 1.5; }}
    h1 {{ font-size: 1.4rem; }}
    ul {{ list-style: none; padding-left: 0; }}
    li {{ margin: 0.35rem 0; }}
    a {{ color: #0b57d0; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .dir::before {{ content: "[dir] "; color: #666; }}
    .file::before {{ content: "[file] "; color: #666; }}
    .parent {{ margin-bottom: 1.5rem; }}
    .empty {{ color: #666; }}
  </style>
</head>
<body>
  <h1>{html.escape(title)}</h1>
  {parent_link}
  <ul>
    {body}
  </ul>
</body>
</html>
"""
    (directory / "index.html").write_text(content, encoding="utf-8")


def generate_indexes(output_dir: Path) -> int:
    directories = [output_dir]
    directories.extend(sorted([p for p in output_dir.rglob("*") if p.is_dir()], key=lambda p: str(p)))
    for directory in directories:
        write_index(directory, output_dir)
    return len(directories)


def run_export(
    output_dir: Path,
    account: str,
    folder: str,
    limit: int,
    include_recently_deleted: bool,
) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".scpt", delete=False, encoding="utf-8") as handle:
        handle.write(APPLESCRIPT)
        script_path = Path(handle.name)

    try:
        result = subprocess.run(
            [
                "osascript",
                str(script_path),
                str(output_dir),
                account,
                "true" if include_recently_deleted else "false",
                folder,
                str(limit),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
    finally:
        script_path.unlink(missing_ok=True)

    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "osascript failed")

    stdout = result.stdout.strip()
    return int(stdout.splitlines()[-1]) if stdout else 0


def default_output_dir() -> Path:
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path.home() / "Downloads" / f"AppleNotesMarkdownBackup-{timestamp}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Back up local macOS Apple Notes to Markdown.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=default_output_dir(),
        help="Backup output directory. Defaults to a timestamped folder in Downloads.",
    )
    parser.add_argument(
        "-a",
        "--account",
        default="",
        help='Only export this Notes account, for example "iCloud". Defaults to all accounts.',
    )
    parser.add_argument(
        "-f",
        "--folder",
        default="",
        help='Only export this Notes folder name, for example "Journal". Defaults to all folders.',
    )
    parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=0,
        help="Maximum number of notes to export. Defaults to 0, meaning no limit.",
    )
    parser.add_argument(
        "--include-recently-deleted",
        action="store_true",
        help='Also export the "Recently Deleted" folder.',
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output.expanduser().resolve()

    print(f"Exporting Apple Notes to: {output_dir}")
    print("macOS may ask for permission to let Terminal control Notes.")

    exported = run_export(output_dir, args.account, args.folder, args.limit, args.include_recently_deleted)
    converted = convert_manifest(output_dir)
    indexed = generate_indexes(output_dir)

    print(f"Exported {exported} notes.")
    print(f"Created {converted} Markdown files in: {output_dir / 'markdown'}")
    print(f"Created {indexed} index.html files for browsing the backup.")
    print(f"Raw HTML is kept in: {output_dir / 'raw_html'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit("\nCancelled.")
    except Exception as exc:
        raise SystemExit(f"Error: {exc}")

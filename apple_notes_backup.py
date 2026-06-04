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
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


APPLESCRIPT = r'''
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

    set exportedCount to 0

    tell application "Notes"
        repeat with anAccount in accounts
            set accountName to name of anAccount
            if accountFilter is "" or accountName is accountFilter then
                repeat with aFolder in folders of anAccount
                    set folderName to name of aFolder
                    if (folderFilter is "" or folderName is folderFilter) and (includeRecentlyDeleted is "true" or folderName is not "Recently Deleted") then
                        set safeAccountDir to my safeName(accountName)
                        set safeFolderDir to my safeName(folderName)
                        set noteDirRel to safeAccountDir & "/" & safeFolderDir
                        set rawDir to rawRoot & "/" & noteDirRel
                        set textDir to textRoot & "/" & noteDirRel
                        do shell script "mkdir -p " & quoted form of rawDir
                        do shell script "mkdir -p " & quoted form of textDir

                        set folderIndex to 0
                        repeat with aNote in notes of aFolder
                            if maxNotes is not 0 and exportedCount ≥ maxNotes then exit repeat
                            set folderIndex to folderIndex + 1
                            set exportedCount to exportedCount + 1

                            set noteTitle to name of aNote
                            set safeTitle to my safeName(noteTitle)
                            set baseName to safeTitle & "-" & (folderIndex as string)

                            set rawRel to "raw_html/" & noteDirRel & "/" & baseName & ".html"
                            set textRel to "text/" & noteDirRel & "/" & baseName & ".txt"
                            set rawPath to rootDir & "/" & rawRel
                            set textPath to rootDir & "/" & textRel

                            my writeFile(rawPath, body of aNote)
                            my writeFile(textPath, plaintext of aNote)

                            set createdValue to (creation date of aNote) as string
                            set modifiedValue to (modification date of aNote) as string
                            set manifestLine to my tsv(rawRel) & tab & my tsv(textRel) & tab & my tsv(noteTitle) & tab & my tsv(accountName) & tab & my tsv(folderName) & tab & my tsv(createdValue) & tab & my tsv(modifiedValue) & linefeed
                            my appendFile(manifestPath, manifestLine)
                        end repeat
                    end if
                end repeat
            end if
        end repeat
    end tell

    return exportedCount as string
end run

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


def html_to_markdown(html: str, md_path: Path) -> str:
    try:
        from bs4 import BeautifulSoup
        from markdownify import markdownify as markdownify_html
    except ImportError:
        return re.sub(r"\n{3,}", "\n\n", re.sub(r"<[^>]+>", "", html)).strip() + "\n"

    soup = BeautifulSoup(html, "html.parser")
    attachments_dir = md_path.parent / "attachments"
    image_index = 0

    for img in soup.find_all("img"):
        src = img.get("src", "")
        if src.startswith("data:"):
            image_index += 1
            replacement = data_url_to_file(src, attachments_dir, md_path.stem, image_index)
            if replacement:
                img["src"] = replacement

    markdown = markdownify_html(str(soup), heading_style="ATX", bullets="-")
    markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip()
    return markdown + "\n"


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
            raw_rel = Path(row["raw_rel"])
            note_dir = raw_rel.parent.relative_to("raw_html")
            md_dir = md_root / note_dir
            md_dir.mkdir(parents=True, exist_ok=True)

            md_name = raw_rel.with_suffix(".md").name
            md_path = md_dir / md_name
            html = raw_path.read_text(encoding="utf-8", errors="replace")
            body = html_to_markdown(html, md_path)

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

    print(f"Exported {exported} notes.")
    print(f"Created {converted} Markdown files in: {output_dir / 'markdown'}")
    print(f"Raw HTML is kept in: {output_dir / 'raw_html'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit("\nCancelled.")
    except Exception as exc:
        raise SystemExit(f"Error: {exc}")

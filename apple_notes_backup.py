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
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

ATTACHMENT_MARKER = "\ufffc"
IMAGE_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
PROGRESS_PREFIX = "PROGRESS\t"


APPLESCRIPT = r'''
property exportedCount : 0
property countedCount : 0

on run argv
    set rootDir to item 1 of argv
    set accountFilter to item 2 of argv
    set includeRecentlyDeleted to item 3 of argv
    set folderFilter to item 4 of argv
    set maxNotes to item 5 of argv as integer
    set titleFilter to item 6 of argv

    set my exportedCount to 0
    set my countedCount to 0

    tell application "Notes"
        repeat with anAccount in accounts
            set accountName to name of anAccount
            if accountFilter is "" or accountName is accountFilter then
                set accountRel to my safeName(accountName)
                repeat with aFolder in folders of anAccount
                    set parentObject to container of aFolder
                    if class of parentObject is account then
                        my countFolder(aFolder, "", includeRecentlyDeleted, folderFilter, maxNotes, titleFilter)
                    end if
                end repeat
            end if
        end repeat
    end tell

    set totalCount to my countedCount
    log "PROGRESS" & tab & "FOUND" & tab & (totalCount as string)

    set rawRoot to rootDir & "/raw_html"
    set textRoot to rootDir & "/text"
    set manifestPath to rootDir & "/manifest.tsv"

    do shell script "mkdir -p " & quoted form of rawRoot
    do shell script "mkdir -p " & quoted form of textRoot
    my writeFile(manifestPath, "raw_rel	text_rel	attachment_rel	title	account	folder	created	modified" & linefeed)

    tell application "Notes"
        repeat with anAccount in accounts
            set accountName to name of anAccount
            if accountFilter is "" or accountName is accountFilter then
                set accountRel to my safeName(accountName)
                repeat with aFolder in folders of anAccount
                    set parentObject to container of aFolder
                    if class of parentObject is account then
                        my exportFolder(aFolder, accountName, accountRel, "", "", rootDir, rawRoot, textRoot, manifestPath, includeRecentlyDeleted, folderFilter, maxNotes, titleFilter, totalCount)
                    end if
                end repeat
            end if
        end repeat
    end tell

    log "PROGRESS" & tab & "DONE" & tab & (my exportedCount as string)
    return my exportedCount as string
end run

on countFolder(aFolder, parentDisplayPath, includeRecentlyDeleted, folderFilter, maxNotes, titleFilter)
    if maxNotes is not 0 and (my countedCount) ≥ maxNotes then return

    set folderName to name of aFolder
    if includeRecentlyDeleted is not "true" and folderName is "Recently Deleted" then return

    if parentDisplayPath is "" then
        set folderDisplayPath to folderName
    else
        set folderDisplayPath to parentDisplayPath & "/" & folderName
    end if

    set shouldCountFolderNotes to folderFilter is "" or folderName is folderFilter or folderDisplayPath is folderFilter
    if shouldCountFolderNotes then
        set folderNotes to {}
        try
            tell application "Notes" to set folderNotes to notes of aFolder
        end try
        repeat with aNote in folderNotes
            if maxNotes is not 0 and (my countedCount) ≥ maxNotes then exit repeat
            tell application "Notes" to set noteTitle to name of aNote
            if titleFilter is "" or noteTitle is titleFilter then
                set my countedCount to (my countedCount) + 1
            end if
        end repeat
    end if

    set childFolders to {}
    try
        tell application "Notes" to set childFolders to folders of aFolder
    end try
    repeat with childFolder in childFolders
        if maxNotes is not 0 and (my countedCount) ≥ maxNotes then exit repeat
        my countFolder(childFolder, folderDisplayPath, includeRecentlyDeleted, folderFilter, maxNotes, titleFilter)
    end repeat
end countFolder

on exportFolder(aFolder, accountName, accountRel, parentRel, parentDisplayPath, rootDir, rawRoot, textRoot, manifestPath, includeRecentlyDeleted, folderFilter, maxNotes, titleFilter, totalCount)
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

            tell application "Notes" to set noteTitle to name of aNote
            if titleFilter is "" or noteTitle is titleFilter then
                tell application "Notes"
                    set noteBody to body of aNote
                    set noteText to plaintext of aNote
                    set createdValue to (creation date of aNote) as string
                    set modifiedValue to (modification date of aNote) as string
                end tell
                set folderIndex to folderIndex + 1
                set my exportedCount to (my exportedCount) + 1
                set safeTitle to my safeName(noteTitle)
                set baseName to safeTitle & "-" & (folderIndex as string)

                set rawRel to "raw_html/" & noteDirRel & "/" & baseName & ".html"
                set textRel to "text/" & noteDirRel & "/" & baseName & ".txt"
                set attachmentRel to "attachments/" & baseName
                set rawPath to rootDir & "/" & rawRel
                set textPath to rootDir & "/" & textRel
                set markdownAttachmentDir to rootDir & "/markdown/" & noteDirRel & "/" & attachmentRel

                my writeFile(rawPath, noteBody)
                my writeFile(textPath, noteText)
                my copyNoteAttachments(aNote, markdownAttachmentDir)

                set manifestLine to my tsv(rawRel) & tab & my tsv(textRel) & tab & my tsv(attachmentRel) & tab & my tsv(noteTitle) & tab & my tsv(accountName) & tab & my tsv(folderDisplayPath) & tab & my tsv(createdValue) & tab & my tsv(modifiedValue) & linefeed
                my appendFile(manifestPath, manifestLine)
                log "PROGRESS" & tab & "EXPORT" & tab & (my exportedCount as string) & tab & (totalCount as string) & tab & my progressText(noteTitle)
            end if
        end repeat
    end if

    set childFolders to {}
    try
        tell application "Notes" to set childFolders to folders of aFolder
    end try
    repeat with childFolder in childFolders
        if maxNotes is not 0 and (my exportedCount) ≥ maxNotes then exit repeat
        my exportFolder(childFolder, accountName, accountRel, folderRel, folderDisplayPath, rootDir, rawRoot, textRoot, manifestPath, includeRecentlyDeleted, folderFilter, maxNotes, titleFilter, totalCount)
    end repeat
end exportFolder

on copyNoteAttachments(aNote, attachmentDir)
    set attachmentIndex to 0
    set noteAttachments to {}
    try
        tell application "Notes" to set noteAttachments to attachments of aNote
    end try
    if (count of noteAttachments) is 0 then return
    do shell script "mkdir -p " & quoted form of attachmentDir

    repeat with anAttachment in noteAttachments
        set attachmentIndex to attachmentIndex + 1
        set attachmentName to "attachment-" & (attachmentIndex as string)
        try
            tell application "Notes"
                set attachmentProperties to properties of anAttachment
                set attachmentName to name of attachmentProperties
                set attachmentContents to contents of attachmentProperties
            end tell

            if attachmentName is missing value or attachmentName is "" then
                set attachmentName to "attachment-" & (attachmentIndex as string)
            end if

            set safeAttachmentName to my uniqueAttachmentName(attachmentDir, attachmentName, attachmentIndex)
            set sourcePath to POSIX path of attachmentContents
            set destinationPath to attachmentDir & "/" & safeAttachmentName
            do shell script "cp -p " & quoted form of sourcePath & " " & quoted form of destinationPath
        on error errMsg
            do shell script "mkdir -p " & quoted form of attachmentDir
            my appendFile(attachmentDir & "/unavailable-attachments.txt", (attachmentIndex as string) & " - " & attachmentName & " - " & errMsg & linefeed)
        end try
    end repeat
end copyNoteAttachments

on uniqueAttachmentName(attachmentDir, attachmentName, attachmentIndex)
    set safeAttachmentName to my safeFileName(attachmentName)
    return (attachmentIndex as string) & "-" & safeAttachmentName
end uniqueAttachmentName

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

on safeFileName(inputText)
    set cleaned to my safeName(inputText)
    if cleaned is "" or cleaned is "-" then set cleaned to "attachment"
    return cleaned
end safeFileName

on tsv(inputText)
    set cleaned to inputText as string
    set cleaned to my replaceText(tab, " ", cleaned)
    set cleaned to my replaceText(return, " ", cleaned)
    set cleaned to my replaceText(linefeed, " ", cleaned)
    return cleaned
end tsv

on progressText(inputText)
    set cleaned to my tsv(inputText)
    if length of cleaned > 120 then set cleaned to text 1 through 120 of cleaned
    return cleaned
end progressText

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


def is_image_file(name: str) -> bool:
    return Path(name).suffix.lower() in IMAGE_EXTENSIONS


def parse_attachment_entries(md_path: Path, attachment_rel: str) -> list[dict[str, str]]:
    attachment_dir = md_path.parent / attachment_rel
    if not attachment_dir.exists():
        return []

    entries: dict[int, dict[str, str]] = {}
    unavailable_path = attachment_dir / "unavailable-attachments.txt"

    for attachment in sorted(attachment_dir.iterdir(), key=lambda p: p.name.lower()):
        if not attachment.is_file() or attachment.name in {"index.html", "unavailable-attachments.txt"}:
            continue
        match = re.match(r"^(\d+)-", attachment.name)
        if not match:
            continue
        index = int(match.group(1))
        href = quote(f"{attachment_rel}/{attachment.name}")
        entries[index] = {"name": attachment.name, "href": href, "available": "true"}

    if unavailable_path.exists():
        for line in unavailable_path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = re.match(r"^(\d+) - (.*?) - (.*)$", line)
            if not match:
                continue
            index = int(match.group(1))
            entries.setdefault(
                index,
                {
                    "name": match.group(2) or f"attachment-{index}",
                    "href": quote(f"{attachment_rel}/unavailable-attachments.txt"),
                    "available": "false",
                    "error": match.group(3),
                },
            )

    return [entries[index] for index in sorted(entries)]


def copy_attachments_for_html(md_path: Path, html_path: Path, attachment_rel: str) -> None:
    source = md_path.parent / attachment_rel
    if not source.exists():
        return

    destination = html_path.parent / attachment_rel
    shutil.copytree(source, destination, dirs_exist_ok=True)


def markdown_for_attachment(entry: dict[str, str]) -> str:
    name = entry["name"]
    href = entry["href"]
    if entry.get("available") == "false":
        return f"[{name} unavailable]({href})"
    if is_image_file(name):
        return f"![{name}]({href})"
    return f"[{name}]({href})"


def html_for_attachment(entry: dict[str, str]) -> str:
    name = html.escape(entry["name"])
    href = html.escape(entry["href"], quote=True)
    if entry.get("available") == "false":
        return f'<a class="missing-attachment" href="{href}">{name} unavailable</a>'
    if is_image_file(entry["name"]):
        return f'<img class="attachment-image" src="{href}" alt="{name}">'
    return f'<a class="file-attachment" href="{href}">{name}</a>'


def replace_attachment_markers_markdown(text: str, entries: list[dict[str, str]]) -> tuple[str, list[dict[str, str]]]:
    remaining = iter(entries)
    used = 0

    def replace_marker(_: re.Match[str]) -> str:
        nonlocal used
        try:
            entry = next(remaining)
        except StopIteration:
            return "[missing attachment]"
        used += 1
        return markdown_for_attachment(entry)

    replaced = re.sub(ATTACHMENT_MARKER, replace_marker, text)
    return replaced, entries[used:]


def text_to_markdown(text: str, html_text: str, md_path: Path, attachment_entries: list[dict[str, str]]) -> tuple[str, list[dict[str, str]]]:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    text, remaining_entries = replace_attachment_markers_markdown(text, attachment_entries)
    text = re.sub(r"\n{3,}", "\n\n", text)
    image_links = [] if attachment_entries else extract_image_links(html_text, md_path)
    sections = [text] if text else []
    if image_links:
        sections.extend(["## Attachments", "\n".join(image_links)])
    return "\n\n".join(sections).strip() + "\n", remaining_entries


def attachment_links_markdown(entries: list[dict[str, str]]) -> list[str]:
    return [f"- {markdown_for_attachment(entry)}" for entry in entries]


def text_to_html(text: str, attachment_entries: list[dict[str, str]], title: str) -> tuple[str, list[dict[str, str]]]:
    remaining = iter(attachment_entries)
    used = 0

    def render_line(line: str) -> str:
        nonlocal used
        pieces = []
        for part in re.split(f"({ATTACHMENT_MARKER})", line):
            if part == "":
                continue
            if part == ATTACHMENT_MARKER:
                try:
                    entry = next(remaining)
                except StopIteration:
                    pieces.append('<span class="missing-attachment">missing attachment</span>')
                else:
                    used += 1
                    pieces.append(html_for_attachment(entry))
            else:
                pieces.append(html.escape(part))
        return "".join(pieces)

    rows = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.strip():
            rows.append(f"<div>{render_line(line)}</div>")
        else:
            rows.append("<div><br></div>")

    body = "\n".join(rows)
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 2rem; line-height: 1.5; }}
    .attachment-image {{ display: block; max-width: 100%; height: auto; margin: 0.75rem 0; }}
    .file-attachment, .missing-attachment {{ display: inline-block; margin: 0.25rem 0; }}
    .missing-attachment {{ color: #8a5a00; }}
  </style>
</head>
<body>
{body}
</body>
</html>
"""
    return page, attachment_entries[used:]


def yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def progress_value(value: str, fallback: str) -> str:
    return value if value else fallback


def print_planned_summary(args: argparse.Namespace, output_dir: Path) -> None:
    print("Apple Notes Backup")
    print()
    print(f"Output: {output_dir}")
    print(f"Account: {progress_value(args.account, 'All accounts')}")
    print(f"Folder: {progress_value(args.folder, 'All folders')}")
    print(f"Title filter: {progress_value(args.title, 'None')}")
    print(f"Limit: {args.limit if args.limit else 'None'}")
    print()
    print("Planned Phases:")
    print("  1. Count matching notes")
    print("  2. Export raw Notes data and attachments")
    print("  3. Convert to Markdown and HTML")
    print("  4. Create folder indexes")
    print()
    print("macOS may ask for permission to let Terminal control Notes.")
    print()


def convert_manifest(output_dir: Path, progress_total: int | None = None) -> int:
    manifest = output_dir / "manifest.tsv"
    md_root = output_dir / "markdown"
    count = 0
    total_label = str(progress_total) if progress_total is not None else "?"

    with manifest.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            count += 1
            print(f"[{count}/{total_label}] Converting: {row['title']}", flush=True)
            raw_path = output_dir / row["raw_rel"]
            text_path = output_dir / row["text_rel"]
            raw_rel = Path(row["raw_rel"])
            note_dir = raw_rel.parent.relative_to("raw_html")
            md_dir = md_root / note_dir
            md_dir.mkdir(parents=True, exist_ok=True)

            md_name = raw_rel.with_suffix(".md").name
            md_path = md_dir / md_name
            html_dir = output_dir / "html" / note_dir
            html_dir.mkdir(parents=True, exist_ok=True)
            html_path = html_dir / raw_rel.name
            html_text = raw_path.read_text(encoding="utf-8", errors="replace")
            plain_text = text_path.read_text(encoding="utf-8", errors="replace")
            attachment_entries = parse_attachment_entries(md_path, row["attachment_rel"])
            copy_attachments_for_html(md_path, html_path, row["attachment_rel"])
            body, remaining_markdown_entries = text_to_markdown(plain_text, html_text, md_path, attachment_entries)
            processed_html, remaining_html_entries = text_to_html(plain_text, attachment_entries, row["title"])
            file_attachment_links = attachment_links_markdown(remaining_markdown_entries)
            if file_attachment_links:
                body = body.rstrip() + "\n\n## Files\n\n" + "\n".join(file_attachment_links) + "\n"
            if remaining_html_entries:
                links = "\n".join(
                    f"<li>{html_for_attachment(entry)}</li>" for entry in remaining_html_entries
                )
                processed_html = processed_html.replace("</body>", f"<h2>Files</h2>\n<ul>\n{links}\n</ul>\n</body>")

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
            html_path.write_text(processed_html, encoding="utf-8")

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
    title: str,
    limit: int,
    include_recently_deleted: bool,
) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".scpt", delete=False, encoding="utf-8") as handle:
        handle.write(APPLESCRIPT)
        script_path = Path(handle.name)

    print("Phase 1/4: Counting matching notes...", flush=True)
    exported_count: int | None = None
    total_count: int | None = None
    output_lines: list[str] = []

    try:
        process = subprocess.Popen(
            [
                "osascript",
                str(script_path),
                str(output_dir),
                account,
                "true" if include_recently_deleted else "false",
                folder,
                str(limit),
                title,
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.rstrip()
            output_lines.append(line)
            if not line.startswith(PROGRESS_PREFIX):
                continue

            parts = line.split("\t")
            event = parts[1] if len(parts) > 1 else ""
            if event == "FOUND" and len(parts) >= 3:
                total_count = int(parts[2])
                print(f"Found {total_count} matching notes.", flush=True)
                print()
                print("Phase 2/4: Exporting Apple Notes...", flush=True)
                if total_count == 0:
                    print("No matching notes to export.", flush=True)
            elif event == "EXPORT" and len(parts) >= 5:
                current = parts[2]
                total = parts[3]
                note_title = parts[4]
                print(f"[{current}/{total}] Exporting: {note_title}", flush=True)
            elif event == "DONE" and len(parts) >= 3:
                exported_count = int(parts[2])

        return_code = process.wait()
    finally:
        script_path.unlink(missing_ok=True)

    if return_code != 0:
        details = "\n".join(line for line in output_lines if line.strip())
        raise RuntimeError(details or "osascript failed")

    if exported_count is not None:
        return exported_count

    for line in reversed(output_lines):
        if line.strip().isdigit():
            return int(line.strip())

    raise RuntimeError("osascript finished without an exported note count")


def default_output_dir() -> Path:
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path.home() / "Downloads" / f"AppleNotesMarkdownBackup-{timestamp}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Back up local macOS Apple Notes to Markdown and HTML.")
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
        "-t",
        "--title",
        default="",
        help="Only export notes with this exact title. Defaults to all notes.",
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

    print_planned_summary(args, output_dir)

    exported = run_export(output_dir, args.account, args.folder, args.title, args.limit, args.include_recently_deleted)
    print()
    print("Phase 3/4: Converting to Markdown and HTML...", flush=True)
    if exported == 0:
        print("No notes to convert.", flush=True)
    converted = convert_manifest(output_dir, exported)
    print()
    print("Phase 4/4: Creating folder indexes...", flush=True)
    indexed = generate_indexes(output_dir)
    print(f"Created {indexed} index.html files.", flush=True)
    print()

    print(f"Exported {exported} notes.")
    print(f"Created {converted} Markdown files in: {output_dir / 'markdown'}")
    print(f"Created {converted} processed HTML files in: {output_dir / 'html'}")
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

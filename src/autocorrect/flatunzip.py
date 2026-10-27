import hashlib
import json
import unicodedata
import zipfile
import os
import argparse

SUBMISSIONS_INDEX = "_submissions_index.json"


def load_submissions_index(directory):
    """Map flat file name -> {"submission": Moodle folder, "student": "Surname, Name", ...}."""
    path = os.path.join(directory, SUBMISSIONS_INDEX)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _display_path(member: zipfile.ZipInfo) -> str:
    """The member's real name. Moodle writes UTF-8 names without the zip UTF-8 flag, so Python
    decodes them as CP437 ("IÃ±aki"); recover the UTF-8 name when that is the case."""
    if member.flag_bits & 0x800:
        return member.filename
    try:
        return member.filename.encode('cp437').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return member.filename


def _ascii_name(display_path: str) -> str:
    """Fold accents to ASCII (Iñaki -> Inaki) instead of dropping the letters."""
    return unicodedata.normalize('NFKD', display_path).encode('ascii', 'ignore').decode()


def _flat_filename(zip_basename: str, original_path: str, ascii_path: str) -> str:
    """Short unique flat name: ``<zip name[:10]>_<hash of the path in the zip>_<suffix>``.

    The suffix keeps the path parts that look like Moodle student folders ("Surname, Name_...")
    plus the file name, or else the end of the flattened path; long suffixes are truncated."""
    flattened_path = ascii_path.replace('/', '_').replace('\\', '_')
    short_zip_name = zip_basename[:10]
    # Hash of the original path inside the zip: the same file always gets the same name.
    name_hash = hashlib.md5(original_path.encode('utf-8')).hexdigest()[:8]
    ext = os.path.splitext(flattened_path)[1]

    path_parts = ascii_path.replace('\\', '/').split('/')
    student_parts = [p for p in path_parts if ',' in p]
    if student_parts:
        relevant = []
        for p in student_parts + [path_parts[-1]]:
            if p not in relevant:
                relevant.append(p)
        safe_suffix = "_".join(relevant)
    else:
        safe_suffix = flattened_path[-50:] if len(flattened_path) > 50 else flattened_path
    safe_suffix = safe_suffix.replace('/', '_').replace('\\', '_')

    # Target ~80 chars: short zip name (10) + hash (8) + separators (2) leave 60 for the suffix.
    if len(safe_suffix) > 60:
        safe_suffix = safe_suffix[:30] + "..." + safe_suffix[-20:]
    new_filename = f"{short_zip_name}_{name_hash}_{safe_suffix}"
    if len(new_filename) > 100:
        new_filename = f"{short_zip_name}_{name_hash}{ext}"
    return new_filename


def _index_entry(zip_path: str, display_path: str) -> dict:
    """Which Moodle submission folder a flat file came from: the flat names are truncated,
    so they cannot be used to group a student's files."""
    normalized = display_path.replace('\\', '/')
    folder = normalized.split('/')[0] if '/' in normalized else ''
    return {
        "zip": os.path.basename(zip_path),
        "path_in_zip": display_path,
        "submission": folder,
        "student": folder.split('_')[0] if ',' in folder else '',
    }


def _load_index_file(index_path: str) -> dict:
    if not os.path.exists(index_path):
        return {}
    with open(index_path, encoding="utf-8") as f:
        return json.load(f)


def unpack_and_flatten(zip_path, output_path):
    """
    Unpacks a zip file, flattening the directory structure.

    For example, a file at 'folder1/file1.txt' inside the zip will be
    extracted as 'folder1_file1.txt' in the output path. The Moodle folder of each
    extracted file is recorded in ``_submissions_index.json`` (merged with any existing index).

    Args:
        zip_path (str): The path to the zip file.
        output_path (str): The directory where files will be extracted.
    """
    if not os.path.exists(output_path):
        os.makedirs(output_path)

    zip_basename = os.path.splitext(os.path.basename(zip_path))[0]
    index_path = os.path.join(output_path, SUBMISSIONS_INDEX)

    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        members = zip_ref.infolist()
        print(f"Found {len(members)} items in zip file.")
        count = 0
        index = _load_index_file(index_path)
        for member in members:
            # Skip folders and Mac OS X metadata
            if member.is_dir() or '__MACOSX' in member.filename or '.DS_Store' in member.filename:
                continue
            display_path = _display_path(member)
            new_filename = _flat_filename(zip_basename, member.filename, _ascii_name(display_path))
            try:
                with open(os.path.join(output_path, new_filename), 'wb') as f:
                    f.write(zip_ref.read(member.filename))
                count += 1
                index[new_filename] = _index_entry(zip_path, display_path)
            except Exception as e:
                print(f"Failed to extract {member.filename}: {e}")

        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=1)
        print(f"Successfully unpacked and flattened {count} files from {zip_path} to {output_path}")


def main():
    """
    Main function to parse command-line arguments and run the script.
    """
    parser = argparse.ArgumentParser(
        description="Unpack a zip file and flatten its folder structure."
    )
    parser.add_argument(
        "zip_file", 
        help="Path to the input zip file."
    )
    parser.add_argument(
        "-o", "--output", 
        default=".", 
        help="Output directory path. Defaults to the current directory."
    )

    args = parser.parse_args()

    if not os.path.isfile(args.zip_file):
        print(f"Error: File not found at {args.zip_file}")
        return

    if not zipfile.is_zipfile(args.zip_file):
        print(f"Error: {args.zip_file} is not a valid zip file.")
        return

    unpack_and_flatten(args.zip_file, args.output)

if __name__ == "__main__":
    main()

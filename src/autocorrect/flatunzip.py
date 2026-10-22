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


def unpack_and_flatten(zip_path, output_path):
    """
    Unpacks a zip file, flattening the directory structure.
    
    For example, a file at 'folder1/file1.txt' inside the zip will be
    extracted as 'folder1_file1.txt' in the output path.

    Args:
        zip_path (str): The path to the zip file.
        output_path (str): The directory where files will be extracted.
    """
    if not os.path.exists(output_path):
        os.makedirs(output_path)

    zip_basename = os.path.splitext(os.path.basename(zip_path))[0]

    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        members = zip_ref.infolist()
        print(f"Found {len(members)} items in zip file.")
        count = 0
        index_path = os.path.join(output_path, SUBMISSIONS_INDEX)
        index = json.load(open(index_path, encoding="utf-8")) if os.path.exists(index_path) else {}
        for member in members:
            if member.is_dir():
                continue
            
            # Skip Mac OS X metadata
            if '__MACOSX' in member.filename or '.DS_Store' in member.filename:
                continue

            original_path = member.filename
            # Moodle writes UTF-8 names without the zip UTF-8 flag, so Python decodes them as
            # CP437 ("IÃ±aki"). Recover the real name, then fold accents to ASCII (Iñaki -> Inaki)
            # instead of dropping the letters.
            display_path = original_path
            if not member.flag_bits & 0x800:
                try:
                    display_path = original_path.encode('cp437').decode('utf-8')
                except (UnicodeEncodeError, UnicodeDecodeError):
                    pass
            safe_name = unicodedata.normalize('NFKD', display_path).encode('ascii', 'ignore').decode()
            flattened_path = safe_name.replace('/', '_').replace('\\', '_')
            
            # Truncate zip basename if too long (keep first 10 chars)
            short_zip_name = zip_basename[:10]
            
            # Use a hash for the flattened path to guarantee unique short filenames
            import hashlib
            # Create a hash based on the *original relative path* inside the zip
            # This ensures the same file always gets the same hash
            name_hash = hashlib.md5(original_path.encode('utf-8')).hexdigest()[:8]
            ext = os.path.splitext(flattened_path)[1]
            
            # Heuristic: Find parts of the path that look like student names (contain a comma)
            # original_path uses forward or backward slashes
            path_parts = safe_name.replace('\\', '/').split('/')
            student_parts = [p for p in path_parts if ',' in p]
            
            if student_parts:
                # Use the found student part(s) and the filename
                filename_part = path_parts[-1]
                
                relevant = []
                for p in student_parts:
                    if p not in relevant:
                        relevant.append(p)
                if filename_part not in relevant:
                    relevant.append(filename_part)
                
                safe_suffix = "_".join(relevant)
            else:
                # Fallback: use the end of the flattened path
                safe_suffix = flattened_path[-50:] if len(flattened_path) > 50 else flattened_path

            # Sanitize
            safe_suffix = safe_suffix.replace('/', '_').replace('\\', '_')

            # Length check - Aggressive truncation for deep paths
            # Max filename length target: ~80 chars
            # short_zip(10) + hash(8) + separators(2) = 20 chars used.
            # Available for suffix: 60 chars.
            if len(safe_suffix) > 60:
                 safe_suffix = safe_suffix[:30] + "..." + safe_suffix[-20:]

            new_filename = f"{short_zip_name}_{name_hash}_{safe_suffix}"
            
            # Final safety check
            if len(new_filename) > 100:
                 new_filename = f"{short_zip_name}_{name_hash}{ext}"

            output_filepath = os.path.join(output_path, new_filename)

            try:
                # Extract the file data
                file_data = zip_ref.read(member.filename)

                # Write the data to the new flattened file
                with open(output_filepath, 'wb') as f:
                    f.write(file_data)
                count += 1
                # Remember which Moodle submission folder each flat file came from: the flat
                # names are truncated, so they cannot be used to group a student's files.
                folder = display_path.replace('\\', '/').split('/')[0] if '/' in display_path.replace('\\', '/') else ''
                index[new_filename] = {
                    "zip": os.path.basename(zip_path),
                    "path_in_zip": display_path,
                    "submission": folder,
                    "student": folder.split('_')[0] if ',' in folder else '',
                }
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

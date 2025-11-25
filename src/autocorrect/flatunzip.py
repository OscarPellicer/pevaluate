import zipfile
import os
import argparse

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
        for member in zip_ref.infolist():
            if member.is_dir():
                continue

            original_path = member.filename
            flattened_path = original_path.replace('/', '_').replace('\\', '_')
            
            new_filename = f"{zip_basename}_{flattened_path}"
            
            output_filepath = os.path.join(output_path, new_filename)

            # Extract the file data
            file_data = zip_ref.read(member.filename)

            # Write the data to the new flattened file
            with open(output_filepath, 'wb') as f:
                f.write(file_data)
    print(f"Successfully unpacked and flattened {zip_path} to {output_path}")


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

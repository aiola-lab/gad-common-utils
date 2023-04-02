import os
from pathlib import Path


class filesMethods:
    def create_local_folder(file_path: str) -> None:
        """
        Create a local folder at the specified path.

        Args:
            file_path (str): Path to the folder to be created.

        Returns:
            None
        """
        folder_path = os.path.dirname(file_path)
        Path(folder_path).mkdir(parents=True, exist_ok=True)

    def list_files_with_ext_in_dir(base_dir, extensions_list):
        """
        Get a list of all files with the specified extensions in a directory.

        Args:
            base_dir (str): Base directory to search for files.
            extensions_list (list): List of file extensions to search for, without the '.'.

        Returns:
            list: List of file paths that match the specified extensions.
        """
        file_list = []
        for path in Path(base_dir).glob(r"**/*"):
            if path.suffix in extensions_list:
                file_list.append(str(path))

        file_list.sort()
        return file_list

    def get_file_extension_without_dot(file_name: str) -> str:
        """
        Get the file extension of a file, without the '.'.

        Args:
            file_name (str): Name of the file, can be either "name.ext" or "path/to/file/name.ext".

        Returns:
            str: The file extension without the '.'.
        """
        return os.path.splitext(file_name)[-1][1:]

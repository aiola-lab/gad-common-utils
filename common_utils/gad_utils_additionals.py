import subprocess


def write_xcom_to_file(xcom_dict):
    """
    Recives a dictionary of items needed to be passed as xcoms.
    Writes a dictionary to a JSON file.

    Args:
        xcom_dict (dict): A dictionary to be written to the file.

    Returns:
        None
    """
    # Convert the dictionary to a list of key-value pairs formatted as strings
    str_list = []
    for i in xcom_dict.keys():
        str_list.append(f'\"{i}\": \"{xcom_dict[i]}\"')

    # Join the strings together to form a JSON object
    new_dict = "[{" + ", ".join(str_list) + "}]"

    # Construct a shell command to create the directory and write the JSON object to a file
    bash_command = ["sh", "-c"]
    cmd = f"mkdir -p ../airflow/xcom/;echo '{new_dict}' > ../airflow/xcom/return.json"
    bash_command.append(cmd)

    # Execute the shell command using subprocess.run
    subprocess.run(bash_command)

import subprocess

def write_xcom_to_file(xcom_dict):
    str_list = []
    for i in xcom_dict.keys():
        str_list.append(f'\"{i}\": \"{xcom_dict[i]}\"')
    new_dict = "[{" + ", ".join(str_list) + "}]"
 
    bash_command = ["sh", "-c"]
    cmd = f"mkdir -p ../airflow/xcom/;echo '{new_dict}' > ../airflow/xcom/return.json"
    bash_command.append(cmd)

    subprocess.run(bash_command)

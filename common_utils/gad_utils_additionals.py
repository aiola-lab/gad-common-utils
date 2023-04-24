import subprocess

def write_xcom_to_file(xcom_names,xcom_values):
    if len(xcom_names) != len(xcom_values):
        print('error')
        #todo: raise exception instead
    str_list = []
    for i in range(len(xcom_names)):
        str_list.append(f'\"{xcom_names[i]}\": \"{xcom_values[i]}\"')
    new_dict = "[{" + ", ".join(str_list) + "}]"
 
    bash_command = ["sh", "-c"]
    cmd = f"mkdir -p ../airflow/xcom/;echo '{new_dict}' > ../airflow/xcom/return.json"
    bash_command.append(cmd)

    subprocess.run(bash_command)

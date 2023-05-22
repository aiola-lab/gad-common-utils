import json
import os
from datetime import timedelta

import requests
from airflow import DAG, settings
from airflow.contrib.operators.kubernetes_pod_operator import KubernetesPodOperator
from airflow.exceptions import AirflowException
from airflow.models import TaskInstance
from airflow.operators.python_operator import PythonOperator
from airflow.utils.dates import days_ago
from kubernetes.client import models as k8s
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from sqlalchemy import func


def return_dag_ingrediants(project):
    """
    This function returns a tuple that contains various objects used in an Airflow DAG
    for the specified project.

    Parameters:
        project (str): The name of the project for which to return the DAG ingredients.

    Returns:
        tuple: A tuple containing the following objects:
            - paths (dict): A dictionary that maps path-related variables to their respective names.
            - default_args (dict): A dictionary that specifies default arguments for the DAG.
            - envFromSource (k8s.V1EnvFromSource): An object that specifies the ConfigMap to use as a source of environment variables.
            - volumes (list): A list of V1Volume objects that specify the volumes to mount in the Kubernetes Pod.
            - volumes_mounts (list): A list of V1VolumeMount objects that specify the volume mounts to use in the Kubernetes Pod.
    """
    WORK_DIR = "/opt/aiola/projects"
    SUB_FOLDER = os.environ.get("DEPLOYMENT_DIR", "gad-deliveries")
    PROJECT_DIR = f"{WORK_DIR}/{SUB_FOLDER}/{project}"
    DBT_OUTPUT_DIR = "/opt/airflow/logs"
    PYTHON_DIR = f"{PROJECT_DIR}/python"
    DBT_DIR = f"{PROJECT_DIR}/dbt"
    CONFIG_DIR = f"{PROJECT_DIR}/configuration"

    paths = {
        "WORK_DIR": WORK_DIR,
        "SUB_FOLDER": SUB_FOLDER,
        "PROJECT_DIR": PROJECT_DIR,
        "DBT_DIR": DBT_DIR,
        "DBT_OUTPUT_DIR": DBT_OUTPUT_DIR,
        "PYTHON_DIR": PYTHON_DIR,
        "CONFIG_DIR": CONFIG_DIR,
    }

    default_args = {
        "owner": "GAD",
        "depends_on_past": False,
        "start_date": days_ago(0),
        "catchup": False,
        "retries": 0,
        "retry_delay": timedelta(seconds=10),
        "provide_context": True,
    }
    configMapEnvSource = k8s.V1ConfigMapEnvSource(name="gad-configmap", optional=False)
    envFromSource = k8s.V1EnvFromSource(config_map_ref=configMapEnvSource)

    volume_mount = k8s.V1VolumeMount(
        name="project-volume",
        mount_path="/opt/aiola/projects",
        sub_path=None,
        read_only=True,
    )

    volume = k8s.V1Volume(
        name="project-volume",
        host_path=k8s.V1HostPathVolumeSource(path="/home/docker/projects"),
    )

    volumes = [volume]
    volumes_mounts = [volume_mount]

    return paths, default_args, envFromSource, volumes, volumes_mounts


def generate_airflow_dag(project: str, dag_id: str, schedule_interval, tasks: list):
    """
    Creates a DAG using the specified parameters.

    Args:
        project (str): The name of the project.
        dag_id (str): The ID of the DAG.
        schedule_interval (str): The schedule interval for the DAG.
        tasks (list): A list of dictionaries containing information about each task.

    Returns:
        dag (DAG): A DAG object.
    """

    paths, default_args, envConfigMap, volumes, volumes_mounts = return_dag_ingrediants(
        project
    )

    def return_image_name(task_type):
        """
        Returns the image name based on the task type.

        Parameters:
        task_type (str): A string representing the task type.

        Returns:
        str: A string representing the name of the image based on the task type.

        """
        if task_type == "dbt":
            return "gad-dbt:0.1"
        elif task_type == "python":
            return "gad-papermill:0.1"

    def is_xcom_push_task(task_dict: dict):
        """
        This function checks if a given task dictionary specifies that its output should be pushed to XCom.

        Parameters:
            task_dict (dict): A dictionary that represents a task in an Airflow DAG.

        Returns:
            bool: True if the task's output should be pushed to XCom, False otherwise.
        """
        if "xcom_push" in task_dict.keys():
            return task_dict["xcom_push"]
        else:
            return False

    def extract_xcom_data(task_dict: dict):
        """
        This function extracts XCom data from a given task dictionary.

        Parameters:
            task_dict (dict): A dictionary that represents a task in an Airflow DAG.

        Returns:
            dict: A dictionary containing the XCom data for the task.
        """
        return_dict = {}
        if "xcom_pull" in task_dict.keys():
            task_id = task_dict["xcom_pull"]["task"]
            xcoms_list = task_dict["xcom_pull"]["xcoms"]
            for xcom in xcoms_list:
                value = (
                    "{{ ti.xcom_pull(task_ids=['"
                    + task_id
                    + "_service_task'], key='"
                    + xcom
                    + "') }}"
                )
                return_dict[xcom] = value
        return return_dict

    def return_cmds(task_dict: dict) -> list:
        """Returns a list of command-line commands based on task_dict.

        Args:
        task_dict: A dictionary containing information about the task to be executed.
                The dictionary must have 'task_type' key with value 'dbt' or 'python'.
                If 'task_type' is 'dbt', then the dictionary must have 'executable' key
                with a string value containing the name of the dbt executable to be run.
                If 'task_type' is 'python', then the dictionary must have 'executable' key
                with a string value containing the name of the python script to be run.

        Returns:
        A list of command-line commands based on the task type specified in task_dict.
        If task_type is 'dbt', then the returned list will contain ['dbt', <executable>]
        where <executable> is the value of 'executable' key in the task_dict.
        If task_type is 'python', then the returned list will contain ['python', <path/to/executable>]
        where <path/to/executable> is the full path to the python script specified in the
        'executable' key of the task_dict.
        """
        if task_dict["task_type"] == "dbt":
            return ["dbt", task_dict["executable"]]
        elif task_dict["task_type"] == "python":
            return ["python", f"{paths['PYTHON_DIR']}/{task_dict['executable']}.py"]

    def return_command_args(task_dict: dict, configs: dict) -> list:
        """Returns a list of command-line arguments based on task_dict and configs.

        Args:
        task_dict: A dictionary containing information about the task to be executed.
                The dictionary must have 'task_type' key with value 'dbt' or 'python'.
                If 'task_type' is 'dbt', then the dictionary must have 'dbt_models' key
                with a list of strings containing the names of dbt models to be executed.

        configs: A dictionary containing configuration values for the task.
                If the task is of type 'dbt', then the dictionary can have 'dbt_vars' key
                with a string value containing the variable values to be passed to dbt.
                If the task is of type 'python', then the dictionary can have 'python_args'
                key with a list of strings containing command-line arguments for the python script.

        Returns:
        A list of command-line arguments based on the task and configuration values.
        If task_type is 'dbt', then the returned list will contain arguments for dbt models
        and default dbt arguments such as project-dir, profiles-dir, target-path, and log-path.
        If task_type is 'python', then the returned list will contain arguments specified
        in the 'python_args' key of the configs dictionary.
        """

        xcom_val = extract_xcom_data(task_dict)

        if task_dict["task_type"] == "dbt":
            dbt_default_args = [
                "--project-dir",
                paths["DBT_DIR"],
                "--profiles-dir",
                paths["DBT_DIR"],
                "--target-path",
                paths["DBT_OUTPUT_DIR"],
                "--log-path",
                paths["DBT_OUTPUT_DIR"],
            ]

            dbt_default_args_and_models = task_dict["dbt_models"] + dbt_default_args

            dbt_vars = configs.get("dbt_vars")
            if dbt_vars:
                dbt_vars.update(xcom_val)
                dbt_all_args = dbt_default_args_and_models + [
                    "--vars",
                    json.dumps(dbt_vars),
                ]
            elif bool(xcom_val):
                dbt_all_args = dbt_default_args_and_models + [
                    "--vars",
                    json.dumps(xcom_val),
                ]
            else:
                dbt_all_args = dbt_default_args_and_models

            return dbt_all_args

        elif task_dict["task_type"] == "python":
            if configs.get("python_args"):
                python_args = configs.get("python_args")
            else:
                python_args = {}
            python_args.update(xcom_val)
            list_args = []
            if python_args:
                for key in python_args:
                    list_args.append(f"--{key}")
                    if python_args[key]:
                        list_args.append(python_args[key])
            return list_args

    def return_configs() -> dict:
        """
        Returns the dictionary of configurations read from a JSON file.

        Parameters:
        None

        Returns:
        dict: A dictionary containing the configurations read from the JSON file located in the CONFIG_DIR directory.

        """

        with open(f"{paths['CONFIG_DIR']}/config.json", "r") as f:
            j = f.read()
        return json.loads(j)

    def parse_xcoms(task_id, **kwargs):
        """
        This function extracts XCom data from a specified task instance and pushes the data to XCom with individual keys.

        Parameters:
            task_id (str): The ID of the task instance from which to extract XCom data.
            **kwargs: A dictionary containing additional keyword arguments. This dictionary must contain the 'ti' key, which
                    provides the task instance.

        Returns:
            None
        """
        task_instance = kwargs["ti"]
        value = task_instance.xcom_pull(task_ids=task_id)
        for i in value[0][0].keys():
            print("xcom push", "key", i, "val", value[0][0][i])
            task_instance.xcom_push(key=i, value=value[0][0][i])

    def check_channel_exists(slack_channel: str) -> bool:
        """
        This function checks if the specified slack channel exists.

        Parameters:
            slack_channel (str): The name of the slack channel to be checked.

        Returns:
            bool: True if the specified slack channel exists, False otherwise.
        """
        try:
            client = WebClient(token=os.getenv("api_token"))
            response = client.conversations_list(types="public_channel,private_channel")
            if response["ok"]:
                print(f"List of slack channels: {response['channels']}")
                for channel in response["channels"]:
                    if channel["name"] == slack_channel:
                        print(f"Fround Slack channel - {channel['name']}")
                        return True

            return False

        except SlackApiError as e:
            raise AirflowException(
                f"Failed to check if Slack channel {slack_channel} exists: {e.response['error']}"
            )

    def get_bot_user_name() -> str:
        """
        This function retrieves the bot user name associated with the Slack token.

        Returns:
            str: The bot user name.
        """
        client = WebClient(token=os.getenv("api_token"))
        try:
            response = client.auth_test()
            if response["ok"]:
                print(f"Bot user {response['user']}")
                return response["user"]
        except SlackApiError as e:
            raise AirflowException(
                f"Failed to retrieve bot user name: {e.response['error']}"
            )
        return ""

    def build_slack_message(context):
        task_instance = context["task_instance"]
        dag_id = task_instance.dag_id
        task_id = task_instance.task_id
        dag_execution_date = context["execution_date"]
        exception = context["exception"]

        # Retrieve EC2 machine name
        try:
            ec2_machine_name = requests.get(
                "http://169.254.169.254/latest/meta-data/hostname"
            ).text
        except requests.RequestException as e:
            ec2_machine_name = "Unknown"

        # Retrieve logs
        logs = task_instance.log

        # Retrieve number of incomplete tasks
        session = settings.Session()
        num_incomplete = (
            session.query(func.count())
            .filter(
                TaskInstance.dag_id == dag_id,
                TaskInstance.execution_date == dag_execution_date,
                TaskInstance.state != "success",
            )
            .scalar()
        )
        session.close()

        # Change local host to this machine ip
        my_ip = "54.170.202.148"
        task_log_url = str(task_instance.log_url).replace("localhost", my_ip)

        # Access the KubernetesPodOperator logs
        # logs_pod = context['ti'].xcom_pull(task_ids=task_id, key='logs')
        logs_pod = task_instance.xcom_pull(
            task_ids="task_id"
        )  # This is not working sine the xcom is empty, need to pass the pod stdout to the xcom

        slack_message = f"""
        Name of EC2 Machine: {ec2_machine_name} 
        Name of DAG: {dag_id}
        Name of Task: {task_id}
        Exception of DAG: {logs}
        Pod Logs: {logs_pod}
        Link to Log: {task_log_url}
        Start Time of Running DAG: {dag_execution_date}
        Start Time of Running Task: {task_instance.start_date}
        "Numer of Tries of Task: {task_instance.try_number}
        Number of Incomplete Tasks: {num_incomplete}
        """

        return slack_message

    def send_slack_notification(context) -> bool:
        """
        This function sends a slack notification to the specified slack channel.

        Parameters:
            context (dict): A dictionary containing the following keys:
                - dag_run (Airflow DAG run)
                - task_instance (Airflow task instance)
                - execution_date (str)
                - slack_channel (str)

        """
        task_id = context["task_instance"].task_id
        execution_date = context["execution_date"]

        slack_message = build_slack_message(context)

        slack_token = os.getenv("api_token")
        slack_channel = env_vars["slack_channel"]
        bot_user_name = get_bot_user_name()
        client = WebClient(token=slack_token)

        # Check if the specified slack channel exists. If not, create it.
        print(f"Checking if Slack channel {slack_channel} exists...")

        if not check_channel_exists(slack_channel):
            try:
                response = client.conversations_create(name=slack_channel)

                if response["ok"]:
                    channel_id = response["channel"]["id"]
                    print(f"New channel created. Channel ID: {channel_id}")

                else:
                    print(f"Failed to create channel: {response['error']}")

            except SlackApiError as e:
                if str(e.response["error"]) == "name_taken":
                    print(f"Channel '{slack_channel}' already exists.")

                else:
                    print(f"Error creating channel: {e.response['error']}")

        # Try to send the message to the specified slack channel.

        try:
            response = client.chat_postMessage(
                channel=slack_channel, text=slack_message, username=bot_user_name
            )
            if not response["ok"]:
                raise AirflowException(
                    f"Failed to send Slack notification: {response['error']}"
                )
        except SlackApiError as e:
            raise AirflowException(
                f"Failed to send Slack notification: {e.response['error']}"
            )

    # dag creation
    dag = DAG(
        dag_id=dag_id,
        default_args=default_args,
        schedule_interval=schedule_interval,
        max_active_runs=1,
        concurrency=10,
    )

    configs = return_configs()
    env_vars = configs.get("env_vars")

    """
    This code is a loop that iterates over a list of tasks and creates a KubernetesPodOperator object for each task.
    return_command_args() function is used to obtain the command arguments for the task.
    return_image_name() function is used to get the image name based on the task type.
    return_configs() function is used to get environment variables.
    The KubernetesPodOperator object is then created using these variables and appended to a dictionary named kubernetes_tasks with the task ID as the key.
    """

    # Define an empty list to store new tasks
    new_tasks_list = []

    # Iterate through the original tasks list and add each task to the new list
    # If a task has an xcom_push attribute set to True, create a new service task and add it to the new list
    for task in tasks:
        new_tasks_list.append(task)
        if "xcom_push" in task.keys():
            if task["xcom_push"]:
                previous_task_id = task["task_id"]
                service_task = {
                    "task_id": f"{previous_task_id}_service_task",
                    "service": True,
                    "upstream": [previous_task_id],
                }
                new_tasks_list.append(service_task)

    # Set upstream dependencies for each task in the new list
    for i, task in enumerate(new_tasks_list):
        if i > 0:
            if "service" in new_tasks_list[i - 1].keys():
                new_tasks_list[i]["upstream"] = [new_tasks_list[i - 1]["task_id"]]

    # Define a dictionary to store KubernetesPodOperator and PythonOperator tasks
    kubernetes_tasks = {}

    # Iterate through each task in the new list and create a KubernetesPodOperator or PythonOperator task based on its properties
    for task in new_tasks_list:
        # If the task is a service task, create a PythonOperator with parse_xcoms function as its callable
        if "service" in task.keys():
            service_task = PythonOperator(
                task_id=task["task_id"],
                python_callable=parse_xcoms,
                op_args=[task["upstream"]],
                dag=dag,
                on_failure_callback=send_slack_notification,
                provide_context=True,
            )
            kubernetes_tasks[task["task_id"]] = service_task

        # If the task is not a service task, create a KubernetesPodOperator
        else:
            cmds = return_cmds(task)
            arguments = return_command_args(task, configs)
            image = return_image_name(task["task_type"])

            kubernetes_task = KubernetesPodOperator(
                volumes=volumes,
                volume_mounts=volumes_mounts,
                env_vars=env_vars,
                env_from=[envConfigMap],
                namespace="default",
                labels={"Task": task["task_type"]},
                image_pull_policy="Never",
                name=task["task_id"],
                task_id=task["task_id"],
                is_delete_operator_pod=True,
                get_logs=True,
                image=image,
                cmds=cmds,
                arguments=arguments,
                dag=dag,
                do_xcom_push=is_xcom_push_task(task),
                on_failure_callback=send_slack_notification,
            )
            kubernetes_tasks[task["task_id"]] = kubernetes_task

    # using the tasks list, and the kubernetes_tasks dictionary - this loop creates the dependancies.
    # each task in tasks contains a value in the 'upstream' key that tells what is the pervious task (or tasks).
    # the kubernates operator created gets the dependancies and is configured to use them with the set_upstream setting.

    for task in new_tasks_list:
        if task["upstream"] is None or task["upstream"] == "" or task["upstream"] == []:
            pass
        else:
            dependancies = []
            for t in task["upstream"]:
                dependancies.append(kubernetes_tasks[t])
            kubernetes_tasks[task["task_id"]].set_upstream(dependancies)

    return dag

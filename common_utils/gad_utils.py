import ast
import json
import os
import time
from datetime import timedelta

import requests
from airflow import DAG
from airflow.contrib.operators.kubernetes_pod_operator import KubernetesPodOperator
from airflow.exceptions import AirflowException
from airflow.kubernetes.secret import Secret
from airflow.operators.python_operator import PythonOperator
from airflow.utils.dates import days_ago
from kubernetes.client import models as k8s
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


def return_dag_ingrediants(content_path, project):
    """
    This function returns a tuple that contains various objects used in an Airflow DAG
    for the specified project.

    Parameters:
        content_path (str): The path of the content we want to run via DAG.
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
    SUB_FOLDER = os.environ.get("DEPLOYMENT_DIR", content_path)
    PROJECT_DIR = f"{WORK_DIR}/{SUB_FOLDER}/{project}"
    DBT_OUTPUT_DIR = "/opt/airflow/logs"
    PYTHON_DIR = f"{PROJECT_DIR}/python"
    DBT_DIR = f"{PROJECT_DIR}/dbt"
    GX_DIR = f"{PROJECT_DIR}/gx/checkpoints_executions"
    CONFIG_DIR = f"{PROJECT_DIR}/configuration"

    paths = {
        "WORK_DIR": WORK_DIR,
        "SUB_FOLDER": SUB_FOLDER,
        "PROJECT_DIR": PROJECT_DIR,
        "DBT_DIR": DBT_DIR,
        "DBT_OUTPUT_DIR": DBT_OUTPUT_DIR,
        "PYTHON_DIR": PYTHON_DIR,
        "GX_DIR": GX_DIR,
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
        read_only=False,
    )

    volume = k8s.V1Volume(
        name="project-volume",
        host_path=k8s.V1HostPathVolumeSource(path="/home/docker/projects"),
    )

    volumes = [volume]
    volumes_mounts = [volume_mount]

    return paths, default_args, envFromSource, volumes, volumes_mounts


def generate_airflow_dag(
    project: str,
    dag_id: str,
    schedule_interval,
    tasks: list,
    content_path: str = "gad-deliveries",
    dag_params: dict = {},
):
    """
    Creates a DAG using the specified parameters.

    Args:
        project (str): The name of the project.
        dag_id (str): The ID of the DAG.
        schedule_interval (str): The schedule interval for the DAG.
        tasks (list): A list of dictionaries containing information about each task.
        content_path (str): The path of the content we want to run via DAG. by default it would get "gad-deliveries" as its the local content.

    Returns:
        dag (DAG): A DAG object.
    """

    paths, default_args, envConfigMap, volumes, volumes_mounts = return_dag_ingrediants(
        content_path, project
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
        elif task_type == "gx":
            return "gad-ge:0.1"

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
                return_dict[xcom] = value.replace("[", "").replace(
                    "]", ""
                )  # this is MANDATORY to make sure we get the right value from XCOM (using [1:-1] doesn't work)
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
        elif task_dict["task_type"] == "gx":
            return ["python", f"{paths['GX_DIR']}/{task_dict['executable']}.py"]

    def return_command_args(task_dict: dict, xcom_pull_task_id: str) -> list:
        """Returns a list of command-line arguments based on task_dict and configs.

        Args:
        task_dict: dict
        A dictionary containing information about the task to be executed.
                The dictionary must have 'task_type' key with value 'dbt' or 'python'.
                If 'task_type' is 'dbt', then the dictionary must have 'dbt_models' key
                with a list of strings containing the names of dbt models to be executed.

        xcom_pull_task_id: str
        The task ID of either the digest_args_task or the last service task that pushed data to XCom.

        Returns:
        A list of command-line arguments based on the task and configuration values.
        If task_type is 'dbt', then the returned list will contain arguments for dbt models
        and default dbt arguments such as project-dir, profiles-dir, target-path, and log-path.
        If task_type is 'python', then the returned list will contain arguments specified
        in the 'python_args' key of the configs dictionary.
        """

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

            # get the latest version of dbt vars from XCOM
            dbt_vars = (
                (
                    "{{ ti.xcom_pull(task_ids=['"
                    + xcom_pull_task_id
                    + "'], key='dbt_vars') }}"
                )
                .replace(
                    "[", ""
                )  # this is MANDATORY to make sure we get the right value from XCOM (using [1:-1] doesn't work)
                .replace(
                    "]", ""
                )  # this is MANDATORY to make sure we get the right value from XCOM (using [1:-1] doesn't work)
            )

            dbt_all_args = (
                task_dict["dbt_models"] + dbt_default_args + ["--vars", dbt_vars]
            )

            return dbt_all_args

        elif task_dict["task_type"] == "python":
            list_args = []
            # iterate over the non-empty dag_params, pull them from XCOM ands add them to the list
            for key in dag_params_not_empty:
                list_args.append(f"--{key}")
                list_args.append(
                    (
                        "{{ ti.xcom_pull(task_ids=['digest_args_task'], key='"
                        + key
                        + "') }}"
                    )
                    .replace(
                        "[", ""
                    )  # this is MANDATORY to make sure we get the right value from XCOM (using [1:-1] doesn't work)
                    .replace(
                        "]", ""
                    )  # this is MANDATORY to make sure we get the right value from XCOM (using [1:-1] doesn't work)
                )

            # get the xcom values
            xcom_val = extract_xcom_data(task_dict)
            for key, val in xcom_val.items():
                list_args.append(f"--{key}")
                list_args.append(val)

            return list_args

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

        for key in value[0][0].keys():
            print("xcom push", "key", key, "val", value[0][0][key])

            # pull initial dbt_vars from xcom
            dbt_vars_dict = task_instance.xcom_pull(
                task_ids=["digest_args_task"], key="dbt_vars"
            )[0]
            # add new dbt vars from XCOM of another task to dbt_vars_dict
            dbt_vars_dict[key] = value[0][0][key]

            # push individual xcoms for python use
            task_instance.xcom_push(key=key, value=value[0][0][key])

        # push dbt_vars back to xcom
        task_instance.xcom_push(key="dbt_vars", value=dbt_vars_dict)

    def digest_args(given_args: str, default_args_dict: dict, **kwargs):
        """
        Process and store arguments for further use.

        Args:
            given_args (str): A string representing the given arguments.
            default_args_dict (dict): A dict of the default arguments.
            **kwargs: Additional keyword arguments.

        Returns:
            None
        """

        # convert the given args to a dict
        given_args_dict = ast.literal_eval(given_args)

        print(f"The given args: {given_args}")
        print(f"The default args: {default_args_dict}")

        args_to_use = {}
        if given_args_dict:
            print("There are some given args, using given args")
            args_to_use = given_args_dict
        else:
            print("There are NO given args, using default args")
            args_to_use = default_args_dict

        # create a dict of non-empty dbt vars and push to xcom
        dbt_vars = {key: str(val) for key, val in args_to_use.items() if val != ""}
        kwargs["ti"].xcom_push(key="dbt_vars", value=dbt_vars)

        # push each python arg to xcom
        for arg in args_to_use:
            if args_to_use[arg] != "":
                kwargs["ti"].xcom_push(key=arg, value=args_to_use[arg])

    def list_all_conversations(client):
        """
        Retrieves a list of all conversations (channels) from Slack using the provided client.

        Args:
            client (SlackClient): The Slack client object.

        Returns:
            list: A list of conversation objects.

        Raises:
            SlackApiError: If an error occurs while retrieving conversations from Slack.
        """
        all_conversations = []
        max_retries = 1
        retry_delay = 1
        retry_counter = 0

        while retry_counter < max_retries:
            try:
                response = client.conversations_list(
                    types="private_channel,public_channel,mpim,im"
                )
                all_conversations.extend(response["channels"])

                if (
                    "response_metadata" in response
                    and "next_cursor" in response["response_metadata"]
                ):
                    next_cursor = response["response_metadata"]["next_cursor"]
                    response = client.conversations_list(
                        cursor=next_cursor,
                        types="private_channel,public_channel,mpim,im",
                    )
                else:
                    break

            except SlackApiError as e:
                if e.response["error"] == "ratelimited":
                    # Retry after the specified duration
                    retry_after = int(e.response.headers["Retry-After"])
                    time.sleep(retry_after)
                else:
                    print(f"Failed to retrieve conversations: {e}")
                    break

            retry_counter += 1
            time.sleep(1)

        return all_conversations

    def check_channel_exists(slack_channel: str, client) -> str:
        """
        This function checks if the specified Slack channel exists and returns its ID if found.

        Parameters:
            slack_channel (str): The name of the Slack channel to be checked.
            client (object): The Slack client to interact with the Slack API.

        Returns:
            str: The ID of the Slack channel if it exists, or an empty string if not found.
        """
        try:
            all_channels = list_all_conversations(client)
            channels_names = [
                (channel["name"], channel["id"]) for channel in all_channels
            ]
            print(f"List of Slack channels: {channels_names}")
            for channel in channels_names:
                if channel[0] == slack_channel:
                    print(f"Found Slack channel - name: {channel[0]}, id: {channel[1]}")
                    return channel[1]

            return ""

        except SlackApiError as e:
            print(
                f"Failed to check if Slack channel {slack_channel} exists: {e.response['error']}"
            )
            return ""

    def get_bot_user_name(client) -> str:
        """
        This function retrieves the bot user name associated with the Slack token.

        Returns:
            str: The bot user name.
        """
        try:
            response = client.auth_test()
            if response["ok"]:
                print(f"Bot user {response['user']}")
                return response["user"]
        except SlackApiError as e:
            raise AirflowException(
                f"Failed to retrieve bot user name: {e.response['error']}"
            )
        return ""  # TO BE REMOVED

    def build_slack_message(context):
        print("Strting to build Slack message")
        task_instance = context["task_instance"]
        dag_id = task_instance.dag_id
        task_id = task_instance.task_id
        dag_execution_date = context["dag_run"].start_date
        exception = context["exception"]

        # Retrieve EC2 machine name
        try:
            ec2_machine_name = requests.get(
                "http://169.254.169.254/latest/meta-data/hostname"
            ).text
        except requests.RequestException as e:
            ec2_machine_name = "Unknown"

        # Retrieve EC2 machine IP address
        my_ip = requests.get("https://checkip.amazonaws.com").text.strip()

        # Change local host to this machine ip
        task_log_url = str(task_instance.log_url).replace("localhost", my_ip)

        # TODO: Add abillity to send the pod stdout to slack

        slack_message = f"""
        *Name of EC2 Machine*: {ec2_machine_name} 
        *Name of DAG*: {dag_id}
        *Name of Task*: {task_id}
        *Link to Log*: {task_log_url}
        *Start Time of Running DAG*: {dag_execution_date}
        *Start Time of Running Task*: {task_instance.start_date}
        *Number of Tries of Task*: {task_instance.try_number}
        ----------------------------
        """

        return slack_message

    def build_slack_message_blocks(context):
        print("Starting to build Slack message")
        task_instance = context["task_instance"]
        dag_id = task_instance.dag_id
        task_id = task_instance.task_id
        dag_execution_date = context["dag_run"].logical_date
        exception = context["exception"]

        # Retrieve EC2 machine name
        try:
            ec2_machine_name = requests.get(
                "http://169.254.169.254/latest/meta-data/hostname"
            ).text
        except requests.RequestException as e:
            ec2_machine_name = "Unknown"

        # Retrieve EC2 machine IP address
        my_ip = requests.get("https://checkip.amazonaws.com").text.strip()

        # Change local host to this machine IP
        task_log_url = str(task_instance.log_url).replace("localhost", my_ip)

        # Create the blocks for the message
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*EC2 Machine:* " + ec2_machine_name,
                },
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*DAG:* " + dag_id},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Task:* " + task_id},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Start Time DAG:* " + str(dag_execution_date),
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Start Time Task:* " + str(task_instance.start_date),
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Number of Tries of Task:* "
                    + str(task_instance.try_number),
                },
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Log:* " + task_log_url},
            },
        ]

        # Convert the blocks to a JSON-encoded string
        blocks_json = json.dumps(blocks)

        return blocks_json

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
        channel_id = ""
        slack_token = os.environ.get("api_token")
        if slack_token is None:
            print("Missing Slack API token.")
            return False
        else:
            print("Slack API token exists, getting to business")

        slack_channel = (
            os.getenv("ENV_PREFIX") + "-" + os.getenv("REGION") + "-gad-alerts"
        )
        print(f"Slack channel: {slack_channel}")
        user_id = os.environ.get("user_id")

        slack_message = build_slack_message_blocks(context)
        # slack_channel = os.getenv("ENV_PREFIX") + "_alerts"
        client = WebClient(token=slack_token)

        # Get the name of the slack bot
        bot_user_name = get_bot_user_name(client)

        # Check if the specified slack channel exists. If not, create it.
        print(f"Checking if Slack channel {slack_channel} exists...")
        channel_id = check_channel_exists(slack_channel, client)
        if channel_id == "":
            try:
                response = client.conversations_create(name=slack_channel)

                if response["ok"]:
                    channel_id = response["channel"]["id"]
                    print(
                        f"New channel created. name: {slack_channel} id: {channel_id}"
                    )

                else:
                    print(f"Failed to create channel: {response['error']}")

            except SlackApiError as e:
                if str(e.response["error"]) == "name_taken":
                    print(f"Channel '{slack_channel}' already exists.")

                else:
                    print(f"Error creating channel: {e.response['error']}")

        # Try to invite the user to the slack channel
        if user_id is not None and channel_id != "":
            response = client.conversations_invite(channel=channel_id, users=user_id)
            if response["ok"]:
                print(
                    f"Succeeded in inviting user {user_id} to channel {slack_channel}"
                )
            else:
                print(f"Failed in inviting user {user_id} to channel {slack_channel}")

        # Try to send the message to the specified slack channel.

        try:
            response = client.chat_postMessage(
                channel=slack_channel, blocks=slack_message, username=bot_user_name
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
        params=dag_params,
    )

    # use only the params that are not empty
    dag_params_not_empty = {key: val for key, val in dag_params.items() if val != ""}

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

    # this variable is used to store the task id of the last task that updated the dbt_vars key in xcom. It can be either "digest_args_task" or a service task. If there are no service tasks - it will be "digest_args_task"
    last_service_task_id = "digest_args_task"

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
            last_service_task_id = task["task_id"]

        # If the task is not a service task, create a KubernetesPodOperator
        else:
            cmds = return_cmds(task)
            arguments = return_command_args(task, last_service_task_id)
            image = return_image_name(task["task_type"])
            slack_api_token_secret = Secret(
                deploy_type="env",
                deploy_target="api_token",
                secret="gad-slack-api-token",
                key="api_token",
            )

            kubernetes_task = KubernetesPodOperator(
                volumes=volumes,
                volume_mounts=volumes_mounts,
                env_vars=[],
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
                secrets=[slack_api_token_secret],
            )
            kubernetes_tasks[task["task_id"]] = kubernetes_task

    # Define an empty list to store tasks without upstream dependencies, so we will set
    # the digest_args_task as their upstream
    tasks_without_upstream = []

    # using the tasks list, and the kubernetes_tasks dictionary - this loop creates the dependancies.
    # each task in tasks contains a value in the 'upstream' key that tells what is the pervious task (or tasks).
    # the kubernates operator created gets the dependancies and is configured to use them with the set_upstream setting.
    for task in new_tasks_list:
        if task["upstream"] is None or task["upstream"] == "" or task["upstream"] == []:
            tasks_without_upstream.append(kubernetes_tasks[task["task_id"]])
            pass
        else:
            dependancies = []
            for t in task["upstream"]:
                dependancies.append(kubernetes_tasks[t])
            kubernetes_tasks[task["task_id"]].set_upstream(dependancies)

    # define the digest_args_task and set it as upstream for all tasks without upstream dependencies
    digest_args_task = PythonOperator(
        task_id="digest_args_task",
        python_callable=digest_args,
        op_kwargs={"given_args": "{{ dag_run.conf }}", "default_args_dict": dag_params},
        dag=dag,
    ).set_downstream(tasks_without_upstream)

    return dag

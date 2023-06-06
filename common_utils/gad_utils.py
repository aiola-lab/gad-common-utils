import ast
import json
import os
from datetime import timedelta

from airflow import DAG
from airflow.contrib.operators.kubernetes_pod_operator import KubernetesPodOperator
from airflow.operators.python_operator import PythonOperator
from airflow.utils.dates import days_ago
from kubernetes.client import models as k8s


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
                return_dict[xcom] = value.replace("[", "").replace("]", "")
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

    def return_command_args(task_dict: dict, last_service_task_id: str) -> list:
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

            dbt_vars = (
                (
                    "{{ ti.xcom_pull(task_ids=['"
                    + last_service_task_id
                    + "'], key='dbt_vars') }}"
                )
                .replace("[", "")
                .replace("]", "")
            )

            dbt_all_args = (
                task_dict["dbt_models"] + dbt_default_args + ["--vars", dbt_vars]
            )

            return dbt_all_args

        elif task_dict["task_type"] == "python":
            list_args = []
            for key in dag_params_not_empty:
                list_args.append(f"--{key}")
                list_args.append(
                    (
                        "{{ ti.xcom_pull(task_ids=['digest_args_task'], key='"
                        + key
                        + "') }}"
                    )
                    .replace("[", "")
                    .replace("]", "")
                )

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
            task_type (str): The type of task that will pull the XCOM. This must be either 'dbt' or 'python'.
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
            dbt_vars = task_instance.xcom_pull(
                task_ids=["digest_args_task"], key="dbt_vars"
            )
            dbt_vars_dict = ast.literal_eval(dbt_vars[0])
            # add new dbt vars from XCOM of another task to dbt_vars_dict
            dbt_vars_dict[key] = value[0][0][key]

            # push individual xcoms for python use
            task_instance.xcom_push(key=key, value=value[0][0][key])

        # push dbt_vars back to xcom
        task_instance.xcom_push(key="dbt_vars", value=dbt_vars_dict)

    def digest_args(given_args, default_args, **kwargs):
        print(f"given_args: {given_args}")
        print(f"default_args: {default_args}")

        given_args_dict = ast.literal_eval(given_args)
        default_args_dict = ast.literal_eval(default_args)

        args_to_use = {}
        if given_args_dict:
            print("using given args")
            args_to_use = given_args_dict
        else:
            print("using default args")
            args_to_use = default_args_dict

        print(f"args_to_use: {args_to_use}")

        # create a string of the dbt vars to be used and push to xcom as one string
        dbt_vars = (
            "{"
            + ", ".join([f'"{k}": "{v}"' for k, v in args_to_use.items() if v != ""])
            + "}"
        )
        kwargs["ti"].xcom_push(key="dbt_vars", value=dbt_vars)

        # push each python arg to xcom
        for arg in args_to_use:
            if args_to_use[arg] != "":
                kwargs["ti"].xcom_push(key=arg, value=args_to_use[arg])

    # use only the params that are not empty
    dag_params_not_empty = {k: v for k, v in dag_params.items() if v != ""}

    # dag creation
    dag = DAG(
        dag_id=dag_id,
        default_args=default_args,
        schedule_interval=schedule_interval,
        max_active_runs=1,
        concurrency=10,
        params=dag_params,
    )

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
            )
            kubernetes_tasks[task["task_id"]] = service_task
            last_service_task_id = task["task_id"]

        # If the task is not a service task, create a KubernetesPodOperator
        else:
            cmds = return_cmds(task)
            arguments = return_command_args(task, last_service_task_id)
            image = return_image_name(task["task_type"])

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
            )
            kubernetes_tasks[task["task_id"]] = kubernetes_task

    # using the tasks list, and the kubernetes_tasks dictionary - this loop creates the dependancies.
    # each task in tasks contains a value in the 'upstream' key that tells what is the pervious task (or tasks).
    # the kubernates operator created gets the dependancies and is configured to use them with the set_upstream setting.

    tasks_without_upstream = []

    for task in new_tasks_list:
        if task["upstream"] is None or task["upstream"] == "" or task["upstream"] == []:
            tasks_without_upstream.append(kubernetes_tasks[task["task_id"]])
            pass
        else:
            dependancies = []
            for t in task["upstream"]:
                dependancies.append(kubernetes_tasks[t])
            kubernetes_tasks[task["task_id"]].set_upstream(dependancies)

    digest_args_task = PythonOperator(
        task_id="digest_args_task",
        python_callable=digest_args,
        op_kwargs={"given_args": "{{ dag_run.conf }}", "default_args": "{{ params }}"},
        dag=dag,
    ).set_downstream(tasks_without_upstream)

    return dag

import glob
import json
import logging
import os

import awswrangler as wr
import boto3
import pandas as pd
from botocore.exceptions import ClientError


class S3GeneralMethods:
    def split_s3_path(s3_path: str) -> str:
        """returns the bucket name and path

        Args:
            s3_path (str): s3 path

        Returns:
            str: bucket name
            str: s3 path (after the bucket name)
        """
        path_parts = s3_path.replace("s3://", "").split("/")
        bucket = path_parts.pop(0)
        key = "/".join(path_parts)
        return bucket, key


class S3Upload:
    def upload_dict_as_json_to_s3(dict_to_load: dict, s3_path: str) -> None:
        """load dict to s3 as json file

        Args:
            dict_to_load (dict): the dict to load
            s3_path (str): the path to load save the json file
        """
        df = pd.DataFrame.from_dict(data=dict_to_load.items(), orient="columns").T
        df.columns = df.iloc[0]
        df.drop(df.index[0], inplace=True)

        wr.s3.to_json(df=df, path=s3_path, index=False, orient="records", lines=True)
        logging.info(f"file was saved in s3: {s3_path}")

    def upload_s3_folder(
        s3_url: str, local_dir: str, file_extension: str = "*"
    ) -> None:
        """Uploads a local folder to an S3 bucket.

        Args:
            s3_url (str): The URL of the S3 bucket and folder.
            local_dir (str): The path of the local folder to be uploaded.
            file_extension (str, optional): The extension of the files to be uploaded. Defaults to '*'.

        Returns:
            None
        """
        s3 = boto3.resource("s3")
        bucket_name = S3GeneralMethods.split_s3_path(s3_path=s3_url)[0]

        # add '*/' so the iglob function will work as expected (in case there is no trailing slash in the given param)
        local_dir = os.path.join(local_dir, "*/")

        for file in glob.iglob(local_dir + f"**/*{file_extension}", recursive=True):
            file_name = str(file)
            s3.meta.client.upload_file(
                Filename=file_name, Bucket=bucket_name, Key=file_name
            )


class S3Read:
    def get_json_file_from_s3_as_dict(s3_path: str) -> dict:
        """retruns a dict containing the json file in the given s3 path.
        if no file is found an empty dict is returned

        Args:
            s3_path (str): full path to json file in s3 (e.g. "s3://bucket/path/to/file.json")

        Returns:
            dict: a df containing the json file
        """
        s3 = boto3.resource("s3")

        bucket_name, path = S3GeneralMethods.split_s3_path(s3_path)
        content_object = s3.Object(bucket_name=bucket_name, key=path)

        try:
            file_content = content_object.get()["Body"].read().decode("utf-8")
        except ClientError as ex:
            if ex.response["Error"]["Code"] == "NoSuchKey":
                logging.info("No object found - returning empty")
                return dict()
            else:
                raise

        return json.loads(file_content)

    def download_s3_folder(s3_url: str, dest_root_folder: str = None) -> None:
        """
        Downloads a folder from Amazon S3 to the local file system.

        Args:
            s3_url (str): The URL of the S3 folder, e.g. 's3://my-bucket/my-folder/'.
            dest_root_folder (str, optional): The local directory where the folder will be saved. If not specified, the folder will be saved in the current working directory.

        Returns:
            None
        """
        s3 = boto3.resource("s3")
        bucket_name, s3_folder = S3GeneralMethods.split_s3_path(s3_path=s3_url)
        bucket = s3.Bucket(bucket_name)

        for obj in bucket.objects.filter(Prefix=s3_folder):
            if dest_root_folder:
                # the target is the full s3 path of the file, but we replace the first folder in the
                # path with the dest_root_folder
                target = os.path.join(
                    dest_root_folder, os.path.relpath(obj.key, dest_root_folder)
                )
            else:
                # the target is the full s3 path of the file
                target = obj.key
            if not os.path.exists(os.path.dirname(target)):
                os.makedirs(os.path.dirname(target))
            if obj.key[-1] == "/":
                continue
            bucket.download_file(obj.key, target)

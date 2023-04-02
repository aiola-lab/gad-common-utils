import ray
from dynamodb_methods import DynamoDbTable


@ray.remote
class DynamoDbTableRay(DynamoDbTable):
    pass
